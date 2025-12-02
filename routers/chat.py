"""
對話相關 API 路由
包含對話管理、消息歷史等
"""

import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from core.auth import require_auth
from core.database import (
    create_chat,
    get_user_chats,
    get_chat,
    update_chat_title,
    delete_chat,
    get_chat_messages,
)
from core.database.optimized import (
    get_chat as get_chat_optimized,
    get_user_chats as get_user_chats_optimized,
)

logger = logging.getLogger("routers.chat")

router = APIRouter(prefix="/api/chats", tags=["對話"])


class ChatCreateRequest(BaseModel):
    """創建對話請求"""
    title: Optional[str] = "新對話"


class ChatTitleUpdateRequest(BaseModel):
    """更新對話標題請求"""
    title: str


class ChatSummary(BaseModel):
    """對話摘要"""
    chat_id: str
    title: str
    updated_at: datetime


class ChatListResponse(BaseModel):
    """對話列表響應"""
    success: bool
    chats: List[ChatSummary]


@router.post("")
async def create_new_chat(
    request: ChatCreateRequest,
    user: dict = Depends(require_auth)
):
    """
    創建新對話
    """
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="無效的用戶")

    result = await create_chat(user_id, request.title)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))

    return result


@router.get("")
async def list_user_chats(user: dict = Depends(require_auth)):
    """
    獲取用戶的所有對話
    """
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="無效的用戶")

    result = await get_user_chats_optimized(user_id)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))

    return result


@router.get("/{chat_id}")
async def get_chat_detail(
    chat_id: str,
    user: dict = Depends(require_auth)
):
    """
    獲取對話詳情（包含消息）
    """
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="無效的用戶")

    result = await get_chat_optimized(chat_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail="對話不存在")

    chat = result.get("chat", {})
    
    # 驗證對話所有權
    if chat.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="無權訪問此對話")

    return result


@router.get("/{chat_id}/messages")
async def get_chat_messages_api(
    chat_id: str,
    limit: int = 50,
    user: dict = Depends(require_auth)
):
    """
    獲取對話消息歷史
    """
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="無效的用戶")

    # 先驗證對話所有權
    chat_result = await get_chat_optimized(chat_id)
    if not chat_result.get("success"):
        raise HTTPException(status_code=404, detail="對話不存在")

    chat = chat_result.get("chat", {})
    if chat.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="無權訪問此對話")

    # 獲取消息
    messages = await get_chat_messages(chat_id, limit=limit)
    
    return {
        "success": True,
        "chat_id": chat_id,
        "messages": messages,
    }


@router.put("/{chat_id}/title")
async def update_chat_title_api(
    chat_id: str,
    request: ChatTitleUpdateRequest,
    user: dict = Depends(require_auth)
):
    """
    更新對話標題
    """
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="無效的用戶")

    # 先驗證對話所有權
    chat_result = await get_chat_optimized(chat_id)
    if not chat_result.get("success"):
        raise HTTPException(status_code=404, detail="對話不存在")

    chat = chat_result.get("chat", {})
    if chat.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="無權修改此對話")

    result = await update_chat_title(chat_id, request.title)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))

    return result


@router.delete("/{chat_id}")
async def delete_chat_api(
    chat_id: str,
    user: dict = Depends(require_auth)
):
    """
    刪除對話
    """
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="無效的用戶")

    # 先驗證對話所有權
    chat_result = await get_chat_optimized(chat_id)
    if not chat_result.get("success"):
        raise HTTPException(status_code=404, detail="對話不存在")

    chat = chat_result.get("chat", {})
    if chat.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="無權刪除此對話")

    result = await delete_chat(chat_id)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))

    return result
