import uuid
from typing import Annotated
import mimetypes
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core import get_db
from app.models import Paper, PaperFile, PaperAsset, Project, ProjectMember, User
from app.schemas import PaperCreate, PaperResponse, PaperDetailResponse
from app.api.v1.auth import get_current_user
from app.services.storage import StorageService
from app.services.paper_parser import parse_paper_task

router = APIRouter()


async def verify_project_access(
    project_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
    required_roles: list[str] | None = None
) -> Project:
    """Verify user has access to a project and return the project."""
    query = (
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(Project.id == project_id, ProjectMember.user_id == current_user.id)
    )
    if required_roles:
        query = query.where(ProjectMember.role.in_(required_roles))

    result = await db.execute(query)
    project = result.scalar_one_or_none()
    if not project:
        if required_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found or no access")
    return project


async def verify_paper_access(
    paper_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
    required_roles: list[str] | None = None
) -> Paper:
    """Verify user has access to a paper and return the paper."""
    result = await db.execute(
        select(Paper).options(selectinload(Paper.files)).where(Paper.id == paper_id)
    )
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")

    query = select(ProjectMember).where(
        ProjectMember.project_id == paper.project_id,
        ProjectMember.user_id == current_user.id
    )
    if required_roles:
        query = query.where(ProjectMember.role.in_(required_roles))

    member_result = await db.execute(query)
    if not member_result.scalar_one_or_none():
        if required_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this paper")

    return paper


@router.get("/files/{storage_key:path}")
async def get_stored_file(
    storage_key: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Serve locally stored paper assets (PDFs, images) with authentication and authorization."""
    # Verify user has access to the file by checking project membership
    result = await db.execute(
        select(PaperFile)
        .join(Paper, Paper.id == PaperFile.paper_id)
        .join(ProjectMember, ProjectMember.project_id == Paper.project_id)
        .where(
            PaperFile.storage_key == storage_key,
            ProjectMember.user_id == current_user.id
        )
    )
    if not result.scalar_one_or_none():
        # Also check PaperAsset for image files
        asset_result = await db.execute(
            select(PaperAsset)
            .join(Paper, Paper.id == PaperAsset.paper_id)
            .join(ProjectMember, ProjectMember.project_id == Paper.project_id)
            .where(
                PaperAsset.storage_key == storage_key,
                ProjectMember.user_id == current_user.id
            )
        )
        if not asset_result.scalar_one_or_none():
            # Fallback: check if storage_key is in paper_assets/{paper_id}/ format
            # and verify user has access to that paper
            import re
            match = re.match(r"paper_assets/([0-9a-f-]{36})/", storage_key)
            if match:
                paper_id = match.group(1)
                paper_access = await db.execute(
                    select(Paper)
                    .join(ProjectMember, ProjectMember.project_id == Paper.project_id)
                    .where(
                        Paper.id == uuid.UUID(paper_id),
                        ProjectMember.user_id == current_user.id
                    )
                )
                if not paper_access.scalar_one_or_none():
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this file")
            else:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this file")

    storage = StorageService()

    try:
        file_path = await storage.get_file_path(storage_key)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    media_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(path=file_path, media_type=media_type or "application/octet-stream")


@router.post("/upload", response_model=PaperResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_paper(
    project_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...)
):
    """Upload a PDF file and trigger parsing."""
    await verify_project_access(project_id, current_user, db)

    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported")

    storage = StorageService()
    max_size = 50 * 1024 * 1024
    try:
        storage_key = await storage.save_upload_file(
            file,
            max_size=max_size,
            required_ext=".pdf",
            magic_header=b"%PDF-",
        )
    except ValueError as e:
        msg = str(e)
        if msg == "File size exceeds limit":
            msg = "File size exceeds 50MB limit"
        elif msg == "Invalid file format":
            msg = "Invalid PDF file format"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    paper = Paper(
        project_id=project_id,
        title=file.filename.replace(".pdf", "").replace("_", " "),
        status="parsing"
    )
    db.add(paper)
    await db.flush()

    paper_file = PaperFile(
        paper_id=paper.id,
        storage_key=storage_key,
        mime_type="application/pdf"
    )
    db.add(paper_file)

    await db.commit()
    await db.refresh(paper)

    background_tasks.add_task(parse_paper_task, paper.id, storage_key)

    return paper


@router.post("", response_model=PaperResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_paper(
    paper_data: PaperCreate,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Create paper from storage key or external ID (arXiv/DOI)."""
    await verify_project_access(paper_data.project_id, current_user, db)

    paper = Paper(
        project_id=paper_data.project_id,
        title="Untitled Paper",
        arxiv_id=paper_data.arxiv_id,
        doi=paper_data.doi,
        status="parsing" if paper_data.storage_key else "pending"
    )
    db.add(paper)
    await db.flush()

    if paper_data.storage_key:
        paper_file = PaperFile(
            paper_id=paper.id,
            storage_key=paper_data.storage_key,
            mime_type="application/pdf"
        )
        db.add(paper_file)
        background_tasks.add_task(parse_paper_task, paper.id, paper_data.storage_key)

    await db.commit()
    await db.refresh(paper)

    return paper


@router.get("", response_model=list[PaperResponse])
async def list_papers(
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0)
):
    await verify_project_access(project_id, current_user, db)

    result = await db.execute(
        select(Paper)
        .where(Paper.project_id == project_id)
        .order_by(Paper.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    papers = result.scalars().all()
    return papers


@router.get("/{paper_id}", response_model=PaperDetailResponse)
async def get_paper(
    paper_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    # Use custom query to load sections, assets, formulas
    result = await db.execute(
        select(Paper)
        .options(
            selectinload(Paper.sections),
            selectinload(Paper.assets),
            selectinload(Paper.formulas)
        )
        .where(Paper.id == paper_id)
    )
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")

    # Verify access
    query = select(ProjectMember).where(
        ProjectMember.project_id == paper.project_id,
        ProjectMember.user_id == current_user.id
    )
    member_result = await db.execute(query)
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this paper")

    return PaperDetailResponse(
        id=paper.id,
        project_id=paper.project_id,
        title=paper.title,
        abstract=paper.abstract,
        authors=paper.authors,
        arxiv_id=paper.arxiv_id,
        doi=paper.doi,
        language=paper.language,
        status=paper.status,
        published_at=paper.published_at,
        created_at=paper.created_at,
        sections=[s for s in paper.sections],
        assets=[a for a in paper.assets],
        formulas=[f for f in paper.formulas]
    )


@router.get("/{paper_id}/pdf")
async def get_paper_pdf(
    paper_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Download/preview original PDF for a paper."""
    paper = await verify_paper_access(paper_id, current_user, db)

    if not paper.files:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No PDF file associated with this paper")

    storage = StorageService()
    file_path = await storage.get_file_path(paper.files[0].storage_key)
    return FileResponse(path=file_path, media_type="application/pdf")


@router.post("/{paper_id}/reparse", status_code=status.HTTP_202_ACCEPTED)
async def reparse_paper(
    paper_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Trigger re-parsing of a paper."""
    paper = await verify_paper_access(paper_id, current_user, db)

    if not paper.files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No PDF file associated with this paper")

    paper.status = "parsing"
    await db.commit()

    storage_key = paper.files[0].storage_key
    background_tasks.add_task(parse_paper_task, paper.id, storage_key)

    return {"status": "queued", "paper_id": str(paper_id)}


@router.delete("/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_paper(
    paper_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    paper = await verify_paper_access(paper_id, current_user, db, required_roles=["owner", "admin"])

    storage = StorageService()
    for paper_file in paper.files:
        try:
            await storage.delete_file(paper_file.storage_key)
        except FileNotFoundError:
            pass

    await db.delete(paper)
    await db.commit()
