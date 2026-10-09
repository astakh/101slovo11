// app/static/js/app.js

/**
 * Генерация UUID с фолбэком для старых браузеров.
 * Использует нативный crypto.randomUUID() если доступен,
 * иначе — ручная генерация.
 * @returns {string} UUID
 */
function generateUUID() {
    if (window.crypto && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }
    // Фолбэк: ручная генерация (для старых браузеров или небезопасного контекста)
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = Math.random() * 16 | 0;
        var v = (c === 'x') ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

/**
 * Копирование текста в буфер обмена с фолбэком.
 * Использует нативный navigator.clipboard.writeText() если доступен,
 * иначе — document.execCommand('copy') через временный textarea.
 * @param {string} text - текст для копирования
 * @returns {Promise<boolean>} - true если копирование удалось
 */
async function copyToClipboard(text) {
    // Попытка 1: нативный Clipboard API (требует secure context)
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (e) {
            // Нативный метод не сработал (например, не в secure context
            // или пользователь не дал разрешение). Переходим к фолбэку.
            console.warn('[copyToClipboard] Native clipboard failed, falling back:', e);
        }
    }

    // Попытка 2: фолбэк через временный textarea и execCommand
    try {
        var textarea = document.createElement('textarea');
        textarea.value = text;
        // Размещаем элемент вне видимой области
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        textarea.style.top = '-9999px';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        textarea.setSelectionRange(0, text.length); // для мобильных устройств
        var success = document.execCommand('copy');
        document.body.removeChild(textarea);
        return success;
    } catch (e) {
        console.error('[copyToClipboard] Fallback failed:', e);
        return false;
    }
}