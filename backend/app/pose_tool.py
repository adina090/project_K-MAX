import math
from statistics import fmean

from pydantic import BaseModel, Field

MIN_QUALITY = 0.65
MIN_REQUIRED_VISIBILITY = 0.55
REQUIRED_LANDMARKS = (11, 12, 13, 14, 15, 16)


class Landmark(BaseModel):
    x: float
    y: float
    z: float = 0.0
    visibility: float = Field(default=0.0, ge=0.0, le=1.0)
    # MediaPipe Tasks Vision's browser NormalizedLandmark does not expose
    # `presence`. Keep it optional for other clients instead of treating a
    # missing value as zero confidence.
    presence: float | None = Field(default=None, ge=0.0, le=1.0)


class PoseMeasurementRequest(BaseModel):
    landmarks: list[Landmark]
    sample_count: int = Field(default=1, ge=1, le=30)
    detected_sample_count: int = Field(default=1, ge=0, le=30)
    frame_width: float = Field(default=1.0, gt=0)
    frame_height: float = Field(default=1.0, gt=0)


class MeasurementError(BaseModel):
    code: str
    message: str


class PoseResult(BaseModel):
    success: bool
    quality: float
    features: dict[str, float]
    change_from_baseline: dict = Field(default_factory=dict)
    error: MeasurementError | None = None


def _failure(code: str, message: str, quality: float = 0.0) -> PoseResult:
    return PoseResult(
        success=False,
        quality=round(quality, 3),
        features={},
        error=MeasurementError(code=code, message=message),
    )


def _angle(
    first: Landmark,
    center: Landmark,
    last: Landmark,
    frame_width: float = 1.0,
    frame_height: float = 1.0,
) -> float:
    # Landmark x/y values are normalized independently by image width/height.
    # Convert them back to the frame aspect ratio before calculating geometry.
    vector_a = (
        (first.x - center.x) * frame_width,
        (first.y - center.y) * frame_height,
    )
    vector_b = (
        (last.x - center.x) * frame_width,
        (last.y - center.y) * frame_height,
    )
    magnitude = math.hypot(*vector_a) * math.hypot(*vector_b)
    if magnitude == 0:
        return 0.0

    cosine = max(-1.0, min(1.0, sum(a * b for a, b in zip(vector_a, vector_b)) / magnitude))
    return math.degrees(math.acos(cosine))


def stretch_check(request: PoseMeasurementRequest) -> PoseResult:
    if request.detected_sample_count == 0 or not request.landmarks:
        return _failure("no_pose", "죄송하지만 자세를 찾지 못했습니다. 가능하시다면 카메라에서 조금 뒤로 이동해 주시겠어요?")

    detection_ratio = min(1.0, request.detected_sample_count / request.sample_count)
    if request.detected_sample_count < 3 or detection_ratio < 0.6:
        return _failure(
            "unstable_pose",
            "자세가 안정적으로 인식되지 않았습니다. 준비되시면 전신이 보이도록 편안히 서 주시겠어요?",
            detection_ratio,
        )

    if len(request.landmarks) < 33:
        return _failure("insufficient_landmarks", "필수 신체 지점을 충분히 찾지 못했습니다.")

    required = [request.landmarks[index] for index in REQUIRED_LANDMARKS]
    visibility_scores = [
        min(point.visibility, point.presence)
        if point.presence is not None
        else point.visibility
        for point in required
    ]
    visibility_quality = fmean(visibility_scores)
    quality = visibility_quality * detection_ratio

    if any(point.x < 0.02 or point.x > 0.98 or point.y < 0.02 or point.y > 0.98 for point in required):
        return _failure(
            "out_of_frame",
            "어깨부터 손목까지 화면에 보이도록 편안한 위치로 조금만 조정해 주시겠어요?",
            quality,
        )

    if min(visibility_scores) < MIN_REQUIRED_VISIBILITY:
        return _failure(
            "low_visibility",
            "손목이나 팔꿈치를 선명하게 확인하기 어렵습니다. 가능하시다면 양팔을 몸에서 조금 떼고 밝은 곳에서 다시 확인해 주시겠어요?",
            quality,
        )

    if quality < MIN_QUALITY:
        return _failure(
            "low_quality",
            "자세를 선명하게 확인하기 어렵습니다. 가능하실 때 주변 밝기와 카메라 위치를 확인해 주시겠어요?",
            quality,
        )

    left_shoulder, right_shoulder = request.landmarks[11], request.landmarks[12]
    left_elbow, right_elbow = request.landmarks[13], request.landmarks[14]
    left_wrist, right_wrist = request.landmarks[15], request.landmarks[16]
    left_angle = _angle(
        left_shoulder,
        left_elbow,
        left_wrist,
        request.frame_width,
        request.frame_height,
    )
    right_angle = _angle(
        right_shoulder,
        right_elbow,
        right_wrist,
        request.frame_width,
        request.frame_height,
    )

    features = {
        "left_arm_angle": round(left_angle, 2),
        "right_arm_angle": round(right_angle, 2),
        "arm_angle_difference": round(abs(left_angle - right_angle), 2),
        "left_arm_height": round(left_shoulder.y - left_wrist.y, 4),
        "right_arm_height": round(right_shoulder.y - right_wrist.y, 4),
        "wrist_height_difference": round(abs(left_wrist.y - right_wrist.y), 4),
        "measurement_quality": round(quality, 3),
    }

    return PoseResult(success=True, quality=round(quality, 3), features=features)
