import uuid
import json
import logging
import re
import httpx
from typing import Any
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from openai import AsyncOpenAI
from app.core.config import get_settings
from app.services.react_agent import ReActAgent
from app.services.tools import ArxivSearchTool, BaseTool, TavilyTool
from app.models import Term, TermOccurrence, KnowledgeTerm, Paper, PaperSection, Project


settings = get_settings()
logger = logging.getLogger(__name__)


class TermService:
    MAX_EMPTY_CONTENT_RETRIES = 2

    def __init__(self, db: AsyncSession):
        self.db = db
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key or None,
            base_url=settings.openai_base_url or None
        )

    def _term_system_prompt(self) -> str:
        return (
            "你是学术论文术语翻译与解释助手。"
            "输出语言：简体中文。"
            "只输出最终答案，不要输出思考过程/推理/自我对话。"
            "如果模型会输出推理内容，请把最终答案放在 <final>...</final> 内。"
            "除术语本身和常见缩写（如 LLM/GPU/CNN）外不要使用英文单词。"
        )

    def _redact_reasoning_fields(self, obj):
        if isinstance(obj, dict):
            return {
                k: self._redact_reasoning_fields(v)
                for k, v in obj.items()
                if k not in {"reasoning_content"}
            }
        if isinstance(obj, list):
            return [self._redact_reasoning_fields(x) for x in obj]
        return obj

    async def _raw_chat_completion(
        self,
        prompt: str,
        max_tokens: int | None = 600,
        phrase: str | None = None,
        debug: bool = False,
        response_format: dict | None = None,
    ) -> str:
        """Call OpenAI-compatible endpoint via raw HTTP and return best-effort text.

        When debug=True, log the raw provider response (truncated).
        """
        base = (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
        # If user configured a bare host without /v1, prefer /v1 for OpenAI-style APIs.
        if not base.endswith("/v1") and "/v1/" not in base:
            base = f"{base}/v1"
        url = f"{base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        debug_enabled = settings.debug and debug
        system_prompt = self._term_system_prompt()
        payload = {
            "model": settings.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.8,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = response_format
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=payload)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as err:
                # Some OpenAI-compatible providers don't support response_format.
                if response_format is not None and err.response.status_code in (400, 422):
                    payload.pop("response_format", None)
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                else:
                    raise
            data = resp.json()
        debug_enabled = settings.debug and debug
        if debug_enabled:
            safe_data = self._redact_reasoning_fields(data)
            try:
                raw_preview = json.dumps(safe_data, ensure_ascii=False)[:5000]
            except Exception:
                raw_preview = str(safe_data)[:5000]
            logger.info("Raw term analyze response preview: %s", raw_preview)
            try:
                # Store under backend/app/tmp for easy access during local debugging.
                debug_dir = Path(__file__).resolve().parents[1] / "tmp"
                debug_dir.mkdir(parents=True, exist_ok=True)
                debug_path = debug_dir / "term_analyze_raw.json"
                debug_path.write_text(json.dumps(safe_data, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info("Raw term analyze response saved to %s", debug_path)
            except Exception:
                logger.warning("Failed to save raw term analyze response", exc_info=True)

        choices = data.get("choices") or []
        if not choices:
            return ""
        choice0 = choices[0] or {}
        msg = choice0.get("message") or {}
        # Only use final content; do not surface chain-of-thought fields.
        content = msg.get("content") or choice0.get("text") or ""
        if not content:
            reasoning = msg.get("reasoning_content") or ""
            if reasoning:
                content = self._extract_final_from_reasoning(reasoning, phrase)
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    parts.append(str(part["text"]))
            content = "".join(parts)
        final_text = self._extract_final_from_text(str(content), phrase=phrase)
        return self._strip_thinking(final_text).strip()

    def _strip_thinking(self, text: str) -> str:
        """Remove provider reasoning blocks like <thinking>...</thinking> or <analysis>...</analysis>."""
        if not text:
            return ""
        cleaned = re.sub(r"<thinking[^>]*>[\s\S]*?</thinking>", "", text, flags=re.I)
        cleaned = re.sub(r"<think[^>]*>[\s\S]*?</think>", "", cleaned, flags=re.I)
        cleaned = re.sub(r"<reasoning[^>]*>[\s\S]*?</reasoning>", "", cleaned, flags=re.I)
        cleaned = re.sub(r"<analysis[^>]*>[\s\S]*?</analysis>", "", cleaned, flags=re.I)
        # Keep <final> inner text if present.
        cleaned = re.sub(r"</?final[^>]*>", "", cleaned, flags=re.I)
        return cleaned.strip()

    def _get_term_tools(self) -> list[BaseTool]:
        tools: list[BaseTool] = [ArxivSearchTool()]
        if settings.tavily_api_key:
            tavily_tool = TavilyTool(settings.tavily_api_key)
            if getattr(tavily_tool, "_client", None) is not None:
                tools.append(tavily_tool)
        return tools

    def _compact_context_paragraphs(
        self,
        text: str | None,
        *,
        max_paragraphs: int = 5,
        max_chars: int | None = None,
    ) -> list[str]:
        raw = (text or "").strip()
        if not raw:
            return []
        parts = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
        if not parts:
            parts = [raw]

        out: list[str] = []
        total = 0
        for part in parts:
            if len(out) >= max_paragraphs:
                break
            if max_chars is not None:
                remaining = max_chars - total
                if remaining <= 0:
                    break
            cleaned = re.sub(r"\s+", " ", part).strip()
            if not cleaned:
                continue
            if max_chars is not None and len(cleaned) > remaining:
                cleaned = cleaned[:remaining].rstrip()
            out.append(cleaned)
            total += len(cleaned)
        return out

    def _extract_final_from_reasoning(self, reasoning: str, phrase: str | None = None) -> str:
        """Some providers put the final answer in reasoning_content; extract safely."""
        if not reasoning:
            return ""
        m = re.search(r"(?is)<final[^>]*>(.*?)</final>", reasoning)
        if m:
            return m.group(1).strip()
        # Prefer explicit final markers.
        m = re.search(r"(?:最终答案|Final Answer|Answer)\s*[:：]\s*([\s\S]+)$", reasoning, re.I)
        if m:
            candidate = m.group(1).strip()
            return candidate

        lines = [ln.strip() for ln in reasoning.splitlines() if ln.strip()]
        if not lines:
            return ""
        # Prefer explicit translation labels if present.
        for line in reversed(lines):
            m = re.search(r"(?:中文翻译|译名|翻译)\s*[:：]\s*(.+)$", line, flags=re.I)
            if m:
                return m.group(1).strip()
        if phrase:
            for line in reversed(lines):
                # Old format: "{phrase}（译名）: 解释"
                if re.match(
                    rf"^{re.escape(phrase)}\s*[（(][^）)]+[）)]\s*[:：]\s*.+$",
                    line,
                    flags=re.I,
                ):
                    return line
                m = re.match(rf"^{re.escape(phrase)}\s*[:：]\s*(.+)$", line, flags=re.I)
                if m:
                    return m.group(1).strip()

        # Last resort: a Chinese-looking line without reasoning cues.
        for line in reversed(lines):
            if re.search(r"(?:思考|推理|分析|reasoning|analysis)\s*[:：]?", line, re.I):
                continue
            if re.search(r"(?:okay, so|let me|i think|i need|step by step)", line, re.I):
                continue
            if re.search(r"[\u4e00-\u9fff]", line) and len(line) <= 300:
                return line
        return ""

    def _extract_final_from_text(self, text: str, phrase: str | None = None) -> str:
        """Extract final answer from mixed reasoning+final text (best-effort)."""
        if not text:
            return ""

        # Prefer explicit <final> markers.
        m = re.search(r"(?is)<final[^>]*>(.*?)</final>", text)
        if m:
            return m.group(1).strip()

        # Prefer explicit final markers.
        marker_patterns = (
            r"(?:最终答案|最终输出|最终回复|最终结论|最终结果|答案|Final Answer|Final|Answer)\s*[:：]\s*",
            r"(?:最终答案|最终输出|答案)\s*\n+",
        )
        for pat in marker_patterns:
            m = re.search(pat + r"([\s\S]+)$", text, re.I)
            if m:
                return m.group(1).strip()

        cleaned = self._strip_thinking(text)
        for pat in marker_patterns:
            m = re.search(pat + r"([\s\S]+)$", cleaned, re.I)
            if m:
                return m.group(1).strip()

        return cleaned.strip()

    def _extract_text_from_completion(self, completion, phrase: str | None = None) -> str:
        """Best-effort text extraction from SDK completion object."""
        try:
            choice = completion.choices[0]
        except Exception:
            return ""
        message = getattr(choice, "message", None)
        if message is not None:
            content = getattr(message, "content", None)
            if not content:
                reasoning = getattr(message, "reasoning_content", None)
                if isinstance(reasoning, str) and reasoning.strip():
                    content = self._extract_final_from_reasoning(reasoning, phrase=phrase)
            if isinstance(content, list):
                parts: list[str] = []
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        parts.append(str(part["text"]))
                content = "".join(parts)
            if isinstance(content, str) and content.strip():
                final_text = self._extract_final_from_text(content, phrase=phrase)
                return self._strip_thinking(final_text).strip()
        text = getattr(choice, "text", None)
        if isinstance(text, str) and text.strip():
            final_text = self._extract_final_from_text(text, phrase=phrase)
            return self._strip_thinking(final_text).strip()
        # raw dict fallback
        try:
            raw = completion.model_dump()
        except Exception:
            raw = {}
        choices = raw.get("choices") or []
        if choices:
            msg = (choices[0].get("message") or {})
            cand = msg.get("content") or choices[0].get("text") or ""
            if not cand and msg.get("reasoning_content"):
                cand = self._extract_final_from_reasoning(str(msg.get("reasoning_content")), phrase=phrase)
            if isinstance(cand, list):
                parts: list[str] = []
                for part in cand:
                    if isinstance(part, dict) and "text" in part:
                        parts.append(str(part["text"]))
                cand = "".join(parts)
            if isinstance(cand, str):
                final_text = self._extract_final_from_text(cand, phrase=phrase)
                return self._strip_thinking(final_text).strip()
        return ""

    def _build_fuzzy_pattern(self, phrase: str) -> re.Pattern:
        """Build a case-insensitive regex that tolerates whitespace and dash variants."""
        normalized = re.sub(r"\s+", " ", phrase.strip())
        if not normalized:
            return re.compile(r"(?!x)x")

        # Actual dash characters we want to normalize / match.
        dash_variants = "‐‑‒–—−-"
        dash_class = r"[-‐‑‒–—−]"
        parts: list[str] = []
        for token in normalized.split(" "):
            token_norm = re.sub(f"[{dash_variants}]", "-", token)
            escaped = re.escape(token_norm)
            escaped = escaped.replace(r"\-", dash_class)
            parts.append(escaped)
        pattern = r"\s+".join(parts)
        return re.compile(pattern, re.IGNORECASE)

    async def _build_paper_full_text(self, paper: Paper) -> str:
        """Build full text from paper abstract and sections."""
        full_text = paper.abstract or ""
        sections_result = await self.db.execute(
            select(PaperSection).where(PaperSection.paper_id == paper.id)
        )
        for section in sections_result.scalars().all():
            if section.content_text:
                full_text += " " + section.content_text
        return full_text

    def _add_term_occurrences(
        self, term: Term, paper_id: uuid.UUID, full_text: str
    ) -> int:
        """Find and add all occurrences of a term in the full text."""
        pattern = self._build_fuzzy_pattern(term.phrase)
        occurrence_count = 0
        for match in pattern.finditer(full_text):
            pos = match.start()
            end = match.end()
            snippet_start = max(0, pos - 50)
            snippet_end = min(len(full_text), end + 50)
            snippet = full_text[snippet_start:snippet_end]

            occurrence = TermOccurrence(
                term_id=term.id,
                paper_id=paper_id,
                char_start=pos,
                char_end=end,
                text_snippet=snippet,
            )
            self.db.add(occurrence)
            occurrence_count += 1
        return occurrence_count

    async def scan_paper_for_terms(self, paper_id: uuid.UUID, project_id: uuid.UUID) -> int:
        terms_result = await self.db.execute(
            select(Term)
            .options(selectinload(Term.knowledge))
            .where(Term.project_id == project_id)
        )
        terms = terms_result.scalars().all()

        paper = await self.db.get(Paper, paper_id)
        if not paper:
            return 0

        full_text = await self._build_paper_full_text(paper)
        occurrence_count = 0

        for term in terms:
            occurrence_count += self._add_term_occurrences(term, paper_id, full_text)

        await self.db.commit()
        return occurrence_count

    async def scan_paper_for_term(self, term_id: uuid.UUID, paper_id: uuid.UUID) -> int:
        term = await self.db.get(Term, term_id)
        paper = await self.db.get(Paper, paper_id)
        if not term or not paper:
            return 0

        # Clear existing occurrences for this term+paper to avoid duplicates.
        await self.db.execute(
            TermOccurrence.__table__.delete().where(
                TermOccurrence.term_id == term_id,
                TermOccurrence.paper_id == paper_id,
            )
        )

        full_text = await self._build_paper_full_text(paper)
        occurrence_count = self._add_term_occurrences(term, paper_id, full_text)

        await self.db.commit()
        return occurrence_count

    async def get_term_occurrences_in_paper(
        self, paper_id: uuid.UUID, project_id: uuid.UUID
    ) -> list[dict]:
        result = await self.db.execute(
            select(TermOccurrence, Term, KnowledgeTerm)
            .join(Term, Term.id == TermOccurrence.term_id)
            .outerjoin(KnowledgeTerm, KnowledgeTerm.term_id == Term.id)
            .where(
                TermOccurrence.paper_id == paper_id,
                Term.project_id == project_id
            )
        )
        rows = result.all()

        occurrences = []
        for occ, term, knowledge in rows:
            occurrences.append({
                "term_id": str(term.id),
                "phrase": term.phrase,
                "translation": knowledge.translation if knowledge else None,
                "definition": knowledge.definition if knowledge else None,
                "char_start": occ.char_start,
                "char_end": occ.char_end
            })

        return occurrences

    async def analyze_term(
        self,
        phrase: str,
        project_id: uuid.UUID,
        paper_id: uuid.UUID | None = None,
        context: str | None = None,
        debug_raw: bool = False,
    ) -> dict:
        # If term already exists with knowledge, return it
        existing_result = await self.db.execute(
            select(Term)
            .options(selectinload(Term.knowledge))
            .where(Term.project_id == project_id, Term.phrase == phrase)
        )
        existing_term = existing_result.scalar_one_or_none()
        if existing_term and existing_term.knowledge:
            existing_translation = existing_term.knowledge.translation or ""
            if existing_translation and "解析失败" not in existing_translation:
                return {
                    "term": existing_term.phrase,
                    "translation": existing_translation,
                    "explanation": existing_term.knowledge.definition or "",
                    "sources": []
                }

        project_result = await self.db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = project_result.scalar_one_or_none()
        domain = project.domain if project else None

        paper_title = None
        paper_abstract = None
        if paper_id:
            paper_result = await self.db.execute(
                select(Paper).where(Paper.id == paper_id)
            )
            paper = paper_result.scalar_one_or_none()
            if paper:
                paper_title = paper.title
                paper_abstract = paper.abstract

        known_terms_result = await self.db.execute(
            select(Term)
            .options(selectinload(Term.knowledge))
            .where(Term.project_id == project_id)
            .limit(50)
        )
        known_terms = [
            f"{t.phrase}（{t.knowledge.translation}）"
            for t in known_terms_result.scalars().all()
            if t.knowledge and t.knowledge.translation
        ][:20]

        # Use provided context, fallback to abstract
        effective_context = context or (paper_abstract or "")
        context_paragraphs = self._compact_context_paragraphs(
            effective_context, max_paragraphs=5
        )
        context_block = "\n\n".join(
            f"[段落{i + 1}] {p}" for i, p in enumerate(context_paragraphs)
        )

        try:
            tools = self._get_term_tools()
            tool_hint = "、".join(t.name for t in tools) if tools else "无"
            system_prompt = (
                "你是学术论文术语解释助手。"
                f"可使用检索工具：{tool_hint}。"
                "优先根据上下文判断，不确定再检索。"
                "输出80-120字简体中文解释，不要输出思考过程。"
                "如果模型会输出推理内容，请把最终答案放在 <final>...</final> 内。"
            )
            user_prompt = (
                f"术语：{phrase}\n"
                f"论文领域: {domain or '通用/未知'}\n"
                f"论文标题: {paper_title or '未知'}\n"
                "上下文（3-5段）：\n"
                f"{context_block or '（无）'}\n\n"
                "请解释该术语在上下文中的含义。"
            )

            agent = ReActAgent(
                client=self.client,
                tools=tools,
                max_steps=3,
                temperature=0.2,
                tool_output_limit=2000,
                max_tool_messages=4,
            )
            explanation = await agent.run(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=300,
            )

            if not explanation:
                agent_no_tools = ReActAgent(
                    client=self.client,
                    tools=tools,
                    max_steps=2,
                    temperature=0.2,
                    disable_tools=True,
                )
                explanation = await agent_no_tools.run(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=300,
                )

            if not explanation:
                explanation = await self._raw_chat_completion(
                    prompt=user_prompt,
                    max_tokens=300,
                    phrase=phrase,
                    debug=debug_raw,
                    response_format={"type": "text"},
                )

            if not explanation:
                explanation = await self._raw_chat_completion(
                    prompt=user_prompt,
                    max_tokens=None,
                    phrase=phrase,
                    debug=debug_raw,
                )

            if not explanation:
                logger.warning("Failed to get explanation for term: %s", phrase)
                explanation = f"术语 {phrase} 的解释暂时无法获取。"
            else:
                explanation = self._strip_thinking(
                    self._extract_final_from_text(explanation, phrase=phrase)
                ).strip()

            # === Step 2: Get translation ===
            translate_prompt = f"""术语：{phrase}
术语解释：{explanation}

项目已有术语翻译(参考风格): {known_terms}

请给出这个术语的中文译名。如果是专有名词可保留原名或使用"中文（原文）"格式。只输出译名本身。"""

            translate_messages = [{"role": "user", "content": translate_prompt}]

            translation = await self._chat_completion_simple(
                translate_messages, max_tokens=100, debug=debug_raw
            )
            if not translation:
                translation = await self._raw_chat_completion(
                    prompt=translate_prompt,
                    max_tokens=100,
                    phrase=phrase,
                    debug=debug_raw,
                    response_format={"type": "text"},
                )
            if not translation:
                translation = await self._raw_chat_completion(
                    prompt=translate_prompt,
                    max_tokens=None,
                    phrase=phrase,
                    debug=debug_raw,
                )

            if translation:
                translation = translation.strip().split('\n')[0].strip()

            if not translation:
                translation = phrase

            return {
                "term": phrase,
                "translation": translation,
                "explanation": explanation,
                "sources": [],
            }
        except Exception as e:
            logger.warning("Term analyze failed: %s", str(e), exc_info=settings.debug)
            return {
                "term": phrase,
                "translation": "解析失败",
                "explanation": "解析失败，请检查 OpenAI 配置或稍后重试。",
                "sources": []
            }

    async def _chat_completion_simple(
        self,
        messages: list[dict],
        max_tokens: int = 400,
        debug: bool = False,
    ) -> str:
        """Simple chat completion."""
        base = (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
        if not base.endswith("/v1") and "/v1/" not in base:
            base = f"{base}/v1"
        url = f"{base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        local_messages = list(messages)
        empty_retries = 0
        debug_enabled = settings.debug and debug
        while True:
            payload = {
                "model": settings.openai_model,
                "messages": local_messages,
                "temperature": 0.8,
                "max_tokens": max_tokens,
                "stream": False,
            }

            if debug_enabled:
                logger.info("Sending messages: %s", json.dumps(local_messages, ensure_ascii=False)[:1000])

            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

            if debug_enabled:
                safe_data = self._redact_reasoning_fields(data)
                logger.info("Response: %s", json.dumps(safe_data, ensure_ascii=False)[:2000])

            choices = data.get("choices") or []
            if not choices:
                return ""

            message = choices[0].get("message") or {}
            content = message.get("content") or choices[0].get("text") or ""
            if not content and message.get("reasoning_content"):
                content = self._extract_final_from_reasoning(
                    str(message.get("reasoning_content")), phrase=None
                )
            if isinstance(content, list):
                parts: list[str] = []
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        parts.append(str(part["text"]))
                content = "".join(parts)
            content = self._strip_thinking(str(content)).strip()
            if content or empty_retries >= self.MAX_EMPTY_CONTENT_RETRIES:
                return content

            empty_retries += 1
            local_messages.append({
                "role": "user",
                "content": "请直接输出文字，不要空白。",
            })
