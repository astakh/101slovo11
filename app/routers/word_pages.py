# app/routers/word_pages.py
"""Публичные роуты для функционала «Страница слова» (Word Pages)."""
import hashlib
import logging
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.core.templates import templates
from app.services.word_page import (
    get_published_word_page,
    increment_view_count,
    get_all_word_links,
    build_meta_tags,
    get_catalog,
    get_sitemap_xml,
    SITE_BASE_URL,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["word_pages"])


@router.get("/word/{slug}")
async def word_page(
    request: Request,
    slug: str,
    preview: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
):
    allow_draft = preview and user is not None and user.is_admin

    page = await get_published_word_page(db, slug, allow_draft=allow_draft)
    if not page:
        raise HTTPException(status_code=404, detail="Страница не найдена")

    # ETag ДО инкремента просмотров
    etag_source = page.updated_at.isoformat() if page.updated_at else ""
    etag = hashlib.md5(etag_source.encode()).hexdigest()
    etag_quoted = f'"{etag}"'
    if_none_match = request.headers.get("if-none-match")
    if if_none_match == etag_quoted:
        return Response(status_code=304, headers={"ETag": etag_quoted})

    if not allow_draft:
        await increment_view_count(db, page.id)

    content = page.content or {}
    meta = build_meta_tags(page)

    # Единый запрос: все перекрёстные ссылки (синонимы, антонимы,
    # ловушки, related_words) — поиск по lemma + pos
    word_links = await get_all_word_links(db, content)

    canonical_url = f"{SITE_BASE_URL}/word/{page.slug}"
    word = page.word

    response = templates.TemplateResponse(
        "word_page/page.html",
        {
            "request": request,
            "page": page,
            "word": word,
            "content": content,
            "meta_title": meta["title"],
            "meta_description": meta["description"],
            "canonical_url": canonical_url,
            "word_links": word_links,
            "view_count": page.view_count,
        },
    )
    response.headers["Cache-Control"] = "public, max-age=2592000"
    response.headers["ETag"] = etag_quoted
    return response


@router.get("/words")
async def words_catalog(
    request: Request,
    dict: str | None = None,
    level: str | None = None,
    page: int = 1,
    db: AsyncSession = Depends(get_db),
):
    valid_dicts = {"general", "it", "travel"}
    valid_levels = {"A1", "A2", "B1", "B2", "C1", "C2"}
    dict_filter = dict if dict in valid_dicts else None
    level_filter = level if level in valid_levels else None
    page = max(1, page)
    catalog = await get_catalog(db, dict_filter=dict_filter, level_filter=level_filter, page=page)
    response = templates.TemplateResponse("word_page/catalog.html", {"request": request, **catalog})
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response


@router.get("/sitemap.xml")
async def sitemap(db: AsyncSession = Depends(get_db)):
    xml_content = await get_sitemap_xml(db)
    return Response(content=xml_content, media_type="application/xml", headers={"Cache-Control": "public, max-age=3600"})