import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from statistics import fmean, pstdev
from threading import Lock
from typing import Any

from pydantic import BaseModel

MIN_BASELINE_SAMPLES = 3
MAX_BASELINE_SAMPLES = 20
POSE_FEATURES = (
    "left_arm_angle",
    "right_arm_angle",
    "arm_angle_difference",
    "left_arm_height",
    "right_arm_height",
    "wrist_height_difference",
    "measurement_quality",
)

COMPARISON_TOLERANCES = {
    "left_arm_angle": 15.0,
    "right_arm_angle": 15.0,
    "arm_angle_difference": 10.0,
    "left_arm_height": 0.08,
    "right_arm_height": 0.08,
    "wrist_height_difference": 0.06,
}

FACE_FEATURES = (
    "mouth_tilt",
    "nose_center_offset",
    "mouth_eye_distance",
    "measurement_quality",
)

FACE_COMPARISON_TOLERANCES = {
    "mouth_tilt": 0.04,
    "nose_center_offset": 0.06,
    "mouth_eye_distance": 0.08,
}


class PoseBaselineSampleRequest(BaseModel):
    features: dict[str, float]


class FaceBaselineSampleRequest(BaseModel):
    features: dict[str, float]


class PoseDataStore:
    def __init__(self, data_root: Path):
        self.data_root = data_root
        self.baseline_file = data_root / "baseline" / "pose_baseline.json"
        self.face_baseline_file = data_root / "baseline" / "face_baseline.json"
        self.history_dir = data_root / "history"
        self._lock = Lock()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = path.with_suffix(path.suffix + ".tmp")
        temporary_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_file.replace(path)

    @staticmethod
    def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise ValueError(f"{path.name} must contain a JSON object")
        return data

    @staticmethod
    def _validated_features(features: dict[str, float]) -> dict[str, float]:
        missing = [key for key in POSE_FEATURES if key not in features]
        if missing:
            raise ValueError(f"Missing pose features: {', '.join(missing)}")

        validated = {}
        for key in POSE_FEATURES:
            value = float(features[key])
            if not math.isfinite(value):
                raise ValueError(f"Pose feature {key} must be finite")
            validated[key] = value

        if validated["measurement_quality"] < 0.65:
            raise ValueError("Only a successful high-quality pose can be saved as baseline")
        return validated

    @staticmethod
    def _summary(
        samples: list[dict[str, Any]],
        feature_names: tuple[str, ...] = POSE_FEATURES,
    ) -> dict[str, dict[str, float]]:
        summary = {}
        for key in feature_names:
            values = [float(sample["features"][key]) for sample in samples]
            summary[key] = {
                "mean": round(fmean(values), 4),
                "stddev": round(pstdev(values), 4) if len(values) > 1 else 0.0,
                "min": round(min(values), 4),
                "max": round(max(values), 4),
            }
        return summary

    @staticmethod
    def _validated_face_features(features: dict[str, float]) -> dict[str, float]:
        missing = [key for key in FACE_FEATURES if key not in features]
        if missing:
            raise ValueError(f"Missing face features: {', '.join(missing)}")

        validated = {}
        for key in FACE_FEATURES:
            value = float(features[key])
            if not math.isfinite(value):
                raise ValueError(f"Face feature {key} must be finite")
            validated[key] = value

        if validated["measurement_quality"] < 0.65:
            raise ValueError("Only a successful high-quality face can be saved as baseline")
        return validated

    def get_baseline(self) -> dict[str, Any]:
        with self._lock:
            baseline = self._read_json(
                self.baseline_file,
                {"version": 1, "samples": [], "summary": {}, "updated_at": None},
            )
            samples = baseline.get("samples", [])
            return {
                "exists": bool(samples),
                "ready": len(samples) >= MIN_BASELINE_SAMPLES,
                "sample_count": len(samples),
                "required_samples": MIN_BASELINE_SAMPLES,
                "summary": baseline.get("summary", {}),
                "updated_at": baseline.get("updated_at"),
            }

    def add_baseline_sample(self, request: PoseBaselineSampleRequest) -> dict[str, Any]:
        features = self._validated_features(request.features)
        timestamp = self._timestamp()

        with self._lock:
            baseline = self._read_json(
                self.baseline_file,
                {"version": 1, "samples": [], "summary": {}, "updated_at": None},
            )
            samples = baseline.get("samples", [])
            samples.append({"timestamp": timestamp, "features": features})
            baseline["samples"] = samples[-MAX_BASELINE_SAMPLES:]
            baseline["summary"] = self._summary(baseline["samples"])
            baseline["updated_at"] = timestamp
            self._write_json(self.baseline_file, baseline)

            return {
                "exists": True,
                "ready": len(baseline["samples"]) >= MIN_BASELINE_SAMPLES,
                "sample_count": len(baseline["samples"]),
                "required_samples": MIN_BASELINE_SAMPLES,
                "summary": baseline["summary"],
                "updated_at": timestamp,
            }

    def compare_to_baseline(self, features: dict[str, float]) -> dict[str, Any]:
        baseline = self.get_baseline()
        if not baseline["ready"]:
            return {
                "available": False,
                "sample_count": baseline["sample_count"],
                "required_samples": MIN_BASELINE_SAMPLES,
            }

        comparisons = {}
        for key, minimum_tolerance in COMPARISON_TOLERANCES.items():
            if key not in features or key not in baseline["summary"]:
                continue
            baseline_feature = baseline["summary"][key]
            current = float(features[key])
            baseline_mean = float(baseline_feature["mean"])
            delta = current - baseline_mean
            tolerance = max(minimum_tolerance, 3 * float(baseline_feature["stddev"]))
            comparisons[key] = {
                "current": round(current, 4),
                "baseline_mean": round(baseline_mean, 4),
                "delta": round(delta, 4),
                "absolute_delta": round(abs(delta), 4),
                "tolerance": round(tolerance, 4),
                "changed": abs(delta) > tolerance,
            }

        return {
            "available": True,
            "sample_count": baseline["sample_count"],
            "significant_change": any(item["changed"] for item in comparisons.values()),
            "features": comparisons,
        }

    def get_face_baseline(self) -> dict[str, Any]:
        with self._lock:
            baseline = self._read_json(
                self.face_baseline_file,
                {"version": 1, "samples": [], "summary": {}, "updated_at": None},
            )
            samples = baseline.get("samples", [])
            return {
                "exists": bool(samples),
                "ready": len(samples) >= MIN_BASELINE_SAMPLES,
                "sample_count": len(samples),
                "required_samples": MIN_BASELINE_SAMPLES,
                "summary": baseline.get("summary", {}),
                "updated_at": baseline.get("updated_at"),
            }

    def add_face_baseline_sample(self, request: FaceBaselineSampleRequest) -> dict[str, Any]:
        features = self._validated_face_features(request.features)
        timestamp = self._timestamp()

        with self._lock:
            baseline = self._read_json(
                self.face_baseline_file,
                {"version": 1, "samples": [], "summary": {}, "updated_at": None},
            )
            samples = baseline.get("samples", [])
            samples.append({"timestamp": timestamp, "features": features})
            baseline["samples"] = samples[-MAX_BASELINE_SAMPLES:]
            baseline["summary"] = self._summary(baseline["samples"], FACE_FEATURES)
            baseline["updated_at"] = timestamp
            self._write_json(self.face_baseline_file, baseline)

            return {
                "exists": True,
                "ready": len(baseline["samples"]) >= MIN_BASELINE_SAMPLES,
                "sample_count": len(baseline["samples"]),
                "required_samples": MIN_BASELINE_SAMPLES,
                "summary": baseline["summary"],
                "updated_at": timestamp,
            }

    def compare_face_to_baseline(self, features: dict[str, float]) -> dict[str, Any]:
        baseline = self.get_face_baseline()
        if not baseline["ready"]:
            return {
                "available": False,
                "sample_count": baseline["sample_count"],
                "required_samples": MIN_BASELINE_SAMPLES,
            }

        comparisons = {}
        for key, minimum_tolerance in FACE_COMPARISON_TOLERANCES.items():
            if key not in features or key not in baseline["summary"]:
                continue
            baseline_feature = baseline["summary"][key]
            current = float(features[key])
            baseline_mean = float(baseline_feature["mean"])
            delta = current - baseline_mean
            tolerance = max(minimum_tolerance, 3 * float(baseline_feature["stddev"]))
            comparisons[key] = {
                "current": round(current, 4),
                "baseline_mean": round(baseline_mean, 4),
                "delta": round(delta, 4),
                "absolute_delta": round(abs(delta), 4),
                "tolerance": round(tolerance, 4),
                "changed": abs(delta) > tolerance,
            }

        return {
            "available": True,
            "sample_count": baseline["sample_count"],
            "significant_change": any(item["changed"] for item in comparisons.values()),
            "features": comparisons,
        }

    def save_measurement(self, result: dict[str, Any]) -> None:
        now = datetime.now().astimezone()
        history_file = self.history_dir / f"{now.date().isoformat()}.json"
        with self._lock:
            history = self._read_json(
                history_file,
                {"date": now.date().isoformat(), "pose_measurements": []},
            )
            history.setdefault("pose_measurements", []).append(
                {"timestamp": now.isoformat(timespec="seconds"), "result": result}
            )
            self._write_json(history_file, history)

    def save_face_measurement(self, result: dict[str, Any]) -> None:
        now = datetime.now().astimezone()
        history_file = self.history_dir / f"{now.date().isoformat()}.json"
        with self._lock:
            history = self._read_json(
                history_file,
                {"date": now.date().isoformat(), "pose_measurements": []},
            )
            history.setdefault("face_measurements", []).append(
                {"timestamp": now.isoformat(timespec="seconds"), "result": result}
            )
            self._write_json(history_file, history)

    def get_recent_history(self, days: int = 7) -> list[dict[str, Any]]:
        if days < 1 or days > 30:
            raise ValueError("History days must be between 1 and 30")

        today = datetime.now().astimezone().date()
        history = []
        with self._lock:
            for offset in range(days):
                day = today - timedelta(days=offset)
                history_file = self.history_dir / f"{day.isoformat()}.json"
                if history_file.exists():
                    history.append(self._read_json(history_file, {"date": day.isoformat()}))
        return history
