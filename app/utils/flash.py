# app/utils/flash.py
from fastapi import Request, Response
from itsdangerous import URLSafeTimedSerializer, BadSignature
from app.config import settings

FLASH_COOKIE_NAME = "flash"

def get_serializer():
    return URLSafeTimedSerializer(settings.SESSION_SECRET)

def add_flash(response: Response, category: str, message: str):
    serializer = get_serializer()
    flashes = [{"category": category, "message": message}]
    signed = serializer.dumps(flashes)
    response.set_cookie(
        FLASH_COOKIE_NAME,
        signed,
        httponly=True,
        secure=settings.ENV == "production",
        samesite="lax",
        path="/",
        max_age=60
    )

def get_flashes(request: Request) -> list[dict]:
    signed = request.cookies.get(FLASH_COOKIE_NAME)
    if not signed:
        return []
    try:
        serializer = get_serializer()
        return serializer.loads(signed, max_age=60)
    except BadSignature:
        return []

def clear_flashes(response: Response):
    response.delete_cookie(FLASH_COOKIE_NAME, path="/")