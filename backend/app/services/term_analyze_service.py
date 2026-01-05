"""HTTP-based term analysis service with tool calling support.

This service uses raw HTTP requests to call LLM APIs and implements
a manual tool calling loop for arxiv and tavily searches.
"""
import json
import logging
import re
import uuid
import xml.etree.ElementTree as ET
from typing import Any, AsyncGenerator

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models import Term, KnowledgeTerm, Paper, Project

settings = get_settings()
logger = logging.getLogger(__name__)

ARXIV_TOOL = {
    "type": "function",
    "function": {
        "name": "arxiv_search",
        "description": "Search arXiv for academic papers to find authoritative definitions and usage of technical terms.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for arXiv"
                }
            },
            "required": ["query"]
        }
    }
}

TAVILY_TOOL = {
    "type": "function",
    "function": {
        "name": "tavily_search",
        "description": "Search the web for academic definitions and translations. Prioritizes arxiv.org and academic sources.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                }
            },
            "required": ["query"]
        }
    }
}


async def execute_arxiv_search(query: str, max_results: int = 5) -> str:
    """Execute arXiv search and return formatted results."""
    if not query.strip():
        return "Empty query."

    search_query = f"all:{query}"
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                "https://export.arxiv.org/api/query",
                params=params,
                headers={"User-Agent": "PaperMate/1.0"},
            )
            resp.raise_for_status()
    except Exception as e:
        logger.warning("ArXiv search failed", exc_info=True)
        return f"arXiv search error: {e}"

    try:
        root = ET.fromstring(resp.text)
    except Exception:
        logger.warning("ArXiv XML parse failed", exc_info=True)
        return "arXiv response parse error."

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)
    if not entries:
        return "No arXiv results found."

    parts: list[str] = []
    for entry in entries[:max_results]:
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        title = re.sub(r"\s+", " ", title)

        summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
        summary = re.sub(r"\s+", " ", summary)
        if len(summary) > 400:
            summary = summary[:400] + "..."

        authors = [
            a.findtext("atom:name", default="", namespaces=ns)
            for a in entry.findall("atom:author", ns)
        ]
        authors_str = ", ".join(a for a in authors if a)[:150]

        link = ""
        for lnk in entry.findall("atom:link", ns):
            if lnk.attrib.get("rel") == "alternate":
                link = lnk.attrib.get("href", "")
                break

        parts.append(f"Title: {title}\nAuthors: {authors_str}\nSummary: {summary}\nURL: {link}")

    return "\n\n".join(parts)


async def execute_tavily_search(query: str, api_key: str) -> str:
    """Execute Tavily search and return formatted results."""
    if not query.strip():
        return "Empty query."

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "advanced",
                    "include_domains": ["arxiv.org", "scholar.google.com", "semanticscholar.org"],
                    "max_results": 5,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("Tavily search failed", exc_info=True)
        return f"Tavily search error: {e}"

    results = data.get("results") or []
    if not results:
        return "No Tavily results found."

    parts: list[str] = []
    for r in results[:5]:
        title = (r.get("title") or "").strip()
        url = r.get("url") or ""
        content = (r.get("content") or "").strip()
        content = re.sub(r"\s+", " ", content)
        if len(content) > 300:
            content = content[:300] + "..."
        parts.append(f"- {title}\n  URL: {url}\n  {content}")

    return "\n".join(parts)


def _strip_thinking(text: str) -> str:
    """Remove provider reasoning blocks."""
    if not text:
        return ""
    cleaned = re.sub(r"<thinking[^>]*>[\s\S]*?</thinking>", "", text, flags=re.I)
    cleaned = re.sub(r"<think[^>]*>[\s\S]*?</think>", "", cleaned, flags=re.I)
    cleaned = re.sub(r"<reasoning[^>]*>[\s\S]*?</reasoning>", "", cleaned, flags=re.I)
    cleaned = re.sub(r"<analysis[^>]*>[\s\S]*?</analysis>", "", cleaned, flags=re.I)
    cleaned = re.sub(r"</?final[^>]*>", "", cleaned, flags=re.I)
    return cleaned.strip()


def _extract_final_from_reasoning(reasoning: str) -> str:
    """Extract final answer from reasoning content."""
    if not reasoning:
        return ""

    # Try explicit <final> tags first
    m = re.search(r"(?is)<final[^>]*>(.*?)</final>", reasoning)
    if m:
        return m.group(1).strip()

    # Try explicit final markers
    m = re.search(r"(?:最终答案|Final Answer|Answer)\s*[:：]\s*([\s\S]+)$", reasoning, re.I)
    if m:
        return m.group(1).strip()

    # For reasoning models that don't output explicit final markers,
    # extract the substantive content by removing thinking patterns
    cleaned = reasoning

    # Remove common thinking patterns
    thinking_patterns = [
        r"(?:Okay|Alright|Let me|I'm|I need|I seem|I think|My|First|So|Now)[^.!?]*[.!?]",
        r"(?:Let's break|Let's dive|Let's see|Let's think)[^.!?]*[.!?]",
        r"(?:It looks like|It seems|Given the context)[^.!?]*[.!?]",
        r"\*\*[^*]+\*\*",  # Remove markdown bold headers like **GRPO Explained**
    ]

    for pattern in thinking_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.I)

    # Clean up whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # If we have substantial content left, use it
    if len(cleaned) > 50:
        # Truncate to reasonable length
        if len(cleaned) > 300:
            cleaned = cleaned[:300].rsplit(" ", 1)[0] + "..."
        return cleaned

    # Fallback: use the original reasoning but clean it up
    # Remove the first sentence (usually "Let me think about this")
    sentences = re.split(r'(?<=[.!?])\s+', reasoning)
    if len(sentences) > 2:
        # Skip first 1-2 sentences and take the rest
        content = " ".join(sentences[2:])
        if len(content) > 300:
            content = content[:300].rsplit(" ", 1)[0] + "..."
        return content

    return ""


def _extract_content_from_response(data: dict) -> str:
    """Extract text content from LLM response."""
    choices = data.get("choices") or []
    if not choices:
        logger.warning("No choices in LLM response: %s", str(data)[:500])
        return ""

    message = choices[0].get("message") or {}
    content = message.get("content") or choices[0].get("text") or ""

    if not content:
        reasoning = message.get("reasoning_content") or ""
        if reasoning:
            content = _extract_final_from_reasoning(reasoning)
            logger.info("Extracted from reasoning: %s", content[:200] if content else "(empty)")

    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and "text" in part:
                parts.append(str(part["text"]))
        content = "".join(parts)

    result = _strip_thinking(str(content)).strip()
    logger.info("Extracted content: %s", result[:200] if result else "(empty)")
    return result


def _compact_context(text: str | None, max_paragraphs: int = 5, max_chars: int = 2000) -> str:
    """Compact context to reasonable size."""
    raw = (text or "").strip()
    if not raw:
        return ""

    parts = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    if not parts:
        parts = [raw]

    out: list[str] = []
    total = 0
    for part in parts:
        if len(out) >= max_paragraphs:
            break
        remaining = max_chars - total
        if remaining <= 0:
            break
        cleaned = re.sub(r"\s+", " ", part).strip()
        if not cleaned:
            continue
        if len(cleaned) > remaining:
            cleaned = cleaned[:remaining].rstrip()
        out.append(cleaned)
        total += len(cleaned)

    return "\n\n".join(f"[段落{i + 1}] {p}" for i, p in enumerate(out))


class TermAnalyzeService:
    """Service for analyzing terms using HTTP-based LLM calls with tool support."""

    MAX_TOOL_ROUNDS = 5
    LLM_TIMEOUT_SECONDS = 180  # 3 minutes for reasoning models

    def __init__(self, db: AsyncSession, user_id: uuid.UUID):
        self.db = db
        self.user_id = user_id
        self.base_url: str | None = None
        self.api_key: str | None = None
        self.model: str | None = None

    def _get_tools(self) -> list[dict]:
        """Get available tools based on configuration."""
        tools = [ARXIV_TOOL]
        if settings.tavily_api_key:
            tools.append(TAVILY_TOOL)
        return tools

    async def _execute_tool(self, name: str, args: dict) -> tuple[str, int]:
        """Execute a tool and return (result, result_count)."""
        query = args.get("query", "")

        if name == "arxiv_search":
            result = await execute_arxiv_search(query)
            count = result.count("Title:") if "Title:" in result else 0
            return result, count

        if name == "tavily_search" and settings.tavily_api_key:
            result = await execute_tavily_search(query, settings.tavily_api_key)
            count = result.count("- ") if "- " in result else 0
            return result, count

        return f"Unknown tool: {name}", 0

    async def _call_llm(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 500,
        temperature: float = 0.3,
    ) -> dict:
        """Call LLM via HTTP and return raw response."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=self.LLM_TIMEOUT_SECONDS) as client:
            try:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                logger.info("LLM response keys: %s", list(data.keys()))
                if data.get("choices"):
                    msg = data["choices"][0].get("message", {})
                    content_val = msg.get("content", "")
                    reasoning_val = msg.get("reasoning_content", "")
                    logger.info("Message keys: %s", list(msg.keys()))
                    logger.info("Content (len=%d): %s", len(str(content_val)), str(content_val)[:300])
                    logger.info("Reasoning (len=%d): %s", len(str(reasoning_val)), str(reasoning_val)[:500])
                return data
            except httpx.HTTPStatusError as e:
                if tools and e.response.status_code in (400, 422):
                    logger.warning("Tool calling not supported, retrying without tools")
                    payload.pop("tools", None)
                    payload.pop("tool_choice", None)
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    return resp.json()
                raise

    async def _load_user_settings(self) -> None:
        """Load effective settings for the current user."""
        from app.services.openai_settings import get_openai_settings

        user_settings = await get_openai_settings(self.db, self.user_id)
        self.base_url = user_settings["base_url"]
        self.api_key = user_settings["api_key"]
        self.model = user_settings["model"]

    async def analyze_term_stream(
        self,
        phrase: str,
        project_id: uuid.UUID,
        paper_id: uuid.UUID | None = None,
        context: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream term analysis with tool calling support.

        Yields SSE-formatted events:
        - {"type": "status", "message": "..."}
        - {"type": "tool_call", "tool": "...", "query": "...", "status": "calling"}
        - {"type": "tool_result", "tool": "...", "result_count": N}
        - {"type": "content", "text": "..."}
        - {"type": "done", "result": {...}}
        - {"type": "error", "message": "..."}
        """
        await self._load_user_settings()

        def emit(data: dict) -> str:
            result = json.dumps(data, ensure_ascii=False)
            logger.info("SSE emit: %s", result[:200])
            return result

        yield emit({"type": "status", "message": "正在检查已有术语..."})

        existing_result = await self.db.execute(
            select(Term)
            .options(selectinload(Term.knowledge))
            .where(Term.project_id == project_id, Term.phrase == phrase)
        )
        existing_term = existing_result.scalar_one_or_none()
        if existing_term and existing_term.knowledge:
            translation = existing_term.knowledge.translation or ""
            if translation and "解析失败" not in translation:
                yield emit({
                    "type": "done",
                    "result": {
                        "term": existing_term.phrase,
                        "translation": translation,
                        "explanation": existing_term.knowledge.definition or "",
                        "sources": [],
                    }
                })
                return

        yield emit({"type": "status", "message": "正在获取论文信息..."})

        project_result = await self.db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = project_result.scalar_one_or_none()
        domain = project.domain if project else None

        paper_title = None
        if paper_id:
            paper_result = await self.db.execute(
                select(Paper).where(Paper.id == paper_id)
            )
            paper = paper_result.scalar_one_or_none()
            if paper:
                paper_title = paper.title

        context_block = _compact_context(context)

        tools = self._get_tools()
        tool_names = ", ".join(t["function"]["name"] for t in tools)

        system_prompt = (
            "你是学术论文术语解释助手。\n"
            f"可用工具：{tool_names}。\n"
            "优先根据上下文判断术语含义，不确定时再使用工具检索。\n"
            "【重要】必须直接输出80-150字简体中文解释作为最终回复。\n"
            "不要输出思考过程，只输出最终解释内容。"
        )

        user_prompt = (
            f"术语：{phrase}\n"
            f"论文领域: {domain or '通用/未知'}\n"
            f"论文标题: {paper_title or '未知'}\n"
            "上下文（3-5段）：\n"
            f"{context_block or '（无）'}\n\n"
            "请解释该术语在上下文中的含义。"
        )

        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        yield emit({"type": "status", "message": "正在分析术语..."})

        explanation = ""
        sources: list[str] = []

        try:
            for round_num in range(self.MAX_TOOL_ROUNDS):
                data = await self._call_llm(messages, tools=tools, max_tokens=2500)

                choices = data.get("choices") or []
                if not choices:
                    yield emit({"type": "error", "message": "LLM返回空响应"})
                    return

                message = choices[0].get("message") or {}
                tool_calls = message.get("tool_calls") or []

                if not tool_calls:
                    explanation = _extract_content_from_response(data)
                    break

                assistant_msg: dict[str, Any] = {"role": "assistant"}
                if message.get("content"):
                    assistant_msg["content"] = message["content"]
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                    for tc in tool_calls
                ]
                messages.append(assistant_msg)

                for tc in tool_calls:
                    tool_name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}

                    query = args.get("query", "")[:100]

                    yield emit({
                        "type": "tool_call",
                        "tool": tool_name,
                        "query": query,
                        "status": "calling",
                    })

                    result, count = await self._execute_tool(tool_name, args)

                    yield emit({
                        "type": "tool_result",
                        "tool": tool_name,
                        "result_count": count,
                    })

                    if count > 0:
                        sources.append(tool_name)

                    result_truncated = result[:3000] if len(result) > 3000 else result
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_truncated,
                    })

            if not explanation:
                yield emit({"type": "status", "message": "正在生成最终解释..."})
                data = await self._call_llm(messages, tools=None, max_tokens=2500)
                explanation = _extract_content_from_response(data)

            if not explanation:
                explanation = f"术语 {phrase} 的解释暂时无法获取。"

            yield emit({"type": "content", "text": explanation})

            yield emit({"type": "status", "message": "正在生成翻译..."})

            known_terms_result = await self.db.execute(
                select(Term)
                .options(selectinload(Term.knowledge))
                .where(Term.project_id == project_id)
                .limit(30)
            )
            known_terms = [
                f"{t.phrase}（{t.knowledge.translation}）"
                for t in known_terms_result.scalars().all()
                if t.knowledge and t.knowledge.translation
            ][:15]

            translate_prompt = f"""术语：{phrase}
术语解释：{explanation}

项目已有术语翻译(参考风格): {known_terms if known_terms else '无'}

请给出这个术语的中文译名。
- 如果是专有名词/缩写，可保留原名或使用"中文（原文）"格式
- 【格式要求】必须用XML标签包裹译名：<translation>译名</translation>
- 只在标签内输出译名，不要输出其他内容"""

            translate_messages = [{"role": "user", "content": translate_prompt}]

            # Retry up to 3 times to extract translation
            translation = ""
            for retry in range(3):
                translate_data = await self._call_llm(translate_messages, tools=None, max_tokens=800)
                raw_translation = _extract_content_from_response(translate_data)

                # Also check reasoning_content for the tag
                if not raw_translation:
                    choices = translate_data.get("choices") or []
                    if choices:
                        msg = choices[0].get("message") or {}
                        raw_translation = msg.get("reasoning_content") or ""

                # Try to extract from <translation> tag
                match = re.search(r"<translation[^>]*>(.*?)</translation>", raw_translation, re.IGNORECASE | re.DOTALL)
                if match:
                    translation = match.group(1).strip()
                    logger.info("Extracted translation from tag: %s", translation)
                    break

                # Fallback: try other patterns
                # Pattern: 译名：XXX or 翻译：XXX
                match = re.search(r"(?:译名|翻译|中文译名)\s*[:：]\s*([^\n]+)", raw_translation)
                if match:
                    translation = match.group(1).strip()
                    logger.info("Extracted translation from label: %s", translation)
                    break

                # Pattern: 「XXX」 or "XXX"
                match = re.search(r"[「""]([^」""]+)[」""]", raw_translation)
                if match:
                    candidate = match.group(1).strip()
                    # Only use if it looks like a translation (contains Chinese or is short)
                    if re.search(r"[\u4e00-\u9fff]", candidate) or len(candidate) < 30:
                        translation = candidate
                        logger.info("Extracted translation from quotes: %s", translation)
                        break

                logger.warning("Translation extraction failed (attempt %d), raw: %s", retry + 1, raw_translation[:200])

                # Add hint for retry
                if retry < 2:
                    translate_messages.append({
                        "role": "assistant",
                        "content": raw_translation[:500] if raw_translation else ""
                    })
                    translate_messages.append({
                        "role": "user",
                        "content": "请严格按格式输出：<translation>译名</translation>"
                    })

            if translation:
                translation = translation.strip().split('\n')[0].strip()
            if not translation:
                translation = phrase

            yield emit({
                "type": "done",
                "result": {
                    "term": phrase,
                    "translation": translation,
                    "explanation": explanation,
                    "sources": list(set(sources)),
                }
            })

        except Exception as e:
            logger.exception("Term analysis failed")
            yield emit({
                "type": "error",
                "message": f"分析失败: {str(e)}"
            })
