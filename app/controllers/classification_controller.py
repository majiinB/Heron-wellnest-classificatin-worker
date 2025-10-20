from datetime import datetime, timezone
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
        # map ids externally if needed
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

        # 🧽 If it's stored as a JSON string in Postgres, decode it.
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
                    # ignore non-numeric entries
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
    """Recursively convert numpy / non-serializable types to native Python types."""
    if obj is None:
        return None
    # numpy scalar types
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_ ,)):
        return bool(obj)
    # numpy arrays -> lists
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    # dict / list / tuple / set -> recurse
    if isinstance(obj, dict):
        return {str(k): _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_native(v) for v in obj]
    # fallback
    return obj

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
        """
        Build per-user model inputs for today's date (UTC):
        - p_* from averaged journal wellness (L1..L5)
        - one-hot 16 emotions from check-in (mood_1..mood_3)
        - gratitude_flag from gratitude entries presence
        - flipfeel_*_pct default to 0.0
        """
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

            # 1) Journal probs (averages)
            probs = _aggregate_wellness_probs(journals)

            # 2) One-hot emotions from check-in (min 1, max 3)
            one_hot = _one_hot_moods([
                moods.get("mood_1"),
                moods.get("mood_2"),
                moods.get("mood_3"),
            ])

            # 3) Flipfeel default pct
            flipfeel = _default_flipfeel_pct()

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

        # Run the model on the batch while holding the model lock and offloading to a worker thread.
        input_batch = [item["model_input"] for item in per_user_inputs]
        loop = asyncio.get_running_loop()
        async with self.model_lock:
            clf_results = await loop.run_in_executor(
                None, lambda: self.classifcation_service.classify_user(input_batch, top_k=top_k)
            )

        # Merge classification outputs back to users by order.
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

            # Persist analytics and classification
            uid = item["user_id"]
            model_input = item["model_input"]

            # Build CreateStudentAnalytics payload
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

            # moods -> mood_* fields
            for name in EMOTIONS:
                field_name = f"mood_{name.lower()}"
                analytics_kwargs[field_name] = int(model_input.get(name, 0))

            # flipfeel -> f_and_f_* mapping
            analytics_kwargs["f_and_f_in_crisis"] = float(model_input.get("flipfeel_incrisis_pct", 0.0))
            analytics_kwargs["f_and_f_struggling"] = float(model_input.get("flipfeel_struggling_pct", 0.0))
            analytics_kwargs["f_and_f_thriving"] = float(model_input.get("flipfeel_thriving_pct", 0.0))
            analytics_kwargs["f_and_f_excelling"] = float(model_input.get("flipfeel_excelling_pct", 0.0))
            analytics_kwargs["f_and_f_final_category"] = float(model_input.get("f_and_f_final_category", 0.0))

            analytics_kwargs["classification"] = prediction

            if (prediction == "InCrisis") or (prediction == 'Struggling'):
                is_flagged = True
            else:
                is_flagged = False

            payload = CreateStudentAnalytics(**analytics_kwargs)

            try:
                # persist analytics and classification (await both)
                await self.analytics_repo.create(payload)
                # convert uid string to UUIDType if needed
                try:
                    student_uuid = UUIDType(uid)
                except Exception:
                    student_uuid = uid  # let repository handle conversion/fail
                await self.classification_repo.create(student_uuid, prediction, is_flagged=is_flagged)
            except Exception as exc:
                logger.exception("Failed to persist analytics/classification for user=%s: %s", uid, exc)
