from fastapi import Request, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import hmac

from app.db import get_db
from app.models.user import User
from app.models.auth_session import AuthSession
from app.security import hash_token, verify_csrf_token

async def get_current_user(request: Request) -> User | None:
    return getattr(request.state, "user", None)

async def require_auth(
    request: Request, 
    user: User | None = Depends(get_current_user)
) -> User:
    if not user:
        if request.headers.get("HX-Request"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                headers={"HX-Redirect": "/login"}
            )
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER, 
            headers={"Location": "/login"}
        )
    return user

async def require_admin(
    request: Request,
    user: User = Depends(require_auth)
) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user

async def require_csrf(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    form = await request.form()
    form_csrf = form.get("csrf_token")
    cookie_csrf = request.cookies.get("csrf")
    
    if not form_csrf or not cookie_csrf:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CSRF token")
        
    if not hmac.compare_digest(form_csrf, cookie_csrf):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token mismatch")
        
    session_token = request.cookies.get("session")
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        
    token_hash = hash_token(session_token)
    stmt = select(AuthSession).where(AuthSession.token_hash == token_hash)
    result = await db.execute(stmt)
    auth_session = result.scalar_one_or_none()
    
    if not auth_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        
    if not verify_csrf_token(form_csrf, auth_session.csrf_token_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")