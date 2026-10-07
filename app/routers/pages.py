from fastapi import APIRouter, Request, Depends, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_auth
from app.services.dashboard import get_dashboard_data
from app.core.templates import templates
from app.models.user import User

router = APIRouter(tags=["pages"])

@router.get("/dashboard")
async def dashboard_page(
    request: Request, 
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)
        
    data = await get_dashboard_data(db, user)
    
    return templates.TemplateResponse(
        "dashboard.html", 
        {
            "request": request, 
            "user": user,
            **data
        }
    )