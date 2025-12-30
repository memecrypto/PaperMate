import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core import get_db
from app.models import Project, ProjectMember, Paper, Term, User, OrgMembership
from app.schemas import ProjectCreate, ProjectUpdate, ProjectResponse
from app.api.v1.auth import get_current_user

router = APIRouter()


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_data: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    org_member = await db.execute(
        select(OrgMembership).where(
            OrgMembership.org_id == project_data.org_id,
            OrgMembership.user_id == current_user.id,
        )
    )
    if not org_member.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to organization")

    project = Project(
        org_id=project_data.org_id,
        name=project_data.name,
        domain=project_data.domain,
        description=project_data.description
    )
    db.add(project)
    await db.flush()

    member = ProjectMember(project_id=project.id, user_id=current_user.id, role="owner")
    db.add(member)

    await db.commit()
    await db.refresh(project)

    return ProjectResponse(
        id=project.id,
        org_id=project.org_id,
        name=project.name,
        domain=project.domain,
        description=project.description,
        settings=project.settings,
        created_at=project.created_at,
        updated_at=project.updated_at,
        paper_count=0,
        term_count=0
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0)
):
    subq_papers = (
        select(Paper.project_id, func.count(Paper.id).label("paper_count"))
        .group_by(Paper.project_id)
        .subquery()
    )
    subq_terms = (
        select(Term.project_id, func.count(Term.id).label("term_count"))
        .group_by(Term.project_id)
        .subquery()
    )

    query = (
        select(
            Project,
            func.coalesce(subq_papers.c.paper_count, 0).label("paper_count"),
            func.coalesce(subq_terms.c.term_count, 0).label("term_count")
        )
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .outerjoin(subq_papers, subq_papers.c.project_id == Project.id)
        .outerjoin(subq_terms, subq_terms.c.project_id == Project.id)
        .where(ProjectMember.user_id == current_user.id)
        .order_by(Project.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        ProjectResponse(
            id=row.Project.id,
            org_id=row.Project.org_id,
            name=row.Project.name,
            domain=row.Project.domain,
            description=row.Project.description,
            settings=row.Project.settings,
            created_at=row.Project.created_at,
            updated_at=row.Project.updated_at,
            paper_count=row.paper_count,
            term_count=row.term_count
        )
        for row in rows
    ]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(Project.id == project_id, ProjectMember.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    paper_count = await db.scalar(
        select(func.count(Paper.id)).where(Paper.project_id == project_id)
    )
    term_count = await db.scalar(
        select(func.count(Term.id)).where(Term.project_id == project_id)
    )

    return ProjectResponse(
        id=project.id,
        org_id=project.org_id,
        name=project.name,
        domain=project.domain,
        description=project.description,
        settings=project.settings,
        created_at=project.created_at,
        updated_at=project.updated_at,
        paper_count=paper_count or 0,
        term_count=term_count or 0
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: uuid.UUID,
    project_data: ProjectUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(
            Project.id == project_id,
            ProjectMember.user_id == current_user.id,
            ProjectMember.role.in_(["owner", "admin"])
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found or no permission")

    update_data = project_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)

    await db.commit()
    await db.refresh(project)

    paper_count = await db.scalar(
        select(func.count(Paper.id)).where(Paper.project_id == project_id)
    )
    term_count = await db.scalar(
        select(func.count(Term.id)).where(Term.project_id == project_id)
    )

    return ProjectResponse(
        id=project.id,
        org_id=project.org_id,
        name=project.name,
        domain=project.domain,
        description=project.description,
        settings=project.settings,
        created_at=project.created_at,
        updated_at=project.updated_at,
        paper_count=paper_count or 0,
        term_count=term_count or 0
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(
            Project.id == project_id,
            ProjectMember.user_id == current_user.id,
            ProjectMember.role == "owner"
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found or no permission")

    await db.delete(project)
    await db.commit()
