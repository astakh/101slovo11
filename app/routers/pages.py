from fastapi import APIRouter, Request, Depends, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.deps import require_auth
from app.services.dashboard import get_dashboard_data
from app.services.paywall import get_paywall_context
from app.services.subscription import get_subscription_status
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
    paywall = await get_paywall_context(db, user)
    subscription = await get_subscription_status(db, user.id)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "paywall": paywall,
            "subscription": subscription,
            **data,
        }
    )