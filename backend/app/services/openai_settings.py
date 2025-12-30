import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings


async def get_openai_settings(
    db: AsyncSession | None,
    user_id: uuid.UUID | None,
) -> dict[str, str]:
    """Resolve OpenAI settings with user preferences overriding system defaults."""
    settings = get_settings()

    if not user_id or db is None:
        base_url = (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
        if not base_url.endswith("/v1") and "/v1/" not in base_url:
            base_url = f"{base_url}/v1"
        return {
            "base_url": base_url,
            "api_key": settings.openai_api_key or "",
            "model": settings.openai_model,
        }

    from app.api.v1.settings import get_effective_settings

    effective = await get_effective_settings(db, user_id)

    base_url = effective["openai_base_url"].rstrip("/")
    if not base_url.endswith("/v1") and "/v1/" not in base_url:
        base_url = f"{base_url}/v1"

    return {
        "base_url": base_url,
        "api_key": effective["openai_api_key"],
        "model": effective["openai_model"],
    }
