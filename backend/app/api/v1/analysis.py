import uuid
import json
import asyncio
from typing import Annotated, AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core import get_db
from app.models import AnalysisJob, AnalysisResult, Paper, ProjectMember, User
from app.schemas import AnalysisJobCreate, AnalysisJobResponse, AnalysisResultResponse
from app.api.v1.auth import get_current_user
from app.services.deep_analysis_service import run_deep_analysis_task, DeepAnalysisService

router = APIRouter()


@router.post("/{paper_id}/run", response_model=AnalysisJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_analysis(
    paper_id: uuid.UUID,
    job_data: AnalysisJobCreate,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(select(Paper).where(Paper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")

    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == paper.project_id,
            ProjectMember.user_id == current_user.id
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access")

    job = AnalysisJob(
        paper_id=paper_id,
        project_id=paper.project_id,
        user_id=current_user.id,
        dimensions=job_data.dimensions,
        status="queued"
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    DeepAnalysisService.get_progress_queue(job.id)
    background_tasks.add_task(run_deep_analysis_task, job.id)

    return AnalysisJobResponse(
        id=job.id,
        paper_id=job.paper_id,
        status=job.status,
        dimensions=job.dimensions,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error=job.error
    )


@router.get("/{paper_id}/jobs", response_model=list[AnalysisJobResponse])
async def list_analysis_jobs(
    paper_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(select(Paper).where(Paper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")

    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == paper.project_id,
            ProjectMember.user_id == current_user.id
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access")

    jobs = await db.execute(
        select(AnalysisJob)
        .where(AnalysisJob.paper_id == paper_id)
        .order_by(AnalysisJob.started_at.desc())
    )
    return [
        AnalysisJobResponse(
            id=job.id,
            paper_id=job.paper_id,
            status=job.status,
            dimensions=job.dimensions,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error=job.error
        )
        for job in jobs.scalars().all()
    ]


@router.get("/{paper_id}/results", response_model=list[AnalysisResultResponse])
async def get_analysis_results(
    paper_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(select(Paper).where(Paper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")

    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == paper.project_id,
            ProjectMember.user_id == current_user.id
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access")

    latest_job = await db.execute(
        select(AnalysisJob)
        .where(AnalysisJob.paper_id == paper_id, AnalysisJob.status == "succeeded")
        .order_by(AnalysisJob.completed_at.desc())
        .limit(1)
    )
    job = latest_job.scalar_one_or_none()
    if not job:
        return []

    results = await db.execute(
        select(AnalysisResult).where(AnalysisResult.job_id == job.id)
    )
    return results.scalars().all()


@router.get("/jobs/{job_id}", response_model=AnalysisJobResponse)
async def get_job_status(
    job_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(select(AnalysisJob).where(AnalysisJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == job.project_id,
            ProjectMember.user_id == current_user.id
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access")

    return AnalysisJobResponse(
        id=job.id,
        paper_id=job.paper_id,
        status=job.status,
        dimensions=job.dimensions,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error=job.error
    )


@router.get("/jobs/{job_id}/results", response_model=list[AnalysisResultResponse])
async def get_job_results(
    job_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Get all results for a specific analysis job."""
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == job.project_id,
            ProjectMember.user_id == current_user.id
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access")

    results = await db.execute(
        select(AnalysisResult)
        .where(AnalysisResult.job_id == job_id)
        .order_by(AnalysisResult.created_at.asc())
    )
    return results.scalars().all()


@router.get("/jobs/{job_id}/stream")
async def stream_analysis(
    job_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Stream analysis progress events via Server-Sent Events."""
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == job.project_id,
            ProjectMember.user_id == current_user.id
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access")

    queue = DeepAnalysisService.get_progress_queue(job_id)

    async def generate() -> AsyncGenerator[str, None]:
        # Send snapshot of existing results
        existing = await db.execute(
            select(AnalysisResult)
            .where(AnalysisResult.job_id == job_id)
            .order_by(AnalysisResult.created_at.asc())
        )
        snapshot = json.dumps({
            "type": "snapshot",
            "results": [
                {"dimension": r.dimension, "summary": r.summary, "evidences": r.evidences}
                for r in existing.scalars().all()
            ]
        }, ensure_ascii=False)
        yield f"data: {snapshot}\n\n"

        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    current_status = await db.scalar(
                        select(AnalysisJob.status).where(AnalysisJob.id == job_id)
                    )
                    if current_status in ("succeeded", "failed", "cancelled") and queue.empty():
                        break
                    yield 'data: {"type": "ping"}\n\n'
        finally:
            DeepAnalysisService.release_progress(job_id)

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
