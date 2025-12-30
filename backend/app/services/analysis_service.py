import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from openai import AsyncOpenAI
from app.core.database import async_session_maker
from app.models import AnalysisJob, AnalysisResult, Paper, PaperSection
from app.services.openai_settings import get_openai_settings



async def run_analysis_task(job_id: uuid.UUID) -> None:
    async with async_session_maker() as db:
        try:
            job = await db.get(AnalysisJob, job_id)
            if not job:
                return

            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await db.commit()

            # Load user-specific settings
            user_settings = await get_openai_settings(db, job.user_id)

            paper_result = await db.execute(
                select(Paper)
                .options(selectinload(Paper.sections))
                .where(Paper.id == job.paper_id)
            )
            paper = paper_result.scalar_one_or_none()
            if not paper:
                job.status = "failed"
                job.error = "Paper not found"
                await db.commit()
                return

            paper_content = f"Title: {paper.title}\n\n"
            if paper.abstract:
                paper_content += f"Abstract: {paper.abstract}\n\n"
            for section in paper.sections:
                if section.content_text:
                    paper_content += f"## {section.title or section.section_type}\n{section.content_text[:3000]}\n\n"

            client = AsyncOpenAI(
                api_key=user_settings["api_key"] or None,
                base_url=user_settings["base_url"] or None
            )

            for dimension in job.dimensions:
                prompt = _get_analysis_prompt(dimension, paper_content)

                completion = await client.chat.completions.create(
                    model=user_settings["model"],
                    messages=[
                        {"role": "system", "content": "You are an expert academic paper analyst."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=2000
                )

                response = completion.choices[0].message.content or ""

                result = AnalysisResult(
                    job_id=job_id,
                    dimension=dimension,
                    summary=response,
                    evidences={"raw_response": response}
                )
                db.add(result)

            job.status = "succeeded"
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()

        except Exception as e:
            job = await db.get(AnalysisJob, job_id)
            if job:
                job.status = "failed"
                job.error = str(e)
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
            raise


def _get_analysis_prompt(dimension: str, paper_content: str) -> str:
    prompts = {
        "novelty": f"""Analyze the following paper and identify its core innovations (3-5 key points).
For each innovation:
1. Describe what is novel
2. Explain why it matters
3. Compare to prior approaches

Paper:
{paper_content[:8000]}

Format your response as a structured analysis with clear headings.""",

        "methodology": f"""Analyze the methodology of the following paper.
Include:
1. Overall approach/framework
2. Key algorithms or techniques
3. Data processing pipeline
4. Implementation details

Paper:
{paper_content[:8000]}

Provide a clear, structured explanation.""",

        "results": f"""Analyze the experimental results of the following paper.
Include:
1. Datasets used
2. Evaluation metrics
3. Main findings
4. Comparison with baselines
5. Statistical significance

Paper:
{paper_content[:8000]}

Summarize the key results and their implications.""",

        "assumptions": f"""Identify the key assumptions made in the following paper.
Include:
1. Explicit assumptions stated by authors
2. Implicit assumptions in the methodology
3. Potential limitations of these assumptions

Paper:
{paper_content[:8000]}""",

        "limitations": f"""Analyze the limitations of the following paper.
Include:
1. Limitations acknowledged by authors
2. Potential issues not addressed
3. Scope boundaries
4. Generalizability concerns

Paper:
{paper_content[:8000]}""",

        "reproducibility": f"""Assess the reproducibility of the following paper.
Consider:
1. Availability of code/data
2. Clarity of implementation details
3. Hyperparameter specification
4. Computing requirements

Paper:
{paper_content[:8000]}""",

        "related_work": f"""Analyze how this paper relates to existing literature.
Include:
1. Key prior works it builds upon
2. How it differs from related approaches
3. Research gaps it addresses

Paper:
{paper_content[:8000]}"""
    }

    return prompts.get(dimension, f"Analyze the {dimension} aspects of this paper:\n{paper_content[:8000]}")
