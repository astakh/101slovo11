from datetime import date, timedelta
from typing import List

def calculate_streak(dates: List[date], today: date) -> dict:
    if not dates:
        return {"current": 0, "longest": 0, "today_done": False}
    
    # Приводим будущие даты к today (согласно ТЗ)
    capped_dates = [d if d <= today else today for d in dates]
    unique_dates = sorted(list(set(capped_dates)))
    
    today_done = today in unique_dates
    
    # Расчет максимального стрика
    longest = 0
    current_streak = 1
    for i in range(1, len(unique_dates)):
        if unique_dates[i] - unique_dates[i-1] == timedelta(days=1):
            current_streak += 1
        else:
            current_streak = 1
        longest = max(longest, current_streak)
    longest = max(longest, current_streak) if unique_dates else 0
    
    # Расчет текущего стрика (идем назад от максимальной даты)
    current = 0
    if unique_dates:
        max_date = unique_dates[-1]
        # Стрик не прервался, если последняя активность была сегодня или вчера
        if (today - max_date).days <= 1:
            current = 1
            check_date = max_date
            while True:
                prev_date = check_date - timedelta(days=1)
                if prev_date in unique_dates:
                    current += 1
                    check_date = prev_date
                else:
                    break
                
    return {
        "current": current,
        "longest": longest,
        "today_done": today_done
    }