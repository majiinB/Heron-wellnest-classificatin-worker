from typing import List, Dict, Optional, Union
import joblib
import pandas as pd
import numpy as np
from sklearn.preprocessing import LabelEncoder

class ClassificationService:
    """
    Random Forest based classification service.
    - model_path: path to a saved sklearn model (joblib)
    - model_encoder: optional path to a saved LabelEncoder (joblib)
    - x_columns: list of feature column names used at training time (order matters)
    - label_encoder: optional LabelEncoder instance (used if model_encoder path not provided)
    - class_names: optional list of class names (overrides label_encoder)
    """
    def __init__(
        self,
        model_path: str,
        model_encoder: Optional[str] = None,
        x_columns: List[str] = None,
        label_encoder: Optional[LabelEncoder] = None,
        class_names: Optional[List[str]] = None,
    ):
        self.model = joblib.load(model_path)
        # prefer loading a label encoder from the provided path, else use the given instance
        if model_encoder:
            self.le = joblib.load(model_encoder)
        else:
            self.le = label_encoder

        self.x_columns = x_columns or []

        if class_names is not None:
            self.class_names = class_names
        elif self.le is not None:
            self.class_names = list(self.le.classes_)
        else:
            self.class_names = list(getattr(self.model, "classes_", [])) or [str(i) for i in range(getattr(self.model, "n_classes_", 0))]

    def _prepare_input(self, input_data: Union[Dict, List[Dict]]) -> pd.DataFrame:
        df = pd.DataFrame(input_data if isinstance(input_data, list) else [input_data])
        # add missing columns with zeros
        for col in self.x_columns:
            if col not in df.columns:
                df[col] = 0
        # reorder
        df = df[self.x_columns]
        return df

    def classify_user(self, input_data: Union[Dict, List[Dict]], top_k: Optional[int] = None):
        """
        input_data: single dict or list of dicts with feature values
        top_k: if set, return only top_k classes per example

        Returns:
            single result dict if input_data was a dict, else list of dicts.
            Each result: { "prediction": <class>, "probabilities": {class: prob, ...} }
        """
        single_input = isinstance(input_data, dict)
        df = self._prepare_input(input_data)

        # predictions (encoded or label strings depending on model)
        preds = self.model.predict(df)

        # try to decode using label encoder if provided
        try:
            if self.le is not None:
                decoded_preds = list(self.le.inverse_transform(preds))
            else:
                decoded_preds = list(preds)
        except Exception:
            decoded_preds = list(preds)

        # probabilities
        if hasattr(self.model, "predict_proba"):
            proba = self.model.predict_proba(df)
        else:
            # fallback: if no predict_proba, create one-hot like probabilities
            proba = np.zeros((len(df), len(self.class_names)))
            for i, p in enumerate(preds):
                # try to find index in class_names, otherwise use numeric prediction as index
                try:
                    idx = self.class_names.index(p)
                except Exception:
                    try:
                        idx = int(p)
                    except Exception:
                        idx = 0
                if 0 <= idx < proba.shape[1]:
                    proba[i, idx] = 1.0

        results = []
        for row_idx, probs_row in enumerate(proba):
            # map class names to probabilities
            if self.class_names:
                prob_map = {str(cls): float(probs_row[i]) for i, cls in enumerate(self.class_names)}
            else:
                prob_map = {str(i): float(p) for i, p in enumerate(probs_row)}

            # sort and apply top_k if requested
            sorted_items = sorted(prob_map.items(), key=lambda x: x[1], reverse=True)
            if top_k is not None:
                sorted_items = sorted_items[:top_k]
                prob_map = dict(sorted_items)

            result = {
                "prediction": decoded_preds[row_idx],
                "probabilities": prob_map,
            }
            results.append(result)

        return results[0] if single_input else results