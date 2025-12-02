"""
文件處理相關 API 路由
包含文件上傳、分析等
"""

import logging
import base64
import mimetypes
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel

from core.auth import require_auth

logger = logging.getLogger("routers.files")

router = APIRouter(prefix="/api/files", tags=["文件"])


class FileAnalysisRequest(BaseModel):
    """文件分析請求"""
    filename: str
    content: str  # base64 編碼
    mime_type: str
    user_prompt: Optional[str] = "請分析這個檔案的內容"


class FileAnalysisResponse(BaseModel):
    """文件分析響應"""
    success: bool
    filename: str
    analysis: Optional[str] = None
    error: Optional[str] = None


@router.post("/analyze", response_model=FileAnalysisResponse)
async def analyze_file(
    request: FileAnalysisRequest,
    user: dict = Depends(require_auth)
):
    """
    分析上傳的文件內容
    支援 PDF、圖片、文字文件等
    """
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="無效的用戶")

    try:
        # 解碼文件內容
        try:
            file_content = base64.b64decode(request.content)
        except Exception:
            return FileAnalysisResponse(
                success=False,
                filename=request.filename,
                error="無法解碼文件內容",
            )

        # 根據 MIME 類型處理
        mime_type = request.mime_type.lower()
        extracted_text = ""

        if mime_type.startswith("text/"):
            # 文字文件
            try:
                extracted_text = file_content.decode("utf-8")
            except UnicodeDecodeError:
                extracted_text = file_content.decode("latin-1")

        elif mime_type == "application/pdf":
            # PDF 文件
            try:
                import pdfplumber
                import io
                
                with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                    pages_text = []
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            pages_text.append(text)
                    extracted_text = "\n\n".join(pages_text)
            except ImportError:
                return FileAnalysisResponse(
                    success=False,
                    filename=request.filename,
                    error="PDF 處理模組不可用",
                )
            except Exception as e:
                return FileAnalysisResponse(
                    success=False,
                    filename=request.filename,
                    error=f"PDF 解析失敗: {str(e)}",
                )

        elif mime_type.startswith("image/"):
            # 圖片文件 - 使用 GPT-4 Vision
            try:
                import services.ai_service as ai_service
                
                # 構建 Vision API 請求
                image_base64 = request.content
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": request.user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ]

                analysis = await ai_service.generate_response_async(
                    messages,
                    model="gpt-4o-mini",  # 使用支援 Vision 的模型
                )

                return FileAnalysisResponse(
                    success=True,
                    filename=request.filename,
                    analysis=analysis,
                )

            except Exception as e:
                return FileAnalysisResponse(
                    success=False,
                    filename=request.filename,
                    error=f"圖片分析失敗: {str(e)}",
                )

        else:
            return FileAnalysisResponse(
                success=False,
                filename=request.filename,
                error=f"不支援的文件類型: {mime_type}",
            )

        # 使用 AI 分析提取的文字
        if extracted_text:
            try:
                import services.ai_service as ai_service
                
                messages = [
                    {
                        "role": "system",
                        "content": "你是一個專業的文件分析助手。請根據用戶的要求分析以下文件內容。"
                    },
                    {
                        "role": "user",
                        "content": f"{request.user_prompt}\n\n文件內容：\n{extracted_text[:10000]}"  # 限制長度
                    }
                ]

                analysis = await ai_service.generate_response_async(messages)

                return FileAnalysisResponse(
                    success=True,
                    filename=request.filename,
                    analysis=analysis,
                )

            except Exception as e:
                return FileAnalysisResponse(
                    success=False,
                    filename=request.filename,
                    error=f"AI 分析失敗: {str(e)}",
                )

        return FileAnalysisResponse(
            success=False,
            filename=request.filename,
            error="無法提取文件內容",
        )

    except Exception as e:
        logger.exception(f"文件分析失敗: {e}")
        return FileAnalysisResponse(
            success=False,
            filename=request.filename,
            error=str(e),
        )


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    user: dict = Depends(require_auth)
):
    """
    上傳文件（返回 base64 編碼）
    """
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="無效的用戶")

    try:
        # 讀取文件內容
        content = await file.read()
        
        # 檢查文件大小（限制 10MB）
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="文件大小超過限制（10MB）")

        # 編碼為 base64
        content_base64 = base64.b64encode(content).decode("utf-8")

        # 獲取 MIME 類型
        mime_type = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"

        return {
            "success": True,
            "filename": file.filename,
            "mime_type": mime_type,
            "size": len(content),
            "content": content_base64,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"文件上傳失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
