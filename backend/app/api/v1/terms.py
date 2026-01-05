import uuid
from typing import Annotated, AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core import get_db
from app.models import Term, TermOccurrence, KnowledgeTerm, ProjectMember, Paper, User
from app.schemas import (
    TermCreate, TermResponse, TermWithKnowledge,
    KnowledgeTermCreate, KnowledgeTermResponse,
    TermConfirmation, TermAnalyzeRequest, TermScanRequest, TermSuggestion
)
from app.api.v1.auth import get_current_user
from app.services.term_service import TermService
from app.services.term_analyze_service import TermAnalyzeService

router = APIRouter()


@router.get("", response_model=list[TermWithKnowledge])
async def list_terms(
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=100, le=200),
    offset: int = Query(default=0, ge=0),
    search: str | None = None
):
    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == current_user.id
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access")

    query = (
        select(Term, func.count(TermOccurrence.id).label("occurrence_count"))
        .outerjoin(TermOccurrence, TermOccurrence.term_id == Term.id)
        .options(selectinload(Term.knowledge))
        .where(Term.project_id == project_id)
        .group_by(Term.id)
        .order_by(Term.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    if search:
        query = query.where(Term.phrase.ilike(f"%{search}%"))

    result = await db.execute(query)
    rows = result.all()

    return [
        TermWithKnowledge(
            id=row.Term.id,
            project_id=row.Term.project_id,
            phrase=row.Term.phrase,
            language=row.Term.language,
            created_at=row.Term.created_at,
            occurrence_count=row.occurrence_count,
            knowledge=row.Term.knowledge
        )
        for row in rows
    ]


@router.post("", response_model=TermResponse, status_code=status.HTTP_201_CREATED)
async def create_term(
    term_data: TermCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == term_data.project_id,
            ProjectMember.user_id == current_user.id
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access")

    existing = await db.execute(
        select(Term).where(
            Term.project_id == term_data.project_id,
            Term.phrase == term_data.phrase,
            Term.language == term_data.language
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Term already exists")

    term = Term(
        project_id=term_data.project_id,
        phrase=term_data.phrase,
        language=term_data.language,
        created_by=current_user.id
    )
    db.add(term)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Term already exists",
        )
    await db.refresh(term)

    return TermResponse(
        id=term.id,
        project_id=term.project_id,
        phrase=term.phrase,
        language=term.language,
        created_at=term.created_at,
        occurrence_count=0
    )


@router.post("/analyze", response_model=TermSuggestion)
async def analyze_term(
    request: TermAnalyzeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    debug_raw: bool = Query(default=False),
):
    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == request.project_id,
            ProjectMember.user_id == current_user.id
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access")

    term_service = TermService(db)
    return await term_service.analyze_term(
        request.phrase, request.project_id, request.paper_id, context=request.context, debug_raw=debug_raw
    )


@router.post("/analyze/stream")
async def analyze_term_stream(
    request: TermAnalyzeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Stream term analysis with tool calling progress.

    Returns SSE stream with events:
    - status: Progress messages
    - tool_call: Tool being called
    - tool_result: Tool result summary
    - content: Explanation text
    - done: Final result with term, translation, explanation
    - error: Error message
    """
    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == request.project_id,
            ProjectMember.user_id == current_user.id
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access")

    service = TermAnalyzeService(db, current_user.id)

    async def event_generator() -> AsyncGenerator[str, None]:
        async for chunk in service.analyze_term_stream(
            phrase=request.phrase,
            project_id=request.project_id,
            paper_id=request.paper_id,
            context=request.context,
        ):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/{term_id}/confirm", response_model=KnowledgeTermResponse)
async def confirm_term(
    term_id: uuid.UUID,
    confirmation: KnowledgeTermCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(
        select(Term).options(selectinload(Term.knowledge)).where(Term.id == term_id)
    )
    term = result.scalar_one_or_none()
    if not term:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Term not found")

    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == term.project_id,
            ProjectMember.user_id == current_user.id
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access")

    if term.knowledge:
        term.knowledge.canonical_en = confirmation.canonical_en or term.knowledge.canonical_en
        term.knowledge.translation = confirmation.translation or term.knowledge.translation
        term.knowledge.definition = confirmation.definition or term.knowledge.definition
        term.knowledge.sources = confirmation.sources or term.knowledge.sources
        term.knowledge.status = "confirmed"
        term.knowledge.confirmed_by = current_user.id
        from datetime import datetime, timezone
        term.knowledge.confirmed_at = datetime.now(timezone.utc)
    else:
        knowledge = KnowledgeTerm(
            term_id=term_id,
            canonical_en=confirmation.canonical_en,
            translation=confirmation.translation,
            definition=confirmation.definition,
            sources=confirmation.sources,
            status="confirmed",
            confirmed_by=current_user.id
        )
        from datetime import datetime, timezone
        knowledge.confirmed_at = datetime.now(timezone.utc)
        db.add(knowledge)

    await db.commit()

    result = await db.execute(
        select(KnowledgeTerm).where(KnowledgeTerm.term_id == term_id)
    )
    return result.scalar_one()


@router.post("/{term_id}/scan")
async def scan_term_in_paper(
    term_id: uuid.UUID,
    request: TermScanRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    term = await db.get(Term, term_id)
    if not term:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Term not found")

    paper = await db.get(Paper, request.paper_id)
    if not paper or paper.project_id != term.project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")

    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == term.project_id,
            ProjectMember.user_id == current_user.id,
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access")

    term_service = TermService(db)
    count = await term_service.scan_paper_for_term(term_id, request.paper_id)
    return {"occurrence_count": count}


@router.get("/{term_id}", response_model=TermWithKnowledge)
async def get_term(
    term_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(
        select(Term, func.count(TermOccurrence.id).label("occurrence_count"))
        .outerjoin(TermOccurrence, TermOccurrence.term_id == Term.id)
        .options(selectinload(Term.knowledge))
        .where(Term.id == term_id)
        .group_by(Term.id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Term not found")

    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == row.Term.project_id,
            ProjectMember.user_id == current_user.id
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access")

    return TermWithKnowledge(
        id=row.Term.id,
        project_id=row.Term.project_id,
        phrase=row.Term.phrase,
        language=row.Term.language,
        created_at=row.Term.created_at,
        occurrence_count=row.occurrence_count,
        knowledge=row.Term.knowledge
    )


@router.delete("/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_term(
    term_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(select(Term).where(Term.id == term_id))
    term = result.scalar_one_or_none()
    if not term:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Term not found")

    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == term.project_id,
            ProjectMember.user_id == current_user.id,
            ProjectMember.role.in_(["owner", "admin"])
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission")

    await db.delete(term)
    await db.commit()
