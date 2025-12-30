import uuid
import httpx
import ipaddress
from urllib.parse import urlparse
from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes
from pydantic import BaseModel
from app.core import get_db, get_settings
from app.core.encryption import encrypt_value, decrypt_value, mask_api_key
from app.models import User, UserProfile
from app.api.v1.auth import get_current_user

router = APIRouter()
settings = get_settings()


class UserSettingsUpdate(BaseModel):
    mineru_api_key: str | None = None
    mineru_api_url: str | None = None
    mineru_use_cloud: bool | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    tavily_api_key: str | None = None


class UserSettingsResponse(BaseModel):
    mineru_api_key_masked: str | None = None
    mineru_api_url: str | None = None
    mineru_use_cloud: bool | None = None
    openai_api_key_masked: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    tavily_api_key_masked: str | None = None
    has_mineru_key: bool = False
    has_openai_key: bool = False
    has_tavily_key: bool = False


class TestConnectionResponse(BaseModel):
    success: bool
    message: str


async def _get_or_create_profile(db: AsyncSession, user_id: uuid.UUID) -> UserProfile:
    """Get or create user profile."""
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        profile = UserProfile(user_id=user_id)
        db.add(profile)
        await db.flush()
    return profile


def _get_decrypted_key(preferences: dict, key_name: str) -> str:
    """Get decrypted API key from preferences."""
    encrypted = preferences.get(f"{key_name}_encrypted", "")
    if encrypted:
        try:
            return decrypt_value(encrypted)
        except Exception:
            return ""
    return ""


def _is_disallowed_host(host: str) -> bool:
    lowered = (host or "").lower()
    if lowered in {"localhost"} or lowered.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Invalid OpenAI base URL scheme")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="Invalid OpenAI base URL host")
    if not settings.debug and parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="OpenAI base URL must use HTTPS")
    if _is_disallowed_host(parsed.hostname):
        raise HTTPException(status_code=400, detail="OpenAI base URL host is not allowed")


def _validate_local_url(url: str) -> None:
    """Validate URL allowing localhost/private IPs for local deployments."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Invalid URL scheme")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="Invalid URL host")


async def get_effective_settings(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Get effective API settings for a user (user preferences override system defaults)."""
    profile = await _get_or_create_profile(db, user_id)
    preferences = profile.preferences or {}

    # Get decrypted keys
    mineru_key = _get_decrypted_key(preferences, "mineru_api_key") or settings.mineru_api_key or ""
    openai_key = _get_decrypted_key(preferences, "openai_api_key") or settings.openai_api_key or ""
    tavily_key = _get_decrypted_key(preferences, "tavily_api_key") or settings.tavily_api_key or ""

    return {
        "mineru_api_key": mineru_key,
        "mineru_api_url": preferences.get("mineru_api_url") or settings.mineru_api_url,
        "mineru_use_cloud": preferences.get("mineru_use_cloud") if "mineru_use_cloud" in preferences else settings.mineru_use_cloud,
        "openai_api_key": openai_key,
        "openai_base_url": preferences.get("openai_base_url") or settings.openai_base_url or "https://api.openai.com/v1",
        "openai_model": preferences.get("openai_model") or settings.openai_model,
        "tavily_api_key": tavily_key,
    }


@router.get("", response_model=UserSettingsResponse)
async def get_settings(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Get current user's API settings (masked), with system defaults as fallback."""
    profile = await _get_or_create_profile(db, current_user.id)
    preferences = profile.preferences or {}

    # User-specific keys (decrypted)
    mineru_key = _get_decrypted_key(preferences, "mineru_api_key")
    openai_key = _get_decrypted_key(preferences, "openai_api_key")
    tavily_key = _get_decrypted_key(preferences, "tavily_api_key")

    # Fall back to system defaults if user hasn't set
    effective_mineru_key = mineru_key or settings.mineru_api_key or ""
    effective_openai_key = openai_key or settings.openai_api_key or ""
    effective_tavily_key = tavily_key or settings.tavily_api_key or ""

    return UserSettingsResponse(
        mineru_api_key_masked=mask_api_key(effective_mineru_key) if effective_mineru_key else None,
        mineru_api_url=preferences.get("mineru_api_url") or settings.mineru_api_url,
        mineru_use_cloud=preferences.get("mineru_use_cloud") if "mineru_use_cloud" in preferences else settings.mineru_use_cloud,
        openai_api_key_masked=mask_api_key(effective_openai_key) if effective_openai_key else None,
        openai_base_url=preferences.get("openai_base_url") or settings.openai_base_url or "https://api.openai.com/v1",
        openai_model=preferences.get("openai_model") or settings.openai_model,
        tavily_api_key_masked=mask_api_key(effective_tavily_key) if effective_tavily_key else None,
        has_mineru_key=bool(effective_mineru_key),
        has_openai_key=bool(effective_openai_key),
        has_tavily_key=bool(effective_tavily_key),
    )


@router.put("", response_model=UserSettingsResponse)
async def update_settings(
    settings_update: UserSettingsUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Update user's API settings."""
    profile = await _get_or_create_profile(db, current_user.id)
    preferences = profile.preferences or {}

    if settings_update.mineru_api_key is not None:
        if settings_update.mineru_api_key:
            preferences["mineru_api_key_encrypted"] = encrypt_value(settings_update.mineru_api_key)
        else:
            preferences.pop("mineru_api_key_encrypted", None)

    if settings_update.openai_api_key is not None:
        if settings_update.openai_api_key:
            preferences["openai_api_key_encrypted"] = encrypt_value(settings_update.openai_api_key)
        else:
            preferences.pop("openai_api_key_encrypted", None)

    if settings_update.openai_base_url is not None:
        if settings_update.openai_base_url:
            _validate_public_url(settings_update.openai_base_url)
            preferences["openai_base_url"] = settings_update.openai_base_url
        else:
            preferences.pop("openai_base_url", None)

    if settings_update.tavily_api_key is not None:
        if settings_update.tavily_api_key:
            preferences["tavily_api_key_encrypted"] = encrypt_value(settings_update.tavily_api_key)
        else:
            preferences.pop("tavily_api_key_encrypted", None)

    if settings_update.mineru_api_url is not None:
        if settings_update.mineru_api_url:
            _validate_local_url(settings_update.mineru_api_url)
            preferences["mineru_api_url"] = settings_update.mineru_api_url
        else:
            preferences.pop("mineru_api_url", None)

    if settings_update.mineru_use_cloud is not None:
        preferences["mineru_use_cloud"] = settings_update.mineru_use_cloud

    if settings_update.openai_model is not None:
        if settings_update.openai_model:
            preferences["openai_model"] = settings_update.openai_model
        else:
            preferences.pop("openai_model", None)

    profile.preferences = preferences
    attributes.flag_modified(profile, "preferences")
    await db.commit()
    await db.refresh(profile)

    # User-specific keys (decrypted)
    mineru_key = _get_decrypted_key(preferences, "mineru_api_key")
    openai_key = _get_decrypted_key(preferences, "openai_api_key")
    tavily_key = _get_decrypted_key(preferences, "tavily_api_key")

    # Fall back to system defaults if user hasn't set
    effective_mineru_key = mineru_key or settings.mineru_api_key or ""
    effective_openai_key = openai_key or settings.openai_api_key or ""
    effective_tavily_key = tavily_key or settings.tavily_api_key or ""

    return UserSettingsResponse(
        mineru_api_key_masked=mask_api_key(effective_mineru_key) if effective_mineru_key else None,
        mineru_api_url=preferences.get("mineru_api_url") or settings.mineru_api_url,
        mineru_use_cloud=preferences.get("mineru_use_cloud") if "mineru_use_cloud" in preferences else settings.mineru_use_cloud,
        openai_api_key_masked=mask_api_key(effective_openai_key) if effective_openai_key else None,
        openai_base_url=preferences.get("openai_base_url") or settings.openai_base_url or "https://api.openai.com/v1",
        openai_model=preferences.get("openai_model") or settings.openai_model,
        tavily_api_key_masked=mask_api_key(effective_tavily_key) if effective_tavily_key else None,
        has_mineru_key=bool(effective_mineru_key),
        has_openai_key=bool(effective_openai_key),
        has_tavily_key=bool(effective_tavily_key),
    )


@router.post("/test/{provider}", response_model=TestConnectionResponse)
async def test_connection(
    provider: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Test API connection for a specific provider."""
    profile = await _get_or_create_profile(db, current_user.id)
    preferences = profile.preferences or {}

    if provider == "mineru":
        api_key = _get_decrypted_key(preferences, "mineru_api_key") or settings.mineru_api_key
        if not api_key:
            raise HTTPException(status_code=400, detail="MinerU API Key not configured")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://mineru.net/api/v4/file-urls/batch",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}"
                    },
                    json={"files": [{"name": "test.pdf"}], "model_version": "pipeline"}
                )
                data = resp.json()
                if resp.status_code == 200 and data.get("code") == 0:
                    return TestConnectionResponse(success=True, message="MinerU 连接成功")
                elif data.get("msgCode") == "A0202":
                    return TestConnectionResponse(success=False, message="API Key 无效或已过期")
                else:
                    return TestConnectionResponse(success=False, message=f"连接失败: {data.get('msg', 'Unknown error')}")
        except Exception as e:
            return TestConnectionResponse(success=False, message=f"连接错误: {str(e)}")

    elif provider == "openai":
        api_key = _get_decrypted_key(preferences, "openai_api_key") or settings.openai_api_key
        base_url = preferences.get("openai_base_url") or settings.openai_base_url or "https://api.openai.com/v1"
        if not api_key:
            raise HTTPException(status_code=400, detail="OpenAI API Key not configured")
        _validate_public_url(base_url)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                if resp.status_code == 200:
                    return TestConnectionResponse(success=True, message="OpenAI 连接成功")
                elif resp.status_code == 401:
                    return TestConnectionResponse(success=False, message="API Key 无效")
                else:
                    return TestConnectionResponse(success=False, message=f"连接失败: HTTP {resp.status_code}")
        except Exception as e:
            return TestConnectionResponse(success=False, message=f"连接错误: {str(e)}")

    elif provider == "tavily":
        api_key = _get_decrypted_key(preferences, "tavily_api_key") or settings.tavily_api_key
        if not api_key:
            raise HTTPException(status_code=400, detail="Tavily API Key not configured")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": api_key, "query": "test", "max_results": 1}
                )
                if resp.status_code == 200:
                    return TestConnectionResponse(success=True, message="Tavily 连接成功")
                elif resp.status_code == 401:
                    return TestConnectionResponse(success=False, message="API Key 无效")
                else:
                    return TestConnectionResponse(success=False, message=f"连接失败: HTTP {resp.status_code}")
        except Exception as e:
            return TestConnectionResponse(success=False, message=f"连接错误: {str(e)}")

    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
