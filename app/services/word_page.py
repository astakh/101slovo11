# app/services/word_page.py
"""Сервис для функционала «Страница слова» (Word Pages)."""
import asyncio
import json
import logging
from datetime import datetime, timezone
from sqlalchemy import select, func, update, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.word import Word
from app.models.word_page import WordPage
from app.models.word_page_queue import WordPageQueue
from app.models.prompt import Prompt
from app.models.event import Event
from app.db import AsyncSessionLocal
from app.llm.gigachat import chat_json, GigaChatError
from app.llm.validation import WordPageContentResponse
from app.llm.llm_logger import log_llm_call

logger = logging.getLogger(__name__)

MAX_VALIDATION_RETRIES = 1
CATALOG_PER_PAGE = 20
SITE_BASE_URL = "https://101slovo.ru"

_sitemap_cache: str | None = None
_sitemap_cache_time: datetime | None = None
SITEMAP_CACHE_TTL_SECONDS = 3600


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def generate_slug(lemma: str, pos: str) -> str:
    normalized = lemma.lower().strip().replace(" ", "-")
    return f"{normalized}-{pos}"


async def _get_prompt_template(db: AsyncSession, key: str) -> str:
    stmt = select(Prompt).where(Prompt.key == key)
    result = await db.execute(stmt)
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise GigaChatError(f"Prompt '{key}' not found in DB", code="llm_config_error")
    return prompt.system_template


async def _log_llm_call_safe(
    *, purpose: str = "word_page", user_id: int | None = None,
    attempt: int = 1, request: dict | None = None,
    response_raw: str | None = None, response_json: dict | None = None,
    status: str = "ok", http_status: int | None = None,
    latency_ms: int | None = None, prompt_tokens: int | None = None,
    completion_tokens: int | None = None, error_code: str | None = None,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            await log_llm_call(
                session, purpose=purpose, user_id=user_id, attempt=attempt,
                request=request, response_raw=response_raw, response_json=response_json,
                status=status, http_status=http_status, latency_ms=latency_ms,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                error_code=error_code,
            )
            await session.commit()
    except Exception as e:
        logger.warning(f"[WORD PAGE LOG] Failed to log LLM call: {e}")


def _get_word_dictionary(word: Word) -> str:
    if word.in_it:
        return "it"
    if word.in_travel:
        return "travel"
    return "general"


def invalidate_sitemap_cache() -> None:
    global _sitemap_cache, _sitemap_cache_time
    _sitemap_cache = None
    _sitemap_cache_time = None
    logger.info("[WORD PAGE] Sitemap cache invalidated")


def _normalize_pos(pos: str) -> list[str]:
    """
    Нормализует POS. Обрабатывает составные значения:
    'noun/verb' → ['noun', 'verb']
    'verb' → ['verb']
    '' → []
    """
    if not pos or not pos.strip():
        return []
    parts = [p.strip().lower() for p in pos.replace("/", ",").replace("|", ",").split(",")]
    return [p for p in parts if p]


def _make_link_key(lemma: str, pos: str) -> str:
    """Ключ для словаря ссылок: 'lemma|pos' или 'lemma'."""
    lemma_l = lemma.strip().lower()
    pos_l = pos.strip().lower()
    if pos_l:
        return f"{lemma_l}|{pos_l}"
    return lemma_l


# ============================================================
# ГЕНЕРАЦИЯ КОНТЕНТА
# ============================================================

async def generate_word_page_content(
    db: AsyncSession, word: Word, admin_user_id: int,
) -> tuple[dict, int, int]:
    system_template = await _get_prompt_template(db, "word_page")
    dictionary = _get_word_dictionary(word)
    level = word.level or "A1"
    system_message = (
        system_template
        .replace("{word}", word.lemma)
        .replace("{pos}", word.pos)
        .replace("{dictionary}", dictionary)
        .replace("{level}", level)
    )
    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": f"Сгенерируй разбор слова: {word.lemma}"},
    ]

    response: WordPageContentResponse | None = None
    usage_data: tuple[int, int, int, int] | None = None
    final_attempt = 1

    for validation_attempt in range(MAX_VALIDATION_RETRIES + 1):
        final_attempt = validation_attempt + 1
        attempt_request_messages = list(messages)
        parsed, prompt_tokens, completion_tokens, total_tokens, latency_ms = await chat_json(
            messages, temperature=0.7, max_tokens=4096, deadline_seconds=60.0,
        )
        usage_data = (prompt_tokens, completion_tokens, total_tokens, latency_ms)

        try:
            response = WordPageContentResponse.model_validate(parsed)
        except Exception as e:
            error_msg = f"Pydantic validation failed: {e}"
            logger.error(f"[WORD PAGE] {error_msg}")
            await _log_llm_call_safe(
                purpose="word_page", user_id=admin_user_id, attempt=final_attempt,
                request={"messages": attempt_request_messages},
                response_json=parsed if isinstance(parsed, dict) else None,
                status="invalid_response", latency_ms=latency_ms,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                error_code="llm_invalid_response",
            )
            if validation_attempt < MAX_VALIDATION_RETRIES:
                messages = messages + [
                    {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)},
                    {"role": "user", "content": f"Ответ не прошёл проверку структуры: {error_msg}. Исправь и верни ТОЛЬКО валидный JSON."},
                ]
                continue
            raise GigaChatError(f"LLM response validation failed: {e}", code="llm_invalid_response")

        if response.word.lemma.lower().strip() != word.lemma.lower().strip():
            error_msg = f"Lemma mismatch: expected '{word.lemma}', got '{response.word.lemma}'"
            logger.error(f"[WORD PAGE] {error_msg}")
            await _log_llm_call_safe(
                purpose="word_page", user_id=admin_user_id, attempt=final_attempt,
                request={"messages": attempt_request_messages},
                response_json=parsed if isinstance(parsed, dict) else None,
                status="invalid_response", latency_ms=latency_ms,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                error_code="llm_lemma_mismatch",
            )
            if validation_attempt < MAX_VALIDATION_RETRIES:
                messages = messages + [
                    {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)},
                    {"role": "user", "content": f"Ошибка: {error_msg}. Используй ровно слово '{word.lemma}'. Верни ТОЛЬКО валидный JSON."},
                ]
                continue
            raise GigaChatError(f"LLM returned wrong lemma: {error_msg}", code="llm_invalid_response")

        if response.word.part_of_speech.lower().strip() != word.pos.lower().strip():
            error_msg = f"POS mismatch: expected '{word.pos}', got '{response.word.part_of_speech}'"
            logger.error(f"[WORD PAGE] {error_msg}")
            await _log_llm_call_safe(
                purpose="word_page", user_id=admin_user_id, attempt=final_attempt,
                request={"messages": attempt_request_messages},
                response_json=parsed if isinstance(parsed, dict) else None,
                status="invalid_response", latency_ms=latency_ms,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                error_code="llm_pos_mismatch",
            )
            if validation_attempt < MAX_VALIDATION_RETRIES:
                messages = messages + [
                    {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)},
                    {"role": "user", "content": f"Ошибка: {error_msg}. Часть речи должна быть '{word.pos}'. Верни ТОЛЬКО валидный JSON."},
                ]
                continue
            raise GigaChatError(f"LLM returned wrong POS: {error_msg}", code="llm_invalid_response")

        break

    if response is None:
        raise GigaChatError("Max validation retries exceeded", code="llm_invalid_response")

    await _log_llm_call_safe(
        purpose="word_page", user_id=admin_user_id, attempt=final_attempt,
        response_json=response.model_dump(), status="ok",
        latency_ms=usage_data[3], prompt_tokens=usage_data[0],
        completion_tokens=usage_data[1],
    )
    return response.model_dump(), usage_data[0], usage_data[1]


async def create_or_update_word_page(
    db: AsyncSession, word: Word, content: dict,
    prompt_tokens: int, completion_tokens: int,
) -> WordPage:
    slug = generate_slug(word.lemma, word.pos)
    now = datetime.now(timezone.utc)
    stmt = select(WordPage).where(WordPage.word_id == word.id)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        existing.content = content
        existing.slug = slug
        existing.generated_at = now
        existing.gen_prompt_tokens = prompt_tokens
        existing.gen_completion_tokens = completion_tokens
        await db.flush()
        await db.refresh(existing)
        logger.info(f"[WORD PAGE] Updated word_page id={existing.id}, slug={slug}, status={existing.status}")
        return existing
    else:
        page = WordPage(
            word_id=word.id, slug=slug, content=content, status="draft",
            generated_at=now, gen_prompt_tokens=prompt_tokens,
            gen_completion_tokens=completion_tokens,
        )
        db.add(page)
        await db.flush()
        await db.refresh(page)
        logger.info(f"[WORD PAGE] Created word_page id={page.id}, slug={slug}, status=draft")
        return page


# ============================================================
# ОЧЕРЕДЬ ГЕНЕРАЦИИ
# ============================================================

async def add_words_to_queue(db: AsyncSession, word_ids: list[int]) -> tuple[int, list[str]]:
    added = 0
    warnings: list[str] = []
    for word_id in word_ids:
        stmt = select(Word).where(Word.id == word_id)
        result = await db.execute(stmt)
        word = result.scalar_one_or_none()
        if not word:
            warnings.append(f"Слово с id={word_id} не найдено")
            continue
        stmt_queue = select(WordPageQueue).where(WordPageQueue.word_id == word_id)
        result_queue = await db.execute(stmt_queue)
        existing_queue = result_queue.scalar_one_or_none()
        if existing_queue:
            if existing_queue.status in ("queued", "processing"):
                warnings.append(f"'{word.lemma}' ({word.pos}) уже в очереди (статус: {existing_queue.status})")
                continue
            existing_queue.status = "queued"
            existing_queue.error_message = None
            existing_queue.attempt_count = 0
            existing_queue.processed_at = None
            added += 1
        else:
            queue_item = WordPageQueue(word_id=word_id, status="queued", attempt_count=0)
            db.add(queue_item)
            added += 1
        stmt_page = select(WordPage).where(WordPage.word_id == word_id)
        result_page = await db.execute(stmt_page)
        existing_page = result_page.scalar_one_or_none()
        if existing_page:
            warnings.append(f"⚠️ '{word.lemma}' ({word.pos}): страница уже существует, будет перегенерация")
    await db.flush()
    return added, warnings


async def get_queue_items(db: AsyncSession) -> list[dict]:
    stmt = (
        select(WordPageQueue, Word)
        .join(Word, WordPageQueue.word_id == Word.id)
        .order_by(WordPageQueue.created_at.desc())
    )
    result = await db.execute(stmt)
    return [{"queue_item": qi, "word": w} for qi, w in result.all()]


async def delete_queue_item(db: AsyncSession, queue_id: int) -> bool:
    stmt = select(WordPageQueue).where(WordPageQueue.id == queue_id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if not item or item.status not in ("queued", "error"):
        return False
    await db.delete(item)
    await db.flush()
    return True


async def search_words_for_admin(db: AsyncSession, query: str, limit: int = 20) -> list[Word]:
    if not query.strip():
        return []
    like_pattern = f"%{query.strip().lower()}%"
    stmt = (
        select(Word)
        .where(func.lower(Word.lemma).like(like_pattern))
        .order_by(Word.lemma.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ============================================================
# БАТЧ-ГЕНЕРАЦИЯ
# ============================================================

async def process_queue_batch(db: AsyncSession, admin_user_id: int) -> dict:
    stmt = (
        select(WordPageQueue)
        .where(WordPageQueue.status == "queued")
        .order_by(WordPageQueue.id.asc())
    )
    result = await db.execute(stmt)
    queue_items = list(result.scalars().all())
    if not queue_items:
        return {"generated": 0, "errors": 0, "total": 0}

    generated = 0
    errors = 0
    for queue_item in queue_items:
        queue_item.status = "processing"
        await db.flush()
        try:
            stmt_word = select(Word).where(Word.id == queue_item.word_id)
            result_word = await db.execute(stmt_word)
            word = result_word.scalar_one_or_none()
            if not word:
                raise ValueError(f"Word with id={queue_item.word_id} not found")
            content, pt, ct = await generate_word_page_content(db, word, admin_user_id)
            await create_or_update_word_page(db, word, content, pt, ct)
            queue_item.status = "done"
            queue_item.processed_at = datetime.now(timezone.utc)
            queue_item.error_message = None
            generated += 1
        except Exception as e:
            logger.error(f"[WORD PAGE] Error generating word_page for word_id={queue_item.word_id}: {e}")
            queue_item.status = "error"
            queue_item.error_message = str(e)[:1000]
            queue_item.attempt_count += 1
            queue_item.processed_at = datetime.now(timezone.utc)
            errors += 1
        await db.flush()
        await asyncio.sleep(1)
    return {"generated": generated, "errors": errors, "total": len(queue_items)}


# ============================================================
# ПЕРЕГЕНЕРАЦИЯ
# ============================================================

async def regenerate_word_page(db: AsyncSession, word_page_id: int, admin_user_id: int) -> WordPage:
    stmt = select(WordPage).where(WordPage.id == word_page_id)
    result = await db.execute(stmt)
    page = result.scalar_one_or_none()
    if not page:
        raise ValueError("Страница слова не найдена")
    stmt_word = select(Word).where(Word.id == page.word_id)
    result_word = await db.execute(stmt_word)
    word = result_word.scalar_one_or_none()
    if not word:
        raise ValueError("Слово не найдено")
    content, pt, ct = await generate_word_page_content(db, word, admin_user_id)
    page.content = content
    page.generated_at = datetime.now(timezone.utc)
    page.gen_prompt_tokens = pt
    page.gen_completion_tokens = ct
    await db.flush()
    await db.refresh(page)
    logger.info(f"[WORD PAGE] Regenerated word_page id={page.id}, slug={page.slug}, status={page.status}")
    return page


# ============================================================
# ПУБЛИКАЦИЯ / АРХИВАЦИЯ
# ============================================================

async def publish_word_page(db: AsyncSession, word_page_id: int, admin_user_id: int) -> WordPage:
    stmt = select(WordPage).where(WordPage.id == word_page_id)
    result = await db.execute(stmt)
    page = result.scalar_one_or_none()
    if not page:
        raise ValueError("Страница слова не найдена")
    if page.status == "published":
        raise ValueError("Страница уже опубликована")
    page.status = "published"
    if not page.published_at:
        page.published_at = datetime.now(timezone.utc)
    event = Event(user_id=admin_user_id, type="word_page_published", payload={"word_page_id": page.id, "slug": page.slug})
    db.add(event)
    await db.flush()
    await db.refresh(page)
    invalidate_sitemap_cache()
    logger.info(f"[WORD PAGE] Published word_page id={page.id}, slug={page.slug}")
    return page


async def archive_word_page(db: AsyncSession, word_page_id: int, admin_user_id: int) -> WordPage:
    stmt = select(WordPage).where(WordPage.id == word_page_id)
    result = await db.execute(stmt)
    page = result.scalar_one_or_none()
    if not page:
        raise ValueError("Страница слова не найдена")
    page.status = "archived"
    event = Event(user_id=admin_user_id, type="word_page_archived", payload={"word_page_id": page.id, "slug": page.slug})
    db.add(event)
    await db.flush()
    await db.refresh(page)
    invalidate_sitemap_cache()
    logger.info(f"[WORD PAGE] Archived word_page id={page.id}, slug={page.slug}")
    return page


# ============================================================
# ПУБЛИЧНЫЕ СТРАНИЦЫ
# ============================================================

async def get_published_word_page(db: AsyncSession, slug: str, allow_draft: bool = False) -> WordPage | None:
    stmt = select(WordPage).where(WordPage.slug == slug)
    if not allow_draft:
        stmt = stmt.where(WordPage.status == "published")
    stmt = stmt.options(selectinload(WordPage.word))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def increment_view_count(db: AsyncSession, word_page_id: int) -> None:
    stmt = (
        update(WordPage)
        .where(WordPage.id == word_page_id)
        .values(view_count=WordPage.view_count + 1)
    )
    await db.execute(stmt)
    await db.flush()


# ============================================================
# ПЕРЕКРЁСТНЫЕ ССЫЛКИ (по lemma + pos)
# ============================================================

def _extract_all_word_refs(content: dict) -> list[tuple[str, str]]:
    """
    Извлекает все пары (lemma, pos) из контента страницы.
    Источники: synonyms, antonyms, level_b_trap, related_words.
    Возвращает список кортежей (lowercase_lemma, lowercase_pos).
    """
    refs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(lemma: str, pos: str):
        l = lemma.strip().lower()
        if not l:
            return
        # Нормализуем составной POS: берём первую часть
        pos_parts = _normalize_pos(pos)
        p = pos_parts[0] if pos_parts else ""
        key = (l, p)
        if key not in seen:
            seen.add(key)
            refs.append(key)

    # related_words — список объектов {lemma, pos} или строк (старый формат)
    for rw in content.get("related_words", []):
        if isinstance(rw, dict):
            _add(rw.get("lemma", ""), rw.get("pos", ""))
        elif isinstance(rw, str):
            _add(rw, "")

    # synonyms[].word
    for syn in content.get("synonyms", []):
        wd = syn.get("word", {})
        if isinstance(wd, dict):
            _add(wd.get("lemma", ""), wd.get("part_of_speech", ""))

    # antonyms[].word
    for ant in content.get("antonyms", []):
        wd = ant.get("word", {})
        if isinstance(wd, dict):
            _add(wd.get("lemma", ""), wd.get("part_of_speech", ""))

    # level_b_trap[].word
    for trap in content.get("level_b_trap", []):
        wd = trap.get("word", {})
        if isinstance(wd, dict):
            _add(wd.get("lemma", ""), wd.get("part_of_speech", ""))

    return refs


async def get_all_word_links(db: AsyncSession, content: dict) -> dict[str, str]:
    """
    Собирает ВСЕ перекрёстные ссылки из контента страницы.
    Поиск по lemma + pos (если POS указан).

    Возвращает словарь с двумя типами ключей:
    - "lemma|pos" → slug  (точное совпадение по лемме и POS)
    - "lemma"     → slug  (фолбэк: первое совпадение по лемме)

    В шаблоне сначала ищем по "lemma|pos", потом по "lemma".
    """
    refs = _extract_all_word_refs(content)
    if not refs:
        return {}

    # Собираем уникальные леммы для SQL-запроса
    lemmas = list({r[0] for r in refs})

    # Один SQL-запрос: ищем опубликованные страницы по всем леммам
    stmt = (
        select(WordPage, Word)
        .join(Word, WordPage.word_id == Word.id)
        .where(
            WordPage.status == "published",
            func.lower(Word.lemma).in_(lemmas),
        )
        .order_by(WordPage.published_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Строим индексы
    # lemma_lower → список (pos, slug) для фолбэка
    by_lemma: dict[str, list[tuple[str, str]]] = {}
    for page, word in rows:
        key = word.lemma.lower()
        if key not in by_lemma:
            by_lemma[key] = []
        by_lemma[key].append((word.pos.lower(), page.slug))

    # Строим результат
    links: dict[str, str] = {}
    for lemma_l, pos_l in refs:
        candidates = by_lemma.get(lemma_l, [])
        if not candidates:
            continue

        # Точное совпадение по lemma + pos
        if pos_l:
            for c_pos, c_slug in candidates:
                if c_pos == pos_l:
                    links[f"{lemma_l}|{pos_l}"] = c_slug
                    break

        # Фолбэк по лемме (первый найденный)
        if lemma_l not in links and candidates:
            links[lemma_l] = candidates[0][1]

    logger.debug(
        f"[WORD PAGE] get_all_word_links: "
        f"requested {len(refs)} refs, found {len(links)} links"
    )
    return links


def build_meta_tags(page: WordPage) -> dict:
    content = page.content or {}
    word_data = content.get("word", {})
    lemma = word_data.get("lemma", "")
    transcription = word_data.get("transcription", "")
    core_translation = content.get("core_translation", "")
    meta_title = page.meta_title
    if not meta_title:
        meta_title = f"{lemma} — {core_translation} | 101slovo"
    meta_title = meta_title[:200]
    meta_description = page.meta_description
    if not meta_description:
        meta_description = (
            f"{lemma} {transcription} — {core_translation}. "
            f"Примеры из IT, синонимы, устойчивые выражения "
            f"и ловушки для русскоговорящих."
        )
    meta_description = meta_description[:300]
    return {"title": meta_title, "description": meta_description}


async def get_word_pages_list(db: AsyncSession, status_filter: str | None = None) -> list[dict]:
    stmt = (
        select(WordPage, Word)
        .join(Word, WordPage.word_id == Word.id)
        .order_by(WordPage.created_at.desc())
    )
    if status_filter:
        stmt = stmt.where(WordPage.status == status_filter)
    result = await db.execute(stmt)
    return [{"page": p, "word": w} for p, w in result.all()]


# ============================================================
# КАТАЛОГ СЛОВ
# ============================================================

async def get_catalog(
    db: AsyncSession, dict_filter: str | None = None,
    level_filter: str | None = None, page: int = 1,
    per_page: int = CATALOG_PER_PAGE,
) -> dict:
    base_query = (
        select(WordPage, Word)
        .join(Word, WordPage.word_id == Word.id)
        .where(WordPage.status == "published")
    )
    if dict_filter == "general":
        base_query = base_query.where(Word.in_general == True)  # noqa: E712
    elif dict_filter == "it":
        base_query = base_query.where(Word.in_it == True)  # noqa: E712
    elif dict_filter == "travel":
        base_query = base_query.where(Word.in_travel == True)  # noqa: E712
    if level_filter:
        base_query = base_query.where(Word.level == level_filter)

    count_stmt = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_stmt)).scalar_one() or 0
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    stmt = (
        base_query
        .order_by(WordPage.published_at.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    )
    rows = (await db.execute(stmt)).all()
    items = []
    for wp, w in rows:
        content = wp.content or {}
        items.append({"page": wp, "word": w, "core_translation": content.get("core_translation", "")})
    return {
        "items": items, "page": page, "per_page": per_page,
        "total": total, "total_pages": total_pages,
        "dict_filter": dict_filter, "level_filter": level_filter,
    }


# ============================================================
# SITEMAP
# ============================================================

async def get_sitemap_xml(db: AsyncSession) -> str:
    global _sitemap_cache, _sitemap_cache_time
    now = datetime.now(timezone.utc)
    if _sitemap_cache is not None and _sitemap_cache_time is not None:
        elapsed = (now - _sitemap_cache_time).total_seconds()
        if elapsed < SITEMAP_CACHE_TTL_SECONDS:
            return _sitemap_cache

    stmt = (
        select(WordPage)
        .where(WordPage.status == "published")
        .order_by(WordPage.published_at.desc())
    )
    result = await db.execute(stmt)
    pages = list(result.scalars().all())

    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        "  <url>",
        f"    <loc>{SITE_BASE_URL}/</loc>",
        "    <priority>1.0</priority>",
        "  </url>",
        "  <url>",
        f"    <loc>{SITE_BASE_URL}/words</loc>",
        "    <priority>0.9</priority>",
        "    <changefreq>daily</changefreq>",
        "  </url>",
    ]
    for page in pages:
        xml_parts.append("  <url>")
        xml_parts.append(f"    <loc>{SITE_BASE_URL}/word/{page.slug}</loc>")
        if page.updated_at:
            xml_parts.append(f"    <lastmod>{page.updated_at.strftime('%Y-%m-%d')}</lastmod>")
        xml_parts.append("    <priority>0.8</priority>")
        xml_parts.append("    <changefreq>monthly</changefreq>")
        xml_parts.append("  </url>")
    xml_parts.append("</urlset>")
    sitemap_xml = "\n".join(xml_parts)
    _sitemap_cache = sitemap_xml
    _sitemap_cache_time = now
    logger.info(f"[WORD PAGE] Sitemap generated: {len(pages)} word pages")
    return sitemap_xml