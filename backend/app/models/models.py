import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import (
    String, Text, Boolean, Integer, SmallInteger, DateTime, ForeignKey,
    UniqueConstraint, Index, JSON, Numeric, Date, CheckConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from pgvector.sqlalchemy import Vector
from app.core.database import Base


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class AssetType(str, Enum):
    FIGURE = "figure"
    TABLE = "table"
    DATASET = "dataset"
    SUPPLEMENT = "supplement"


class AnalysisDimension(str, Enum):
    # Simple analysis (existing)
    NOVELTY = "novelty"
    METHODOLOGY = "methodology"
    RESULTS = "results"
    ASSUMPTIONS = "assumptions"
    LIMITATIONS = "limitations"
    REPRODUCIBILITY = "reproducibility"
    RELATED_WORK = "related_work"

    # Deep Analysis Agent (design.md 4.2)
    BACKGROUND_MOTIVATION = "background_motivation"
    CORE_INNOVATIONS = "core_innovations"
    METHODOLOGY_DETAILS = "methodology_details"
    FORMULA_ANALYSIS = "formula_analysis"
    EXPERIMENTS_RESULTS = "experiments_results"
    ADVANTAGES_LIMITATIONS = "advantages_limitations"
    FUTURE_DIRECTIONS = "future_directions"
    REPORT = "report"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConfirmStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


def _utc_now() -> datetime:
    """Return current UTC time with timezone info."""
    from datetime import timezone
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    expertise_level: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )

    org_memberships: Mapped[list["OrgMembership"]] = relationship(
        back_populates="user",
        cascade="all, delete",
        passive_deletes=True,
    )
    project_memberships: Mapped[list["ProjectMember"]] = relationship(
        back_populates="user",
        cascade="all, delete",
        passive_deletes=True,
    )
    profile: Mapped["UserProfile"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )

    members: Mapped[list["OrgMembership"]] = relationship(
        back_populates="organization",
        cascade="all, delete",
        passive_deletes=True,
    )
    projects: Mapped[list["Project"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class OrgMembership(Base):
    __tablename__ = "org_membership"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[Role] = mapped_column(String(20), default=Role.MEMBER)

    organization: Mapped["Organization"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="org_memberships")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )

    organization: Mapped["Organization"] = relationship(back_populates="projects")
    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project",
        cascade="all, delete",
        passive_deletes=True,
    )
    papers: Mapped[list["Paper"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    terms: Mapped[list["Term"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (Index("idx_projects_org", "org_id"),)


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[Role] = mapped_column(String(20), default=Role.MEMBER)

    project: Mapped["Project"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="project_memberships")


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    arxiv_id: Mapped[str | None] = mapped_column(String(50))
    doi: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default="en")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    published_at: Mapped[datetime | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    project: Mapped["Project"] = relationship(back_populates="papers")
    files: Mapped[list["PaperFile"]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sections: Mapped[list["PaperSection"]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    references: Mapped[list["PaperReference"]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    formulas: Mapped[list["PaperFormula"]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    assets: Mapped[list["PaperAsset"]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    term_occurrences: Mapped[list["TermOccurrence"]] = relationship(
        back_populates="paper",
        cascade="all, delete",
        passive_deletes=True,
    )
    analysis_jobs: Mapped[list["AnalysisJob"]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    translations: Mapped[list["PaperTranslation"]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("idx_papers_project", "project_id"),
        UniqueConstraint("project_id", "doi", name="uq_papers_proj_doi"),
        UniqueConstraint("project_id", "arxiv_id", name="uq_papers_proj_arxiv"),
    )


class PaperFile(Base):
    __tablename__ = "paper_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    pages: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    paper: Mapped["Paper"] = relationship(back_populates="files")


class PaperSection(Base):
    __tablename__ = "paper_sections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    section_type: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str | None] = mapped_column(String(500))
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    content_text: Mapped[str | None] = mapped_column(Text)
    content_md: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    paper: Mapped["Paper"] = relationship(back_populates="sections")

    __table_args__ = (Index("idx_sections_paper", "paper_id"),)


class PaperReference(Base):
    __tablename__ = "paper_references"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    ref_index: Mapped[int | None] = mapped_column(Integer)
    raw_citation: Mapped[str] = mapped_column(Text, nullable=False)
    doi: Mapped[str | None] = mapped_column(String(255))
    arxiv_id: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    paper: Mapped["Paper"] = relationship(back_populates="references")

    __table_args__ = (Index("idx_refs_paper", "paper_id"),)


class PaperFormula(Base):
    __tablename__ = "paper_formulas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    latex: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    paper: Mapped["Paper"] = relationship(back_populates="formulas")

    __table_args__ = (Index("idx_formulas_paper", "paper_id"),)


class PaperAsset(Base):
    __tablename__ = "paper_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[AssetType] = mapped_column(String(20), nullable=False)
    label: Mapped[str | None] = mapped_column(String(100))
    caption: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[dict | None] = mapped_column(JSON)
    storage_key: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    paper: Mapped["Paper"] = relationship(back_populates="assets")

    __table_args__ = (Index("idx_assets_paper", "paper_id"),)


class PaperTranslation(Base):
    __tablename__ = "paper_translations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    target_language: Mapped[str] = mapped_column(String(10), default="zh")
    mode: Mapped[str] = mapped_column(String(20), default="quick")
    content_md: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    paper: Mapped["Paper"] = relationship(back_populates="translations")
    groups: Mapped[list["TranslationGroup"]] = relationship(
        back_populates="translation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TranslationGroup(Base):
    __tablename__ = "translation_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    translation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_translations.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_sections.id", ondelete="CASCADE"), nullable=False
    )
    group_order: Mapped[int] = mapped_column(Integer, nullable=False)
    source_md: Mapped[str] = mapped_column(Text, nullable=False)
    translated_md: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)

    translation: Mapped["PaperTranslation"] = relationship(back_populates="groups")
    section: Mapped["PaperSection"] = relationship()

    __table_args__ = (
        UniqueConstraint("translation_id", "section_id", "group_order", name="uq_trans_group_order"),
        Index("idx_trans_groups_translation", "translation_id"),
        Index("idx_trans_groups_trans_status", "translation_id", "status"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="chk_trans_group_status"),
    )


class Term(Base):
    __tablename__ = "terms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    phrase: Mapped[str] = mapped_column(String(500), nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    project: Mapped["Project"] = relationship(back_populates="terms")
    aliases: Mapped[list["TermAlias"]] = relationship(
        back_populates="term",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    occurrences: Mapped[list["TermOccurrence"]] = relationship(
        back_populates="term",
        cascade="all, delete",
        passive_deletes=True,
    )
    knowledge: Mapped["KnowledgeTerm"] = relationship(
        back_populates="term",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("project_id", "phrase", "language", name="uq_term_phrase_proj"),
    )


class TermAlias(Base):
    __tablename__ = "term_aliases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("terms.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(500), nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en")

    term: Mapped["Term"] = relationship(back_populates="aliases")

    __table_args__ = (Index("idx_alias_term", "term_id"),)


class TermOccurrence(Base):
    __tablename__ = "term_occurrences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("terms.id", ondelete="CASCADE"), nullable=False
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_sections.id", ondelete="SET NULL")
    )
    page: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    text_snippet: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    term: Mapped["Term"] = relationship(back_populates="occurrences")
    paper: Mapped["Paper"] = relationship(back_populates="term_occurrences")

    __table_args__ = (
        Index("idx_occ_term", "term_id"),
        Index("idx_occ_paper", "paper_id"),
    )


class KnowledgeTerm(Base):
    __tablename__ = "knowledge_terms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("terms.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    canonical_en: Mapped[str | None] = mapped_column(String(500))
    translation: Mapped[str | None] = mapped_column(String(500))
    definition: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[ConfirmStatus] = mapped_column(String(20), default=ConfirmStatus.PENDING)
    suggested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    term: Mapped["Term"] = relationship(back_populates="knowledge")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    expertise_levels: Mapped[dict] = mapped_column(JSON, default=dict)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    difficult_topics: Mapped[list] = mapped_column(JSON, default=list)
    mastered_topics: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )

    user: Mapped["User"] = relationship(back_populates="profile")


class ChatThread(Base):
    __tablename__ = "chat_threads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("idx_threads_scope", "scope_type", "scope_id"),
        CheckConstraint("scope_type IN ('paper', 'project')", name="chk_scope_type"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_threads.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    thread: Mapped["ChatThread"] = relationship(back_populates="messages")
    parent: Mapped["ChatMessage | None"] = relationship(
        "ChatMessage", remote_side=[id], foreign_keys=[parent_id]
    )
    citations: Mapped[list["ChatMessageCitation"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("idx_msgs_thread", "thread_id"),
        Index("idx_msgs_parent", "parent_id"),
        CheckConstraint("role IN ('user', 'assistant', 'system')", name="chk_msg_role"),
    )


class ChatMessageCitation(Base):
    __tablename__ = "chat_message_citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_sections.id", ondelete="SET NULL")
    )
    page: Mapped[int | None] = mapped_column(Integer)
    span: Mapped[dict | None] = mapped_column(JSON)

    message: Mapped["ChatMessage"] = relationship(back_populates="citations")


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[JobStatus] = mapped_column(String(20), default=JobStatus.QUEUED)
    dimensions: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    paper: Mapped["Paper"] = relationship(back_populates="analysis_jobs")
    results: Mapped[list["AnalysisResult"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (Index("idx_jobs_paper", "paper_id"),)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False
    )
    dimension: Mapped[AnalysisDimension] = mapped_column(String(30), nullable=False)
    score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    summary: Mapped[str | None] = mapped_column(Text)
    evidences: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    job: Mapped["AnalysisJob"] = relationship(back_populates="results")

    __table_args__ = (UniqueConstraint("job_id", "dimension", name="uq_result_job_dim"),)


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_type: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    model: Mapped[str] = mapped_column(String(50), nullable=False)
    dims: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    vector: Mapped[list] = mapped_column(Vector(1536), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    __table_args__ = (Index("idx_embed_owner", "owner_type", "owner_id"),)


class ToolCallLog(Base):
    __tablename__ = "tool_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="SET NULL")
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    args: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
