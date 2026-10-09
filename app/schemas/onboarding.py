from pydantic import BaseModel, Field


class OnboardingForm(BaseModel):
    level: str = Field(..., pattern="^(A1|A2|B1|B2|C1|C2)$")
    dictionary_code: str
    words_per_lesson: int = Field(..., ge=1, le=10)
    daily_lesson_limit: int = Field(..., ge=1, le=5)