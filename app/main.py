# app/main.py
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.routers import auth, onboarding, pages, lesson, settings, vocabulary, admin, billing
from app.middleware import AppMiddleware
from app.core.templates import templates
from app.db import AsyncSessionLocal
from app.services.background_tasks import run_periodic_tasks

logger = logging.getLogger(__name__)

# Интервал запуска фоновых задач (секунды)
BG_TASK_INTERVAL = 3600  # 1 час


async def _background_scheduler():
    """Фоновый планировщик периодических задач."""
    while True:
        await asyncio.sleep(BG_TASK_INTERVAL)
        try:
            async with AsyncSessionLocal() as db:
                await run_periodic_tasks(db)
                await db.commit()
        except Exception as e:
            logger.error(f"[BG SCHEDULER] Error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Запуск фонового планировщика
    bg_task = asyncio.create_task(_background_scheduler())
    logger.info(f"[LIFESPAN] Background scheduler started (interval={BG_TASK_INTERVAL}s)")
    yield
    # Остановка
    bg_task.cancel()
    try:
        await bg_task
    except asyncio.CancelledError:
        pass
    logger.info("[LIFESPAN] Background scheduler stopped")


app = FastAPI(title="101slovo", lifespan=lifespan)


# Middleware для защиты от ботов (HEAD/OPTIONS)
@app.middleware("http")
async def bot_protection_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers={
                "Allow": "GET, POST, HEAD, OPTIONS",
                "Cache-Control": "no-store",
            },
        )

    if request.method == "HEAD":
        if request.url.path == "/health":
            return await call_next(request)
        return Response(
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    return await call_next(request)


# Статика
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Middleware
app.add_middleware(AppMiddleware)

# Роутеры
app.include_router(auth.router)
app.include_router(onboarding.router)
app.include_router(pages.router)
app.include_router(lesson.router)
app.include_router(settings.router)
app.include_router(vocabulary.router)
app.include_router(admin.router)
app.include_router(billing.router)


# Обработчик ошибок
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if request.headers.get("HX-Request") and exc.headers and "HX-Redirect" in exc.headers:
        return Response(status_code=200, headers=exc.headers)

    if exc.status_code == 404:
        return templates.TemplateResponse("errors/404.html", {"request": request}, status_code=404)
    if exc.status_code in [401, 403]:
        return templates.TemplateResponse("errors/403.html", {"request": request}, status_code=exc.status_code)
    if exc.status_code == 503:
        return templates.TemplateResponse("errors/503.html", {"request": request}, status_code=503)

    return templates.TemplateResponse("errors/500.html", {"request": request}, status_code=500)


@app.get("/")
async def root(request: Request):
    if request.state.user:
        return Response(status_code=303, headers={"Location": "/dashboard"})
    return templates.TemplateResponse("landing.html", {"request": request})


@app.get("/health")
async def health():
    return {"status": "ok"}