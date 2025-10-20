from typing import List, Optional, Dict, Any, Union, Tuple
from datetime import datetime, date, timedelta
from app.utils.db_utils import fetch_all
import json

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

async def get_journal_by_id(
    user_id: str,
    for_date: Union[str, date, datetime],
    default_wellness: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Fetch all journal entries for a user within the given date.
    Returns a list (possibly empty). Each item contains:
      - journal_id
      - content_encrypted
      - wellness_state (parsed dict or default_wellness)
    """
    if default_wellness is None:
        default_wellness = {}

    start_dt, end_dt = _day_bounds(for_date)

    print(f"📥 Fetching journal entries for user_id={user_id} date={for_date}")
    query = """
        SELECT wellness_state
        FROM journal_entries
        WHERE user_id = :user_id
          AND is_deleted = FALSE
          AND created_at >= :start_dt AND created_at < :end_dt
        ORDER BY created_at ASC
    """
    params = {"user_id": user_id, "start_dt": start_dt, "end_dt": end_dt}
    rows = await fetch_all(query, params)

    if not rows:
        print("ℹ️ No journal entries found — returning empty list")
        return []

    results: List[Dict[str, Any]] = []
    for row in rows:
        wellness_raw = row.get("wellness_state")
        if wellness_raw is None:
            wellness = default_wellness
        elif isinstance(wellness_raw, (dict, list)):
            wellness = wellness_raw
        else:
            try:
                wellness = json.loads(wellness_raw)
            except Exception as e:
                print(f"⚠️ Failed to parse wellness_state for journal_id={row.get('journal_id')}: {e}; using default")
                wellness = default_wellness

        results.append({
            "wellness_state": wellness
        })

    print(f"📤 Returning {len(results)} journal entries")
    return results