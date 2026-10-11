"""SRS (Spaced Repetition System) — чистая функция обновления стадии слова."""

# Интервалы повторения в уроках.
# Удвоены относительно исходных [1, 2, 3, 7, 11, 30],
# т.к. пользователи теперь проходят до 3 уроков в день.
INTERVALS: list[int] = [2, 4, 6, 14, 22, 60]
MAX_STAGE: int = 6


def srs_update(stage: int, result: str, lesson_number: int) -> tuple[int, int | None, str]:
    """
    Обновляет стадию и статус слова после оценки.

    Args:
        stage: текущая стадия (0–6).
        result: "correct", "typo" или "incorrect".
        lesson_number: номер текущего урока.

    Returns:
        (new_stage, due_lesson_number | None, new_status)
    """
    success = result in ("correct", "typo")

    if success:
        if stage >= MAX_STAGE:
            return (MAX_STAGE, None, "mastered")
        new_stage = stage + 1
    else:
        new_stage = max(stage - 1, 0)

    interval = INTERVALS[max(new_stage - 1, 0)]
    due = lesson_number + interval

    return (new_stage, due, "active")