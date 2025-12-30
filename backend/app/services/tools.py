import logging
import re
import uuid
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Paper, PaperSection, Project

settings = get_settings()
logger = logging.getLogger(__name__)


class ToolExecutionError(RuntimeError):
    """Raised when a tool execution fails."""
    pass


class BaseTool(ABC):
    """Base class for agent tools."""

    name: str
    description: str

    @abstractmethod
    async def execute(self, args: Any) -> str:
        pass

    def openai_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query or term to look up",
                        }
                    },
                    "required": ["query"],
                },
            },
        }


class ArxivSearchTool(BaseTool):
    """Search arXiv for academic papers via the official API."""

    name = "arxiv_search"
    description = "Search arXiv for related academic papers. Use this to find authoritative definitions, translations, and usage of technical terms in research papers."

    def __init__(self, max_results: int = 5, categories: list[str] | None = None):
        self.max_results = max_results
        self.categories = categories or []

    async def execute(self, args: Any) -> str:
        q = (str(args) if isinstance(args, str) else str(args.get("query", ""))).strip()
        if not q:
            raise ToolExecutionError("Empty query.")

        search_query = f"all:{q}"
        if self.categories:
            cats = " OR ".join(f"cat:{c}" for c in self.categories)
            search_query = f"({search_query}) AND ({cats})"

        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": self.max_results,
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
            logger.warning("ArxivTool request failed", exc_info=True)
            raise ToolExecutionError(f"arXiv search error: {e}")

        try:
            root = ET.fromstring(resp.text)
        except Exception:
            logger.warning("ArxivTool XML parse failed", exc_info=True)
            raise ToolExecutionError("arXiv response parse error.")

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        if not entries:
            return "No arXiv results found."

        parts: list[str] = []
        for entry in entries[: self.max_results]:
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


class TavilyTool(BaseTool):
    """Search the web via Tavily API for academic sources."""

    name = "tavily_search"
    description = "Search the web via Tavily for authoritative academic definitions and translations. Prioritizes arxiv.org results."

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = None
        try:
            from tavily import AsyncTavilyClient
            self._client = AsyncTavilyClient(api_key=api_key)
        except ImportError:
            logger.warning("Tavily package not installed. Run: pip install tavily-python")
        except Exception:
            logger.warning("Failed to initialize Tavily client", exc_info=True)

    async def execute(self, args: Any) -> str:
        if not self._client:
            raise ToolExecutionError("Tavily not available (missing dependency or config).")

        query = (str(args) if isinstance(args, str) else str(args.get("query", ""))).strip()
        if not query:
            raise ToolExecutionError("Empty query.")

        try:
            resp = await self._client.search(
                query,
                search_depth="advanced",
                include_domains=["arxiv.org", "scholar.google.com", "semanticscholar.org"],
                max_results=5,
            )
        except Exception as e:
            logger.warning("Tavily search failed", exc_info=True)
            raise ToolExecutionError(f"Tavily search error: {e}")

        results = resp.get("results") or []
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


class SearxngTool(BaseTool):
    """Search via SearXNG instance for scientific sources."""

    name = "searxng_search"
    description = "Search a SearXNG instance for scientific sources. Use this to find definitions and usage of academic terms."

    def __init__(self, base_url: str):
        self.base_url = (base_url or "").rstrip("/")

    async def execute(self, args: Any) -> str:
        if not self.base_url:
            raise ToolExecutionError("SearXNG URL not configured.")

        query = (str(args) if isinstance(args, str) else str(args.get("query", ""))).strip()
        if not query:
            raise ToolExecutionError("Empty query.")

        params = {
            "q": query,
            "format": "json",
            "categories": "science",
            "language": "en",
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{self.base_url}/search", params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("SearXNG HTTP error", exc_info=True)
            raise ToolExecutionError(f"SearXNG error: HTTP {e.response.status_code}")
        except Exception as e:
            logger.warning("SearXNG search failed", exc_info=True)
            raise ToolExecutionError(f"SearXNG search error: {e}")

        results = data.get("results") or []
        if not results:
            return "No SearXNG results found."

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


class AddTermTool(BaseTool):
    """Tool for LLM to add a new term to the project's terminology memory."""

    name = "add_term"
    description = """Add a professional term to the project's terminology memory.
Use this tool when you explain a new technical term to the user.
The term will be saved for consistent translation across the project.
Input format: JSON with fields: term (English), translation (Chinese), explanation (brief definition)
Example: {"term": "Transformer", "translation": "变换器", "explanation": "基于自注意力机制的神经网络架构"}"""

    def __init__(self, callback=None):
        self.callback = callback

    def openai_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "term": {
                            "type": "string",
                            "description": "The English term to add",
                        },
                        "translation": {
                            "type": "string",
                            "description": "Chinese translation of the term",
                        },
                        "explanation": {
                            "type": "string",
                            "description": "Brief explanation/definition (50 chars max)",
                        }
                    },
                    "required": ["term", "translation", "explanation"],
                },
            },
        }

    async def execute(self, args: Any) -> str:
        if not isinstance(args, dict):
            raise ToolExecutionError("Invalid arguments for add_term.")

        term = args.get("term", "")
        translation = args.get("translation", "")
        explanation = args.get("explanation", "")

        if not term or not translation:
            raise ToolExecutionError("term and translation are required")

        if self.callback:
            await self.callback({
                "term": term,
                "translation": translation,
                "explanation": explanation
            })
            return f"Term '{term}' ({translation}) added to memory successfully."
        raise ToolExecutionError("Term callback not configured.")


class UpdateProfileTool(BaseTool):
    """Tool for LLM to update user profile based on conversation insights."""

    name = "update_user_profile"
    description = """Update the user's learning profile based on conversation insights.
Use this tool when you notice:
- User's expertise level in a topic (beginner/intermediate/advanced)
- User's preference for explanation style (concise/detailed)
- Topics the user finds difficult or has mastered
Input format: JSON with optional fields: expertise (topic->level), preferences (key->value), difficult_topic, mastered_topic
Example: {"expertise": {"machine learning": "intermediate"}, "preferences": {"likes_examples": true}}"""

    def __init__(self, callback=None):
        self.callback = callback

    def openai_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expertise": {
                            "type": "object",
                            "description": "Map of topic to expertise level (beginner/intermediate/advanced)",
                        },
                        "preferences": {
                            "type": "object",
                            "description": "User preferences like explanation_style, likes_examples, math_comfort",
                        },
                        "difficult_topic": {
                            "type": "string",
                            "description": "A topic the user explicitly finds difficult",
                        },
                        "mastered_topic": {
                            "type": "string",
                            "description": "A topic the user has mastered",
                        }
                    },
                },
            },
        }

    async def execute(self, args: Any) -> str:
        if not isinstance(args, dict):
            raise ToolExecutionError("Invalid arguments for update_user_profile.")

        if self.callback:
            await self.callback(args)
            return "User profile updated successfully."
        raise ToolExecutionError("Profile callback not configured.")


class ProjectMemoryTool(BaseTool):
    """Tool for reading/writing project-level shared notes."""

    name = "project_memory"
    description = """Read/write project-level shared notes.
Use this to store project conventions, translation rules, important conclusions, etc.
Actions: read (get current notes), append (add to notes), replace (overwrite notes), clear (delete notes)."""

    _SETTINGS_KEY = "project_memory_notes"

    def __init__(self, db: AsyncSession, project_id: uuid.UUID):
        self.db = db
        self.project_id = project_id

    def openai_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["read", "append", "replace", "clear"],
                            "description": "Action to perform on project notes",
                        },
                        "content": {
                            "type": "string",
                            "description": "Notes content (required for append/replace)",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    async def execute(self, args: Any) -> str:
        if not isinstance(args, dict):
            raise ToolExecutionError("Invalid arguments for project_memory.")

        action = (args.get("action") or "").strip()
        content = (args.get("content") or "").strip()

        if action not in {"read", "append", "replace", "clear"}:
            raise ToolExecutionError(f"Invalid action: {action}")

        project = await self.db.get(Project, self.project_id)
        if not project:
            raise ToolExecutionError("Project not found.")

        settings_dict = dict(project.settings or {})
        notes = str(settings_dict.get(self._SETTINGS_KEY) or "")

        if action == "read":
            return notes or "(empty)"

        if action == "clear":
            settings_dict[self._SETTINGS_KEY] = ""
            project.settings = settings_dict
            return "Cleared project notes."

        if action == "replace":
            if not content:
                raise ToolExecutionError("content is required for replace.")
            settings_dict[self._SETTINGS_KEY] = content
            project.settings = settings_dict
            return "Replaced project notes."

        if action == "append":
            if not content:
                raise ToolExecutionError("content is required for append.")
            joined = (notes + "\n\n" + content).strip() if notes else content
            settings_dict[self._SETTINGS_KEY] = joined
            project.settings = settings_dict
            return "Appended to project notes."

        raise ToolExecutionError("Unhandled action for project_memory.")


class SearchPaperTool(BaseTool):
    """Tool for searching paper sections by keyword within the current project."""

    name = "search_paper_sections"
    description = """Search paper sections by keyword within the current project.
Use this when user asks about content in the papers, like "where does it mention X" or "find sections about Y"."""

    def __init__(self, db: AsyncSession, project_id: uuid.UUID, paper_id: uuid.UUID | None = None):
        self.db = db
        self.project_id = project_id
        self.paper_id = paper_id

    def openai_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": "Keyword to search for in paper sections",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (1-10, default 5)",
                        },
                    },
                    "required": ["keyword"],
                },
            },
        }

    async def execute(self, args: Any) -> str:
        if not isinstance(args, dict):
            raise ToolExecutionError("Invalid arguments for search_paper_sections.")

        keyword = (args.get("keyword") or "").strip()
        try:
            limit = int(args.get("limit") or 5)
        except (ValueError, TypeError):
            limit = 5
        limit = max(1, min(limit, 10))

        if not keyword:
            raise ToolExecutionError("keyword is required.")

        # Make keyword search more tolerant of punctuation/case differences.
        # Example: "deep-encoder" should match "DeepEncoder".
        patterns = [f"%{keyword}%"]
        normalized = re.sub(r"[-_\\s]+", "", keyword)
        if normalized and normalized.lower() != keyword.lower():
            patterns.append(f"%{normalized}%")

        def _matches_any(field) -> Any:
            return or_(*[field.ilike(p) for p in patterns])

        base_stmt = (
            select(Paper.title, PaperSection.title, PaperSection.content_text)
            .select_from(PaperSection)
            .join(Paper, Paper.id == PaperSection.paper_id)
            .where(Paper.project_id == self.project_id)
            .where(or_(_matches_any(PaperSection.title), _matches_any(PaperSection.content_text)))
        )

        rows = []
        # If this chat is scoped to a specific paper, search within that paper first.
        if self.paper_id:
            rows = (
                await self.db.execute(
                    base_stmt.where(Paper.id == self.paper_id).limit(limit)
                )
            ).all()
            if len(rows) < limit:
                remaining = limit - len(rows)
                more = (
                    await self.db.execute(
                        base_stmt.where(Paper.id != self.paper_id).limit(remaining)
                    )
                ).all()
                rows = rows + more
        else:
            rows = (await self.db.execute(base_stmt.limit(limit))).all()

        if not rows:
            return "No matches found."

        def _snippet(text: str, needles: list[str], width: int = 260) -> str:
            hay = text or ""
            low = hay.lower()
            idx = -1
            needle_used = ""
            for n in needles:
                i = low.find(n.lower())
                if i >= 0:
                    idx = i
                    needle_used = n
                    break
            if idx < 0:
                return (hay[:width] + "...") if len(hay) > width else hay
            start = max(0, idx - width // 2)
            end = min(len(hay), idx + width // 2)
            out = hay[start:end].replace("\n", " ")
            if start > 0:
                out = "..." + out
            if end < len(hay):
                out = out + "..."
            return out

        parts: list[str] = []
        for paper_title, section_title, content_text in rows:
            parts.append(
                f"Paper: {paper_title}\n"
                f"Section: {section_title or '(untitled)'}\n"
                f"Snippet: {_snippet(content_text or '', [keyword, normalized] if normalized else [keyword])}"
            )
        return "\n\n".join(parts)


def get_available_tools() -> list[BaseTool]:
    """Instantiate search tools based on runtime configuration."""
    tools: list[BaseTool] = [ArxivSearchTool()]

    if settings.tavily_api_key:
        tavily_tool = TavilyTool(settings.tavily_api_key)
        if tavily_tool._client is not None:
            tools.append(tavily_tool)

    if settings.searxng_url:
        tools.append(SearxngTool(settings.searxng_url))

    return tools


def get_chat_tools(
    *,
    db: AsyncSession,
    project_id: uuid.UUID,
    paper_id: uuid.UUID | None = None,
    add_term_callback=None,
    update_profile_callback=None,
) -> list[BaseTool]:
    """Get tools for chat service including memory and search tools."""
    tools = get_available_tools()
    tools.append(ProjectMemoryTool(db=db, project_id=project_id))
    tools.append(SearchPaperTool(db=db, project_id=project_id, paper_id=paper_id))
    tools.append(AddTermTool(callback=add_term_callback))
    tools.append(UpdateProfileTool(callback=update_profile_callback))
    return tools
