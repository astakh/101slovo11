# app/llm/validation.py
"""Pydantic-модели для валидации ответов LLM."""
from pydantic import BaseModel, Field, field_validator
from typing import Any


class TargetWordItem(BaseModel):
    lemma: str = Field(min_length=1, max_length=64)
    surface_form: str = Field(min_length=1, max_length=64)
    pos: str = Field(min_length=1, max_length=10)


class GeneratedExercise(BaseModel):
    target_sentence: str = Field(min_length=1, max_length=200)
    reference_translation: str = Field(min_length=1, max_length=300)
    target_words: list[TargetWordItem] = Field(min_length=1, max_length=3)


class GenerateResponse(BaseModel):
    exercises: list[GeneratedExercise] = Field(min_length=1, max_length=10)


class EvaluationItem(BaseModel):
    lemma: str = Field(min_length=1, max_length=64)
    status: str = Field(pattern=r"^(mastered|learning|failed)$")
    comment: str = Field(default="", max_length=500)


class SuggestedWord(BaseModel):
    lemma: str = Field(min_length=1, max_length=64)
    translation: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=300)


class EvaluateResponse(BaseModel):
    status: str = Field(pattern=r"^(correct|typo|incorrect)$")
    feedback: str = Field(default="", max_length=1000)
    evaluations: list[EvaluationItem] = Field(default_factory=list)
    suggested_words: list[SuggestedWord] = Field(default_factory=list)
    translation_errors: list[str] = Field(default_factory=list)

    @field_validator("translation_errors", mode="before")
    @classmethod
    def normalize_translation_errors(cls, v: Any) -> list[str]:
        """
        Нормализует translation_errors в список строк.
        
        GigaChat иногда возвращает:
        - Список словарей (error objects) вместо списка строк
        - Одну строку вместо списка
        - None или пустое значение
        
        Этот валидатор преобразует все варианты в list[str].
        """
        if v is None:
            return []
        
        # Если это не список — оборачиваем в список
        if not isinstance(v, list):
            if isinstance(v, str):
                return [v] if v.strip() else []
            # Неизвестный тип — возвращаем пустой список
            return []
        
        # Обрабатываем каждый элемент списка
        result = []
        for item in v:
            if isinstance(item, str):
                # Уже строка — добавляем как есть
                if item.strip():
                    result.append(item)
            elif isinstance(item, dict):
                # Словарь — пытаемся извлечь полезную информацию
                # Формат может быть: {"original_word": "...", "error_type": "..."}
                # или другие варианты
                parts = []
                if "original_word" in item:
                    parts.append(str(item["original_word"]))
                if "error_type" in item:
                    parts.append(str(item["error_type"]))
                if "message" in item:
                    parts.append(str(item["message"]))
                if "description" in item:
                    parts.append(str(item["description"]))
                
                if parts:
                    result.append(": ".join(parts))
                else:
                    # Если не удалось извлечь — конвертируем dict в строку
                    result.append(str(item))
            else:
                # Любой другой тип — конвертируем в строку
                result.append(str(item))
        
        return result


class LlmUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class EnrichedWordVariant(BaseModel):
    """Вариант слова из LLM (разные части речи)."""
    lemma: str = Field(min_length=1, max_length=64)
    pos: str = Field(min_length=1, max_length=16)
    level: str = Field(pattern=r"^(A1|A2|B1|B2|C1|C2)$")
    translations: list[str] = Field(min_length=1, max_length=5)
    dictionaries: list[str] = Field(default_factory=lambda: ["general"])


class EnrichWordResponse(BaseModel):
    """Ответ LLM на запрос обогащения слова. Может быть пустым, если слово не существует."""
    variants: list[EnrichedWordVariant] = Field(default_factory=list, max_length=5)