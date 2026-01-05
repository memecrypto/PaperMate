import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core import get_db, verify_password, get_password_hash, create_access_token, create_refresh_token, decode_token, get_settings
from app.core.rate_limit import get_client_ip, login_ip_limiter, login_user_limiter
from app.models import User, Organization, OrgMembership, UserProfile
from app.schemas import UserCreate, UserResponse

router = APIRouter()
settings = get_settings()


# Use fixed paths for cookies to ensure consistency between set and delete
_ACCESS_TOKEN_PATH = "/"
_REFRESH_TOKEN_PATH = "/api/v1/auth"


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set httpOnly cookies for authentication tokens."""
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path=_ACCESS_TOKEN_PATH
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=_REFRESH_TOKEN_PATH
    )


def clear_auth_cookies(response: Response) -> None:
    """Clear authentication cookies."""
    response.delete_cookie(key="access_token", path=_ACCESS_TOKEN_PATH)
    response.delete_cookie(key="refresh_token", path=_REFRESH_TOKEN_PATH)


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


@router.get("/registration-status")
async def get_registration_status(db: Annotated[AsyncSession, Depends(get_db)]):
    """Check if registration is available (only first user can register)."""
    result = await db.execute(select(User).limit(1))
    has_users = result.scalar_one_or_none() is not None
    return {"registration_open": not has_users}


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    response: Response,
    user_data: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    # Check if any user exists - only first user can register
    existing_users = await db.execute(select(User).limit(1))
    if existing_users.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is closed. Please contact administrator."
        )

    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(
        email=user_data.email,
        name=user_data.name,
        hashed_password=get_password_hash(user_data.password),
        is_superuser=True  # First user is admin
    )
    db.add(user)
    await db.flush()

    org = Organization(name=f"{user.name or user.email}'s Workspace")
    db.add(org)
    await db.flush()

    membership = OrgMembership(org_id=org.id, user_id=user.id, role="owner")
    db.add(membership)

    profile = UserProfile(user_id=user.id)
    db.add(profile)

    await db.commit()
    await db.refresh(user)

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    set_auth_cookies(response, access_token, refresh_token)

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "expertise_level": user.expertise_level,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "created_at": user.created_at,
        "org_id": org.id
    }


@router.post("/login", response_model=UserResponse)
async def login(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    client_ip = get_client_ip(request)
    identifier = (form_data.username or "").strip().lower()
    user_key = f"user:{identifier}" if identifier else ""

    if login_ip_limiter.is_blocked(client_ip) or (
        user_key and login_user_limiter.is_blocked(user_key)
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later",
        )

    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        login_ip_limiter.record_failure(client_ip)
        if user_key:
            login_user_limiter.record_failure(user_key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive")

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    set_auth_cookies(response, access_token, refresh_token)
    login_user_limiter.reset(user_key)

    # Get user's organization
    result = await db.execute(
        select(OrgMembership).where(OrgMembership.user_id == user.id).limit(1)
    )
    membership = result.scalar_one_or_none()

    # Auto-create organization if missing
    if not membership:
        org = Organization(name=f"{user.name or user.email}'s Workspace")
        db.add(org)
        await db.flush()

        membership = OrgMembership(org_id=org.id, user_id=user.id, role="owner")
        db.add(membership)
        await db.commit()

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "expertise_level": user.expertise_level,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "created_at": user.created_at,
        "org_id": membership.org_id
    }


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing")

    payload = decode_token(token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    new_access_token = create_access_token({"sub": str(user.id)})
    new_refresh_token = create_refresh_token({"sub": str(user.id)})
    set_auth_cookies(response, new_access_token, new_refresh_token)

    return {"message": "Token refreshed"}


@router.post("/logout")
async def logout(response: Response):
    clear_auth_cookies(response)
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    # Get user's organization
    result = await db.execute(
        select(OrgMembership).where(OrgMembership.user_id == current_user.id).limit(1)
    )
    membership = result.scalar_one_or_none()

    # Auto-create organization if missing
    if not membership:
        org = Organization(name=f"{current_user.name or current_user.email}'s Workspace")
        db.add(org)
        await db.flush()

        membership = OrgMembership(org_id=org.id, user_id=current_user.id, role="owner")
        db.add(membership)
        await db.commit()

    # Add org_id to user response
    user_dict = {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "expertise_level": current_user.expertise_level,
        "is_active": current_user.is_active,
        "is_superuser": current_user.is_superuser,
        "created_at": current_user.created_at,
        "org_id": membership.org_id
    }
    return user_dict


@router.get("/me/profile")
async def get_my_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Get current user's profile including expertise levels and preferences."""
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()

    if not profile:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)

    return {
        "id": str(profile.id),
        "user_id": str(profile.user_id),
        "expertise_levels": profile.expertise_levels or {},
        "preferences": profile.preferences or {},
        "difficult_topics": profile.difficult_topics or [],
        "mastered_topics": profile.mastered_topics or [],
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None
    }


@router.patch("/me/profile")
async def update_my_profile(
    updates: dict,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Update current user's profile. Supports partial updates."""
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()

    if not profile:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)

    if "expertise_levels" in updates:
        current = profile.expertise_levels or {}
        current.update(updates["expertise_levels"])
        profile.expertise_levels = current

    if "preferences" in updates:
        current = profile.preferences or {}
        current.update(updates["preferences"])
        profile.preferences = current

    # Process direct replacement fields first
    if "difficult_topics" in updates:
        profile.difficult_topics = updates["difficult_topics"]

    if "mastered_topics" in updates:
        profile.mastered_topics = updates["mastered_topics"]

    # Then process incremental merge fields (won't be overwritten)
    if "added_difficult_topics" in updates:
        incoming = updates["added_difficult_topics"]
        if isinstance(incoming, str):
            incoming_list = [incoming]
        elif isinstance(incoming, list):
            incoming_list = [t for t in incoming if isinstance(t, str)]
        else:
            incoming_list = []
        current = set(profile.difficult_topics or [])
        current |= set(incoming_list)
        profile.difficult_topics = list(current)

    if "added_mastered_topics" in updates:
        incoming = updates["added_mastered_topics"]
        if isinstance(incoming, str):
            incoming_list = [incoming]
        elif isinstance(incoming, list):
            incoming_list = [t for t in incoming if isinstance(t, str)]
        else:
            incoming_list = []
        current = set(profile.mastered_topics or [])
        current |= set(incoming_list)
        profile.mastered_topics = list(current)

    await db.commit()
    await db.refresh(profile)

    return {
        "id": str(profile.id),
        "user_id": str(profile.user_id),
        "expertise_levels": profile.expertise_levels or {},
        "preferences": profile.preferences or {},
        "difficult_topics": profile.difficult_topics or [],
        "mastered_topics": profile.mastered_topics or [],
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None
    }


@router.delete("/me/profile/reset")
async def reset_my_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Reset user profile to defaults."""
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()

    if profile:
        profile.expertise_levels = {}
        profile.preferences = {}
        profile.difficult_topics = []
        profile.mastered_topics = []
        await db.commit()

    return {"status": "ok", "message": "Profile reset successfully"}
