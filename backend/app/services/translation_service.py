import uuid
import json
import re
import asyncio
import logging
import base64
import mimetypes
import aiofiles
from datetime import datetime, timezone
from typing import ClassVar, Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from openai import AsyncOpenAI

from app.core.database import async_session_maker
from app.models import PaperTranslation, Paper, PaperSection, Term, KnowledgeTerm, Project, TranslationGroup
from app.services.openai_settings import get_openai_settings
from app.services.term_service import TermService
from app.services.react_agent import ReActAgent
from app.services.tools import get_available_tools
from app.services.storage import StorageService

logger = logging.getLogger(__name__)


class TranslationService:
    """Domain-adaptive paper translation using ReAct agent with search tools."""

    _progress_queues: ClassVar[dict[uuid.UUID, asyncio.Queue[str]]] = {}
    _queue_refs: ClassVar[dict[uuid.UUID, int]] = {}

    def __init__(self, db: AsyncSession):
        self.db = db
        self.client: AsyncOpenAI | None = None
        self.tools = get_available_tools()

    @classmethod
    def get_progress_queue(cls, translation_id: uuid.UUID) -> asyncio.Queue[str]:
        if translation_id not in cls._progress_queues:
            cls._progress_queues[translation_id] = asyncio.Queue(maxsize=500)
            cls._queue_refs[translation_id] = 0
        cls._queue_refs[translation_id] = cls._queue_refs.get(translation_id, 0) + 1
        return cls._progress_queues[translation_id]

    @classmethod
    async def publish_progress(cls, translation_id: uuid.UUID, payload: dict) -> None:
        if translation_id not in cls._progress_queues:
            return
        queue = cls._progress_queues[translation_id]
        data = json.dumps(payload, ensure_ascii=False)
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        await queue.put(data)

    @classmethod
    def release_progress(cls, translation_id: uuid.UUID) -> None:
        if translation_id in cls._queue_refs:
            cls._queue_refs[translation_id] -= 1
            if cls._queue_refs[translation_id] <= 0:
                cls._progress_queues.pop(translation_id, None)
                cls._queue_refs.pop(translation_id, None)

    @classmethod
    def cleanup_progress(cls, translation_id: uuid.UUID) -> None:
        cls._progress_queues.pop(translation_id, None)
        cls._queue_refs.pop(translation_id, None)


    async def run_translation(self, translation_id: uuid.UUID) -> None:
        translation = await self.db.get(PaperTranslation, translation_id)
        if not translation:
            return

        # Load user-specific settings
        user_settings = await get_openai_settings(self.db, translation.user_id)

        # Create OpenAI client with user-specific settings
        self.client = AsyncOpenAI(
            api_key=user_settings["api_key"] or None,
            base_url=user_settings["base_url"] or None,
        )
        self.model = user_settings["model"]

        try:
            translation.status = "running"
            await self.db.commit()
            await self.publish_progress(translation_id, {"type": "status", "status": "running"})

            paper = await self._load_paper(translation.paper_id)
            if not paper:
                raise ValueError("Paper not found")

            project = await self.db.get(Project, paper.project_id)

            await self.publish_progress(translation_id, {
                "type": "progress",
                "step": "analyzing_domain",
                "message": "正在分析论文领域...",
            })

            domain = (project.domain if project else None) or await self._infer_domain(paper)

            await self.publish_progress(translation_id, {
                "type": "domain_detected",
                "domain": domain,
                "message": f"检测到领域：{domain}",
            })

            term_memory = await self._load_term_memory(paper.project_id)
            known_phrases = set(term_memory.keys())

            sections = self._sort_sections(paper.sections)
            total = len(sections)

            await self.publish_progress(translation_id, {
                "type": "progress",
                "step": "start",
                "current": 0,
                "total": total,
                "paper_id": str(paper.id),
                "mode": translation.mode,
                "domain": domain,
            })

            output_parts: list[str] = []
            term_service = TermService(self.db)

            for idx, section in enumerate(sections, start=1):
                title = section.title or section.section_type or f"Section {idx}"
                source = section.content_md or section.content_text or ""

                if not source.strip():
                    await self.publish_progress(translation_id, {
                        "type": "progress",
                        "step": "skip_empty",
                        "current": idx,
                        "total": total,
                        "section_title": title,
                    })
                    continue

                await self.publish_progress(translation_id, {
                    "type": "progress",
                    "step": "translating",
                    "current": idx,
                    "total": total,
                    "section_title": title,
                })

                try:
                    translated = await self._translate_section(
                        source_text=source,
                        section_title=title,
                        section_id=section.id,
                        domain=domain,
                        term_memory=term_memory,
                        mode=translation.mode,
                        target_language=translation.target_language,
                        paper_title=paper.title,
                        paper_abstract=paper.abstract or "",
                        translation_id=translation_id,
                    )

                    output_parts.append(f"## {title}\n\n{translated.strip()}\n")
                except Exception as section_error:
                    logger.warning(f"Section translation failed: {title}", exc_info=True)
                    output_parts.append(f"## {title}\n\n*[翻译失败: {str(section_error)[:100]}]*\n\n{source[:500]}...\n")
                    await self.publish_progress(translation_id, {
                        "type": "section_error",
                        "section_title": title,
                        "error": str(section_error)[:200],
                    })

                translation.content_md = "\n\n".join(output_parts)
                await self.db.commit()

                await self.publish_progress(translation_id, {
                    "type": "progress",
                    "step": "section_done",
                    "current": idx,
                    "total": total,
                    "section_title": title,
                })

                try:
                    await self._detect_and_save_terms(
                        source, known_phrases, paper.project_id, paper.id, term_service, translation_id, title, term_memory
                    )
                except Exception:
                    logger.warning(f"Term detection failed for section: {title}", exc_info=True)

            translation.status = "succeeded"
            translation.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
            await self.publish_progress(translation_id, {
                "type": "status",
                "status": "succeeded",
                "completed_at": translation.completed_at.isoformat(),
            })

        except Exception as e:
            logger.exception("Translation failed", extra={"translation_id": str(translation_id)})
            translation.status = "failed"
            translation.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
            await self.publish_progress(translation_id, {"type": "status", "status": "failed"})
            await self.publish_progress(translation_id, {"type": "error", "message": str(e)})
        finally:
            self.cleanup_progress(translation_id)

    async def _load_paper(self, paper_id: uuid.UUID) -> Paper | None:
        result = await self.db.execute(
            select(Paper)
            .options(selectinload(Paper.sections))
            .where(Paper.id == paper_id)
        )
        return result.scalar_one_or_none()

    def _sort_sections(self, sections: list[PaperSection]) -> list[PaperSection]:
        return sorted(
            sections,
            key=lambda s: ((s.page_start or 0), (s.char_start or 0), s.created_at),
        )

    async def _infer_domain(self, paper: Paper) -> str:
        prompt = f"""根据论文标题和摘要判断所属学术领域，用中文短语回答，不超过20字。
标题: {paper.title}
摘要: {(paper.abstract or "")[:800]}

只输出领域名称。"""
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=60,
            )
            return (completion.choices[0].message.content or "").strip() or "通用"
        except Exception:
            logger.warning("Domain inference failed", exc_info=True)
            return "通用"

    async def _load_term_memory(self, project_id: uuid.UUID) -> dict[str, str]:
        result = await self.db.execute(
            select(Term)
            .options(selectinload(Term.knowledge))
            .where(Term.project_id == project_id)
            .limit(200)
        )
        return {
            t.phrase: t.knowledge.translation
            for t in result.scalars().all()
            if t.knowledge and t.knowledge.translation
        }

    def _mask_special(self, text: str) -> tuple[str, dict[str, str]]:
        if not text:
            return "", {}
        replacements: dict[str, str] = {}
        idx = 0

        patterns = [
            (re.compile(r"!\[[^\]]*\]\([^)]+\)"), "IMG"),
            (re.compile(r"```[\s\S]*?```"), "CODE"),
            (re.compile(r"\$\$[\s\S]*?\$\$"), "MATH"),
            (re.compile(r"\\\[[\s\S]*?\\\]"), "MATH"),
            (re.compile(r"\\\([\s\S]*?\\\)"), "MATH"),
            (re.compile(r"\\begin\{[^\}]+\}[\s\S]*?\\end\{[^\}]+\}"), "MATH"),
            (re.compile(r"(?<!\$)\$(?!\$)([^\n]+?)(?<!\$)\$(?!\$)"), "MATH"),
            (re.compile(r"\[[^\]]+\]\([^)]+\)"), "LINK"),
        ]

        current = text
        for pattern, kind in patterns:
            def repl(m: re.Match[str]) -> str:
                nonlocal idx
                key = f"__PM_{kind}_{idx}__"
                replacements[key] = m.group(0)
                idx += 1
                return key
            current = pattern.sub(repl, current)

        return current, replacements

    def _unmask_special(self, text: str, replacements: dict[str, str]) -> str:
        for key, value in reversed(list(replacements.items())):
            text = text.replace(key, value)
        return text

    async def _extract_images_as_base64(self, text: str) -> list[dict[str, Any]]:
        """Extract image URLs from markdown and convert to base64 for multimodal input."""
        image_pattern = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
        matches = image_pattern.findall(text)
        images: list[dict[str, Any]] = []
        storage = StorageService()

        for raw_url in matches[:4]:
            url = raw_url.strip().split()[0].strip("<>")
            url = url.split("?", 1)[0].split("#", 1)[0]
            try:
                if url.startswith("/api/v1/papers/files/"):
                    storage_key = url.removeprefix("/api/v1/papers/files/")

                    try:
                        file_path = await storage.get_file_path(storage_key)
                    except (FileNotFoundError, ValueError) as e:
                        logger.debug(f"Invalid or inaccessible image path {storage_key}: {e}")
                        continue

                    mime_type, _ = mimetypes.guess_type(str(file_path))
                    if mime_type and mime_type.startswith("image/"):
                        file_size = file_path.stat().st_size
                        if file_size > 5 * 1024 * 1024:
                            logger.debug(f"Image too large ({file_size} bytes), skipping: {storage_key}")
                            continue

                        async with aiofiles.open(file_path, "rb") as f:
                            content = await f.read()
                        b64 = base64.b64encode(content).decode("utf-8")
                        images.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{b64}"}
                        })
            except Exception as e:
                logger.debug(f"Failed to load image {url}: {e}")
                continue

        return images

    def _split_into_chunks(self, text: str, max_chars: int = 8000) -> list[str]:
        """Split text into chunks by paragraphs, keeping each chunk under max_chars (~4000 tokens)."""
        paragraphs = re.split(r'\n\n+', text)
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_len = 0

        for para in paragraphs:
            para_len = len(para)
            if current_len + para_len > max_chars and current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = [para]
                current_len = para_len
            else:
                current_chunk.append(para)
                current_len += para_len + 2

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks if chunks else [text]

    async def _get_or_create_section_groups(
        self,
        *,
        translation_id: uuid.UUID,
        section_id: uuid.UUID,
        source_text: str,
    ) -> list[TranslationGroup]:
        """Get existing groups or create new ones for a section."""
        result = await self.db.execute(
            select(TranslationGroup)
            .where(
                TranslationGroup.translation_id == translation_id,
                TranslationGroup.section_id == section_id,
            )
            .order_by(TranslationGroup.group_order)
        )
        groups = list(result.scalars().all())
        if groups:
            return groups

        masked_full, replacements = self._mask_special(source_text)
        masked_chunks = self._split_into_chunks(masked_full, max_chars=8000)

        groups = []
        order = 0
        for masked_chunk in masked_chunks:
            source_chunk = self._unmask_special(masked_chunk, replacements)
            if not source_chunk.strip():
                continue
            group = TranslationGroup(
                translation_id=translation_id,
                section_id=section_id,
                group_order=order,
                source_md=source_chunk,
                translated_md=None,
                status="queued",
                attempts=0,
                last_error=None,
            )
            self.db.add(group)
            groups.append(group)
            order += 1

        await self.db.commit()
        return groups

    def _render_group_placeholder(self, group: TranslationGroup) -> str:
        """Render placeholder text for a non-succeeded group."""
        gid = str(group.id)
        if group.status == "running":
            return f"*[翻译中: {gid}]*"
        if group.status == "queued":
            return f"*[待翻译: {gid}]*"

        error = (group.last_error or "翻译失败").strip()[:200]
        source = (group.source_md or "").strip()
        preview = source[:800] + ("..." if len(source) > 800 else "")
        return f"*[翻译失败，可重试: {gid}] {error}*\n\n{preview}"

    async def _translate_masked_chunk(
        self,
        *,
        masked_chunk: str,
        replacements: dict[str, str],
        domain: str,
        memory_lines: str,
        tool_names: str,
        target: str,
        paper_title: str,
        section_title: str,
        chunk_index: int,
        chunk_total: int,
        agent: ReActAgent,
        images: list[dict[str, Any]] | None = None,
    ) -> str:
        """Translate a single masked chunk using the ReAct agent."""
        chunk_placeholders = [k for k in replacements.keys() if k in masked_chunk]
        ph_note = f"占位符: {', '.join(chunk_placeholders)}" if chunk_placeholders else ""

        system_prompt = f"""你是{domain}领域的学术论文翻译专家，使用ReAct架构工作。

可用工具：{tool_names}

**翻译流程（严格遵循）**：
1. 识别专业术语：扫描文本，提取领域专业术语（非通用词汇）
2. 查询术语用法：
   - 遇到重要术语时，使用arxiv_search搜索相关论文，了解学术界标准用法
   - 使用其他搜索工具查询权威翻译和定义
   - 参考下方"项目术语记忆"保持翻译一致性
3. 生成翻译：
   - 术语保留英文原词，括号注中文，如"Reinforcement Learning（强化学习）"
   - 输出纯Markdown，无额外说明

**占位符处理（极其重要！）**：
- 文本中的 __PM_IMG_xxx__、__PM_MATH_xxx__、__PM_CODE_xxx__、__PM_LINK_xxx__ 是占位符
- 这些占位符代表图片、公式、代码块、链接，**必须原样保留在译文中**
- 不要翻译、修改、删除任何占位符
- 占位符应该保持在译文中与原文相同的相对位置

**重要**：
- 遇到不确定的术语，必须主动调用工具查询，不可凭猜测翻译
- 已有项目记忆的术语，必须使用记忆中的翻译保持一致性
- 输出仅包含译文，不要输出工具调用过程或思考过程"""

        context = f"《{paper_title}》{section_title} 第{chunk_index + 1}/{chunk_total}段。" if chunk_total > 1 else f"《{paper_title}》{section_title}。"

        text_prompt = f"""{context}
术语：{memory_lines[:400]}
{ph_note}

翻译为{target}：
{masked_chunk}"""

        if images:
            user_prompt: str | list[dict[str, Any]] = [
                {"type": "text", "text": text_prompt},
                *images,
            ]
        else:
            user_prompt = text_prompt

        content = await agent.run(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        if not content or not content.strip():
            raise ValueError("Empty translation")

        out = content.strip()
        for key, value in replacements.items():
            if key not in masked_chunk:
                continue
            count = out.count(key)
            if count > 1:
                logger.warning(f"Placeholder {key} duplicated {count}x, deduping")
                pos = out.find(key)
                out = out[:pos + len(key)] + out[pos + len(key):].replace(key, "")
            elif count == 0:
                logger.warning(f"Placeholder {key} missing, restoring original")
                out += f"\n\n{value}"

        return self._unmask_special(out, replacements)

    async def _translate_and_store_group(
        self,
        *,
        group: TranslationGroup,
        translation_id: uuid.UUID,
        section_title: str,
        paper_title: str,
        domain: str,
        memory_lines: str,
        tool_names: str,
        target: str,
        agent: ReActAgent,
        chunk_index: int,
        chunk_total: int,
        images: list[dict[str, Any]] | None = None,
    ) -> None:
        """Translate a single group and store the result."""
        group.status = "running"
        group.attempts += 1
        group.last_error = None
        await self.db.commit()
        await self.publish_progress(translation_id, {
            "type": "group_status",
            "group_id": str(group.id),
            "section_title": section_title,
            "status": "running",
            "attempts": group.attempts,
        })

        try:
            masked_chunk, replacements = self._mask_special(group.source_md)
            translated = await self._translate_masked_chunk(
                masked_chunk=masked_chunk,
                replacements=replacements,
                domain=domain,
                memory_lines=memory_lines,
                tool_names=tool_names,
                target=target,
                paper_title=paper_title,
                section_title=section_title,
                chunk_index=chunk_index,
                chunk_total=chunk_total,
                agent=agent,
                images=images,
            )
            group.translated_md = translated.strip()
            group.status = "succeeded"
            group.last_error = None
        except Exception as e:
            group.translated_md = None
            group.status = "failed"
            group.last_error = str(e)[:500]
            logger.warning(f"Group translation failed: {group.id}", exc_info=True)
            await self.publish_progress(translation_id, {
                "type": "group_error",
                "group_id": str(group.id),
                "section_title": section_title,
                "error": group.last_error[:200],
            })

        await self.db.commit()
        payload: dict[str, Any] = {
            "type": "group_status",
            "group_id": str(group.id),
            "section_title": section_title,
            "status": group.status,
            "attempts": group.attempts,
        }
        if group.last_error:
            payload["error"] = group.last_error[:200]
        await self.publish_progress(translation_id, payload)

    async def _rebuild_translation_content_md(self, *, translation_id: uuid.UUID, paper: Paper) -> str:
        """Rebuild the full translation content from all groups."""
        result = await self.db.execute(
            select(TranslationGroup)
            .where(TranslationGroup.translation_id == translation_id)
            .order_by(TranslationGroup.section_id, TranslationGroup.group_order)
        )
        groups = list(result.scalars().all())
        by_section: dict[uuid.UUID, list[TranslationGroup]] = {}
        for g in groups:
            by_section.setdefault(g.section_id, []).append(g)

        output_parts: list[str] = []
        sections = self._sort_sections(paper.sections)

        for idx, section in enumerate(sections, start=1):
            title = section.title or section.section_type or f"Section {idx}"
            section_groups = by_section.get(section.id) or []
            if not section_groups:
                source = section.content_md or section.content_text or ""
                if not source.strip():
                    continue
                output_parts.append(f"## {title}\n\n{source.strip()}\n")
                continue

            section_groups.sort(key=lambda g: g.group_order)
            parts: list[str] = []
            for g in section_groups:
                if g.status == "succeeded" and (g.translated_md or "").strip():
                    parts.append(g.translated_md.strip())
                else:
                    parts.append(self._render_group_placeholder(g))
            body = "\n\n".join(parts).strip()
            output_parts.append(f"## {title}\n\n{body}\n")

        return "\n\n".join(output_parts).strip()

    async def _translate_section(
        self,
        source_text: str,
        section_title: str,
        section_id: uuid.UUID,
        domain: str,
        term_memory: dict[str, str],
        mode: str,
        target_language: str,
        paper_title: str,
        paper_abstract: str,
        translation_id: uuid.UUID,
    ) -> str:
        """Translate a section using TranslationGroups for retry support."""
        groups = await self._get_or_create_section_groups(
            translation_id=translation_id,
            section_id=section_id,
            source_text=source_text,
        )
        if not groups:
            return source_text.strip()

        images: list[dict[str, Any]] = []
        try:
            images = await self._extract_images_as_base64(source_text)
        except Exception:
            logger.debug("Failed to extract images for section", exc_info=True)

        memory_lines = "\n".join(
            f"- {en} -> {zh}" for en, zh in list(term_memory.items())[:30]
        ) or "无"
        target = "中文" if target_language.startswith("zh") else target_language
        tool_names = ", ".join(t.name for t in self.tools) if self.tools else "无"

        logger.info(f"Translating section '{section_title}': {len(source_text)} chars, {len(groups)} groups")

        async def on_tool_progress(event: dict) -> None:
            await self.publish_progress(translation_id, event)

        agent = ReActAgent(
            client=self.client,
            tools=self.tools,
            max_steps=3,
            temperature=0.1,
            on_progress=on_tool_progress,
        )

        translated_parts: list[str] = []
        group_total = len(groups)

        for i, group in enumerate(groups):
            if group.status == "succeeded" and (group.translated_md or "").strip():
                translated_parts.append(group.translated_md.strip())
                continue

            if group.status == "running":
                group.status = "queued"
                await self.db.commit()

            if group_total > 1:
                await self.publish_progress(translation_id, {
                    "type": "chunk_progress",
                    "chunk_current": i + 1,
                    "chunk_total": group_total,
                    "group_id": str(group.id),
                    "message": f"翻译第 {i + 1}/{group_total} 段",
                })

            await self._translate_and_store_group(
                group=group,
                translation_id=translation_id,
                section_title=section_title,
                paper_title=paper_title,
                domain=domain,
                memory_lines=memory_lines,
                tool_names=tool_names,
                target=target,
                agent=agent,
                chunk_index=i,
                chunk_total=group_total,
                images=images if (images and i == 0) else None,
            )

            if group.status == "succeeded" and (group.translated_md or "").strip():
                translated_parts.append(group.translated_md.strip())
            else:
                translated_parts.append(self._render_group_placeholder(group))

        return "\n\n".join(translated_parts).strip()

    async def _detect_and_save_terms(
        self,
        source_text: str,
        known_phrases: set[str],
        project_id: uuid.UUID,
        paper_id: uuid.UUID,
        term_service: TermService,
        translation_id: uuid.UUID,
        section_title: str,
        term_memory: dict[str, str],
    ) -> None:
        try:
            new_terms = await self._detect_new_terms(source_text, known_phrases)
            if new_terms:
                await self.publish_progress(translation_id, {
                    "type": "term_suggestions",
                    "section_title": section_title,
                    "terms": new_terms,
                })
            for phrase in new_terms:
                if phrase.lower() in {p.lower() for p in known_phrases}:
                    continue
                translation = await self._save_term(phrase, project_id, paper_id, term_service)
                if translation:
                    known_phrases.add(phrase)
                    term_memory[phrase] = translation
        except Exception:
            logger.warning("Term detection failed", exc_info=True)

    async def _detect_new_terms(self, source_text: str, existing: set[str]) -> list[str]:
        existing_lower = {t.lower() for t in existing}
        truncated = source_text[:3000]
        preview = list(existing)[:50]

        prompt = f"""从下面英文内容识别需要加入术语库的新学术术语。
已知术语（无需返回）: {preview}

要求：
- 只返回英文术语短语
- 排除一般词汇
- 最多返回 6 个

内容：
{truncated}

只返回 JSON 数组: ["term1", "term2"]"""

        completion = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=250,
        )
        raw = (completion.choices[0].message.content or "[]").strip()

        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1].strip() if len(parts) >= 2 else raw
            if raw.startswith("json"):
                raw = raw[4:].strip()

        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end > start:
            raw = raw[start:end + 1]

        try:
            data = json.loads(raw)
        except Exception:
            return []

        if not isinstance(data, list):
            return []

        out: list[str] = []
        seen: set[str] = set()
        for item in data:
            if not isinstance(item, str):
                continue
            term = item.strip()
            if not term or len(term) > 100:
                continue
            lower = term.lower()
            if lower in existing_lower or lower in seen:
                continue
            seen.add(lower)
            out.append(term)
            if len(out) >= 6:
                break
        return out

    async def _save_term(
        self,
        phrase: str,
        project_id: uuid.UUID,
        paper_id: uuid.UUID,
        term_service: TermService,
    ) -> str | None:
        normalized = " ".join(phrase.strip().split())
        existing = await self.db.scalar(
            select(Term.id).where(
                Term.project_id == project_id,
                func.lower(Term.phrase) == normalized.lower()
            )
        )
        if existing:
            return None

        analysis = await term_service.analyze_term(phrase=normalized, project_id=project_id, paper_id=paper_id)
        trans = (analysis.get("translation") or "").strip()
        explanation = (analysis.get("explanation") or "").strip()
        if not trans or trans == "解析失败":
            return None

        term = Term(project_id=project_id, phrase=normalized, language="en")
        self.db.add(term)
        await self.db.flush()

        knowledge = KnowledgeTerm(
            term_id=term.id,
            canonical_en=normalized,
            translation=trans,
            definition=explanation,
            sources={"sources": analysis.get("sources") or []},
            status="pending",
        )
        self.db.add(knowledge)

        try:
            await self.db.commit()
            return trans
        except Exception:
            await self.db.rollback()
            logger.warning("Failed to save term", exc_info=True)
            return None

    async def retry_group(self, group_id: uuid.UUID) -> None:
        """Retry translation of a single failed group."""
        group = await self.db.get(TranslationGroup, group_id)
        if not group:
            raise ValueError("Translation group not found")

        if group.status == "running":
            raise ValueError("Translation group is running")

        translation = await self.db.get(PaperTranslation, group.translation_id)
        if not translation:
            raise ValueError("Translation not found")

        # Load user-specific settings
        user_settings = await get_openai_settings(self.db, translation.user_id)

        # Create OpenAI client with user-specific settings
        self.client = AsyncOpenAI(
            api_key=user_settings["api_key"] or None,
            base_url=user_settings["base_url"] or None,
        )
        self.model = user_settings["model"]

        group.status = "queued"
        group.translated_md = None
        group.last_error = None
        await self.db.commit()

        paper = await self._load_paper(translation.paper_id)
        if not paper:
            raise ValueError("Paper not found")

        project = await self.db.get(Project, paper.project_id)
        domain = (project.domain if project else None) or await self._infer_domain(paper)

        term_memory = await self._load_term_memory(paper.project_id)
        memory_lines = "\n".join(
            f"- {en} -> {zh}" for en, zh in list(term_memory.items())[:30]
        ) or "无"

        target = "中文" if translation.target_language.startswith("zh") else translation.target_language
        tool_names = ", ".join(t.name for t in self.tools) if self.tools else "无"

        section = next((s for s in paper.sections if s.id == group.section_id), None)
        section_title = ((section.title or section.section_type) if section else None) or "Section"

        async def on_tool_progress(event: dict) -> None:
            await self.publish_progress(translation.id, event)

        agent = ReActAgent(
            client=self.client,
            tools=self.tools,
            max_steps=3,
            temperature=0.1,
            on_progress=on_tool_progress,
        )

        group_total = await self.db.scalar(
            select(func.count())
            .select_from(TranslationGroup)
            .where(
                TranslationGroup.translation_id == translation.id,
                TranslationGroup.section_id == group.section_id,
            )
        )
        chunk_total = int(group_total or 0) or 1

        images: list[dict[str, Any]] = []
        try:
            images = await self._extract_images_as_base64(group.source_md)
        except Exception:
            logger.debug("Failed to extract images for group retry", exc_info=True)

        await self._translate_and_store_group(
            group=group,
            translation_id=translation.id,
            section_title=section_title,
            paper_title=paper.title,
            domain=domain,
            memory_lines=memory_lines,
            tool_names=tool_names,
            target=target,
            agent=agent,
            chunk_index=group.group_order,
            chunk_total=chunk_total,
            images=images or None,
        )

        translation.content_md = await self._rebuild_translation_content_md(
            translation_id=translation.id,
            paper=paper,
        )
        await self.db.commit()


async def run_translation_task(translation_id: uuid.UUID) -> None:
    async with async_session_maker() as db:
        service = TranslationService(db)
        await service.run_translation(translation_id)


async def run_translation_group_retry_task(group_id: uuid.UUID) -> None:
    async with async_session_maker() as db:
        service = TranslationService(db)
        await service.retry_group(group_id)
