# app/llm/validation.py
"""Pydantic-модели для валидации ответов LLM."""
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Any


class TargetWordItem(BaseModel):
    lemma: str = Field(min_length=1, max_length=64)
    surface_form: str = Field(min_length=1, max_length=64)
    pos: str = Field(min_length=1, max_length=16)


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
        if v is None:
            return []
        if not isinstance(v, list):
            if isinstance(v, str):
                return [v] if v.strip() else []
            return []
        result = []
        for item in v:
            if isinstance(item, str):
                if item.strip():
                    result.append(item)
            elif isinstance(item, dict):
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
                    result.append(str(item))
            else:
                result.append(str(item))
        return result


class LlmUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class EnrichedWordVariant(BaseModel):
    lemma: str = Field(min_length=1, max_length=64)
    pos: str = Field(min_length=1, max_length=16)
    level: str = Field(pattern=r"^(A1|A2|B1|B2|C1|C2)$")
    translations: list[str] = Field(min_length=1, max_length=5)
    dictionaries: list[str] = Field(default_factory=lambda: ["general"])


class EnrichWordResponse(BaseModel):
    variants: list[EnrichedWordVariant] = Field(default_factory=list, max_length=5)


# ============================================================
# WORD PAGE (SEO-страницы слов)
# ============================================================

class WordPageWord(BaseModel):
    """Базовая информация о слове."""
    lemma: str = Field(min_length=1, max_length=64)
    transcription: str = Field(min_length=3, max_length=50)
    part_of_speech: str = Field(min_length=1, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def normalize_keys(cls, data: Any) -> Any:
        """Исправляет опечатки LLM в ключах."""
        if isinstance(data, dict):
            for key in list(data.keys()):
                nk = key.replace("_", "").replace(" ", "").replace("-", "").lower()
                if nk == "partofspeech" and "part_of_speech" not in data:
                    data["part_of_speech"] = data.pop(key)
                elif nk == "transcription" and "transcription" not in data:
                    data["transcription"] = data.pop(key)
                elif nk == "lemma" and "lemma" not in data:
                    data["lemma"] = data.pop(key)
        return data


class WordPageContextSentence(BaseModel):
    english: str = Field(min_length=10, max_length=200)
    russian: str = Field(min_length=10, max_length=300)


class WordPageSynonym(BaseModel):
    word: WordPageWord
    nuance: str = Field(min_length=1, max_length=300)


class WordPageCollocation(BaseModel):
    phrase: str = Field(min_length=2, max_length=100)
    translation: str = Field(min_length=2, max_length=200)


class WordPageTrap(BaseModel):
    word: WordPageWord
    nuance: str = Field(min_length=10, max_length=500)


class RelatedWord(BaseModel):
    """Связанное слово с леммой и частью речи."""
    lemma: str = Field(min_length=1, max_length=64)
    pos: str = Field(default="", max_length=20)


class WordPageContentResponse(BaseModel):
    """Полный ответ LLM для страницы слова."""
    word: WordPageWord
    core_translation: str = Field(min_length=1, max_length=50)
    other_translations: list[str] = Field(default_factory=list, max_length=5)
    context_sentence: WordPageContextSentence
    synonyms: list[WordPageSynonym] = Field(min_length=1, max_length=5)
    antonyms: list[WordPageSynonym] = Field(default_factory=list, max_length=3)
    collocations: list[WordPageCollocation] = Field(min_length=2, max_length=6)
    level_b_trap: list[WordPageTrap] = Field(default_factory=list, max_length=3)
    related_words: list[RelatedWord] = Field(default_factory=list, max_length=8)

    @field_validator("related_words", mode="before")
    @classmethod
    def normalize_related_words(cls, v: Any) -> list:
        """
        Обратная совместимость: старый формат — список строк,
        новый формат — список объектов {lemma, pos}.
        """
        if not isinstance(v, list):
            return []
        result = []
        for item in v:
            if isinstance(item, str):
                if item.strip():
                    result.append({"lemma": item.strip(), "pos": ""})
            elif isinstance(item, dict):
                result.append(item)
        return result