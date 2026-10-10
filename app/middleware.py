from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, Response
from sqlalchemy import select
from datetime import datetime, timezone
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

        # 3. Аутентификация
        request.state.user = None
        request.state.is_partner = False

        session_token = request.cookies.get("session")
        if session_token:
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

                    # 4. Проверяем партнёрство (с защитой от ошибок)
                    if request.state.user:
                        try:
                            from app.models.partner import Partner
                            partner_stmt = select(Partner.id).where(
                                Partner.user_id == request.state.user.id,
                                Partner.is_active == True,  # noqa: E712
                            )
                            partner_result = await db.execute(partner_stmt)
                            request.state.is_partner = partner_result.scalar_one_or_none() is not None
                        except Exception:
                            # Если таблица ещё не создана или другая ошибка — не падаем
                            request.state.is_partner = False

        response = await call_next(request)

        # 5. Очистка flash после отдачи ответа
        if request.state.flashes:
            clear_flashes(response)

        return response