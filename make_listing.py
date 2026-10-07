#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт составляет листинг проекта.

Настройки находятся в блоке CONFIG ниже.
Результат сохраняется в текстовый файл заданного формата.
"""

import os
import fnmatch
import sys

# ============================ НАСТРОЙКИ ============================

# Папка, в которой ищем файлы (рекурсивно)
ROOT_DIR = "d:/101slovo11" 

# Имя выходного файла (сохраняется в текущей рабочей папке)
OUTPUT_FILE = "project_listing.txt"

# Маски игнорируемых ПАПОК (glob-шаблоны по имени папки)
IGNORE_DIR_PATTERNS = [
    ".git",
    ".svn",
    ".hg",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "env",
    ".env",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    "*.egg-info",
    "data"
]

# Маски игнорируемых ФАЙЛОВ (glob-шаблоны по имени файла)
IGNORE_FILE_PATTERNS = [
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.so",
    "*.dll",
    "*.exe",
    "*.o",
    "*.a",
    "*.log",
    "*.tmp",
    "*.swp",
    "*.bak",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.7z",
    "*.rar",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.bmp",
    "*.ico",
    "*.svg",
    "*.pdf",
    "*.mp3",
    "*.mp4",
    "*.avi",
    "*.mov",
    "Thumbs.db",
    ".DS_Store",
    OUTPUT_FILE,   # не включать сам файл листинга
    "*.md",        # игнорировать markdown-файлы
]

# Конкретные игнорируемые ПАПКИ (точные имена, сравниваются с именем папки)
IGNORE_DIRS_EXACT = [
    # "some_dir",
    # "temp",
]

# Конкретные игнорируемые ФАЙЛЫ (точные имена, сравниваются с именем файла)
IGNORE_FILES_EXACT = [
    "project_listing.txt",
    "make_listing.py",
    ".gitignore",
    ".env",
]

# Кодировка при чтении файлов (utf-8, cp1251, latin-1 и т.п.)
FILE_ENCODING = "utf-8"

# Если файл не удалось прочитать в FILE_ENCODING — пробовать latin-1?
FALLBACK_ENCODING = "latin-1"

# ===================================================================


def is_ignored_dir(name: str) -> bool:
    if name in IGNORE_DIRS_EXACT:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in IGNORE_DIR_PATTERNS)


def is_ignored_file(name: str) -> bool:
    if name in IGNORE_FILES_EXACT:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in IGNORE_FILE_PATTERNS)


def read_file(path: str) -> str:
    for enc in (FILE_ENCODING, FALLBACK_ENCODING):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
        except OSError as e:
            return f"<<Ошибка чтения файла: {e}>>"
    # Последняя попытка: бинарное чтение с заменой
    try:
        with open(path, "rb") as f:
            return f.read().decode(FILE_ENCODING, errors="replace")
    except OSError as e:
        return f"<<Ошибка чтения файла: {e}>>"


def collect_files(root: str):
    """Обходит дерево и возвращает отсортированный список относительных путей."""
    result = []
    for dirpath, dirnames, filenames in os.walk(root):
        # фильтруем папки на месте (in-place), чтобы os.walk их не заходил
        dirnames[:] = sorted(d for d in dirnames if not is_ignored_dir(d))

        for fname in sorted(filenames):
            if is_ignored_file(fname):
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root)
            result.append(rel.replace(os.sep, "/"))
    result.sort()
    return result


def make_listing(root: str, out_path: str) -> None:
    if not os.path.isdir(root):
        print(f"Ошибка: папка не найдена: {root}", file=sys.stderr)
        sys.exit(1)

    files = collect_files(root)
    print(f"Найдено файлов: {len(files)}")

    with open(out_path, "w", encoding="utf-8") as out:
        for rel in files:
            full = os.path.join(root, rel)
            out.write(f"### {rel} ########################################################################\n")
            out.write(read_file(full))
            if not read_file(full).endswith("\n"):
                out.write("\n")
            out.write(f"### end of {rel} ########################################################################\n\n")

    print(f"Листинг сохранён в: {os.path.abspath(out_path)}")


if __name__ == "__main__":
    # Аргументы командной строки (необязательно) перекрывают настройки:
    #   python listing.py [ROOT_DIR] [OUTPUT_FILE]
    root = sys.argv[1] if len(sys.argv) > 1 else ROOT_DIR
    output = sys.argv[2] if len(sys.argv) > 2 else OUTPUT_FILE
    make_listing(root, output)