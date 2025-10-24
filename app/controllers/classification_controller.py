from datetime import datetime, timezone, timedelta, date
import asyncio
import numpy as np
import re
from typing import Dict, Any, List, Optional
from uuid import UUID as UUIDType

from app.repositories.journal_repository import get_journal_by_id
from app.repositories.mood_entry_repository import get_users_mood_check_ins_for_date
from app.repositories.gratitude_jar_repository import has_gratitude_entry_for_date
from app.services.classification_service import ClassificationService
from app.utils.logger_util import logger
from app.repositories.student_analytics_repository import CreateStudentAnalytics, StudentAnalyticsRepository
from app.repositories.student_classification_repository import StudentClassificationRepository
from app.repositories.flip_and_feel_repository import get_flipfeel_by_user_id
from app.services.weekly_classification_service import WeeklyClassificationService
from app.repositories.student_weekly_classification_repository import StudentWeeklyClassificationRepository

# Journal L1..L5 -> probability feature names
LABEL_TO_PKEY = {
    "L1": "p_anxiety",
    "L2": "p_normal",
    "L3": "p_depressed",
    "L4": "p_suicidal",
    "L5": "p_stressed",
}
ALL_LABELS = ["L1", "L2", "L3", "L4", "L5"]

# Check-in emotions universe (one-hot features)
EMOTIONS = [
    "Depressed", "Sad", "Exhausted", "Hopeless",
    "Anxious", "Angry", "Stressed", "Restless",
    "Calm", "Relaxed", "Peaceful", "Content",
    "Happy", "Energized", "Excited", "Motivated",
]

def _normalize_mood(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, int):
        return None
    if isinstance(val, str):
        name = val.strip()
        if not name:
            return None
        return name[0].upper() + name[1:].lower()
    return None

def _one_hot_moods(selected: List[Any]) -> Dict[str, int]:
    hot = {e: 0 for e in EMOTIONS}
    for raw in selected:
        name = _normalize_mood(raw)
        if name in hot:
            hot[name] = 1
    return hot

import json

def _aggregate_wellness_probs(journals: List[Dict[str, Any]]) -> Dict[str, float]:
    totals = {k: 0.0 for k in ALL_LABELS}
    counted = 0

    for item in journals:
        ws = item.get("wellness_state") or {}

        if isinstance(ws, str):
            try:
                ws = json.loads(ws)
            except json.JSONDecodeError:
                ws = {}

        any_num = False
        for k in ALL_LABELS:
            v = ws.get(k)
            if v is not None:
                try:
                    totals[k] += float(v)
                    any_num = True
                except (ValueError, TypeError):
                    pass

        if any_num:
            counted += 1

    avgs = {k: (totals[k] / counted if counted else 0.0) for k in ALL_LABELS}
    return {LABEL_TO_PKEY[k]: avgs[k] for k in ALL_LABELS}


def _default_flipfeel_pct() -> Dict[str, float]:
    return {
        "flipfeel_incrisis_pct": 0.0,
        "flipfeel_struggling_pct": 0.0,
        "flipfeel_thriving_pct": 0.0,
        "flipfeel_excelling_pct": 0.0,
    }

def _to_native(obj):
    if obj is None:
        return None
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_ ,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {str(k): _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_native(v) for v in obj]
    return obj

def _normalize_flipfeel_label(label: Optional[str]) -> Optional[str]:
    if not label:
        return None
    s = label.strip().lower()
    # normalize common variants
    if "crisi" in s or "crisis" in s:
        return "InCrisis"
    if "excelling" in s:
        return "Excelling"
    if "thriv" in s:
        return "Thriving"
    if "struggl" in s:
        return "Struggling"
    return None

def _compute_flipfeel_pct_from_sessions(sessions: List[Dict[str, Any]]) -> Dict[str, float]:
    if not sessions:
        return _default_flipfeel_pct()
    counts = {"Excelling": 0, "Thriving": 0, "Struggling": 0, "InCrisis": 0}
    total = 0
    for sess in sessions:
        labels = sess.get("mood_labels") or []
        for l in labels:
            norm = _normalize_flipfeel_label(l)
            if norm:
                counts[norm] += 1
                total += 1
    if total == 0:
        return _default_flipfeel_pct()
    return {
        "flipfeel_incrisis_pct": counts["InCrisis"] / total,
        "flipfeel_struggling_pct": counts["Struggling"] / total,
        "flipfeel_thriving_pct": counts["Thriving"] / total,
        "flipfeel_excelling_pct": counts["Excelling"] / total,
    }

class ClassificationController:
    def __init__(
            self,
            classifcation_service: ClassificationService,
            analytics_repo: StudentAnalyticsRepository,
            classification_repo: StudentClassificationRepository,
    ):
        self.classifcation_service = classifcation_service
        self.model_lock = asyncio.Lock()
        self.analytics_repo = analytics_repo
        self.classification_repo = classification_repo

    async def classify_today_entries(self, top_k: int = 1):
        for_date = datetime.now(timezone.utc).date()

        mood_rows = await get_users_mood_check_ins_for_date(for_date)
        if not mood_rows:
            logger.info("No mood check-ins found for date=%s", for_date)
            return []

        mood_by_user = {row["user_id"]: row for row in mood_rows}
        user_ids = list(mood_by_user.keys())

        async def build_model_input(uid: str):
            journals = await get_journal_by_id(uid, for_date, default_wellness={})
            has_grat = await has_gratitude_entry_for_date(uid, for_date)
            moods = mood_by_user[uid]

            probs = _aggregate_wellness_probs(journals)

            one_hot = _one_hot_moods([
                moods.get("mood_1"),
                moods.get("mood_2"),
                moods.get("mood_3"),
            ])

            try:
                sessions = await get_flipfeel_by_user_id(uid, for_date)
            except Exception:
                sessions = []
            flipfeel = _compute_flipfeel_pct_from_sessions(sessions)

            model_input = {
                **probs,
                "gratitude_flag": 1 if has_grat else 0,
                **one_hot,
                **flipfeel,
            }

            return {
                "user_id": uid,
                "date": str(for_date),
                "model_input": model_input,
            }

        per_user_inputs = await asyncio.gather(*(build_model_input(uid) for uid in user_ids))
        logger.info(f"Built {len(per_user_inputs)} model inputs for date={for_date} (top_k={top_k})")

        input_batch = [item["model_input"] for item in per_user_inputs]
        loop = asyncio.get_running_loop()
        async with self.model_lock:
            clf_results = await loop.run_in_executor(
                None, lambda: self.classifcation_service.classify_user(input_batch, top_k=top_k)
            )

        final = []
        for item, clf in zip(per_user_inputs, clf_results):
            prediction = _to_native(clf.get("prediction"))
            probabilities = _to_native(clf.get("probabilities"))
            final_item = {
                **item,
                "prediction": prediction,
                "probabilities": probabilities,
            }
            final.append(final_item)

            uid = item["user_id"]
            model_input = item["model_input"]

            analytics_kwargs = {
                "date_recorded": datetime.now(timezone.utc),
                "gratitude_flag": bool(model_input.get("gratitude_flag", 0)),
                "p_anxiety": float(model_input.get("p_anxiety")) if model_input.get("p_anxiety") is not None else None,
                "p_normal": float(model_input.get("p_normal")) if model_input.get("p_normal") is not None else None,
                "p_stressed": float(model_input.get("p_stressed")) if model_input.get(
                    "p_stressed") is not None else None,
                "p_suicidal": float(model_input.get("p_suicidal")) if model_input.get(
                    "p_suicidal") is not None else None,
                "p_depressed": float(model_input.get("p_depressed")) if model_input.get(
                    "p_depressed") is not None else None,
            }

            for name in EMOTIONS:
                field_name = f"mood_{name.lower()}"
                analytics_kwargs[field_name] = int(model_input.get(name, 0))

            analytics_kwargs["f_and_f_in_crisis"] = float(model_input.get("flipfeel_incrisis_pct", 0.0))
            analytics_kwargs["f_and_f_struggling"] = float(model_input.get("flipfeel_struggling_pct", 0.0))
            analytics_kwargs["f_and_f_thriving"] = float(model_input.get("flipfeel_thriving_pct", 0.0))
            analytics_kwargs["f_and_f_excelling"] = float(model_input.get("flipfeel_excelling_pct", 0.0))
            analytics_kwargs["f_and_f_final_category"] = float(model_input.get("f_and_f_final_category", 0.0))

            analytics_kwargs["classification"] = prediction

            is_flagged = True if (prediction == "InCrisis" or prediction == "Struggling") else False

            payload = CreateStudentAnalytics(**analytics_kwargs)

            try:
                await self.analytics_repo.create(payload)
                try:
                    student_uuid = UUIDType(uid)
                except Exception:
                    student_uuid = uid
                await self.classification_repo.create(student_uuid, prediction)
            except Exception as exc:
                logger.exception("Failed to persist analytics/classification for user=%s: %s", uid, exc)

        return final

    async def classify_weekly_entries(self, days: int = 7):
        """
        Find all students who have daily classifications within the computed week range
        and run WeeklyClassificationService.classify_and_record_week for each.
        """
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days - 1)

        week_start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
        week_end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc) + timedelta(days=1)

        try:
            classifications_in_range = await self.classification_repo.list_between(week_start, week_end)
        except AttributeError:
            try:
                all_items = await self.classification_repo.list_all(limit=10000)
            except AttributeError:
                raise RuntimeError("classification repository lacks `list_between` and `list_all` methods; adapt to repo API")
            classifications_in_range = [
                it for it in all_items
                if getattr(it, "classified_at", None) is not None
                   and (it.classified_at >= week_start and it.classified_at < week_end)
            ]

        if not classifications_in_range:
            logger.info("No student classifications found for week range=%s..%s", start_date, end_date)
            return []

        def _student_id_from_item(it):
            sid = getattr(it, "student_id", None)
            if sid is None:
                sid = getattr(it, "student", None)
            if sid is None:
                sid = getattr(it, "user_id", None)
            return str(sid) if sid is not None else None

        student_ids = { _student_id_from_item(it) for it in classifications_in_range }
        student_ids.discard(None)
        user_ids = list(student_ids)

        weekly_service = WeeklyClassificationService(self.classification_repo, StudentWeeklyClassificationRepository())

        tasks = []
        for uid in user_ids:
            try:
                student_uuid = UUIDType(uid)
            except Exception:
                student_uuid = uid
            tasks.append(weekly_service.classify_and_record_week(student_uuid, week_start, week_end))

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for uid, res in zip(user_ids, raw_results):
            if isinstance(res, Exception):
                logger.exception("Failed weekly classification for user=%s: %s", uid, res)
            else:
                results.append(res)

        logger.info("Completed weekly classification for %d users range=%s..%s", len(user_ids), start_date, end_date)
        return results