import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, EmailStr, Field, field_validator


class UserBase(BaseModel):
    email: EmailStr
    name: str | None = None


class UserCreate(UserBase):
    password: str = Field(min_length=6)


class UserUpdate(BaseModel):
    name: str | None = None
    expertise_level: int | None = None


class UserResponse(UserBase):
    id: uuid.UUID
    expertise_level: int
    is_active: bool
    is_superuser: bool = False
    created_at: datetime

    class Config:
        from_attributes = True




class TokenPayload(BaseModel):
    sub: str
    exp: datetime
    type: str


class ProjectBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    domain: str | None = None
    description: str | None = None


class ProjectCreate(ProjectBase):
    org_id: uuid.UUID


class ProjectUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    description: str | None = None
    settings: dict | None = None


class ProjectResponse(ProjectBase):
    id: uuid.UUID
    org_id: uuid.UUID
    settings: dict
    created_at: datetime
    updated_at: datetime
    paper_count: int = 0
    term_count: int = 0

    class Config:
        from_attributes = True


class PaperBase(BaseModel):
    title: str = Field(max_length=1000)
    abstract: str | None = None
    authors: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None


class PaperCreate(BaseModel):
    project_id: uuid.UUID
    storage_key: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None


class PaperResponse(PaperBase):
    id: uuid.UUID
    project_id: uuid.UUID
    language: str
    status: str
    published_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class PaperDetailResponse(PaperResponse):
    sections: list["SectionResponse"] = []
    assets: list["AssetResponse"] = []
    formulas: list["FormulaResponse"] = []


class SectionResponse(BaseModel):
    id: uuid.UUID
    section_type: str | None
    title: str | None
    page_start: int | None
    page_end: int | None
    content_md: str | None

    class Config:
        from_attributes = True


class AssetResponse(BaseModel):
    id: uuid.UUID
    type: str
    label: str | None
    caption: str | None
    page: int | None

    class Config:
        from_attributes = True


class FormulaResponse(BaseModel):
    id: uuid.UUID
    latex: str | None
    page: int | None

    class Config:
        from_attributes = True


class TermBase(BaseModel):
    phrase: str = Field(min_length=1, max_length=500)
    language: str = "en"


class TermCreate(TermBase):
    project_id: uuid.UUID


class TermResponse(TermBase):
    id: uuid.UUID
    project_id: uuid.UUID
    created_at: datetime
    occurrence_count: int = 0

    class Config:
        from_attributes = True


class KnowledgeTermCreate(BaseModel):
    term_id: uuid.UUID
    canonical_en: str | None = None
    translation: str | None = None
    definition: str | None = None
    sources: dict | None = None


class KnowledgeTermResponse(BaseModel):
    id: uuid.UUID
    term_id: uuid.UUID
    canonical_en: str | None
    translation: str | None
    definition: str | None
    status: str
    confirmed_at: datetime | None

    class Config:
        from_attributes = True


class TermWithKnowledge(TermResponse):
    knowledge: KnowledgeTermResponse | None = None


class ChatThreadCreate(BaseModel):
    scope_type: str = Field(pattern="^(paper|project)$")
    scope_id: uuid.UUID
    title: str | None = None


class ChatThreadResponse(BaseModel):
    id: uuid.UUID
    scope_type: str
    scope_id: uuid.UUID
    title: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatImageAttachment(BaseModel):
    type: Literal["image"] = "image"
    data_url: str = Field(..., description="data:image/...;base64,...")
    name: str | None = None
    size: int | None = None

    @field_validator("data_url")
    @classmethod
    def _validate_data_url(cls, v: str) -> str:
        if not isinstance(v, str) or not v.startswith("data:image/") or ";base64," not in v:
            raise ValueError("Invalid image data_url")
        return v


class ChatMessageCreate(BaseModel):
    content: str
    attachments: list[ChatImageAttachment] = Field(default_factory=list)
    mode: str | None = None
    parent_id: uuid.UUID | None = None


class ChatMessageUpdate(BaseModel):
    content: str


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    role: str
    content_json: dict
    token_count: int | None
    parent_id: uuid.UUID | None = None
    sibling_index: int | None = None
    sibling_count: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class AnalysisJobCreate(BaseModel):
    paper_id: uuid.UUID
    dimensions: list[str] = Field(
        default=["novelty", "methodology", "results", "limitations"]
    )


class AnalysisJobResponse(BaseModel):
    id: uuid.UUID
    paper_id: uuid.UUID
    status: str
    dimensions: list[str]
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None

    class Config:
        from_attributes = True


class AnalysisResultResponse(BaseModel):
    id: uuid.UUID
    dimension: str
    score: float | None
    summary: str | None
    evidences: dict | None

    class Config:
        from_attributes = True


class TranslationCreate(BaseModel):
    paper_id: uuid.UUID
    mode: str = Field(default="quick", pattern="^(quick|deep)$")
    target_language: str = "zh"


class TranslationResponse(BaseModel):
    id: uuid.UUID
    paper_id: uuid.UUID
    target_language: str
    mode: str
    status: str
    content_md: str | None
    created_at: datetime
    completed_at: datetime | None

    class Config:
        from_attributes = True


class UploadUrlResponse(BaseModel):
    upload_url: str
    storage_key: str


class UserProfileResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    expertise_levels: dict
    preferences: dict
    difficult_topics: list
    mastered_topics: list
    updated_at: datetime

    class Config:
        from_attributes = True


class TermSuggestion(BaseModel):
    term: str
    translation: str
    explanation: str
    sources: list[str] = []


class TermAnalyzeRequest(BaseModel):
    phrase: str = Field(min_length=1, max_length=500)
    project_id: uuid.UUID
    paper_id: uuid.UUID | None = None
    context: str | None = None


class TermScanRequest(BaseModel):
    paper_id: uuid.UUID


class TermConfirmation(BaseModel):
    term_id: uuid.UUID
    action: str = Field(pattern="^(confirm|reject|edit)$")
    translation: str | None = None
    definition: str | None = None
