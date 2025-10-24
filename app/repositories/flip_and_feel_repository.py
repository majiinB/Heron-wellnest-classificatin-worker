# python
# File: app/repositories/flip_and_feel_repository.py
from typing import List, Optional, Dict, Any, Union, Tuple
from datetime import datetime, date, timedelta
from app.utils.db_utils import fetch_all
import collections

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

async def get_flipfeel_by_user_id(
    user_id: str,
    for_date: Union[str, date, datetime]
) -> List[Dict[str, Any]]:
    """
    Return a list of flip\_feel sessions for `user_id` on `for_date`.
    Each item contains:
      - flip_feel_id
      - started_at
      - finished_at
      - mood_labels: ordered list of mood_label values (may contain None if choice/mood missing)
    """
    start_dt, end_dt = _day_bounds(for_date)

    query = """
        SELECT ff.flip_feel_id,
               ff.user_id,
               ff.started_at,
               ff.finished_at,
               r.choice_id,
               c.mood_label,
               r.created_at as response_created_at
        FROM flip_feel ff
        JOIN flip_feel_responses r ON ff.flip_feel_id = r.flip_feel_id
        LEFT JOIN flip_feel_choices c ON r.choice_id = c.choice_id
        WHERE ff.user_id = :user_id
          AND ff.started_at >= :start_dt AND ff.started_at < :end_dt
        ORDER BY ff.started_at ASC, r.created_at ASC
    """
    params = {"user_id": user_id, "start_dt": start_dt, "end_dt": end_dt}
    rows = await fetch_all(query, params)

    if not rows:
        return []

    sessions = collections.OrderedDict()
    for row in rows:
        fid = row.get("flip_feel_id")
        if fid not in sessions:
            sessions[fid] = {
                "flip_feel_id": fid,
                "user_id": str(row.get("user_id")) if row.get("user_id") is not None else None,
                "started_at": row.get("started_at"),
                "finished_at": row.get("finished_at"),
                "mood_labels": [],
            }
        sessions[fid]["mood_labels"].append(row.get("mood_label"))

    return list(sessions.values())

async def get_users_flipfeel_for_date(
    for_date: Union[str, date, datetime]
) -> List[Dict[str, Any]]:
    """
    Return one row per user for flip\_feel sessions on `for_date`.
    Each returned dict contains:
      - user_id (string)
      - mood_1, mood_2, mood_3 (first three mood_label values from the user's latest session that day, or None)
    This is suitable for mapping into the controller's mood_1..mood_3 expectations.
    """
    start_dt, end_dt = _day_bounds(for_date)

    query = """
        SELECT ff.user_id,
               ff.flip_feel_id,
               ff.started_at,
               r.choice_id,
               c.mood_label,
               r.created_at as response_created_at
        FROM flip_feel ff
        JOIN flip_feel_responses r ON ff.flip_feel_id = r.flip_feel_id
        LEFT JOIN flip_feel_choices c ON r.choice_id = c.choice_id
        WHERE ff.started_at >= :start_dt AND ff.started_at < :end_dt
        ORDER BY ff.user_id ASC, ff.started_at DESC, r.created_at ASC
    """
    params = {"start_dt": start_dt, "end_dt": end_dt}
    rows = await fetch_all(query, params)

    if not rows:
        return []

    # Group rows by user -> then by flip_feel_id to reconstruct sessions.
    users_sessions: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        user = row.get("user_id")
        if user is None:
            continue
        user_key = str(user)
        fid = row.get("flip_feel_id")
        if user_key not in users_sessions:
            users_sessions[user_key] = {"sessions": collections.OrderedDict()}
        sess_map = users_sessions[user_key]["sessions"]
        if fid not in sess_map:
            sess_map[fid] = {
                "flip_feel_id": fid,
                "started_at": row.get("started_at"),
                "mood_labels": [],
            }
        sess_map[fid]["mood_labels"].append(row.get("mood_label"))

    results: List[Dict[str, Any]] = []
    # For each user pick the latest session (ordered by started_at DESC in the query)
    for user_id, data in users_sessions.items():
        sessions = list(data["sessions"].values())
        if not sessions:
            continue
        # sessions list is ordered by query ordering — first is latest due to ff.started_at DESC
        latest = sessions[0]
        labels = latest.get("mood_labels", [])[:3]
        # pad to 3
        while len(labels) < 3:
            labels.append(None)
        results.append({
            "user_id": user_id,
            "mood_1": labels[0],
            "mood_2": labels[1],
            "mood_3": labels[2],
        })

    return results