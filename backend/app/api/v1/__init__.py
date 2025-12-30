from fastapi import APIRouter
from app.api.v1 import auth, projects, papers, terms, chat, analysis, translation, settings

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(projects.router, prefix="/projects", tags=["projects"])
router.include_router(papers.router, prefix="/papers", tags=["papers"])
router.include_router(terms.router, prefix="/terms", tags=["terms"])
router.include_router(chat.router, prefix="/threads", tags=["chat"])
router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
router.include_router(translation.router, prefix="/translations", tags=["translations"])
router.include_router(settings.router, prefix="/settings", tags=["settings"])
