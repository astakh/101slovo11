"""Pydantic-модели для валидации ответов LLM."""

from pydantic import BaseModel, Field


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


class LlmUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0