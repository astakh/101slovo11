#!/usr/bin/env python3
"""
Тест качества GigaChat для 5 языковых пар.
Проверяет генерацию предложений и оценку переводов.

Запуск:
    python scripts/test_gigachat_multilang.py
"""

import asyncio
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.llm.gigachat import chat_json

TEST_LANGUAGES = [
    ("ru", "Русский", "Russian"),
    ("uk", "Українська", "Ukrainian"),
    ("de", "Deutsch", "German"),
    ("es", "Español", "Spanish"),
    ("pt", "Português", "Portuguese"),
]

USER_TRANSLATIONS = {
    "ru": {
        "correct": "Я бегаю каждый день в парке.",
        "typo": "Я бегаю каджый день в парке.",
        "incorrect": "Я читаю книгу.",
    },
    "uk": {
        "correct": "Я бігаю щодня в парку.",
        "typo": "Я бігаю щоденно в парку.",
        "incorrect": "Я читаю книгу.",
    },
    "de": {
        "correct": "Ich laufe jeden Tag im Park.",
        "typo": "Ich laufe jeden Tag im Parck.",
        "incorrect": "Ich lese ein Buch.",
    },
    "es": {
        "correct": "Corro todos los días en el parque.",
        "typo": "Corro todos los dias en el parque.",
        "incorrect": "Leo un libro.",
    },
    "pt": {
        "correct": "Eu corro todos os dias no parque.",
        "typo": "Eu corro todos os dia no parque.",
        "incorrect": "Eu leio um livro.",
    },
}


async def test_generation(lang_code, lang_name_ru, lang_name_en):
    print(f"\n{'='*60}")
    print(f"🧪 ТЕСТ ГЕНЕРАЦИИ: {lang_name_ru} ({lang_code})")
    print(f"{'='*60}\n")
    
    system_prompt = f"""Ты — эксперт-лингвист. Генерируй короткие предложения на английском (A1).

ТРЕБОВАНИЯ:
1. Используй ТОЛЬКО переданные слова.
2. 3-15 слов в предложении.
3. НЕ используй кириллицу в английском предложении.
4. Перевод на {lang_name_en} должен быть точным.
5. Только JSON.

ФОРМАТ:
{{
  "exercises": [
    {{
      "target_sentence": "English sentence.",
      "reference_translation": "{lang_name_ru} translation.",
      "target_words": [{{"lemma": "word", "surface_form": "words", "pos": "noun"}}]
    }}
  ]
}}"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Сгенерируй предложение со словом: run (verb)"},
    ]
    
    try:
        parsed, pt, ct, tt, lat = await chat_json(messages, temperature=0.7, max_tokens=2048, deadline_seconds=30.0)
        
        if parsed and "exercises" in parsed:
            ex = parsed["exercises"][0]
            print(f"✅ Английское: {ex.get('target_sentence', 'N/A')}")
            print(f"✅ Перевод: {ex.get('reference_translation', 'N/A')}")
            print(f"📊 Токены: {pt}+{ct}={tt}, latency={lat}ms\n")
            return ex.get('target_sentence', 'I run every day in the park.')
        return "I run every day in the park."
    except Exception as e:
        print(f"❌ Ошибка: {e}\n")
        return "I run every day in the park."


async def test_evaluation(lang_code, lang_name_ru, lang_name_en, target_sentence):
    print(f"\n{'='*60}")
    print(f"🧪 ТЕСТ ОЦЕНКИ: {lang_name_ru} ({lang_code})")
    print(f"{'='*60}\n")
    
    system_prompt = f"""Ты — экзаменатор. Оцени перевод на {lang_name_en}.

ВХОД:
- Англ: {target_sentence}
- Эталон ({lang_name_ru}): {USER_TRANSLATIONS[lang_code]['correct']}
- Целевые слова: [{{"lemma": "run", "pos": "verb"}}]

ЗАДАЧА:
1. Статус: "correct", "typo", "incorrect".
2. Для каждого слова: "mastered", "learning", "failed".
3. Комментарий на {lang_name_ru}.

ФОРМАТ (JSON):
{{
  "status": "correct|typo|incorrect",
  "feedback": "Комментарий",
  "evaluations": [{{"lemma": "run", "status": "mastered|learning|failed", "comment": "..."}}]
}}"""
    
    results = []
    for test_type, user_translation in USER_TRANSLATIONS[lang_code].items():
        print(f"📝 '{test_type}': {user_translation}")
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"<<<UT_123>>>{user_translation}<<<UT_123>>>"},
        ]
        
        try:
            parsed, _, _, _, _ = await chat_json(messages, temperature=0.2, max_tokens=1024, deadline_seconds=20.0)
            status = parsed.get("status", "N/A") if parsed else "N/A"
            feedback = parsed.get("feedback", "N/A")[:100] if parsed else "N/A"
            match = "✅" if status == test_type else "⚠️"
            print(f"   {match} {status} | {feedback}...\n")
            results.append(match)
        except Exception as e:
            print(f"   ❌ {e}\n")
            results.append("❌")
    
    return results


async def main():
    print("🚀 Тест GigaChat для 5 языков\n")
    
    all_results = {}
    generated_sentences = {}
    
    for lang_code, lang_name_ru, lang_name_en in TEST_LANGUAGES:
        sentence = await test_generation(lang_code, lang_name_ru, lang_name_en)
        generated_sentences[lang_code] = sentence
        await asyncio.sleep(1)
    
    for lang_code, lang_name_ru, lang_name_en in TEST_LANGUAGES:
        results = await test_evaluation(lang_code, lang_name_ru, lang_name_en, generated_sentences[lang_code])
        all_results[lang_code] = results
        await asyncio.sleep(1)
    
    print("\n" + "="*60)
    print("📊 ИТОГИ")
    print("="*60 + "\n")
    for lang, results in all_results.items():
        correct = sum(1 for r in results if r == "✅")
        print(f"{lang.upper()}: {correct}/{len(results)} ✅")


if __name__ == "__main__":
    asyncio.run(main())