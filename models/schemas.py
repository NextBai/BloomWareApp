"""
Pydantic 模型定義
統一管理 API 請求/回應的資料結構
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field


# ===== 用戶相關 =====

class UserCreate(BaseModel):
    """用戶註冊請求"""
    name: str
    email: EmailStr
    password: str = Field(min_length=6)


class UserLogin(BaseModel):
    """用戶登入請求"""
    email: EmailStr
    password: str


class UserInfo(BaseModel):
    """用戶資訊"""
    id: str
    name: str
    email: EmailStr
    created_at: datetime


class UserPublic(BaseModel):
    """用戶公開資訊回應"""
    success: bool
    user: UserInfo


class UserLoginPublicResponse(BaseModel):
    """用戶登入回應"""
    success: bool
    user: UserInfo
    token: Optional[str] = None


# ===== 對話相關 =====

class ChatCreateRequest(BaseModel):
    """建立對話請求"""
    user_id: str
    title: Optional[str] = "新對話"


class ChatTitleUpdateRequest(BaseModel):
    """更新對話標題請求"""
    title: str


class ChatPublic(BaseModel):
    """對話公開資訊"""
    chat_id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ChatSummary(BaseModel):
    """對話摘要"""
    chat_id: str
    title: str
    updated_at: datetime


class ChatListResponse(BaseModel):
    """對話列表回應"""
    chats: List[ChatSummary]


# ===== 訊息相關 =====

class MessageCreateRequest(BaseModel):
    """建立訊息請求"""
    sender: str
    content: str


class MessagePublic(BaseModel):
    """訊息公開資訊"""
    sender: str
    content: str
    timestamp: datetime


class ChatDetailResponse(ChatPublic):
    """對話詳情回應（含訊息）"""
    messages: List[MessagePublic]


# ===== 檔案分析 =====

class FileAnalysisRequest(BaseModel):
    """檔案分析請求"""
    filename: str
    content: str
    mime_type: str
    user_prompt: Optional[str] = "請分析這個檔案的內容"


class FileAnalysisResponse(BaseModel):
    """檔案分析回應"""
    success: bool
    filename: str
    analysis: Optional[str] = None
    error: Optional[str] = None


# ===== 語音相關 =====

class SpeakerLabelBindRequest(BaseModel):
    """語音標籤綁定請求"""
    speaker_label: str
