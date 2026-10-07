from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.auth import register_user, authenticate_user, create_session, delete_session
from app.deps import require_csrf
from app.core.templates import templates

router = APIRouter(tags=["auth"])

@router.get("/register")
async def register_page(request: Request):
    if request.state.user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("auth/register.html", {"request": request})

@router.post("/register")
async def register_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    if password != password_confirm:
        return templates.TemplateResponse(
            "auth/register.html", 
            {"request": request, "error": "Пароли не совпадают", "email": email}
        )
    
    try:
        user = await register_user(db, email, password)
    except ValueError as e:
        return templates.TemplateResponse(
            "auth/register.html", 
            {"request": request, "error": str(e), "email": email}
        )
        
    response = RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)
    await create_session(db, user.id, response)
    return response

@router.get("/login")
async def login_page(request: Request):
    if request.state.user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("auth/login.html", {"request": request})

@router.post("/login")
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    user = await authenticate_user(db, email, password)
    if not user:
        return templates.TemplateResponse(
            "auth/login.html", 
            {"request": request, "error": "Неверный логин или пароль", "email": email}
        )
    
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    await create_session(db, user.id, response)
    return response

@router.post("/logout", dependencies=[Depends(require_csrf)])
async def logout_post(request: Request, db: AsyncSession = Depends(get_db)):
    session_token = request.cookies.get("session")
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    await delete_session(db, session_token, response)
    return response