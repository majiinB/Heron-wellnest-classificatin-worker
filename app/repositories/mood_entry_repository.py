from typing import Union, Tuple, List, Dict, Any
from datetime import datetime, date, timedelta
from app.utils.db_utils import fetch_all

def _day_bounds(for_date: Union[str, date, datetime]) -> Tuple[datetime, datetime]:
    """
    Normalize a date-like input to start/end datetimes for that day [start, next day).
    Accepts 'YYYY-MM-DD' string, date, or datetime.
    """
    if isinstance(for_date, str):
        d = datetime.strptime(for_date, "%Y-%m-%d").date()
    elif isinstance(for_date, datetime):
        d = for_date.date()
    else:
        d = for_date
    start = datetime(d.year, d.month, d.day, 0, 0, 0)
    end = start + timedelta(days=1)
    return start, end

async def get_users_mood_check_ins_for_date(
    for_date: Union[str, date, datetime],
) -> List[Dict[str, Any]]:
    """
    Get the latest mood check-in per user within the given day.
    Returns a list of dicts with: user_id, mood_1, mood_2, mood_3.
    """
    start_dt, end_dt = _day_bounds(for_date)

    query = """
        WITH ranked AS (
            SELECT
                user_id,
                mood_1,
                mood_2,
                mood_3,
                checked_in_at,
                ROW_NUMBER() OVER (
                    PARTITION BY user_id
                    ORDER BY checked_in_at DESC
                ) AS rn
            FROM mood_check_ins
            WHERE checked_in_at >= :start_dt AND checked_in_at < :end_dt
        )
        SELECT user_id, mood_1, mood_2, mood_3
        FROM ranked
        WHERE rn = 1
        ORDER BY user_id
    """
    params = {"start_dt": start_dt, "end_dt": end_dt}
    rows = await fetch_all(query, params)
    if not rows:
        return []

    return [
        {
            "user_id": row.get("user_id"),
            "mood_1": row.get("mood_1"),
            "mood_2": row.get("mood_2"),
            "mood_3": row.get("mood_3"),
        }
        for row in rows
    ]