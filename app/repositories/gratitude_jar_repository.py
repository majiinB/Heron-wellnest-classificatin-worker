from typing import Union, Tuple
from datetime import datetime, date, timedelta
from app.utils.db_utils import fetch_one

def _day_bounds(for_date: Union[str, date, datetime]) -> Tuple[datetime, datetime]:
    """
    Normalize a date-like input to start/end datetimes for that day \[start, next day).
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

async def has_gratitude_entry_for_date(
    user_id: str,
    for_date: Union[str, date, datetime],
) -> bool:
    """
    Return True if at least one `gratitude_entries` record exists for the user within the given day, else False.
    """
    start_dt, end_dt = _day_bounds(for_date)

    query = """
        SELECT 1
        FROM gratitude_entries
        WHERE user_id = :user_id
          AND is_deleted = FALSE
          AND created_at >= :start_dt AND created_at < :end_dt
        LIMIT 1
    """
    params = {"user_id": user_id, "start_dt": start_dt, "end_dt": end_dt}
    row = await fetch_one(query, params)
    return bool(row)