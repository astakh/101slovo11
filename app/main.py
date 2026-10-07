# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.routers import auth, onboarding, pages, lesson, settings, vocabulary, admin
from app.middleware import AppMiddleware
from app.core.templates import templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="101slovo", lifespan=lifespan)


# Middleware для защиты от ботов (HEAD/OPTIONS)
# ВАЖНО: добавляем ПОСЛЕ AppMiddleware, чтобы он выполнялся ПЕРВЫМ
@app.middleware("http")
async def bot_protection_middleware(request: Request, call_next):
    """
    Быстро отвечает на HEAD и OPTIONS запросы, не нагружая бэкенд.
    Боты (Ahrefs, Semrush, сканеры) постоянно долбят эти методы.
    """
    if request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers={
                "Allow": "GET, POST, HEAD, OPTIONS",
                "Cache-Control": "no-store",
            },
        )
    if request.method == "HEAD":
        # Для HEAD возвращаем 200 с пустым телом, не выполняя роуты.
        # Исключение: /health — пусть FastAPI обработает сам (нужно для мониторинга).
        if request.url.path == "/health":
            return await call_next(request)
        return Response(
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )
    return await call_next(request)


# Статика
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Middleware (выполняется ВТОРЫМ, после bot_protection)
app.add_middleware(AppMiddleware)

# Роутеры
app.include_router(auth.router)
app.include_router(onboarding.router)
app.include_router(pages.router)
app.include_router(lesson.router)
app.include_router(settings.router)
app.include_router(vocabulary.router)
app.include_router(admin.router)


# Обработчик ошибок (включая HTMX редиректы)
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
    """
    Главная страница:
    - Для авторизованных пользователей — редирект на /dashboard
    - Для неавторизованных — красивая landing-страница
    """
    if request.state.user:
        return Response(status_code=303, headers={"Location": "/dashboard"})
    return templates.TemplateResponse("landing.html", {"request": request})


@app.get("/health")
async def health():
    return {"status": "ok"}