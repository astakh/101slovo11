# Сводка по деплою проекта 101slovo

> **Последнее обновление:** 2026-10-08
> **Версия конфига:** 2.0 (локализация статики, фикс ботов, оптимизация Nginx)

---

## 1. Общая информация

| Параметр | Значение |
|----------|----------|
| Проект | 101slovo — веб-приложение для изучения английских слов в контексте через LLM (GigaChat) |
| Домен | `101slovo.ru` + `www.101slovo.ru` |
| Стек | FastAPI + SQLAlchemy (async) + Alembic + Jinja2 + HTMX + Alpine.js + Nginx |
| ОС сервера | Ubuntu 24.04 LTS |
| Деплой | От `root`, без SSH-ключей, репозиторий в `/opt/101slovo` |
| Сертификат | Let's Encrypt через Certbot (`--nginx`), автообновление через `certbot.timer` |

---

## 2. Сервер

| Параметр | Значение |
|----------|----------|
| IP сервера | не зафиксирован (используется DNS `101slovo.ru`) |
| SSH-доступ | root по паролю, порт 22 (без смены) |
| Часовой пояс | `Europe/Moscow` |
| Локаль | `en_US.UTF-8`, `ru_RU.UTF-8` |
| Swap | 2 GB (если RAM < 2 GB) |
| Хостер | не указан |

---

## 3. Файрвол и защита

| Компонент | Настройка |
|-----------|-----------|
| ufw | `OpenSSH` (22/tcp) + `Nginx Full` (80,443/tcp) |
| fail2ban | активен, jail `sshd`: `maxretry=5`, `bantime=3600s` |
| PostgreSQL | слушает `0.0.0.0:5432` (открыт наружу) |
| pg_hba.conf | `scram-sha-256` для внешних подключений |
| HSTS | **не включён** |
| OCSP Stapling | **не включён** |
| HTTP → HTTPS | редирект включён (Certbot `--redirect`) |

> ⚠️ PostgreSQL открыт наружу. Рекомендуется ограничить `pg_hba.conf` конкретными IP или добавить fail2ban jail для PostgreSQL.

---

## 4. PostgreSQL 18

| Параметр | Значение |
|----------|----------|
| Версия | 18.6 (PGDG) |
| Порт | 5432 |
| Слушает | `0.0.0.0` + `[::]` |
| БД | `101slovo` |
| Пользователь | `slovo` |
| Аутентификация | `scram-sha-256` |
| Кодировка | UTF8, `en_US.UTF-8` |
| Схема `public` | владелец — `slovo` |
| Миграции | Alembic: `e415bc2a09fb` → `4ff3f0ad8020` |
| Промпты | загружены через `scripts/seed.py` (2 шт.) |
| Слова | загружены через `scripts/import_words.py` (`words1.json`, `words2.json`) |
| Бэкапы | **не настроены** (cron + pg_dump) |

---

## 5. Приложение

| Параметр | Значение |
|----------|----------|
| Путь | `/opt/101slovo` |
| Владелец | `root:root` |
| venv | `/opt/101slovo/.venv` (Python 3.12.3) |
| Зависимости | `requirements.txt` + `gunicorn==23.0.0` |
| `.env` | `/opt/101slovo/.env`, права `600`, владелец `root` |
| Режим | `ENV=production` |
| `DATABASE_URL` | `postgresql+asyncpg://slovo:***@127.0.0.1:5432/101slovo` |
| `SESSION_SECRET` | сгенерирован через `secrets.token_urlsafe(48)` |
| `GIGACHAT_VERIFY_SSL` | `True` (при проблемах — `False`) |
| Порт приложения | `127.0.0.1:8000` |
| Репозиторий | GitHub, `git clone` в `/opt/101slovo` |
| Способ обновления | **не автоматизирован** (`git pull` вручную) |
| Защита от ботов | ✅ `bot_protection_middleware` (HEAD → 200, OPTIONS → 204) |

---

## 6. Gunicorn + systemd

| Параметр | Значение |
|----------|----------|
| Unit-файл | `/etc/systemd/system/101slovo.service` |
| User / Group | `root:root` |
| WorkingDirectory | `/opt/101slovo` |
| EnvironmentFile | `/opt/101slovo/.env` |
| ExecStart | `gunicorn app.main:app` |
| Worker class | `uvicorn.workers.UvicornWorker` |
| Workers | `2` |
| Bind | `127.0.0.1:8000` |
| Timeout | `90s` (graceful `30s`) |
| `--forwarded-allow-ips` | `127.0.0.1` |
| `--preload` | ✅ **включён** (общая память, экономия ~50–100 МБ) |
| Restart | `on-failure`, `RestartSec=5` |
| Автозапуск | `systemctl enable 101slovo` |
| Логи | journald (`journalctl -u 101slovo`) |

---

## 7. Nginx

| Параметр | Значение |
|----------|----------|
| Конфиг | `/etc/nginx/sites-available/101slovo` |
| Симлинк | `/etc/nginx/sites-enabled/101slovo` |
| Дефолтный сайт | удалён |
| `server_name` | `101slovo.ru www.101slovo.ru` |
| Порт 80 | редирект на HTTPS |
| Порт 443 | HTTPS, SSL от Let's Encrypt |
| HTTP/2 | ✅ **включён** (`listen 443 ssl http2`) |
| Upstream | `keepalive 32`, `proxy_http_version 1.1`, `Connection ""` |
| Статика | `/static/` → `alias /opt/101slovo/app/static/` |
| Кэш статики | `expires 30d`, `Cache-Control: public, immutable`, `access_log off` |
| `client_max_body_size` | `5M` |
| Проксирование | `proxy_pass http://app_server` (upstream) |
| Заголовки | `Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host` |
| Таймауты | `connect 15s`, `read 120s`, `send 120s` |
| gzip | ✅ **включён** (уровень 5, все текстовые типы + SVG) |
| Буферизация | `proxy_buffering on`, `proxy_buffers 8 4k` |
| Логи | `/var/log/nginx/101slovo.access.log`, `.error.log` |

---

## 8. TLS / HTTPS

| Параметр | Значение |
|----------|----------|
| Провайдер | Let's Encrypt |
| Certbot | `certbot --nginx -d 101slovo.ru -d www.101slovo.ru --redirect` |
| Email | `astavimana@yandex.ru` |
| Сертификат | `/etc/letsencrypt/live/101slovo.ru/fullchain.pem` |
| Ключ | `/etc/letsencrypt/live/101slovo.ru/privkey.pem` |
| Срок действия | ~90 дней |
| Автообновление | `certbot.timer` (2 раза в день), dry-run успешен |
| TLS-протоколы | TLS 1.2 + 1.3 (Certbot defaults) |
| HSTS | **не включён** |
| OCSP Stapling | **не включён** |

---

## 9. DNS

| Запись | Значение |
|--------|----------|
| A `101slovo.ru` | IP сервера |
| A `www.101slovo.ru` | IP сервера |
| AAAA (IPv6) | **не настроена** |

---

## 10. Статика и клиентские ресурсы

| Ресурс | Путь | Источник |
|--------|------|----------|
| htmx 2.0.4 | `/static/vendor/htmx.min.js` | unpkg.com |
| Alpine.js 3.14.1 | `/static/vendor/alpine.min.js` | cdn.jsdelivr.net |
| Lucide 0.453.0 | `/static/vendor/lucide.min.js` | unpkg.com |
| Inter 400 | `/static/fonts/inter-400.woff2` | Google Fonts |
| Inter 500 | `/static/fonts/inter-500.woff2` | Google Fonts |
| Inter 600 | `/static/fonts/inter-600.woff2` | Google Fonts |
| Inter 700 | `/static/fonts/inter-700.woff2` | Google Fonts |
| Inter 800 | `/static/fonts/inter-800.woff2` | Google Fonts |
| custom.css | `/static/css/custom.css` | локальный |
| water.css | **удалён** (заменён на `custom.css`) | — |

Все ресурсы локальные. Внешние CDN-запросы **полностью исключены**.

Скрипт обновления статики: `scripts/download_static.sh`

---

## 11. Ресурсы и производительность

| Метрика | Значение |
|---------|----------|
| `/health` (напрямую) | `0.013s` |
| `/` (напрямую) | `0.010s` |
| `/static/css/custom.css` (напрямую) | `0.022s` |
| `/health` (через HTTPS) | `0.055s` |
| `/` (через HTTPS) | `0.021s` |
| Внешние CDN | ✅ **устранены** |
| Ожидаемое время загрузки | ~300–500 мс (было ~1.5 с) |

---

## 12. Безопасность — что сделано и что нет

### Сделано
- ✅ ufw (только 22, 80, 443)
- ✅ fail2ban для SSH
- ✅ HTTPS с Let's Encrypt + редирект
- ✅ CSRF-токены в приложении
- ✅ Сессии в HttpOnly cookie
- ✅ `SESSION_SECRET` сгенерирован
- ✅ `.env` с правами `600`
- ✅ pg_hba `scram-sha-256`
- ✅ Автообновление сертификата
- ✅ **Защита от ботов** (HEAD → 200, OPTIONS → 204, без нагрузки на БД)
- ✅ **Локальная статика** (нет зависимостей от третьих сторон)

### Не сделано / отложено
- ❌ HSTS
- ❌ OCSP Stapling
- ❌ Ограничение PostgreSQL по IP (открыт `0.0.0.0/0`)
- ❌ fail2ban для PostgreSQL
- ❌ Смена SSH-порта
- ❌ SSH по ключам (только пароль)
- ❌ Бэкапы PostgreSQL
- ❌ Мониторинг / алерты
- ❌ Ротация логов Nginx (logrotate из коробки — надо проверить)

---

## 13. Что нужно доделать (приоритеты)

### Высокий приоритет
1. **Бэкапы PostgreSQL** — cron + `pg_dump`, ротация 14 дней.
2. **Ограничить PostgreSQL по IP** в `pg_hba.conf` (если не нужен доступ отовсюду).
3. **Первый админ** — `UPDATE users SET is_admin = true WHERE email = '...'`.
4. **Проверка LLM** — тестовый урок, разбор ошибок GigaChat.

### Средний приоритет
5. **Скрипт обновления** `deploy.sh` — `git pull` + миграции + рестарт.
6. **fail2ban для PostgreSQL** — защита от брутфорса БД.
7. **Проверка шрифта 800** — убедиться, что `inter-800.woff2` скачался (была 404).

### Низкий приоритет
8. HSTS (когда убедитесь в стабильности HTTPS).
9. OCSP Stapling.
10. Мониторинг (UptimeRobot, healthcheck).
11. Смена SSH-порта + ключи.
12. Cloudflare (бесплатный CDN, защита от DDoS, HTTP/3).

---

## 14. Ключевые пути
/opt/101slovo/ — корень проекта
/opt/101slovo/.env — переменные окружения (600)
/opt/101slovo/.venv/ — виртуальное окружение
/opt/101slovo/app/ — код приложения
/opt/101slovo/app/static/ — статика
/opt/101slovo/app/static/vendor/ — JS-библиотеки (локальные)
/opt/101slovo/app/static/fonts/ — шрифты (локальные)
/opt/101slovo/app/static/css/custom.css — основной CSS
/opt/101slovo/migrations/ — Alembic-миграции
/opt/101slovo/scripts/ — seed, import_words, download_static
/opt/101slovo/scripts/download_static.sh — скрипт обновления статики
/opt/101slovo/docs/DEPLOYMENT.md — этот файл
/etc/systemd/system/101slovo.service — systemd unit
/etc/nginx/sites-available/101slovo — конфиг Nginx
/etc/nginx/sites-enabled/101slovo — симлинк
/etc/letsencrypt/live/101slovo.ru/ — сертификаты
/etc/postgresql/18/main/postgresql.conf — конфиг PG
/etc/postgresql/18/main/pg_hba.conf — доступ PG
/var/log/nginx/101slovo.access.log — access-лог
/var/log/nginx/101slovo.error.log — error-лог
/var/log/postgresql/postgresql-18-main.log — лог PG


---

## 15. Ключевые команды обслуживания

```bash
# Статус всех сервисов
systemctl status 101slovo nginx postgresql --no-pager

# Логи приложения
journalctl -u 101slovo -f
journalctl -u 101slovo -n 100 --no-pager

# Логи Nginx
tail -f /var/log/nginx/101slovo.error.log
tail -f /var/log/nginx/101slovo.access.log

# Логи PostgreSQL
tail -f /var/log/postgresql/postgresql-18-main.log

# Перезапуск приложения
systemctl restart 101slovo

# Перезагрузка Nginx (без разрыва соединений)
systemctl reload nginx

# Проверка конфига Nginx
nginx -t

# Обновление кода
cd /opt/101slovo && git pull
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
systemctl restart 101slovo

# Обновление статики (если нужны новые версии библиотек)
cd /opt/101slovo && ./scripts/download_static.sh

# Проверка сертификата
certbot certificates
certbot renew --dry-run

# Подключение к БД
PGPASSWORD='***' psql -h 127.0.0.1 -U slovo -d 101slovo

# Сделать пользователя админом
PGPASSWORD='***' psql -h 127.0.0.1 -U slovo -d 101slovo -c \
  "UPDATE users SET is_admin = true WHERE email = 'ваш@email.com';"

# Health
curl -s https://101slovo.ru/health

# Проверка статики
curl -sI https://101slovo.ru/static/vendor/htmx.min.js | head -5
curl -sI https://101slovo.ru/static/fonts/inter-400.woff2 | head -5

# Проверка HEAD/OPTIONS (должно быть 200/204)
curl -sI -X HEAD https://101slovo.ru/ | head -3
curl -s -X OPTIONS -o /dev/null -w "%{http_code}" https://101slovo.ru/

16. Известные проблемы
Проблема
Статус
Решение
Медленная загрузка в браузере
✅ решена
Локальный хостинг всех ресурсов
HEAD / → 500, OPTIONS / → 500
✅ решено
bot_protection_middleware
inter-800.woff2 → 404
🟡 проверить
Докачать через scripts/download_static.sh или удалить вес 800
GigaChat URL api.giga.chat — не официальный Сбер
⚠️ под вопросом
Проверить на тестовом уроке
GIGACHAT_VERIFY_SSL=True может падать
⚠️ под вопросом
При SSLError — временно False
Бэкапы не настроены
🔴 открыта
Cron + pg_dump
PostgreSQL открыт наружу
🟡 риск
Ограничить pg_hba.conf по IP
17. Итоговая оценка
Аспект
Оценка
Функциональность
✅ работает
HTTPS
✅ настроен, автообновление
Производительность бэкенда
✅ отличная (10–55 мс)
Производительность клиента
✅ отличная (локальная статика)
Безопасность
🟡 базовая (нет HSTS, PG открыт)
Надёжность
🟡 нет бэкапов
Мониторинг
🔴 отсутствует
Автоматизация деплоя
🔴 ручная
Готовность к продакшену: ~85%. Критичные пробелы — бэкапы, ограничение PostgreSQL по IP, проверка шрифта 800. Остальное — «nice to have».
18. История изменений
Дата
Что сделано
2026-10-07
Первичный деплой, миграции, seed, импорт слов
2026-10-08
Фикс ботов: bot_protection_middleware (HEAD → 200, OPTIONS → 204)
2026-10-08
Локализация статики: все CDN-ресурсы скачаны локально
2026-10-08
Удалён water.css: полностью заменён на custom.css
2026-10-08
Добавлены @font-face для Inter (400–800) в custom.css
2026-10-08
Nginx: HTTP/2, gzip, upstream keepalive, Connection ""
2026-10-08
Gunicorn: добавлен --preload
2026-10-08
Создан scripts/download_static.sh для обновления статики
2026-10-08
Создан docs/DEPLOY.md (этот файл)


---

## Итого: что изменилось по сравнению с версией 1.0

| Было (1.0) | Стало (2.0) |
|-------------|-------------|
| ❌ `HEAD /` → 500 | ✅ → 200 (middleware) |
| ❌ `OPTIONS /` → 500 | ✅ → 204 (middleware) |
| ❌ 5 внешних CDN-запросов | ✅ 0 внешних запросов |
| ❌ `water.css` из интернета | ✅ удалён, всё в `custom.css` |
| ❌ Google Fonts из интернета | ✅ локальные `@font-face` |
| ❌ HTTP/1.1 | ✅ HTTP/2 |
| ❌ gzip выключен | ✅ включён |
| ❌ без `--preload` | ✅ с `--preload` |
| ❌ без upstream keepalive | ✅ `keepalive 32` |
| Готовность ~75% | Готовность ~85% |

После сохранения файла не забудьте закоммитить:
```bash
git add docs/DEPLOYMENT.md
git commit -m "docs: обновлена сводка деплоя до версии 2.0"
git push