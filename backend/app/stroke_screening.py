from dataclasses import dataclass
import re
from typing import Any


POSE_ASYMMETRY_FEATURES = {"arm_angle_difference", "wrist_height_difference"}
FACE_ASYMMETRY_FEATURES = {"mouth_tilt"}

NEGATIVE_PATTERNS = (
    r"^(?:아니요?|아뇨|없어요?|없습니다|괜찮아요?|괜찮습니다|문제\s*없어요?)[,.!\s]*$",
    r"(?:그런|해당|말씀하신)?\s*(?:증상|문제|어려움|불편).{0,12}(?:없|괜찮|그렇지\s*않)",
    r"(?:얼굴|입꼬리|팔|다리|말|발음|시야|균형).{0,15}(?:문제\s*없|이상\s*없|어렵지\s*않|괜찮)",
)
POSITIVE_CONFIRMATIONS = (
    r"^(?:네|예|응|그래|맞아|맞아요|있어|있어요|그렇습니다)[.!\s]*$",
    r"(?:증상이|그런\s*증상이)\s*(?:있어|있어요|있습니다)",
)
SYMPTOM_PATTERNS = {
    "한쪽 얼굴 처짐": (
        r"한쪽\s*(?:얼굴|입|입꼬리).{0,12}(?:처지|내려가|마비|돌아가)",
        r"(?:얼굴|입|입꼬리).{0,12}한쪽.{0,12}(?:처지|내려가|마비|돌아가)",
    ),
    "한쪽 팔·다리 힘 빠짐": (
        r"한쪽\s*(?:팔|다리).{0,15}(?:힘이?\s*(?:빠지|없)|마비|들기\s*어렵|저리)",
        r"(?:팔|다리)\s*한쪽.{0,15}(?:힘이?\s*(?:빠지|없)|마비|들기\s*어렵|저리)",
    ),
    "말하기·이해하기 어려움": (
        r"(?:말|발음|말하기|이해하기).{0,15}(?:어렵|어려|안\s*나|이상|꼬이|어눌|흐려)",
        r"(?:말이|발음이).{0,12}(?:잘\s*)?(?:안\s*돼|안\s*되)",
    ),
    "갑작스러운 균형 이상": (
        r"갑자기.{0,15}(?:어지럽|휘청|균형|걷기\s*어렵)",
    ),
    "갑작스러운 시야 이상": (
        r"갑자기.{0,15}(?:안\s*보|시야|눈앞|두\s*개로\s*보)",
    ),
    "원인 불명의 갑작스러운 심한 두통": (
        r"갑자기.{0,15}(?:심한|극심한).{0,8}(?:두통|머리)",
    ),
}


@dataclass(frozen=True)
class MeasurementScreening:
    pose_signal: bool
    face_signal: bool
    changed_pose_features: tuple[str, ...]
    changed_face_features: tuple[str, ...]

    @property
    def needs_confirmation(self) -> bool:
        return self.pose_signal or self.face_signal

    def as_dict(self) -> dict[str, Any]:
        return {
            "pose_signal": self.pose_signal,
            "face_signal": self.face_signal,
            "changed_pose_features": list(self.changed_pose_features),
            "changed_face_features": list(self.changed_face_features),
            "needs_confirmation": self.needs_confirmation,
        }


@dataclass(frozen=True)
class SymptomAssessment:
    urgent: bool
    signs: tuple[str, ...] = ()

    @property
    def reason(self) -> str:
        if not self.signs:
            return ""
        joined = ", ".join(self.signs)
        return f"갑작스러운 신경학적 증상({joined})이 확인되어 염려됩니다. 측정만으로 뇌졸중 여부를 확정할 수는 없지만, 안전을 위해 지금 바로 119에 연락해 주시기 바랍니다."


def _changed_features(result: dict[str, Any], allowed: set[str]) -> tuple[str, ...]:
    if not result.get("success"):
        return ()
    comparison = result.get("change_from_baseline") or {}
    if not comparison.get("available"):
        return ()
    features = comparison.get("features") or {}
    return tuple(sorted(key for key in allowed if (features.get(key) or {}).get("changed") is True))


def summarize_measurements(measurement_context: dict[str, Any] | None) -> MeasurementScreening:
    context = measurement_context or {}
    pose_features = _changed_features(context.get("pose") or {}, POSE_ASYMMETRY_FEATURES)
    face_features = _changed_features(context.get("face") or {}, FACE_ASYMMETRY_FEATURES)
    return MeasurementScreening(
        pose_signal=bool(pose_features),
        face_signal=bool(face_features),
        changed_pose_features=pose_features,
        changed_face_features=face_features,
    )


def screening_question(summary: MeasurementScreening) -> str | None:
    if summary.pose_signal and summary.face_signal:
        observation = "팔과 얼굴 측정에서 평소와 다른 좌우 차이가 함께 보였습니다."
        symptoms = "갑자기 한쪽 얼굴이 처지거나 한쪽 팔에 힘이 빠지고, 말하기가 어려운 증상"
    elif summary.pose_signal:
        observation = "팔 측정에서 평소와 다른 좌우 차이가 보였습니다."
        symptoms = "갑자기 한쪽 팔에 힘이 빠지거나 들기 어려운 증상"
    elif summary.face_signal:
        observation = "얼굴 측정에서 평소와 다른 입꼬리 좌우 차이가 보였습니다."
        symptoms = "갑자기 한쪽 얼굴이나 입꼬리가 처지거나 말하기 어려운 증상"
    else:
        return None
    return f"{observation} 측정만으로 질환을 판단할 수는 없습니다. 혹시 지금 {symptoms}이 있으신가요?"


def assess_response(response: str, screening: MeasurementScreening) -> SymptomAssessment:
    normalized = " ".join(response.strip().lower().split())
    if not normalized:
        return SymptomAssessment(False)
    if any(re.search(pattern, normalized) for pattern in NEGATIVE_PATTERNS):
        return SymptomAssessment(False)

    signs = tuple(
        name
        for name, patterns in SYMPTOM_PATTERNS.items()
        if any(re.search(pattern, normalized) for pattern in patterns)
    )
    if signs:
        return SymptomAssessment(True, signs)

    confirmed = screening.needs_confirmation and any(
        re.search(pattern, normalized) for pattern in POSITIVE_CONFIRMATIONS
    )
    if confirmed:
        measured_signs = []
        if screening.face_signal:
            measured_signs.append("사용자가 확인한 얼굴 증상")
        if screening.pose_signal:
            measured_signs.append("사용자가 확인한 팔 증상")
        return SymptomAssessment(True, tuple(measured_signs))

    return SymptomAssessment(False)


def is_explicit_negative(response: str) -> bool:
    normalized = " ".join(response.strip().lower().split())
    return bool(normalized) and any(re.search(pattern, normalized) for pattern in NEGATIVE_PATTERNS)


def classify_screening_response(response: str, screening: MeasurementScreening) -> str:
    assessment = assess_response(response, screening)
    if assessment.urgent:
        return "urgent"
    if is_explicit_negative(response):
        return "negative"
    return "unclear"
