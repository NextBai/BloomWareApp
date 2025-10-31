import os
import sys
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore import DocumentReference, CollectionReference, FieldFilter
from google.cloud.firestore_v1 import ArrayUnion, Increment
import asyncio
import hashlib

# 設置日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Firestore")

# 載入環境變數
load_dotenv()

# 統一配置管理
from core.config import settings

# 全局變數
firestore_db = None
users_collection = None
chats_collection = None
messages_collection = None
memories_collection = None
health_data_collection = None
device_bindings_collection = None
geo_cache_collection = None
route_cache_collection = None

# 記憶儲存相關設定
MAX_MEMORIES_PER_USER = 500


def _get_user_doc_ref(user_id: str) -> DocumentReference:
    if users_collection is None:
        raise RuntimeError("Firestore尚未連接，無法操作使用者資料")
    return users_collection.document(user_id)


def _get_user_memories_collection(user_id: str) -> CollectionReference:
    return _get_user_doc_ref(user_id).collection("memories")


def _get_chat_messages_collection(chat_id: str) -> CollectionReference:
    if chats_collection is None:
        raise RuntimeError("Firestore尚未連接，無法取得對話消息集合")
    return chats_collection.document(chat_id).collection("messages")

def connect_to_firestore():
    """初始化 Firebase Firestore 連接"""
    global firestore_db, messages_collection, users_collection, chats_collection, memories_collection, health_data_collection, device_bindings_collection

    firebase_project_id = settings.FIREBASE_PROJECT_ID

    if not firebase_project_id:
        logger.error("Firebase專案ID未正確設置，請在.env文件中設置FIREBASE_PROJECT_ID環境變數")
        print("\n❌ 錯誤: Firebase專案ID未設置！請在.env文件中設置FIREBASE_PROJECT_ID\n")
        return False

    try:
        logger.info("正在嘗試連接Firebase Firestore...")
        print("\n🔄 正在連接Firebase Firestore數據庫...\n")

        # 檢查是否已經初始化 Firebase
        try:
            firebase_admin.get_app()
            logger.info("Firebase 已初始化，跳過重複初始化")
        except ValueError:
            # 從統一配置取得 Firebase 憑證（支援環境變數或檔案）
            try:
                firebase_creds_dict = settings.get_firebase_credentials()
                cred = credentials.Certificate(firebase_creds_dict)
                firebase_admin.initialize_app(cred, {
                    'projectId': firebase_project_id,
                })
                logger.info(f"Firebase 初始化成功（專案ID：{firebase_project_id}）")
            except ValueError as e:
                logger.error(f"Firebase 憑證載入失敗: {e}")
                print(f"\n❌ 錯誤: Firebase 憑證載入失敗！{e}\n")
                return False
        
        # 初始化 Firestore 客戶端
        firestore_db = firestore.client()
        
        # 測試連接
        test_doc = firestore_db.collection('_test_connection').document('test')
        test_doc.set({'timestamp': datetime.now(), 'test': True})
        test_doc.delete()  # 清理測試文檔
        
        # 初始化集合引用
        messages_collection = firestore_db.collection('messages')
        users_collection = firestore_db.collection('users')
        chats_collection = firestore_db.collection('chats')
        health_data_collection = firestore_db.collection('health_data')
        device_bindings_collection = firestore_db.collection('device_bindings')
        
        # 其他集合
        global geo_cache_collection, route_cache_collection
        geo_cache_collection = firestore_db.collection('geo_cache')
        route_cache_collection = firestore_db.collection('route_cache')
        
        logger.info(f"✅ Firestore連接成功，專案ID：{firebase_project_id}")
        print(f"\n✅ Firebase Firestore連接成功！專案ID：{firebase_project_id}\n")
        return True
        
    except Exception as e:
        logger.error(f"Firebase Firestore連接失敗：{e}")
        print(f"\n❌ Firebase Firestore連接失敗：{e}\n")
        print("🔧 故障排除建議：")
        print("1. 檢查網絡連接")
        print("2. 確認Firebase服務帳戶金鑰文件路徑正確")
        print("3. 驗證Firebase專案ID是否正確")
        print("4. 確保Firestore Database已在Firebase Console中啟用")
        print("5. 檢查服務帳戶權限是否包含Firestore權限")
        print()
        return False
def ensure_indexes():
    """Firestore 不需要手動創建索引，由 Google 自動優化"""
    logger.info("Firestore 自動處理索引優化，無需手動創建索引")



async def get_user_by_id(user_id: str):
    """根據使用者ID查找使用者，返回公共資訊"""
    if users_collection is None:
        logger.error("Firestore尚未連接，無法查找使用者")
        return None
    try:
        # Firestore 查詢 - 使用新語法
        query = users_collection.where(filter=FieldFilter("user_id", "==", user_id)).limit(1)
        docs = query.get()
        
        if not docs:
            return None
            
        user_doc = docs[0]
        user_data = user_doc.to_dict()
        
        return {
            "id": user_data["user_id"],
            "name": user_data.get("name", ""),
            "email": user_data.get("email", ""),
            "created_at": user_data.get("created_at"),
        }
    except Exception as e:
        logger.error(f"查找使用者時發生錯誤: {e}")
        return None

# 已移除舊的內嵌測試函式 test_connection，避免在生產代碼夾雜測試邏輯

async def save_message(user_id, content, is_bot=False):
    """保存消息到數據庫"""
    if messages_collection is None:
        logger.error("Firestore尚未連接，無法保存消息")
        return False
    try:
        message = {
            "user_id": user_id,  # 使用user_id字段存儲用戶ID
            "content": content,
            "is_bot": is_bot,
            "timestamp": datetime.now(),
        }
        import asyncio as _asyncio
        await _asyncio.to_thread(lambda: messages_collection.add(message))
        logger.debug(f"消息已保存到 Firestore")
        return True
    except Exception as e:
        logger.error(f"保存消息時發生錯誤: {e}")
        return False

async def get_user_history(user_id, limit=20):
    """獲取用戶的歷史對話記錄"""
    if messages_collection is None:
        logger.error("Firestore尚未連接，無法獲取歷史記錄")
        return []
    try:
        import asyncio as _asyncio
        def _fetch_messages():
            docs = messages_collection.where(filter=FieldFilter("user_id", "==", user_id))\
                                    .order_by("timestamp")\
                                    .limit(limit)\
                                    .stream()
            return [doc.to_dict() for doc in docs]
        
        messages = await _asyncio.to_thread(_fetch_messages)
        logger.info(f"已獲取用戶 {user_id} 的 {len(messages)} 條歷史記錄")
        return messages
    except Exception as e:
        logger.error(f"獲取歷史記錄時發生錯誤: {e}")
        return []

# Google OAuth 2.0 用戶認證
async def create_or_login_google_user(google_token_info):
    """Google OAuth 唯一登入入口，自動處理首次註冊和後續登入"""
    if users_collection is None or firestore_db is None:
        logger.error("Firestore尚未連接，無法處理用戶認證")
        return {"success": False, "error": "數據庫未連接"}

    # 檢查 Firestore 連接狀態
    try:
        logger.info("🔍 檢查 Firestore 連接狀態...")
        # 快速連接測試
        import asyncio as _asyncio
        def _test_connection():
            test_ref = firestore_db.collection('_connection_test').document('ping')
            test_ref.set({'ping': 'test'}, merge=True)
            test_ref.delete()
            return True

        await _asyncio.wait_for(
            _asyncio.to_thread(_test_connection),
            timeout=5.0  # 5秒連接測試超時
        )
        logger.info("✅ Firestore 連接正常")
    except _asyncio.TimeoutError:
        logger.error("❌ Firestore 連接測試超時")
        return {"success": False, "error": "數據庫連接超時"}
    except Exception as e:
        logger.error(f"❌ Firestore 連接測試失敗: {e}")
        return {"success": False, "error": f"數據庫連接異常: {str(e)}"}

    google_id = google_token_info.get("id") or google_token_info.get("sub")
    if not google_id:
        logger.error(f"Google用戶信息中缺少ID字段，收到的信息: {google_token_info}")
        return {"success": False, "error": "INVALID_GOOGLE_USER_INFO"}

    email = google_token_info.get("email")
    if not email:
        logger.error(f"Google用戶信息中缺少email字段，收到的信息: {google_token_info}")
        return {"success": False, "error": "INVALID_GOOGLE_USER_INFO"}

    logger.info(f"🔍 處理Google用戶: google_id={google_id}, email={email}")

    try:
        import asyncio as _asyncio

        def _fetch_existing_user():
            try:
                logger.info(f"🔍 查詢現有用戶: google_id={google_id}")
                # 使用新的 filter 語法
                query = users_collection.where(filter=FieldFilter("google_id", "==", google_id)).limit(1)
                docs = list(query.stream())
                logger.info(f"🔍 查詢結果: 找到 {len(docs)} 個用戶")
                return docs[0] if docs else None
            except Exception as e:
                error_msg = str(e).lower()
                if "quota" in error_msg or "exceeded" in error_msg:
                    logger.error(f"❌ Firestore 配額已超出限制: {e}")
                    raise Exception("FIRESTORE_QUOTA_EXCEEDED")
                else:
                    logger.error(f"❌ Firestore 查詢失敗: {e}")
                    raise e

        logger.info(f"📤 開始查詢用戶...")
        # 添加超時機制
        try:
            user_doc = await _asyncio.wait_for(
                _asyncio.to_thread(_fetch_existing_user),
                timeout=10.0  # 10秒超時
            )
            logger.info(f"🔍 用戶查詢完成: {'找到現有用戶' if user_doc else '未找到用戶'}")
        except _asyncio.TimeoutError:
            logger.error("❌ Firestore 查詢超時（10秒）")
            return {"success": False, "error": "數據庫查詢超時"}
        except Exception as e:
            error_str = str(e)
            if "FIRESTORE_QUOTA_EXCEEDED" in error_str:
                logger.error("❌ Firestore 每日配額已用完")
                return {
                    "success": False,
                    "error": "QUOTA_EXCEEDED",
                    "message": "Firestore 每日配額已用完，請稍後再試或聯繫管理員升級服務"
                }
            else:
                logger.error(f"❌ 用戶查詢異常: {e}")
                return {"success": False, "error": f"用戶查詢失敗: {str(e)}"}

        if user_doc:
            user_data = user_doc.to_dict()

            def _update_user():
                users_collection.document(user_doc.id).update({
                    "name": google_token_info.get("name", user_data.get("name")),
                    "picture": google_token_info.get("picture", user_data.get("picture")),
                    "last_login": datetime.now(),
                    "updated_at": datetime.now()
                })

            await _asyncio.to_thread(_update_user)

            logger.info(f"用戶 {email} 登入成功，user_id: {user_data.get('user_id')}")
            return {
                "success": True,
                "user": {
                    "id": user_data.get("user_id", google_id),
                    "name": user_data.get("name", ""),
                    "email": user_data.get("email", email),
                    "picture": user_data.get("picture"),
                    "created_at": user_data.get("created_at")
                },
                "is_new_user": False
            }

        logger.info(f"📤 創建新用戶...")
        now = datetime.now()
        new_user = {
            "user_id": google_id,
            "google_id": google_id,
            "email": email,
            "name": google_token_info.get("name", ""),
            "picture": google_token_info.get("picture"),
            "locale": google_token_info.get("locale", "zh-TW"),
            "first_login": now,
            "last_login": now,
            "created_at": now,
            "updated_at": now
        }

        logger.info(f"🔍 新用戶數據: {new_user}")
        logger.info(f"📤 寫入Firestore...")
        await _asyncio.to_thread(lambda: users_collection.document(google_id).set(new_user))
        logger.info(f"✅ 新用戶 {email} 註冊成功，user_id: {google_id}")

        return {
            "success": True,
            "user": {
                "id": google_id,
                "name": new_user["name"],
                "email": new_user["email"],
                "picture": new_user["picture"],
                "created_at": new_user["created_at"]
            },
            "is_new_user": True
        }

    except Exception as e:
        logger.error(f"❌ Google OAuth 認證時發生錯誤: {e}")
        logger.error(f"❌ 錯誤類型: {type(e).__name__}")
        logger.error(f"❌ 錯誤堆疊:", exc_info=True)
        return {"success": False, "error": str(e)}

# 對話管理
async def create_chat(user_id, title="新對話"):
    if chats_collection is None:
        logger.error("Firestore尚未連接，無法創建對話")
        return {"success": False, "error": "數據庫未連接"}
    try:
        chat = {
            "user_id": user_id,
            "title": title,
            "messages": [],
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        import asyncio as _asyncio
        doc_ref = await _asyncio.to_thread(lambda: chats_collection.add(chat))
        chat_id = doc_ref[1].id
        logger.info(f"為用戶 {user_id} 創建了新對話，ID: {chat_id}")
        chat_info = {
            "chat_id": chat_id,
            "user_id": user_id,
            "title": title,
            "created_at": chat["created_at"],
            "updated_at": chat["updated_at"],
        }
        return {"success": True, "chat": chat_info}
    except Exception as e:
        logger.error(f"創建對話時發生錯誤: {e}")
        return {"success": False, "error": str(e)}

async def get_user_chats(user_id):
    if chats_collection is None:
        logger.error("Firestore尚未連接，無法獲取對話")
        return {"success": False, "error": "數據庫未連接"}
    try:
        import asyncio as _asyncio
        def _fetch_chats():
            docs = chats_collection.where(filter=FieldFilter("user_id", "==", user_id))\
                                 .order_by("updated_at", direction=firestore.Query.DESCENDING)\
                                 .stream()
            chats = []
            for doc in docs:
                chat = doc.to_dict()
                chat["chat_id"] = doc.id
                if "user_id" in chat:
                    del chat["user_id"]
                if "messages" in chat:
                    del chat["messages"]
                if "created_at" in chat:
                    del chat["created_at"]
                chats.append(chat)
            return chats
        
        chats = await _asyncio.to_thread(_fetch_chats)
        logger.info(f"獲取到用戶 {user_id} 的 {len(chats)} 個對話")
        return {"success": True, "chats": chats}
    except Exception as e:
        logger.error(f"獲取用戶對話時發生錯誤: {e}")
        return {"success": False, "error": str(e)}

async def get_chat(chat_id):
    if chats_collection is None:
        logger.error("Firestore尚未連接，無法獲取對話")
        return {"success": False, "error": "數據庫未連接"}
    try:
        import asyncio as _asyncio
        def _get_doc():
            doc = chats_collection.document(chat_id).get()
            return doc if doc.exists else None
        
        doc = await _asyncio.to_thread(_get_doc)
        if not doc:
            logger.warning(f"對話 {chat_id} 不存在")
            return {"success": False, "error": "對話不存在"}
        
        chat = doc.to_dict() or {}
        chat["chat_id"] = doc.id

        # 從 chat 子集合讀取完整對話（按時間升序）
        try:
            def _fetch_msgs():
                ref = _get_chat_messages_collection(chat_id)
                return [
                    {**doc.to_dict(), "id": doc.id}
                    for doc in ref.order_by("timestamp").stream()
                ]

            msgs = await _asyncio.to_thread(_fetch_msgs)
            chat["messages"] = msgs
            logger.info(f"獲取到對話 {chat_id}，包含 {len(msgs)} 條消息（chat 子集合）")
        except Exception as _e:
            # 向後相容：若讀取失敗，退回文件內嵌 messages（若存在）
            msgs_fallback = chat.get('messages', []) or []
            chat["messages"] = msgs_fallback
            logger.warning(f"讀取 chat 子集合失敗，使用內嵌 messages。原因: {_e}")

        return {"success": True, "chat": chat}
    except Exception as e:
        logger.error(f"獲取對話時發生錯誤: {e}")
        return {"success": False, "error": str(e)}

async def save_chat_message(chat_id, sender, content):
    """保存對話消息（chat/{chat_id}/messages 子集合作為主要儲存）"""
    if chats_collection is None:
        logger.error("Firestore尚未連接，無法保存消息")
        return {"success": False, "error": "數據庫未連接"}
    try:
        import asyncio as _asyncio

        now = datetime.now()
        message = {
            "chat_id": chat_id,
            "sender": sender,
            "content": content,
            "timestamp": now,
        }

        def _write_message():
            ref = _get_chat_messages_collection(chat_id)
            ref.add(message)

        def _write_legacy_copy():
            if messages_collection is None:
                return
            try:
                messages_collection.add(message)
            except Exception as legacy_err:  # pragma: no cover
                logger.debug(f"寫入頂層 messages 集合失敗（兼容用途，可忽略）: {legacy_err}")

        def _touch_chat():
            doc_ref = chats_collection.document(chat_id)
            snap = doc_ref.get()
            if not snap.exists:
                return False
            doc_ref.update({"updated_at": now})
            return True

        await _asyncio.to_thread(_write_message)
        # 兼容舊資料模型：非阻塞地寫入頂層 messages 集合，供舊功能查詢使用
        await _asyncio.to_thread(_write_legacy_copy)
        touched = await _asyncio.to_thread(_touch_chat)
        if not touched:
            logger.warning(f"對話 {chat_id} 不存在，但消息已寫入 chat 子集合")

        logger.info(f"消息已保存到 chat 子集合（chat_id={chat_id}）")
        return {"success": True, "message": message}
    except Exception as e:
        logger.error(f"保存消息時發生錯誤: {e}")
        return {"success": False, "error": str(e)}


async def get_chat_messages(chat_id: str, limit: int | None = None, ascending: bool = True):
    """讀取指定對話的消息（優先使用 chat 子集合）"""
    if chats_collection is None:
        logger.error("Firestore尚未連接，無法讀取消息")
        return []
    try:
        import asyncio as _asyncio
        from google.cloud import firestore as _fs

        def _query():
            ref = _get_chat_messages_collection(chat_id)
            direction = _fs.Query.ASCENDING if ascending else _fs.Query.DESCENDING
            q = ref.order_by("timestamp", direction=direction)
            if limit and limit > 0:
                q = q.limit(limit)
            docs = q.stream()
            records = []
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                records.append(data)
            if not ascending:
                records = list(reversed(records))
            return records

        messages = await _asyncio.to_thread(_query)
        if messages:
            return messages

        # 向後相容：若子集合無資料，嘗試讀取舊頂層 messages 集合
        if messages_collection is None:
            return []

        def _legacy_query():
            docs = messages_collection.where(filter=FieldFilter("chat_id", "==", chat_id)).stream()
            legacy = [d.to_dict() for d in docs]
            legacy.sort(key=lambda item: item.get("timestamp"))
            if limit and limit > 0:
                legacy = legacy[:limit]
            return legacy

        legacy_sorted = await _asyncio.to_thread(_legacy_query)
        view_messages = list(legacy_sorted)
        if not ascending:
            view_messages.reverse()
        if legacy_sorted:
            def _backfill():
                try:
                    ref = _get_chat_messages_collection(chat_id)
                    # 若子集合仍為空，將舊資料搬遷過去
                    has_existing = any(True for _ in ref.limit(1).stream())
                    if has_existing:
                        return
                    for legacy_msg in legacy_sorted:
                        ref.add(legacy_msg)
                    logger.info(f"已將 legacy messages 回填至 chat 子集合（chat_id={chat_id}）")
                except Exception as backfill_err:
                    logger.warning(f"回填 legacy messages 失敗（可忽略）: {backfill_err}")

            await _asyncio.to_thread(_backfill)
        return view_messages
    except Exception as e:
        logger.error(f"讀取對話消息失敗: {e}")
        return []

async def update_chat_title(chat_id, title):
    if chats_collection is None:
        logger.error("Firestore尚未連接，無法更新對話標題")
        return {"success": False, "error": "數據庫未連接"}
    try:
        import asyncio as _asyncio

        def _update_doc():
            doc_ref = chats_collection.document(chat_id)
            doc = doc_ref.get()
            if not doc.exists:
                return False
            doc_ref.update({
                "title": title,
                "updated_at": datetime.now(),
            })
            return True

        updated = await _asyncio.to_thread(_update_doc)
        if not updated:
            logger.warning(f"對話 {chat_id} 不存在，無法更新標題")
            return {"success": False, "error": "對話不存在"}

        logger.info(f"對話 {chat_id} 標題已更新為 '{title}'")
        return {"success": True}
    except Exception as e:
        logger.error(f"更新對話標題時發生錯誤: {e}")
        return {"success": False, "error": str(e)}

async def delete_chat(chat_id):
    if chats_collection is None:
        logger.error("Firestore尚未連接，無法刪除對話")
        return {"success": False, "error": "數據庫未連接"}
    try:
        import asyncio as _asyncio

        def _delete_doc():
            doc_ref = chats_collection.document(chat_id)
            doc = doc_ref.get()
            if not doc.exists:
                return False
            # 先刪除子集合中的消息，避免孤兒資料
            try:
                messages_ref = _get_chat_messages_collection(chat_id)
                for msg_snapshot in messages_ref.stream():
                    msg_snapshot.reference.delete()
            except Exception as msg_err:
                logger.warning(f"刪除對話 {chat_id} 的子消息時發生錯誤：{msg_err}")
            doc_ref.delete()
            return True

        deleted = await _asyncio.to_thread(_delete_doc)
        if not deleted:
            logger.warning(f"對話 {chat_id} 不存在，無法刪除")
            return {"success": False, "error": "對話不存在"}

        logger.info(f"對話 {chat_id} 已刪除")
        return {"success": True}
    except Exception as e:
        logger.error(f"刪除對話時發生錯誤: {e}")
        return {"success": False, "error": str(e)}


# ===== 對話情緒記憶 =====
async def set_chat_emotion(chat_id: str, emotion: dict):
    """為指定對話記錄最近的情緒狀態（label, confidence, timestamp）。"""
    if chats_collection is None:
        logger.error("Firestore尚未連接，無法設定對話情緒")
        return {"success": False, "error": "數據庫未連接"}
    try:
        import asyncio as _asyncio

        def _update_doc():
            doc_ref = chats_collection.document(chat_id)
            doc = doc_ref.get()
            if not doc.exists:
                return False
            payload = {
                "label": emotion.get("label"),
                "confidence": emotion.get("confidence"),
                "timestamp": datetime.now(),
            }
            doc_ref.update({
                "context.emotion": payload,
                "updated_at": datetime.now(),
            })
            return True

        updated = await _asyncio.to_thread(_update_doc)
        if not updated:
            return {"success": False, "error": "對話不存在"}
        return {"success": True}
    except Exception as e:
        logger.error(f"設定對話情緒時發生錯誤: {e}")
        return {"success": False, "error": str(e)}

async def get_chat_emotion(chat_id: str):
    """取得對話記錄的最近情緒狀態。"""
    if chats_collection is None:
        logger.error("Firestore尚未連接，無法讀取對話情緒")
        return {"success": False, "error": "數據庫未連接"}
    try:
        import asyncio as _asyncio

        def _get_doc():
            doc = chats_collection.document(chat_id).get()
            return doc if doc.exists else None

        doc = await _asyncio.to_thread(_get_doc)
        if not doc:
            return {"success": False, "error": "對話不存在"}
        data = doc.to_dict() or {}
        emotion = (data.get("context") or {}).get("emotion")
        return {"success": True, "emotion": emotion}
    except Exception as e:
        logger.error(f"讀取對話情緒時發生錯誤: {e}")
        return {"success": False, "error": str(e)}

# ===== 語音登入：使用者與說話者標籤關聯 =====
async def set_user_speaker_label(user_id: str, speaker_label: str):
    if users_collection is None:
        logger.error("Firestore尚未連接，無法設定語音標籤")
        return {"success": False, "error": "數據庫未連接"}
    try:
        import asyncio as _asyncio

        def _is_label_taken():
            docs = list(users_collection.where(filter=FieldFilter("speaker_label", "==", speaker_label)).limit(1).stream())
            return docs[0] if docs else None

        existing_label = await _asyncio.to_thread(_is_label_taken)
        if existing_label and existing_label.to_dict().get("user_id") != user_id:
            return {"success": False, "error": "SPEAKER_LABEL_TAKEN"}

        def _update_user():
            doc_ref = users_collection.document(user_id)
            doc = doc_ref.get()
            if not doc.exists:
                return False
            doc_ref.update({"speaker_label": speaker_label})
            return True

        updated = await _asyncio.to_thread(_update_user)
        if not updated:
            return {"success": False, "error": "USER_NOT_FOUND"}

        return {"success": True}
    except Exception as e:
        logger.error(f"設定語音標籤時發生錯誤: {e}")
        return {"success": False, "error": str(e)}


async def get_user_by_speaker_label(speaker_label: str):
    if users_collection is None:
        logger.error("Firestore尚未連接，無法查詢語音標籤")
        return None
    try:
        import asyncio as _asyncio

        def _fetch_user():
            docs = list(users_collection.where(filter=FieldFilter("speaker_label", "==", speaker_label)).limit(1).stream())
            return docs[0] if docs else None

        doc = await _asyncio.to_thread(_fetch_user)
        if not doc:
            return None

        data = doc.to_dict()
        return {
            "id": data.get("user_id"),
            "name": data.get("name", ""),
            "email": data.get("email", ""),
            "created_at": data.get("created_at"),
        }
    except Exception as e:
        logger.error(f"查詢語音標籤對應用戶時發生錯誤: {e}")
        return None


# ===== 專門記憶系統 =====

async def save_memory(
    user_id: str,
    memory_type: str,
    content: str,
    importance: float = 1.0,
    metadata: dict | None = None,
) -> Dict[str, Any]:
    """保存重要記憶到 Firestore"""
    if users_collection is None or firestore_db is None:
        logger.error("Firestore尚未連接，無法保存記憶")
        return {"success": False, "error": "數據庫未連接"}

    try:
        import asyncio as _asyncio

        now = datetime.now()
        sanitized_importance = max(0.0, min(1.0, importance))
        metadata_payload = metadata.copy() if metadata else {}
        metadata_payload.setdefault("source", "unknown")
        metadata_payload.setdefault("last_updated_by", "memory_system")
        metadata_payload["updated_at"] = now.isoformat()

        context_tags = metadata_payload.get("context_tags", [])
        if not isinstance(context_tags, list):
            context_tags = list(context_tags) if context_tags else []
        metadata_payload["context_tags"] = context_tags

        triggers = metadata_payload.get("triggers", [])
        if not isinstance(triggers, list):
            triggers = list(triggers) if triggers else []
        metadata_payload["triggers"] = triggers

        col_ref = _get_user_memories_collection(user_id)
        content_hash = hashlib.sha1(content.strip().lower().encode("utf-8")).hexdigest()

        def _ensure_user_stub():
            user_doc = _get_user_doc_ref(user_id)
            snap = user_doc.get()
            if not snap.exists:
                user_doc.set(
                    {
                        "user_id": user_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                    merge=True,
                )

        def _find_existing():
            docs = (
                col_ref.where(filter=FieldFilter("content_hash", "==", content_hash))
                .limit(1)
                .stream()
            )
            for doc in docs:
                return doc
            return None

        await _asyncio.to_thread(_ensure_user_stub)
        existing_doc = await _asyncio.to_thread(_find_existing)

        if existing_doc:
            doc_ref = existing_doc.reference

            def _update_memory():
                doc_ref.update({
                    "content": content,
                    "importance": sanitized_importance,
                    "metadata": metadata_payload,
                    "updated_at": now,
                    "access_count": Increment(1),
                    "last_accessed": now,
                    "content_hash": content_hash,
                })

            await _asyncio.to_thread(_update_memory)
            logger.info(f"更新用戶 {user_id} 的記憶: {memory_type}")
            return {"success": True, "action": "updated", "memory_id": existing_doc.id}

        def _create_memory():
            doc_ref = col_ref.document()
            doc_ref.set({
                "user_id": user_id,
                "type": memory_type,
                "content": content,
                "importance": sanitized_importance,
                "metadata": metadata_payload,
                "access_count": 0,
                "last_accessed": now,
                "updated_at": now,
                "created_at": now,
                "content_hash": content_hash,
            })
            return doc_ref.id

        memory_id = await _asyncio.to_thread(_create_memory)
        await _asyncio.to_thread(_enforce_memory_quota, col_ref)
        logger.info(f"保存用戶 {user_id} 的新記憶: {memory_type}")
        return {"success": True, "action": "created", "memory_id": memory_id}

    except Exception as e:
        logger.error(f"保存記憶時發生錯誤: {e}")
        return {"success": False, "error": str(e)}


# ===== 環境 Context（位置/方位/時序） =====

async def set_user_env_current(user_id: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """更新使用者環境現況 users/{uid}/context/current（含 TTL/新鮮度由讀取端判斷）。"""
    if users_collection is None:
        return {"success": False, "error": "數據庫未連接"}
    try:
        import asyncio as _asyncio
        now = datetime.now()

        def _update():
            user_doc = _get_user_doc_ref(user_id)
            ctx_ref = user_doc.collection('context').document('current')
            payload = ctx.copy()
            payload['updated_at'] = now
            ctx_ref.set(payload, merge=True)
            return True

        await _asyncio.to_thread(_update)
        return {"success": True}
    except Exception as e:
        logger.error(f"更新環境現況失敗: {e}")
        return {"success": False, "error": str(e)}


async def add_user_env_snapshot(user_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """新增使用者環境快照 users/{uid}/context/snapshots。僅保留短期歷史。"""
    if users_collection is None:
        return {"success": False, "error": "數據庫未連接"}
    try:
        import asyncio as _asyncio
        now = datetime.now()

        def _write():
            user_doc = _get_user_doc_ref(user_id)
            col = user_doc.collection('context').document('meta').collection('snapshots')
            payload = snapshot.copy()
            payload['created_at'] = now
            col.add(payload)
            return True

        await _asyncio.to_thread(_write)
        return {"success": True}
    except Exception as e:
        logger.error(f"寫入環境快照失敗: {e}")
        return {"success": False, "error": str(e)}


async def get_user_env_current(user_id: str) -> Dict[str, Any]:
    """讀取使用者環境現況。"""
    if users_collection is None:
        return {"success": False, "error": "數據庫未連接"}
    try:
        import asyncio as _asyncio

        def _read():
            user_doc = _get_user_doc_ref(user_id)
            ctx_ref = user_doc.collection('context').document('current')
            snap = ctx_ref.get()
            return snap.to_dict() if snap.exists else None

        data = await _asyncio.to_thread(_read)
        if not data:
            return {"success": False, "error": "NOT_FOUND"}
        return {"success": True, "context": data}
    except Exception as e:
        logger.error(f"讀取環境現況失敗: {e}")
        return {"success": False, "error": str(e)}


# ===== 反地理/路線 全域快取集合 =====

async def get_geo_cache(geohash7: str) -> Optional[Dict[str, Any]]:
    if geo_cache_collection is None:
        return None
    try:
        import asyncio as _asyncio
        def _read():
            doc = geo_cache_collection.document(geohash7).get()
            return doc.to_dict() if doc.exists else None
        return await _asyncio.to_thread(_read)
    except Exception as e:
        logger.warning(f"讀取 geo_cache 失敗: {e}")
        return None


async def set_geo_cache(geohash7: str, payload: Dict[str, Any]) -> bool:
    if geo_cache_collection is None:
        return False
    try:
        import asyncio as _asyncio
        now = datetime.now()
        def _write():
            data = payload.copy()
            data['cached_at'] = now
            geo_cache_collection.document(geohash7).set(data, merge=True)
            return True
        return await _asyncio.to_thread(_write)
    except Exception as e:
        logger.warning(f"寫入 geo_cache 失敗: {e}")
        return False


async def get_route_cache(key: str) -> Optional[Dict[str, Any]]:
    if route_cache_collection is None:
        return None
    try:
        import asyncio as _asyncio
        def _read():
            doc = route_cache_collection.document(key).get()
            return doc.to_dict() if doc.exists else None
        return await _asyncio.to_thread(_read)
    except Exception as e:
        logger.warning(f"讀取 route_cache 失敗: {e}")
        return None


async def set_route_cache(key: str, payload: Dict[str, Any]) -> bool:
    if route_cache_collection is None:
        return False
    try:
        import asyncio as _asyncio
        now = datetime.now()
        def _write():
            data = payload.copy()
            data['cached_at'] = now
            route_cache_collection.document(key).set(data, merge=True)
            return True
        return await _asyncio.to_thread(_write)
    except Exception as e:
        logger.warning(f"寫入 route_cache 失敗: {e}")
        return False


async def get_user_memories(
    user_id: str,
    memory_type: str | None = None,
    limit: int = 10,
    min_importance: float = 0.0,
) -> Dict[str, Any]:
    """獲取用戶的記憶"""
    if users_collection is None:
        logger.error("Firestore尚未連接，無法獲取記憶")
        return {"success": False, "error": "數據庫未連接"}

    try:
        import asyncio as _asyncio

        def _fetch_memories():
            col_ref = _get_user_memories_collection(user_id)
            query = col_ref.where(filter=FieldFilter("importance", ">=", min_importance))
            if memory_type:
                query = query.where(filter=FieldFilter("type", "==", memory_type))
            docs = (
                query.order_by("importance", direction=firestore.Query.DESCENDING)
                .order_by("updated_at", direction=firestore.Query.DESCENDING)
                .limit(limit)
                .stream()
            )
            return [doc.to_dict() | {"memory_id": doc.id} for doc in docs]

        memories = await _asyncio.to_thread(_fetch_memories)

        def _mark_accessed(mem_ids):
            col_ref = _get_user_memories_collection(user_id)
            now_inner = datetime.now()
            for mid in mem_ids:
                col_ref.document(mid).update({
                    "access_count": Increment(1),
                    "last_accessed": now_inner,
                })

        if memories:
            await _asyncio.to_thread(_mark_accessed, [m["memory_id"] for m in memories])

        logger.info(f"獲取到用戶 {user_id} 的 {len(memories)} 條記憶")
        return {"success": True, "memories": memories}

    except Exception as e:
        logger.error(f"獲取記憶時發生錯誤: {e}")
        return {"success": False, "error": str(e)}


async def search_memories(user_id: str, query_text: str, limit: int = 5) -> Dict[str, Any]:
    """基於簡易文本匹配的記憶搜索"""
    if users_collection is None:
        logger.error("Firestore尚未連接，無法搜索記憶")
        return {"success": False, "error": "數據庫未連接"}

    try:
        import asyncio as _asyncio

        normalized_query = query_text.lower()

        def _candidate_memories():
            col_ref = _get_user_memories_collection(user_id)
            docs = (
                col_ref.order_by("updated_at", direction=firestore.Query.DESCENDING)
                .limit(80)
                .stream()
            )
            results = []
            for doc in docs:
                data = doc.to_dict() or {}
                haystack = "{} {}".format(
                    data.get("content", ""),
                    " ".join(data.get("metadata", {}).get("context_tags", [])),
                ).lower()
                if normalized_query in haystack:
                    data["memory_id"] = doc.id
                    results.append(data)
                    if len(results) >= limit:
                        break
            return results

        memories = await _asyncio.to_thread(_candidate_memories)

        def _mark_accessed(mem_ids):
            col_ref = _get_user_memories_collection(user_id)
            now_inner = datetime.now()
            for mid in mem_ids:
                col_ref.document(mid).update({
                    "access_count": Increment(1),
                    "last_accessed": now_inner,
                })

        if memories:
            await _asyncio.to_thread(_mark_accessed, [m["memory_id"] for m in memories])

        logger.info(f"搜索到用戶 {user_id} 的 {len(memories)} 條相關記憶")
        return {"success": True, "memories": memories}

    except Exception as e:
        logger.error(f"搜索記憶時發生錯誤: {e}")
        return {"success": False, "error": str(e)}


async def update_memory_importance(memory_id: str, new_importance: float):
    """更新記憶的重要性分數"""
    if users_collection is None:
        logger.error("Firestore尚未連接，無法更新記憶")
        return {"success": False, "error": "數據庫未連接"}

    try:
        import asyncio as _asyncio

        sanitized_importance = max(0.0, min(1.0, new_importance))
        now = datetime.now()

        def _update_doc():
            users = users_collection.stream()
            for user_doc in users:
                mem_ref = user_doc.reference.collection("memories").document(memory_id)
                snapshot = mem_ref.get()
                if snapshot.exists:
                    mem_ref.update({
                        "importance": sanitized_importance,
                        "updated_at": now,
                    })
                    return True
            return False

        updated = await _asyncio.to_thread(_update_doc)
        if not updated:
            return {"success": False, "error": "記憶不存在"}

        logger.info(f"更新記憶 {memory_id} 的重要性為 {sanitized_importance}")
        return {"success": True}

    except Exception as e:
        logger.error(f"更新記憶重要性時發生錯誤: {e}")
        return {"success": False, "error": str(e)}


async def delete_memory(memory_id: str):
    """刪除記憶"""
    if users_collection is None:
        logger.error("Firestore尚未連接，無法刪除記憶")
        return {"success": False, "error": "數據庫未連接"}

    try:
        import asyncio as _asyncio

        def _delete_doc():
            users = users_collection.stream()
            for user_doc in users:
                mem_ref = user_doc.reference.collection("memories").document(memory_id)
                snapshot = mem_ref.get()
                if snapshot.exists:
                    mem_ref.delete()
                    return True
            return False

        deleted = await _asyncio.to_thread(_delete_doc)
        if not deleted:
            return {"success": False, "error": "記憶不存在"}

        logger.info(f"刪除記憶 {memory_id}")
        return {"success": True}

    except Exception as e:
        logger.error(f"刪除記憶時發生錯誤: {e}")
        return {"success": False, "error": str(e)}


async def cleanup_old_memories(user_id: str, days_old: int = 90, min_importance: float = 0.3):
    """清理舊的、低重要性的記憶

    Args:
        user_id: 用戶ID
        days_old: 刪除多少天前的記憶
        min_importance: 保留的最小重要性分數
    """
    if users_collection is None:
        logger.error("Firestore尚未連接，無法清理記憶")
        return {"success": False, "error": "數據庫未連接"}

    try:
        import asyncio as _asyncio
        from datetime import timedelta

        cutoff_date = datetime.now() - timedelta(days=days_old)

        def _delete_old():
            col_ref = _get_user_memories_collection(user_id)
            docs = (
                col_ref.where(filter=FieldFilter("importance", "<", min_importance))
                .where(filter=FieldFilter("updated_at", "<", cutoff_date))
                .stream()
            )
            deleted_count = 0
            for doc in docs:
                doc.reference.delete()
                deleted_count += 1
            return deleted_count

        deleted = await _asyncio.to_thread(_delete_old)

        logger.info(f"為用戶 {user_id} 清理 {deleted} 條舊記憶")
        return {"success": True, "deleted": deleted}

    except Exception as e:
        logger.error(f"清理記憶時發生錯誤: {e}")
        return {"success": False, "error": str(e)}


def _enforce_memory_quota(col_ref: CollectionReference) -> None:
    docs = list(
        col_ref.order_by("importance", direction=firestore.Query.ASCENDING)
        .order_by("updated_at", direction=firestore.Query.ASCENDING)
        .stream()
    )
    if len(docs) <= MAX_MEMORIES_PER_USER:
        return
    excess = len(docs) - MAX_MEMORIES_PER_USER
    for doc in docs[:excess]:
        doc.reference.delete()
