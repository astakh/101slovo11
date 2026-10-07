from datetime import datetime, timedelta, timezone
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Response

from app.models.user import User
from app.models.auth_session import AuthSession
from app.models.event import Event
from app.security import hash_password, verify_password, generate_session_token, hash_token, generate_csrf_token, hash_csrf_token
from app.config import settings

async def register_user(db: AsyncSession, email: str, password: str) -> User:
    stmt = select(User).where(User.email == email.lower())
    result = await db.execute(stmt)
    existing_user = result.scalar_one_or_none()
    
    if existing_user:
        raise ValueError("Пользователь с таким email уже существует")
        
    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        words_per_lesson=settings.WORDS_PER_LESSON_DEFAULT,
        daily_lesson_limit=settings.DAILY_LESSON_LIMIT_DEFAULT
    )
    db.add(user)
    await db.flush() # Получаем user.id
    
    event = Event(user_id=user.id, type="signup")
    db.add(event)
    
    await db.commit()
    await db.refresh(user)
    return user

async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    stmt = select(User).where(User.email == email.lower())
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(password, user.password_hash):
        return None
    return user

async def create_session(db: AsyncSession, user_id: int, response: Response):
    session_token = generate_session_token()
    csrf_token = generate_csrf_token()
    
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.SESSION_TTL_DAYS)
    
    session = AuthSession(
        user_id=user_id,
        token_hash=hash_token(session_token),
        csrf_token_hash=hash_csrf_token(csrf_token),
        expires_at=expires_at
    )
    db.add(session)
    await db.commit()
    
    is_secure = settings.ENV == "production"
    
    response.set_cookie(
        "session", session_token, httponly=True, secure=is_secure, samesite="lax", path="/",
        max_age=settings.SESSION_TTL_DAYS * 24 * 60 * 60
    )
    response.set_cookie(
        "csrf", csrf_token, httponly=False, secure=is_secure, samesite="lax", path="/",
        max_age=settings.SESSION_TTL_DAYS * 24 * 60 * 60
    )

async def delete_session(db: AsyncSession, session_token: str | None, response: Response):
    if session_token:
        token_hash = hash_token(session_token)
        await db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash))
        await db.commit()
        
    response.delete_cookie("session", path="/")
    response.delete_cookie("csrf", path="/")