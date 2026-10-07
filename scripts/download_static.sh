#!/usr/bin/env bash
# scripts/download_static.sh
# Скачивает все внешние ресурсы в локальные директории для ускорения загрузки.

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATIC_DIR="$PROJECT_ROOT/app/static"
VENDOR_DIR="$STATIC_DIR/vendor"
FONTS_DIR="$STATIC_DIR/fonts"

echo "📁 Создание директорий..."
mkdir -p "$VENDOR_DIR" "$FONTS_DIR"

# Версии (фиксированные, чтобы не было сюрпризов при деплое)
HTMX_VERSION="2.0.4"
ALPINE_VERSION="3.14.1"
LUCIDE_VERSION="0.453.0"

echo "⬇️  Скачивание htmx ${HTMX_VERSION}..."
curl -fsSL "https://unpkg.com/htmx.org@${HTMX_VERSION}/dist/htmx.min.js" -o "$VENDOR_DIR/htmx.min.js"

echo "⬇️  Скачивание Alpine.js ${ALPINE_VERSION}..."
curl -fsSL "https://cdn.jsdelivr.net/npm/alpinejs@${ALPINE_VERSION}/dist/cdn.min.js" -o "$VENDOR_DIR/alpine.min.js"

echo "⬇️  Скачивание Lucide ${LUCIDE_VERSION}..."
curl -fsSL "https://unpkg.com/lucide@${LUCIDE_VERSION}/dist/umd/lucide.min.js" -o "$VENDOR_DIR/lucide.min.js"

echo "⬇️  Скачивание шрифта Inter (woff2)..."
# Inter v18 от Google Fonts (woff2, latin subset)
BASE="https://fonts.gstatic.com/s/inter/v18/UcCO3FwrK3iLTeHuS_nVMrMxCp50SjIw2boKoduKmME"

curl -fsSL "${BASE}VuLyfAZ9hiA.woff2" -o "$FONTS_DIR/inter-400.woff2"
curl -fsSL "${BASE}VuI6fAZ9hiA.woff2" -o "$FONTS_DIR/inter-500.woff2"
curl -fsSL "${BASE}VuGKYAZ9hiA.woff2" -o "$FONTS_DIR/inter-600.woff2"
curl -fsSL "${BASE}VuFuYAZ9hiA.woff2" -o "$FONTS_DIR/inter-700.woff2"
curl -fsSL "${BASE}VuD2YAZ9hiA.woff2" -o "$FONTS_DIR/inter-800.woff2"

echo ""
echo "✅ Готово! Файлы скачаны:"
echo "   $VENDOR_DIR/htmx.min.js    ($(wc -c < "$VENDOR_DIR/htmx.min.js") bytes)"
echo "   $VENDOR_DIR/alpine.min.js  ($(wc -c < "$VENDOR_DIR/alpine.min.js") bytes)"
echo "   $VENDOR_DIR/lucide.min.js  ($(wc -c < "$VENDOR_DIR/lucide.min.js") bytes)"
echo "   $FONTS_DIR/inter-*.woff2   (5 файлов)"
echo ""
echo "Не забудь закоммитить:"
echo "   git add app/static/vendor app/static/fonts"
echo "   git commit -m 'feat: localize static assets (htmx, alpine, lucide, inter font)'"