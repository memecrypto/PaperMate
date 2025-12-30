import uuid
import json
import logging
import re
from typing import Any, AsyncGenerator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import httpx
from app.core.config import get_settings
from app.services.tools import ToolExecutionError, get_chat_tools
from app.services.openai_settings import get_openai_settings
from app.utils.text_signals import get_signal_injection

logger = logging.getLogger(__name__)
from app.models import (
    ChatThread, ChatMessage, Paper, PaperSection, Project,
    Term, KnowledgeTerm, UserProfile
)

settings = get_settings()


class ChatService:
    MAX_EMPTY_CONTENT_RETRIES = 2

    def __init__(self, db: AsyncSession, user_id: uuid.UUID | None = None):
        self.db = db
        self.user_id = user_id
        # Will be initialized lazily in stream_response
        self.base_url: str | None = None
        self.api_key: str | None = None
        self.model: str | None = None
        self.max_tool_rounds = settings.chat_max_tool_rounds
        self._pending_terms: list[dict] = []
        self._pending_profile_updates: list[dict] = []

    async def _load_user_settings(self) -> None:
        """Load effective settings for the current user (user prefs override system defaults)."""
        user_settings = await get_openai_settings(self.db, self.user_id)
        self.base_url = user_settings["base_url"]
        self.api_key = user_settings["api_key"]
        self.model = user_settings["model"]

    def _strip_thinking(self, text: str) -> str:
        """Remove provider reasoning blocks."""
        if not text:
            return ""
        cleaned = re.sub(r"<thinking[^>]*>[\s\S]*?</thinking>", "", text, flags=re.I)
        cleaned = re.sub(r"<think[^>]*>[\s\S]*?</think>", "", cleaned, flags=re.I)
        cleaned = re.sub(r"<reasoning[^>]*>[\s\S]*?</reasoning>", "", cleaned, flags=re.I)
        cleaned = re.sub(r"<analysis[^>]*>[\s\S]*?</analysis>", "", cleaned, flags=re.I)
        cleaned = re.sub(r"</?final[^>]*>", "", cleaned, flags=re.I)
        return cleaned.strip()

    def _extract_from_reasoning(self, reasoning: str) -> str:
        """Extract final answer from reasoning content for reasoning models."""
        if not reasoning:
            return ""

        logger.info("Extracting from reasoning (len=%d): %s...", len(reasoning), reasoning[:300])

        # Try explicit <final> tags first
        m = re.search(r"(?is)<final[^>]*>(.*?)</final>", reasoning)
        if m:
            result = m.group(1).strip()
            logger.info("Extracted from <final> tag: %s", result[:200])
            return result

        # Try explicit final markers (Chinese)
        m = re.search(r"(?:最终答案|最终回复|回复内容|答案)\s*[:：]\s*([\s\S]+?)(?:\n\n|\Z)", reasoning, re.I)
        if m:
            result = m.group(1).strip()
            logger.info("Extracted from Chinese final marker: %s", result[:200])
            return result

        # Try explicit final markers (English)
        m = re.search(r"(?:Final Answer|Answer|Response)\s*[:：]\s*([\s\S]+?)(?:\n\n|\Z)", reasoning, re.I)
        if m:
            result = m.group(1).strip()
            logger.info("Extracted from English final marker: %s", result[:200])
            return result

        # Look for Chinese content blocks (likely the actual response)
        chinese_blocks = re.findall(r'[\u4e00-\u9fff][^\n]*[\u4e00-\u9fff。！？][^\n]*', reasoning)
        if chinese_blocks:
            # Find the longest Chinese block that looks like a response
            best_block = max(chinese_blocks, key=len)
            if len(best_block) > 30:
                logger.info("Extracted Chinese block: %s", best_block[:200])
                return best_block

        # Try to find the last substantial paragraph (often the conclusion)
        paragraphs = [p.strip() for p in reasoning.split('\n\n') if p.strip()]
        if paragraphs:
            # Look for a paragraph that looks like a conclusion (not starting with thinking words)
            thinking_starters = (
                'okay', 'alright', 'let me', "i'm", 'i need', 'i think', 'first',
                'so,', 'now,', 'hmm', 'well,', '好的', '让我', '首先', '那么',
                '**deciphering', '**formulating', '**clarifying', '**refining', '**defining'
            )
            for para in reversed(paragraphs):
                para_lower = para.lower()
                if not any(para_lower.startswith(s) for s in thinking_starters):
                    # Check if it contains substantial Chinese content
                    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', para))
                    if chinese_chars > 20 or len(para) > 50:
                        logger.info("Extracted last substantial paragraph: %s", para[:200])
                        return para

        # Fallback: return empty to trigger retry
        logger.warning("Could not extract meaningful content from reasoning")
        return ""

    @staticmethod
    def _collect_tool_outputs(messages: list[dict[str, Any]], *, limit: int = 5) -> list[str]:
        outs: list[str] = []
        for m in messages:
            if m.get("role") != "tool":
                continue
            content = (m.get("content") or "").strip()
            if content:
                outs.append(content)
        return outs[-limit:]

    @staticmethod
    def _compact_text(text: str, *, max_chars: int = 700, max_lines: int = 12) -> str:
        lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
        compact = "\n".join(lines[:max_lines]).strip()
        if len(compact) > max_chars:
            compact = compact[: max(0, max_chars - 3)].rstrip() + "..."
        return compact

    @classmethod
    def _fallback_from_tools(cls, messages: list[dict[str, Any]], *, reason: str) -> str:
        tool_outputs = cls._collect_tool_outputs(messages, limit=5)
        if not tool_outputs:
            return f"{reason}请稍后点击“重新发送”重试。"

        evidence = "\n\n".join(cls._compact_text(t) for t in tool_outputs[:3] if t.strip())
        return (
            f"{reason}我先根据已完成的工具检索结果给出临时说明（节选）：\n\n"
            f"{evidence}\n\n"
            "（你可以稍后点击“重新发送”再试一次，通常网络/代理恢复后即可正常回答。）"
        )

    @staticmethod
    def _format_history(messages: list[ChatMessage]) -> str:
        history = ""
        for msg in messages:
            content_json = msg.content_json or {}
            content = content_json.get("text") or ""
            attachments = content_json.get("attachments") or []
            if msg.role == "user" and attachments:
                content = f"{content}\n\n[User attached {len(attachments)} image(s)]"
            if msg.role == "user":
                role = "用户"
            elif msg.role == "system":
                role = "系统"
            else:
                role = "助手"
            history += f"{role}: {content}\n\n"
        return history

    @staticmethod
    def _branch_path_to_root(
        messages: list[ChatMessage],
        leaf_id: uuid.UUID,
        *,
        limit: int = 10,
    ) -> list[ChatMessage]:
        """Return up to last `limit` messages on the parent-pointer path ending at leaf_id."""
        msg_by_id: dict[str, ChatMessage] = {str(m.id): m for m in messages}
        cur = msg_by_id.get(str(leaf_id))
        if not cur:
            return messages[-limit:]

        path: list[ChatMessage] = []
        visited: set[str] = set()
        while cur:
            cur_id = str(cur.id)
            if cur_id in visited:
                break
            visited.add(cur_id)
            path.append(cur)
            if cur.parent_id:
                cur = msg_by_id.get(str(cur.parent_id))
            else:
                cur = None
        path.reverse()
        return path[-limit:]

    # Longer timeout for streaming with reasoning models
    STREAM_TIMEOUT_SECONDS = 300

    async def stream_response(
        self, thread_id: uuid.UUID, user_id: uuid.UUID
    ) -> AsyncGenerator[str, None]:
        logger.info("ChatService.stream_response started thread_id=%s user_id=%s", thread_id, user_id)

        # Load user-specific settings
        await self._load_user_settings()

        if not self.api_key:
            msg = "OPENAI_API_KEY 未配置，请在设置中配置 API Key"
            logger.error("ChatService cannot run: %s", msg)
            yield json.dumps({"type": "error", "message": msg})
            return

        result = await self.db.execute(
            select(ChatThread).where(ChatThread.id == thread_id)
        )
        thread = result.scalar_one_or_none()
        if not thread:
            yield json.dumps({"type": "error", "message": "Thread not found"})
            return

        messages_result = await self.db.execute(
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.created_at.asc())
        )
        messages = messages_result.scalars().all()

        context = await self._build_context(thread, user_id)
        system_prompt = self._build_system_prompt(context)

        last_user_msg = ""
        last_user_msg_id: uuid.UUID | None = None
        last_user_attachments: list[dict[str, Any]] = []
        for msg in reversed(messages):
            if msg.role == "user":
                content_json = msg.content_json or {}
                last_user_msg = content_json.get("text", "") or ""
                raw_attachments = content_json.get("attachments") or []
                if isinstance(raw_attachments, list):
                    last_user_attachments = [a for a in raw_attachments if isinstance(a, dict)]
                last_user_msg_id = msg.id
                break
        if not last_user_msg_id:
            yield json.dumps({"type": "error", "message": "No user message to respond to"})
            return

        branch_msgs = self._branch_path_to_root(messages, last_user_msg_id, limit=10)
        history = self._format_history(branch_msgs)

        self._pending_terms = []
        self._pending_profile_updates = []

        async def on_add_term(term_data: dict):
            self._pending_terms.append(term_data)
            logger.info("Term added via tool: %s", term_data.get("term"))

        async def on_update_profile(profile_data: dict):
            normalized = dict(profile_data or {})

            difficult = normalized.pop("difficult_topic", None)
            if difficult:
                added = normalized.get("added_difficult_topics", [])
                if isinstance(added, str):
                    added = [added]
                elif not isinstance(added, list):
                    added = []
                added.append(difficult)
                normalized["added_difficult_topics"] = added

            mastered = normalized.pop("mastered_topic", None)
            if mastered:
                added = normalized.get("added_mastered_topics", [])
                if isinstance(added, str):
                    added = [added]
                elif not isinstance(added, list):
                    added = []
                added.append(mastered)
                normalized["added_mastered_topics"] = added

            self._pending_profile_updates.append(normalized)
            logger.info("Profile update via tool: %s", normalized)

        project_id = context.get("project", {}).get("id")
        if not project_id:
            yield json.dumps({"type": "error", "message": "Project context unavailable"})
            return

        tools = get_chat_tools(
            db=self.db,
            project_id=project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(str(project_id)),
            paper_id=thread.scope_id if thread.scope_type == "paper" else None,
            add_term_callback=on_add_term,
            update_profile_callback=on_update_profile,
        )

        try:
            logger.info("ChatService calling streaming function-calling for thread_id=%s", thread_id)

            prompt_text = f"对话历史:\n{history}\n\n用户最新问题: {last_user_msg or '（用户上传了图片，请结合图片回答）'}"
            image_parts: list[dict[str, Any]] = []
            for att in last_user_attachments:
                data_url = att.get("data_url")
                if isinstance(data_url, str) and data_url.startswith("data:image/"):
                    image_parts.append({"type": "image_url", "image_url": {"url": data_url}})
            user_content: Any = prompt_text
            if image_parts:
                user_content = [{"type": "text", "text": prompt_text}, *image_parts]

            tool_specs = [t.openai_spec() for t in tools]
            tools_by_name = {t.name: t for t in tools}
            openai_messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]

            # Inject signal-based prompt to force profile update tool calls
            signal_injection = get_signal_injection(last_user_msg)
            if signal_injection:
                openai_messages.append(signal_injection)
                logger.info("Injected profile signal prompt: %s", signal_injection["content"][:50])

            used_tools = False
            empty_content_retries = 0
            full_response = ""

            url = f"{self.base_url}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            for round_num in range(self.max_tool_rounds):
                logger.debug("Streaming function calling round %d, messages count=%d", round_num + 1, len(openai_messages))

                payload: dict[str, Any] = {
                    "model": self.model,
                    "messages": openai_messages,
                    "temperature": 0.7,
                    "stream": True,
                }
                if tool_specs:
                    payload["tools"] = tool_specs
                    payload["tool_choice"] = "auto"

                try:
                    async with httpx.AsyncClient(timeout=self.STREAM_TIMEOUT_SECONDS) as client:
                        async with client.stream("POST", url, headers=headers, json=payload) as resp:
                            resp.raise_for_status()

                            round_text_parts: list[str] = []
                            tool_calls_by_index: dict[int, dict[str, Any]] = {}
                            reasoning_buffer = ""

                            async for line in resp.aiter_lines():
                                if not line.startswith("data: "):
                                    continue
                                data_str = line[6:].strip()
                                if data_str == "[DONE]":
                                    logger.info("Stream [DONE] received. reasoning_buffer len=%d, round_text_parts len=%d",
                                               len(reasoning_buffer), len(round_text_parts))
                                    break

                                try:
                                    chunk = json.loads(data_str)
                                except json.JSONDecodeError:
                                    continue

                                # Log raw chunk for debugging proxy issues
                                if len(round_text_parts) < 2:
                                    logger.info("Raw chunk: %s", json.dumps(chunk, ensure_ascii=False)[:500])

                                choices = chunk.get("choices") or []
                                if not choices:
                                    continue

                                delta = choices[0].get("delta") or {}
                                finish_reason = choices[0].get("finish_reason")

                                # Log first few chunks and finish for debugging
                                if len(round_text_parts) < 3 or finish_reason:
                                    logger.debug("Stream chunk delta keys: %s, finish_reason: %s, delta: %s",
                                               list(delta.keys()), finish_reason, str(delta)[:200])

                                # Handle reasoning content (for reasoning models)
                                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                                if reasoning:
                                    reasoning_buffer += reasoning

                                # Handle regular content
                                token = delta.get("content")
                                if token:
                                    cleaned = self._strip_thinking(token)
                                    if cleaned:
                                        round_text_parts.append(cleaned)
                                        yield json.dumps({"type": "token", "content": cleaned})

                                # Handle tool calls
                                for tc in delta.get("tool_calls") or []:
                                    used_tools = True
                                    idx = tc.get("index", 0)
                                    entry = tool_calls_by_index.setdefault(
                                        idx, {"id": None, "type": "function", "function": {"name": "", "arguments": ""}}
                                    )
                                    if tc.get("id"):
                                        entry["id"] = tc["id"]
                                    fn = tc.get("function") or {}
                                    if fn.get("name"):
                                        entry["function"]["name"] = fn["name"]
                                    if fn.get("arguments"):
                                        existing = entry["function"]["arguments"]
                                        if existing:
                                            try:
                                                json.loads(existing)
                                                json.loads(fn["arguments"])
                                                entry["function"]["arguments"] = fn["arguments"]
                                            except json.JSONDecodeError:
                                                entry["function"]["arguments"] += fn["arguments"]
                                        else:
                                            entry["function"]["arguments"] = fn["arguments"]

                except httpx.HTTPStatusError as e:
                    if tool_specs and e.response.status_code in (400, 422):
                        logger.warning("Tool calling not supported in streaming, retrying without tools")
                        payload.pop("tools", None)
                        payload.pop("tool_choice", None)
                        async with httpx.AsyncClient(timeout=self.STREAM_TIMEOUT_SECONDS) as client:
                            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                                resp.raise_for_status()
                                round_text_parts = []
                                async for line in resp.aiter_lines():
                                    if not line.startswith("data: "):
                                        continue
                                    data_str = line[6:].strip()
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        chunk = json.loads(data_str)
                                        delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                                        token = delta.get("content")
                                        if token:
                                            cleaned = self._strip_thinking(token)
                                            if cleaned:
                                                round_text_parts.append(cleaned)
                                                yield json.dumps({"type": "token", "content": cleaned})
                                    except json.JSONDecodeError:
                                        continue
                        tool_calls_by_index = {}
                    else:
                        # Show detailed HTTP error to user
                        status_code = e.response.status_code
                        error_detail = ""
                        if status_code == 429:
                            error_detail = "API 调用频率超限（429 Too Many Requests），请稍后重试或检查配额"
                        elif status_code == 401:
                            error_detail = "API Key 无效（401 Unauthorized），请检查设置"
                        elif status_code == 403:
                            error_detail = "API 访问被拒绝（403 Forbidden），请检查权限"
                        elif status_code == 500:
                            error_detail = "API 服务器错误（500 Internal Server Error），请稍后重试"
                        elif status_code == 503:
                            error_detail = "API 服务暂时不可用（503 Service Unavailable），请稍后重试"
                        else:
                            error_detail = f"API 请求失败（HTTP {status_code}）"

                        logger.warning("HTTP streaming request failed: %s - %s", status_code, str(e))
                        full_response = self._fallback_from_tools(openai_messages, reason=f"{error_detail}；")
                        yield json.dumps({"type": "token", "content": full_response})
                        break
                except Exception as e:
                    logger.warning("Streaming request failed: %s", str(e))
                    full_response = self._fallback_from_tools(openai_messages, reason="模型连接失败，无法继续生成完整回答；")
                    yield json.dumps({"type": "token", "content": full_response})
                    break

                tool_calls = [tool_calls_by_index[i] for i in sorted(tool_calls_by_index.keys())]
                streamed_content = "".join(round_text_parts)

                # Handle tool calls first - don't extract from reasoning if we have tool calls
                if tool_calls:
                    assistant_msg: dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls}
                    if streamed_content:
                        assistant_msg["content"] = streamed_content
                    openai_messages.append(assistant_msg)

                    for tc in tool_calls:
                        tool_name = tc.get("function", {}).get("name", "")
                        tool = tools_by_name.get(tool_name)
                        if not tool:
                            raise ToolExecutionError(f"Unknown tool: {tool_name}")
                        if not tc.get("id"):
                            raise ToolExecutionError(f"Missing tool_call id for {tool_name}")
                        try:
                            args_obj = json.loads(tc.get("function", {}).get("arguments") or "{}")
                        except Exception as e:
                            raise ToolExecutionError(f"Invalid tool arguments for {tool_name}: {e}")
                        query_preview = str(args_obj.get("query") or args_obj.get("q") or args_obj.get("term") or "")[:80]
                        yield json.dumps({
                            "type": "tool_call",
                            "tool": tool_name,
                            "query": query_preview,
                            "status": "calling"
                        })
                        try:
                            result = await tool.execute(args_obj)
                        except ToolExecutionError:
                            raise
                        except Exception as e:
                            logger.exception("Tool %s execution error", tool_name)
                            raise ToolExecutionError(f"Tool {tool_name} failed: {e}")
                        tool_result_content = str(result)[:4000]
                        result_count = tool_result_content.count("Title:") or tool_result_content.count("- ") or (1 if tool_result_content and "error" not in tool_result_content.lower() else 0)
                        yield json.dumps({
                            "type": "tool_call",
                            "tool": tool_name,
                            "query": query_preview,
                            "status": "done",
                            "result_count": result_count
                        })
                        openai_messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result_content})
                    # Reset reasoning buffer for next round
                    reasoning_buffer = ""
                    continue

                # No tool calls - this is the final response
                full_response = streamed_content

                # If no content but we have reasoning, extract from reasoning
                if not full_response.strip() and reasoning_buffer:
                    logger.info("No content but got reasoning (len=%d), extracting...", len(reasoning_buffer))
                    full_response = self._extract_from_reasoning(reasoning_buffer)
                    if full_response:
                        yield json.dumps({"type": "token", "content": full_response})

                if not full_response.strip():
                    logger.warning("Model returned empty content in streaming mode (reasoning_len=%d)", len(reasoning_buffer))
                    if empty_content_retries < self.MAX_EMPTY_CONTENT_RETRIES:
                        empty_content_retries += 1
                        # More explicit prompt for reasoning models
                        retry_prompt = (
                            "【重要】你必须在content字段中直接输出回答，不能只在思考过程中回答。"
                            "请现在直接用中文回答用户的问题，不要再思考，直接输出最终答案。"
                        )
                        openai_messages.append({
                            "role": "user",
                            "content": retry_prompt
                        })
                        reasoning_buffer = ""  # Reset for retry
                        continue
                    if used_tools:
                        full_response = self._fallback_from_tools(openai_messages, reason="模型返回空内容，无法生成最终回答；")
                    else:
                        full_response = "抱歉，我没有生成有效的回复。请尝试重新发送问题。"
                    yield json.dumps({"type": "token", "content": full_response})
                break
            else:
                raise ToolExecutionError("Exceeded maximum tool call rounds.")

            logger.info("ChatService streaming function-calling returned %d chars for thread_id=%s", len(full_response or ""), thread_id)

            assistant_message = ChatMessage(
                thread_id=thread_id,
                role="assistant",
                parent_id=last_user_msg_id,
                content_json={"text": full_response}
            )
            self.db.add(assistant_message)

            if self._pending_terms:
                yield json.dumps({"type": "term_suggestions", "terms": self._pending_terms})
                await self._save_terms_to_db(context, self._pending_terms)

            if self._pending_profile_updates:
                # Send profile updates to frontend for user confirmation (3s countdown)
                yield json.dumps({"type": "profile_update_suggestions", "updates": self._pending_profile_updates})

            await self.db.commit()

        except ToolExecutionError as e:
            logger.exception("Tool call failed for thread_id=%s", thread_id)
            await self.db.rollback()
            yield json.dumps({"type": "error", "message": str(e)})
        except Exception as e:
            logger.exception("Chat response failed for thread_id=%s", thread_id)
            await self.db.rollback()
            yield json.dumps({"type": "error", "message": str(e)})

    async def _save_terms_to_db(self, context: dict, terms: list[dict]) -> None:
        """Save terms added via tool to the database."""
        project_id = context.get("project", {}).get("id")
        if not project_id:
            return

        project_uuid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(str(project_id))

        for term_data in terms:
            phrase = term_data.get("term", "")
            translation = term_data.get("translation", "")
            explanation = term_data.get("explanation", "")

            if not phrase:
                continue

            # Check if term exists
            existing = await self.db.execute(
                select(Term).where(
                    Term.project_id == project_uuid,
                    Term.phrase.ilike(phrase)
                )
            )
            term = existing.scalar_one_or_none()

            if not term:
                term = Term(
                    project_id=project_uuid,
                    phrase=phrase,
                    language="en"
                )
                self.db.add(term)
                await self.db.flush()

            # Update or create knowledge
            if term.id:
                knowledge_result = await self.db.execute(
                    select(KnowledgeTerm).where(KnowledgeTerm.term_id == term.id)
                )
                knowledge = knowledge_result.scalar_one_or_none()

                if knowledge:
                    knowledge.translation = translation
                    knowledge.definition = explanation
                else:
                    knowledge = KnowledgeTerm(
                        term_id=term.id,
                        canonical_en=phrase,
                        translation=translation,
                        definition=explanation,
                        status="auto"
                    )
                    self.db.add(knowledge)

    async def _build_context(self, thread: ChatThread, user_id: uuid.UUID) -> dict:
        context = {"terms": [], "paper": None, "project": None, "user_profile": None}

        profile_result = await self.db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = profile_result.scalar_one_or_none()
        if profile:
            context["user_profile"] = {
                "expertise_levels": profile.expertise_levels or {},
                "preferences": profile.preferences or {},
                "difficult_topics": profile.difficult_topics or [],
                "mastered_topics": profile.mastered_topics or []
            }

        if thread.scope_type == "paper":
            result = await self.db.execute(
                select(Paper)
                .options(selectinload(Paper.sections))
                .where(Paper.id == thread.scope_id)
            )
            paper = result.scalar_one_or_none()
            if paper:
                context["paper"] = {
                    "title": paper.title,
                    "abstract": paper.abstract,
                    "sections": [
                        {"title": s.title, "content": s.content_text[:2000] if s.content_text else ""}
                        for s in paper.sections[:5]
                    ]
                }
                context["project"] = {"id": paper.project_id}

                terms_result = await self.db.execute(
                    select(Term)
                    .options(selectinload(Term.knowledge))
                    .where(Term.project_id == paper.project_id)
                    .limit(50)
                )
                terms = terms_result.scalars().all()
                context["terms"] = [
                    {
                        "phrase": t.phrase,
                        "translation": t.knowledge.translation if t.knowledge else None,
                        "definition": t.knowledge.definition if t.knowledge else None
                    }
                    for t in terms if t.knowledge
                ]

        elif thread.scope_type == "project":
            result = await self.db.execute(
                select(Project).where(Project.id == thread.scope_id)
            )
            project = result.scalar_one_or_none()
            if project:
                context["project"] = {
                    "id": project.id,
                    "name": project.name,
                    "domain": project.domain
                }

                terms_result = await self.db.execute(
                    select(Term)
                    .options(selectinload(Term.knowledge))
                    .where(Term.project_id == project.id)
                    .limit(50)
                )
                terms = terms_result.scalars().all()
                context["terms"] = [
                    {
                        "phrase": t.phrase,
                        "translation": t.knowledge.translation if t.knowledge else None,
                        "definition": t.knowledge.definition if t.knowledge else None
                    }
                    for t in terms if t.knowledge
                ]

        return context

    def _build_system_prompt(self, context: dict) -> str:
        prompt = """你是PaperMate，一个专门帮助研究人员理解学术论文的AI助手。

**核心能力**：
1. 用清晰易懂的语言解释复杂概念
2. 翻译和定义专业术语
3. 提供研究领域的背景知识
4. 引用论文内容回答问题

**【重要】输出格式要求**：
- 你必须直接输出最终回答给用户
- 使用中文回答用户问题

**工具使用规则**：

1. **add_term工具** - 当你向用户解释一个专业术语时，必须调用此工具保存到术语库：
   - 触发条件：你在回答中解释了一个技术术语的含义
   - 示例：当你解释"Attention mechanism是一种让模型关注输入特定部分的技术"时，调用add_term
   - 不要重复添加已存在的术语（见下方术语列表）

2. **update_user_profile工具** - 【重要】当你观察到用户的知识水平或偏好时，**必须立即调用此工具**：
   - 用户问基础问题（如"什么是X"） → expertise: {"当前话题": "beginner"}
   - 用户问高级问题（如"X和Y的区别"） → expertise: {"当前话题": "advanced"}
   - 用户表示困惑（"我不太懂"/"有点难"） → difficult_topic: "当前话题"
   - 用户表示理解（"我学会了"/"我懂了"/"明白了"） → mastered_topic: "当前话题"
   - 用户喜欢某种解释方式 → preferences: {"likes_examples": true} 或 {"likes_analogies": true}
   **注意**：每次对话中只要检测到上述信号，就应该调用此工具，这对个性化学习体验至关重要。

3. **project_memory工具** - 读取/写入项目级共享笔记：
   - 当需要确认项目背景/约定时先read
   - 当用户明确给出"把这个记录下来/以后统一这样翻译/项目约定是…"时append或replace

4. **search_paper_sections工具** - 在当前项目的论文段落中按关键词检索：
   - 当用户提到"这篇/这些论文里哪里提到X""找一下X出现在哪个章节"时使用
   - 返回结果后结合检索到的段落回答，并标注引用信息

5. **arxiv_search/tavily_search/searxng_search** - 搜索外部学术资源：
   - 当用户询问论文中未涉及的概念或需要更多背景知识时使用

**回答格式**：
- 术语格式：Term（中文翻译）: 解释
- 引用论文时标注：[Section: xxx]
- 根据用户水平调整解释深度

**关键行为规则**：
当用户表达以下意图时，你必须在回复前先调用相应工具：
- "我学会了/我懂了/明白了/理解了/学到了" → 调用 update_user_profile(mastered_topic: "刚才讨论的话题")
- "我不太懂/有点难/不理解/看不懂" → 调用 update_user_profile(difficult_topic: "当前话题")
- 用户问基础概念问题 → 调用 update_user_profile(expertise: {"话题": "beginner"})
这些工具调用对于个性化用户体验至关重要，请务必执行。
"""

        user_profile = context.get("user_profile")
        if user_profile:
            prompt += "\n\n**User Profile (adapt your responses accordingly):**\n"

            expertise = user_profile.get("expertise_levels", {})
            if expertise:
                prompt += "Knowledge levels:\n"
                for topic, level in list(expertise.items())[:10]:
                    prompt += f"  - {topic}: {level}\n"

            prefs = user_profile.get("preferences", {})
            if prefs:
                style = prefs.get("explanation_style", "balanced")
                prompt += f"Explanation style preference: {style}\n"
                if prefs.get("likes_analogies"):
                    prompt += "User appreciates analogies and metaphors.\n"
                if prefs.get("likes_examples"):
                    prompt += "User appreciates concrete examples.\n"
                math_comfort = prefs.get("math_comfort", "medium")
                prompt += f"Math comfort level: {math_comfort}\n"

            difficult = user_profile.get("difficult_topics", [])
            if difficult:
                prompt += f"Topics user finds difficult (explain more carefully): {', '.join(difficult[:5])}\n"

            mastered = user_profile.get("mastered_topics", [])
            if mastered:
                prompt += f"Topics user has mastered (can skip basics): {', '.join(mastered[:5])}\n"

        if context.get("paper"):
            paper = context["paper"]
            prompt += f"\n\nCurrent Paper: {paper['title']}\n"
            if paper.get("abstract"):
                prompt += f"Abstract: {paper['abstract'][:500]}...\n"

        if context.get("terms"):
            prompt += "\n\nProject Terminology (use these translations consistently):\n"
            for term in context["terms"][:20]:
                if term.get("translation"):
                    prompt += f"- {term['phrase']}（{term['translation']}）\n"

        return prompt
