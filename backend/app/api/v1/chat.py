import uuid
import base64
import binascii
from typing import Annotated, AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.core import get_db
import logging
from app.models import ChatThread, ChatMessage, Project, Paper, ProjectMember, User
from app.schemas import ChatThreadCreate, ChatThreadResponse, ChatMessageCreate, ChatMessageUpdate, ChatMessageResponse

logger = logging.getLogger(__name__)
from app.api.v1.auth import get_current_user
from app.services.chat_service import ChatService

router = APIRouter()


async def _assert_scope_access(
    db: AsyncSession,
    scope_type: str,
    scope_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    if scope_type == "project":
        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == scope_id,
                ProjectMember.user_id == user_id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to project")
    elif scope_type == "paper":
        result = await db.execute(
            select(Paper)
            .join(ProjectMember, ProjectMember.project_id == Paper.project_id)
            .where(Paper.id == scope_id, ProjectMember.user_id == user_id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to paper")
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid scope_type")


@router.post("", response_model=ChatThreadResponse, status_code=status.HTTP_201_CREATED)
async def create_thread(
    thread_data: ChatThreadCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    ensure: bool = Query(default=False, description="If true, return existing thread instead of creating duplicate")
):
    await _assert_scope_access(db, thread_data.scope_type, thread_data.scope_id, current_user.id)

    # If ensure=true, use atomic idempotent creation
    if ensure:
        # First check for any existing thread (may have non-deterministic ID from before)
        existing = await db.execute(
            select(ChatThread)
            .where(
                ChatThread.scope_type == thread_data.scope_type,
                ChatThread.scope_id == thread_data.scope_id,
            )
            .order_by(ChatThread.created_at.desc())
            .limit(1)
        )
        existing_thread = existing.scalar_one_or_none()
        if existing_thread:
            return existing_thread

        # Use deterministic ID + ON CONFLICT to prevent race condition
        ensure_thread_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"papermate:chat_thread:{thread_data.scope_type}:{thread_data.scope_id}",
        )
        stmt = (
            insert(ChatThread)
            .values(
                id=ensure_thread_id,
                scope_type=thread_data.scope_type,
                scope_id=thread_data.scope_id,
                title=thread_data.title,
                created_by=current_user.id,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await db.execute(stmt)
        await db.commit()
        result = await db.execute(select(ChatThread).where(ChatThread.id == ensure_thread_id))
        return result.scalar_one()

    thread = ChatThread(
        scope_type=thread_data.scope_type,
        scope_id=thread_data.scope_id,
        title=thread_data.title,
        created_by=current_user.id,
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return thread


@router.get("", response_model=list[ChatThreadResponse])
async def list_threads(
    scope_type: str = Query(pattern="^(paper|project)$"),
    scope_id: uuid.UUID = Query(),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    limit: int = Query(default=20, le=50),
    offset: int = Query(default=0, ge=0)
):
    await _assert_scope_access(db, scope_type, scope_id, current_user.id)
    result = await db.execute(
        select(ChatThread)
        .where(ChatThread.scope_type == scope_type, ChatThread.scope_id == scope_id)
        .order_by(ChatThread.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{thread_id}", response_model=ChatThreadResponse)
async def get_thread(
    thread_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(select(ChatThread).where(ChatThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    await _assert_scope_access(db, thread.scope_type, thread.scope_id, current_user.id)
    return thread


@router.get("/{thread_id}/messages", response_model=list[ChatMessageResponse])
async def list_messages(
    thread_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0)
):
    result = await db.execute(select(ChatThread).where(ChatThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    await _assert_scope_access(db, thread.scope_type, thread.scope_id, current_user.id)

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.thread_id == thread_id)
        .order_by(ChatMessage.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()


@router.post("/{thread_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_message(
    thread_id: uuid.UUID,
    message_data: ChatMessageCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(select(ChatThread).where(ChatThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    await _assert_scope_access(db, thread.scope_type, thread.scope_id, current_user.id)

    if message_data.parent_id:
        parent_result = await db.execute(
            select(ChatMessage.id).where(
                ChatMessage.id == message_data.parent_id,
                ChatMessage.thread_id == thread_id,
            )
        )
        if not parent_result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid parent message")

    content_json: dict = {"text": message_data.content}
    if message_data.attachments:
        allowed_mimes = {"image/png", "image/jpeg", "image/webp", "image/gif"}
        max_bytes = 4 * 1024 * 1024
        validated: list[dict] = []
        for att in message_data.attachments:
            data_url = att.data_url
            try:
                header, b64 = data_url.split(",", 1)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image attachment")
            if not header.startswith("data:image/") or ";base64" not in header:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image attachment")
            mime = header[len("data:"):].split(";", 1)[0]
            if mime not in allowed_mimes:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported image type: {mime}")
            try:
                raw = base64.b64decode(b64, validate=True)
            except (binascii.Error, ValueError):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image attachment")
            if len(raw) > max_bytes:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image exceeds 4MB limit")
            validated.append(att.model_dump(exclude_none=True))
        content_json["attachments"] = validated

    user_message = ChatMessage(
        thread_id=thread_id,
        user_id=current_user.id,
        parent_id=message_data.parent_id,
        role="user",
        content_json=content_json
    )
    db.add(user_message)
    await db.commit()

    return {"status": "accepted", "message_id": str(user_message.id)}


@router.get("/{thread_id}/stream")
async def stream_response(
    thread_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(select(ChatThread).where(ChatThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    await _assert_scope_access(db, thread.scope_type, thread.scope_id, current_user.id)

    chat_service = ChatService(db, user_id=current_user.id)

    async def event_generator() -> AsyncGenerator[str, None]:
        async for chunk in chat_service.stream_response(thread_id, current_user.id):
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


@router.patch("/{thread_id}/messages/{message_id}", response_model=ChatMessageResponse)
async def edit_message(
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    message_data: ChatMessageUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(ChatThread).where(ChatThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    await _assert_scope_access(db, thread.scope_type, thread.scope_id, current_user.id)

    result = await db.execute(
        select(ChatMessage).where(ChatMessage.id == message_id, ChatMessage.thread_id == thread_id)
    )
    message = result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    is_thread_owner = thread.created_by == current_user.id
    is_author = message.user_id == current_user.id
    if not (is_thread_owner or is_author):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    content_json = dict(message.content_json or {})
    content_json["text"] = message_data.content
    message.content_json = content_json

    await db.commit()
    await db.refresh(message)
    return message


@router.delete("/{thread_id}/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(ChatThread).where(ChatThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    await _assert_scope_access(db, thread.scope_type, thread.scope_id, current_user.id)

    result = await db.execute(
        select(ChatMessage).where(ChatMessage.id == message_id, ChatMessage.thread_id == thread_id)
    )
    message = result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    is_thread_owner = thread.created_by == current_user.id
    is_author = message.user_id == current_user.id
    if not (is_thread_owner or is_author):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    await db.delete(message)
    await db.commit()


@router.get("/{thread_id}/messages/{message_id}/siblings")
async def get_message_siblings(
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get sibling messages (same parent) for branch navigation."""
    result = await db.execute(select(ChatThread).where(ChatThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    await _assert_scope_access(db, thread.scope_type, thread.scope_id, current_user.id)

    result = await db.execute(
        select(ChatMessage).where(ChatMessage.id == message_id, ChatMessage.thread_id == thread_id)
    )
    message = result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    siblings_result = await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.thread_id == thread_id,
            ChatMessage.parent_id == message.parent_id,
        )
        .order_by(ChatMessage.created_at.asc())
    )
    siblings = siblings_result.scalars().all()

    sibling_ids = [str(s.id) for s in siblings]
    current_index = sibling_ids.index(str(message_id)) if str(message_id) in sibling_ids else 0

    return {
        "siblings": sibling_ids,
        "current_index": current_index,
        "total": len(siblings),
    }


@router.get("/{thread_id}/branch")
async def get_branch_messages(
    thread_id: uuid.UUID,
    leaf_id: uuid.UUID = Query(None, description="Leaf message ID to trace back from"),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Get messages along a specific branch path from root to leaf."""
    result = await db.execute(select(ChatThread).where(ChatThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    await _assert_scope_access(db, thread.scope_type, thread.scope_id, current_user.id)

    all_msgs_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.thread_id == thread_id)
        .order_by(ChatMessage.created_at.asc())
    )
    all_msgs_list = all_msgs_result.scalars().all()
    if not all_msgs_list:
        return []

    msg_by_id: dict[str, ChatMessage] = {str(m.id): m for m in all_msgs_list}

    # Build children adjacency for fast subtree/leaf selection + sibling metadata.
    children_by_parent: dict[str | None, list[ChatMessage]] = {}
    has_child: set[str] = set()
    for m in all_msgs_list:
        parent_key = str(m.parent_id) if m.parent_id else None
        children_by_parent.setdefault(parent_key, []).append(m)
        if m.parent_id:
            has_child.add(str(m.parent_id))

    # Stable ordering for sibling navigation.
    for siblings in children_by_parent.values():
        siblings.sort(key=lambda x: (x.created_at, str(x.id)))

    def _pick_leaf_in_subtree(root_id: str) -> ChatMessage | None:
        """Pick the most recently created leaf under root_id (inclusive)."""
        if root_id not in msg_by_id:
            return None

        stack = [root_id]
        visited: set[str] = set()
        subtree_nodes: list[ChatMessage] = []

        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            node = msg_by_id.get(cur)
            if not node:
                continue
            subtree_nodes.append(node)
            for child in children_by_parent.get(cur, []):
                stack.append(str(child.id))

        if not subtree_nodes:
            return None

        leaves = [m for m in subtree_nodes if str(m.id) not in has_child]
        if not leaves:
            return subtree_nodes[-1]

        return max(leaves, key=lambda x: (x.created_at, str(x.id)))

    # Resolve which leaf to display:
    # - If leaf_id points to a non-leaf node, extend to the deepest/most-recent leaf under it.
    # - If leaf_id is omitted/invalid, default to the most recent leaf in the whole thread.
    selected_leaf: ChatMessage | None = None
    if leaf_id and str(leaf_id) in msg_by_id:
        selected_leaf = _pick_leaf_in_subtree(str(leaf_id))

    if not selected_leaf:
        all_leaves = [m for m in all_msgs_list if str(m.id) not in has_child]
        selected_leaf = max(all_leaves, key=lambda x: (x.created_at, str(x.id))) if all_leaves else all_msgs_list[-1]

    # Trace back to root via parent pointers.
    path: list[ChatMessage] = []
    current: ChatMessage | None = selected_leaf
    visited: set[str] = set()
    while current:
        cur_id = str(current.id)
        if cur_id in visited:
            break
        visited.add(cur_id)
        path.append(current)
        if current.parent_id:
            current = msg_by_id.get(str(current.parent_id))
        else:
            current = None
    path.reverse()

    response = []
    for msg in path:
        parent_key = str(msg.parent_id) if msg.parent_id else None
        siblings = children_by_parent.get(parent_key, [])
        sibling_index = 0
        for i, s in enumerate(siblings):
            if s.id == msg.id:
                sibling_index = i
                break

        response.append({
            "id": str(msg.id),
            "thread_id": str(msg.thread_id),
            "role": msg.role,
            "content_json": msg.content_json,
            "token_count": msg.token_count,
            "parent_id": str(msg.parent_id) if msg.parent_id else None,
            "sibling_index": sibling_index,
            "sibling_count": len(siblings) or 1,
            "created_at": msg.created_at.isoformat(),
        })

    return response


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(select(ChatThread).where(ChatThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    await _assert_scope_access(db, thread.scope_type, thread.scope_id, current_user.id)

    if thread.created_by != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    await db.delete(thread)
    await db.commit()
