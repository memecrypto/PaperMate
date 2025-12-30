import uuid
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from openai import AsyncOpenAI

from app.core.database import async_session_maker
from app.models import (
    AnalysisJob,
    AnalysisResult,
    Paper,
    Project,
    Term,
    KnowledgeTerm,
)
from app.services.react_agent import ReActAgent
from app.services.tools import get_available_tools
from app.services.openai_settings import get_openai_settings

logger = logging.getLogger(__name__)

# 7 deep analysis dimensions
DEEP_DIMENSIONS: list[str] = [
    "background_motivation",
    "core_innovations",
    "methodology_details",
    "formula_analysis",
    "experiments_results",
    "advantages_limitations",
    "future_directions",
]

# Dimension metadata
DIM_META: dict[str, dict[str, str]] = {
    "background_motivation": {
        "title": "研究背景与动机",
        "instruction": "补充领域背景、问题动机、研究空白；必要时用工具搜索2-4篇强相关工作并给出URL。",
    },
    "core_innovations": {
        "title": "核心创新点（3-5个）",
        "instruction": "列出3-5条创新点，每条包含：是什么、为什么重要、与已有方法对比。",
    },
    "methodology_details": {
        "title": "方法论详解（流程/架构）",
        "instruction": "给出整体流程、关键模块/网络结构、训练与推理细节；必要时用伪代码/列表描述。",
    },
    "formula_analysis": {
        "title": "关键公式解析（含义/推导/作用）",
        "instruction": "选择最关键的公式（优先有page的），逐个解释含义、（可选）推导思路、在方法中的作用。",
    },
    "experiments_results": {
        "title": "实验设计与结果（数据集/指标/对比）",
        "instruction": "提取数据集、评价指标、对比方法、主要结论；如有表/图资产，引用page并总结。",
    },
    "advantages_limitations": {
        "title": "优势与局限性",
        "instruction": "分别列优势与局限；局限需具体到假设/数据/计算/泛化等维度。",
    },
    "future_directions": {
        "title": "未来研究方向（论文+AI推断）",
        "instruction": "先列论文明确提出的方向，再给AI推断的2-4条可行方向（并说明理由）。",
    },
}


class DeepAnalysisService:
    """Deep analysis service using ReAct agent with multi-dimensional analysis."""

    _progress_queues: ClassVar[dict[uuid.UUID, asyncio.Queue[str]]] = {}
    _queue_refs: ClassVar[dict[uuid.UUID, int]] = {}

    def __init__(self, db: AsyncSession):
        self.db = db
        self.client: AsyncOpenAI | None = None
        self.tools = get_available_tools()

    @classmethod
    def get_progress_queue(cls, job_id: uuid.UUID) -> asyncio.Queue[str]:
        if job_id not in cls._progress_queues:
            cls._progress_queues[job_id] = asyncio.Queue(maxsize=500)
            cls._queue_refs[job_id] = 0
        cls._queue_refs[job_id] = cls._queue_refs.get(job_id, 0) + 1
        return cls._progress_queues[job_id]

    @classmethod
    async def publish_progress(cls, job_id: uuid.UUID, payload: dict) -> None:
        if job_id not in cls._progress_queues:
            return
        queue = cls._progress_queues[job_id]
        data = json.dumps(payload, ensure_ascii=False)
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        await queue.put(data)

    @classmethod
    def release_progress(cls, job_id: uuid.UUID) -> None:
        if job_id in cls._queue_refs:
            cls._queue_refs[job_id] -= 1
            if cls._queue_refs[job_id] <= 0:
                cls._progress_queues.pop(job_id, None)
                cls._queue_refs.pop(job_id, None)

    async def _load_paper(self, paper_id: uuid.UUID) -> Paper | None:
        result = await self.db.execute(
            select(Paper)
            .options(
                selectinload(Paper.sections),
                selectinload(Paper.formulas),
                selectinload(Paper.assets),
                selectinload(Paper.references),
            )
            .where(Paper.id == paper_id)
        )
        return result.scalar_one_or_none()

    async def _load_term_memory(self, project_id: uuid.UUID) -> list[str]:
        rows = await self.db.execute(
            select(Term.phrase, KnowledgeTerm.translation, KnowledgeTerm.definition)
            .join(KnowledgeTerm, KnowledgeTerm.term_id == Term.id)
            .where(Term.project_id == project_id)
            .order_by(Term.created_at.desc())
            .limit(30)
        )
        lines: list[str] = []
        for phrase, translation, definition in rows.all():
            zh = (translation or "").strip()
            if not zh:
                continue
            brief = (definition or "").strip()
            if brief:
                brief = brief.replace("\n", " ")[:80]
                lines.append(f"- {phrase} -> {zh}（{brief}）")
            else:
                lines.append(f"- {phrase} -> {zh}")
        return lines

    async def _load_other_papers(self, project_id: uuid.UUID, exclude_paper_id: uuid.UUID) -> list[str]:
        rows = await self.db.execute(
            select(Paper)
            .where(Paper.project_id == project_id, Paper.id != exclude_paper_id)
            .order_by(Paper.created_at.desc())
            .limit(5)
        )
        items: list[str] = []
        for p in rows.scalars().all():
            abstract = (p.abstract or "").strip().replace("\n", " ")[:300]
            items.append(f"- {p.title}\n  Abstract: {abstract if abstract else 'N/A'}")
        return items

    def _build_paper_text(self, paper: Paper) -> str:
        parts: list[str] = [f"Title: {paper.title}"]
        if paper.abstract:
            parts.append(f"Abstract: {paper.abstract.strip()}")
        for s in paper.sections or []:
            body = (s.content_md or s.content_text or "").strip()
            if not body:
                continue
            title = s.title or s.section_type or "Section"
            parts.append(f"## {title}\n{body}")
        return "\n\n".join(parts)

    def _truncate_head_tail(self, text: str, max_chars: int = 18000) -> str:
        t = (text or "").strip()
        if len(t) <= max_chars:
            return t
        half = max_chars // 2
        return "\n\n".join([
            t[:half],
            "...[TRUNCATED]...",
            t[-half:],
        ])

    def _format_formulas(self, paper: Paper) -> str:
        formulas = getattr(paper, "formulas", None) or []
        if not formulas:
            return "无"
        lines: list[str] = []
        for idx, f in enumerate(formulas[:20], start=1):
            latex = (f.latex or "").strip().replace("\n", " ")
            page = f.page if f.page is not None else "?"
            if not latex:
                continue
            lines.append(f"- F{idx} (p.{page}): {latex[:300]}")
        return "\n".join(lines) if lines else "无"

    def _format_assets(self, paper: Paper) -> str:
        assets = getattr(paper, "assets", None) or []
        if not assets:
            return "无"
        lines: list[str] = []
        for a in assets[:20]:
            page = a.page if a.page is not None else "?"
            caption = (a.caption or "").strip().replace("\n", " ")[:200]
            label = (a.label or "").strip()
            lines.append(f"- {a.type} {label} (p.{page}): {caption if caption else 'N/A'}")
        return "\n".join(lines) if lines else "无"

    def _system_prompt(self, domain: str, tool_names: str) -> str:
        d = domain.strip()
        domain_hint = f"领域：{d}。" if d else ""
        return (
            f"你是资深学术论文深度解析专家。{domain_hint}"
            f"可用工具：{tool_names}。"
            "输出必须为中文Markdown（可包含HTML <details>/<summary> 用于折叠），不要输出与任务无关内容。"
        )

    def _user_prompt(
        self,
        dim_key: str,
        dim_title: str,
        idx: int,
        total: int,
        paper_excerpt: str,
        formulas: str,
        assets: str,
        term_memory_lines: list[str],
        other_papers_lines: list[str],
        instruction: str,
    ) -> str:
        tools_note = (
            "如需补充背景/对比，请调用搜索工具；外部信息必须给出可点击URL。\n"
        )
        cite_note = (
            "引用论文页码请用链接格式：[p.3](papermate://pdf?page=3)。"
            "若无法确定页码可省略。\n"
        )
        term_note = "\n".join(term_memory_lines) if term_memory_lines else "无"
        other_note = "\n".join(other_papers_lines) if other_papers_lines else "无"
        return f"""请完成第 {idx}/{total} 个维度：{dim_title}

输出格式（必须）：<details open><summary>{idx}. {dim_title}</summary>

...正文Markdown...

</details>

要求：
- {instruction}
- 使用项目术语记忆保持一致性（术语尽量保留英文原词，必要时括号给中文释义）。
- 结论尽量给出证据/引用（见下方页码链接规范）。
- {tools_note.strip()}
- {cite_note.strip()}

项目术语记忆（截断）：
{term_note}

项目内其他论文（用于对比，截断）：
{other_note}

公式清单（若有page，优先用于公式解析维度）：
{formulas}

图表/资产清单（若有page，优先用于实验维度）：
{assets}

论文内容摘录（头尾截断）：
{paper_excerpt}
"""

    def _compose_report(self, paper: Paper, dims: list[str], results: dict[str, str]) -> str:
        header = f"# 深度解析报告\n\n**论文**：{paper.title}\n\n"
        body = "\n\n".join(results.get(d, "").strip() for d in dims if results.get(d))
        return (header + body).strip()

    async def run(self, job_id: uuid.UUID) -> None:
        job = await self.db.get(AnalysisJob, job_id)
        if not job:
            return

        # Load user-specific settings
        user_settings = await get_openai_settings(self.db, job.user_id)

        # Create OpenAI client with user-specific settings
        self.client = AsyncOpenAI(
            api_key=user_settings["api_key"] or None,
            base_url=user_settings["base_url"] or None,
        )
        self.model = user_settings["model"]

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.completed_at = None
        job.error = None
        await self.db.commit()
        await self.publish_progress(job_id, {"type": "status", "status": "running"})

        paper = await self._load_paper(job.paper_id)
        if not paper:
            raise ValueError("Paper not found")

        project = await self.db.get(Project, job.project_id)
        domain = (project.domain if project else "") or ""

        dims = (job.dimensions or []) or DEEP_DIMENSIONS
        total = len(dims)

        term_memory = await self._load_term_memory(job.project_id)
        other_papers = await self._load_other_papers(job.project_id, paper.id)

        paper_text = self._build_paper_text(paper)
        excerpt = self._truncate_head_tail(paper_text, max_chars=18000)
        formulas = self._format_formulas(paper)
        assets = self._format_assets(paper)

        tool_names = ", ".join(t.name for t in self.tools) if self.tools else "无"

        async def on_tool_progress(event: dict) -> None:
            await self.publish_progress(job_id, event)

        agent = ReActAgent(
            client=self.client,
            tools=self.tools,
            max_steps=6,
            temperature=0.2,
            on_progress=on_tool_progress,
        )

        results_by_dim: dict[str, str] = {}

        for i, dim in enumerate(dims, start=1):
            meta = DIM_META.get(dim, {"title": dim, "instruction": ""})
            await self.publish_progress(job_id, {
                "type": "progress",
                "step": "dimension_start",
                "current": i,
                "total": total,
                "dimension": dim,
                "dimension_title": meta["title"],
            })

            prompt = self._user_prompt(
                dim_key=dim,
                dim_title=meta["title"],
                idx=i,
                total=total,
                paper_excerpt=excerpt,
                formulas=formulas,
                assets=assets,
                term_memory_lines=term_memory,
                other_papers_lines=other_papers,
                instruction=meta.get("instruction", ""),
            )

            try:
                content = await agent.run(
                    system_prompt=self._system_prompt(domain=domain, tool_names=tool_names),
                    user_prompt=prompt,
                    max_tokens=3500,
                )
            except Exception as e:
                logger.error(f"Dimension {dim} analysis failed: {e}")
                content = f"*[分析失败: {str(e)[:100]}]*"

            results_by_dim[dim] = content or ""
            self.db.add(AnalysisResult(
                job_id=job_id,
                dimension=dim,
                summary=content or "",
                evidences={"dimension_title": meta["title"]},
            ))
            await self.db.commit()

            await self.publish_progress(job_id, {
                "type": "dimension_result",
                "dimension": dim,
                "dimension_title": meta["title"],
                "summary": content or "",
            })

        report_md = self._compose_report(paper=paper, dims=dims, results=results_by_dim)
        self.db.add(AnalysisResult(
            job_id=job_id,
            dimension="report",
            summary=report_md,
            evidences={"dimensions": dims},
        ))

        job.status = "succeeded"
        job.completed_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.publish_progress(job_id, {"type": "status", "status": "succeeded"})


async def run_deep_analysis_task(job_id: uuid.UUID) -> None:
    async with async_session_maker() as db:
        service = DeepAnalysisService(db)
        try:
            await service.run(job_id)
        except Exception as e:
            logger.exception("Deep analysis failed", extra={"job_id": str(job_id)})
            job = await db.get(AnalysisJob, job_id)
            if job:
                job.status = "failed"
                job.error = str(e)
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
            await DeepAnalysisService.publish_progress(job_id, {
                "type": "status",
                "status": "failed",
                "error": str(e)[:200],
            })
            raise
