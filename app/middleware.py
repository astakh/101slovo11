from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, Response
from sqlalchemy import select
from datetime import datetime, timezone

# Импортируем правильное имя фабрики сессий
from app.db import AsyncSessionLocal
from app.models.user import User
from app.models.auth_session import AuthSession
from app.security import hash_token
from app.utils.flash import get_flashes, clear_flashes

class AppMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. CSRF Token для шаблонов
        request.state.csrf_token = request.cookies.get("csrf", "")
        
        # 2. Flash сообщения
        request.state.flashes = get_flashes(request)
        
        # 3. Аутентификация (загрузка user в request.state)
        request.state.user = None
        session_token = request.cookies.get("session")
        
        if session_token:
            # Используем правильную фабрику сессий
            async with AsyncSessionLocal() as db:
                token_hash = hash_token(session_token)
                stmt = select(AuthSession).where(
                    AuthSession.token_hash == token_hash,
                    AuthSession.expires_at > datetime.now(timezone.utc)
                )
                result = await db.execute(stmt)
                auth_session = result.scalar_one_or_none()
                
                if auth_session:
                    user_stmt = select(User).where(User.id == auth_session.user_id)
                    user_result = await db.execute(user_stmt)
                    request.state.user = user_result.scalar_one_or_none()
        
        response = await call_next(request)
        
        # 4. Очистка flash после отдачи ответа
        if request.state.flashes:
            clear_flashes(response)
            
        return response