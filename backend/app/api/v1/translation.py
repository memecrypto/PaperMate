import uuid
import json
import asyncio
from typing import Annotated, AsyncGenerator

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.models import PaperTranslation, Paper, PaperSection, ProjectMember, User, TranslationGroup
from app.schemas import TranslationCreate, TranslationResponse
from app.api.v1.auth import get_current_user
from app.services.translation_service import (
    TranslationService, run_translation_task, run_translation_group_retry_task
)

router = APIRouter()


class TranslationGroupResponse(BaseModel):
    id: uuid.UUID
    translation_id: uuid.UUID
    section_id: uuid.UUID
    section_title: str | None = None
    group_order: int
    source_md: str
    translated_md: str | None
    status: str
    attempts: int
    last_error: str | None

    class Config:
        from_attributes = True


async def _check_translation_access(
    db: AsyncSession, translation_id: uuid.UUID, user_id: uuid.UUID
) -> PaperTranslation | None:
    result = await db.execute(
        select(PaperTranslation)
        .join(Paper, Paper.id == PaperTranslation.paper_id)
        .join(ProjectMember, ProjectMember.project_id == Paper.project_id)
        .where(
            PaperTranslation.id == translation_id,
            ProjectMember.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


@router.post("", response_model=TranslationResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_translation(
    request: TranslationCreate,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start a translation job for a paper."""
    paper = await db.get(Paper, request.paper_id)
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")

    member = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == paper.project_id,
            ProjectMember.user_id == current_user.id,
        )
    )
    if not member.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access")

    translation = PaperTranslation(
        paper_id=paper.id,
        target_language=request.target_language,
        mode=request.mode,
        status="queued",
        user_id=current_user.id,
    )
    db.add(translation)
    await db.commit()
    await db.refresh(translation)

    TranslationService.get_progress_queue(translation.id)
    background_tasks.add_task(run_translation_task, translation.id)

    return translation


@router.get("/{translation_id}", response_model=TranslationResponse)
async def get_translation(
    translation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get translation status and result."""
    translation = await _check_translation_access(db, translation_id, current_user.id)
    if not translation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Translation not found")
    return translation


@router.get("/{translation_id}/groups", response_model=list[TranslationGroupResponse])
async def list_translation_groups(
    translation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all translation groups for a translation."""
    translation = await _check_translation_access(db, translation_id, current_user.id)
    if not translation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Translation not found")

    result = await db.execute(
        select(TranslationGroup, PaperSection.title, PaperSection.section_type)
        .join(PaperSection, PaperSection.id == TranslationGroup.section_id)
        .where(TranslationGroup.translation_id == translation_id)
        .order_by(
            func.coalesce(PaperSection.page_start, 0),
            func.coalesce(PaperSection.char_start, 0),
            PaperSection.created_at,
            TranslationGroup.group_order,
        )
    )
    groups = []
    for row in result.all():
        group = row[0]
        section_title = row[1] or row[2] or "Section"
        groups.append(TranslationGroupResponse(
            id=group.id,
            translation_id=group.translation_id,
            section_id=group.section_id,
            section_title=section_title,
            group_order=group.group_order,
            source_md=group.source_md,
            translated_md=group.translated_md,
            status=group.status,
            attempts=group.attempts,
            last_error=group.last_error,
        ))
    return groups


@router.post(
    "/{translation_id}/groups/{group_id}/retry",
    response_model=TranslationGroupResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_translation_group(
    translation_id: uuid.UUID,
    group_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Retry a failed translation group."""
    translation = await _check_translation_access(db, translation_id, current_user.id)
    if not translation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Translation not found")

    group = await db.get(TranslationGroup, group_id)
    if not group or group.translation_id != translation_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Translation group not found")

    if group.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Translation group is running")

    if group.status not in ("failed", "queued"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Group is not failed or queued")

    group.status = "queued"
    group.last_error = None
    group.translated_md = None
    await db.commit()
    await db.refresh(group)

    background_tasks.add_task(run_translation_group_retry_task, group.id)
    return group


@router.get("/{translation_id}/stream")
async def stream_translation(
    translation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """SSE stream for translation progress."""
    translation = await _check_translation_access(db, translation_id, current_user.id)
    if not translation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Translation not found")

    queue = TranslationService.get_progress_queue(translation_id)

    async def generate() -> AsyncGenerator[str, None]:
        if translation.content_md:
            snapshot = json.dumps(
                {"type": "snapshot", "content_md": translation.content_md},
                ensure_ascii=False,
            )
            yield f"data: {snapshot}\n\n"

        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    current_status = await db.scalar(
                        select(PaperTranslation.status).where(PaperTranslation.id == translation_id)
                    )
                    if current_status in ("succeeded", "failed", "cancelled") and queue.empty():
                        break
                    yield 'data: {"type": "ping"}\n\n'
        finally:
            TranslationService.release_progress(translation_id)

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


@router.get("", response_model=list[TranslationResponse])
async def list_translations(
    paper_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List translations for a paper."""
    paper = await db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")

    member = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == paper.project_id,
            ProjectMember.user_id == current_user.id,
        )
    )
    if not member.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access")

    result = await db.execute(
        select(PaperTranslation)
        .where(PaperTranslation.paper_id == paper_id)
        .order_by(PaperTranslation.created_at.desc())
    )
    return result.scalars().all()
