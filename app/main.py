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