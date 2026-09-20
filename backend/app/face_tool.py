import math
from statistics import fmean

from pydantic import BaseModel, Field


# A usable current measurement may be more permissive than a baseline sample.
# Baseline storage still requires quality >= 0.65 in pose_store.py.
MIN_QUALITY = 0.55
MIN_VISIBILITY = 0.35
MIN_DETECTION_RATIO = 0.5
MIN_LANDMARK_STABILITY = 0.55
MAX_HEAD_ROLL_DEGREES = 25.0
MAX_YAW_PROXY = 0.32
MIN_EYE_DISTANCE = 0.06
FRAME_MARGIN = 0.015
# Nose tip, eye/mouth corners, forehead, chin, and cheek edges.
REQUIRED_LANDMARKS = (1, 10, 33, 61, 152, 234, 263, 291, 454)


class FaceLandmark(BaseModel):
    x: float
    y: float
    z: float = 0.0
    visibility: float | None = Field(default=None, ge=0.0, le=1.0)


class FaceMeasurementRequest(BaseModel):
    landmarks: list[FaceLandmark]
    sample_count: int = Field(default=1, ge=1, le=30)
    detected_sample_count: int = Field(default=1, ge=0, le=30)
    landmark_stability: float = Field(default=1.0, ge=0.0, le=1.0)
    baseline_features: dict[str, float] = Field(default_factory=dict)


class FaceMeasurementError(BaseModel):
    code: str
    message: str


class FaceResult(BaseModel):
    success: bool
    quality: float
    features: dict[str, float]
    change_from_baseline: dict = Field(default_factory=dict)
    error: FaceMeasurementError | None = None


def _failure(code: str, message: str, quality: float = 0.0) -> FaceResult:
    return FaceResult(
        success=False,
        quality=round(max(0.0, min(1.0, quality)), 3),
        features={},
        error=FaceMeasurementError(code=code, message=message),
    )


def face_check(request: FaceMeasurementRequest) -> FaceResult:
    if request.detected_sample_count == 0 or not request.landmarks:
        return _failure("no_face", "죄송하지만 얼굴을 찾지 못했습니다. 준비되시면 카메라를 편안히 바라봐 주시겠어요?")
    if len(request.landmarks) <= max(REQUIRED_LANDMARKS):
        return _failure("insufficient_landmarks", "얼굴 특징점을 충분히 찾지 못했습니다.")

    detection_ratio = min(1.0, request.detected_sample_count / request.sample_count)
    points = [request.landmarks[index] for index in REQUIRED_LANDMARKS]
    reported_visibility = [point.visibility for point in points if point.visibility is not None]
    visibility_quality = fmean(reported_visibility) if reported_visibility else 1.0
    # Detection ratio already has its own hard floor. Keep it as a modest
    # confidence penalty so four good frames are not rejected only because
    # four neighboring frames were missed.
    detection_quality = 0.7 + (0.3 * detection_ratio)
    quality = visibility_quality * detection_quality * request.landmark_stability
    if detection_ratio < MIN_DETECTION_RATIO:
        return _failure("unstable_face", "얼굴 인식이 안정적이지 않습니다. 가능하시다면 잠시 자세를 유지해 주세요.", quality)
    if request.landmark_stability < MIN_LANDMARK_STABILITY:
        return _failure("unstable_face", "얼굴이 움직이거나 특징점이 흔들립니다. 가능하시다면 카메라를 바라보며 잠시 자세를 유지해 주세요.", quality)
    if reported_visibility and min(reported_visibility) < MIN_VISIBILITY:
        return _failure("low_visibility", "얼굴 일부가 가려져 있습니다. 괜찮으시다면 카메라 앞에서 다시 한번 확인해 주시겠어요?", quality)

    if any(
        point.x < FRAME_MARGIN or point.x > 1 - FRAME_MARGIN
        or point.y < FRAME_MARGIN or point.y > 1 - FRAME_MARGIN
        for point in points
    ):
        return _failure("out_of_frame", "얼굴 전체가 화면에 보이도록 편안한 위치로 조금만 조정해 주시겠어요?", quality)

    nose = request.landmarks[1]
    left_eye, right_eye = request.landmarks[33], request.landmarks[263]
    left_mouth, right_mouth = request.landmarks[61], request.landmarks[291]
    left_cheek, right_cheek = request.landmarks[234], request.landmarks[454]
    face_width = math.hypot(right_eye.x - left_eye.x, right_eye.y - left_eye.y)
    if face_width < MIN_EYE_DISTANCE:
        return _failure("face_too_small", "얼굴이 작게 보입니다. 가능하시다면 카메라 쪽으로 조금만 가까이 와 주시겠어요?", quality)

    head_roll_radians = math.atan2(right_eye.y - left_eye.y, right_eye.x - left_eye.x)
    head_roll_degrees = math.degrees(head_roll_radians)
    if abs(head_roll_degrees) > MAX_HEAD_ROLL_DEGREES:
        return _failure("not_frontal", "가능하시다면 고개를 편안히 세우고 카메라를 바라봐 주시겠어요?", quality)

    eye_center_x = (left_eye.x + right_eye.x) / 2
    eye_center_y = (left_eye.y + right_eye.y) / 2
    cosine = math.cos(-head_roll_radians)
    sine = math.sin(-head_roll_radians)

    def aligned(point: FaceLandmark) -> tuple[float, float]:
        dx = point.x - eye_center_x
        dy = point.y - eye_center_y
        return (
            dx * cosine - dy * sine,
            dx * sine + dy * cosine,
        )

    aligned_nose = aligned(nose)
    aligned_left_mouth = aligned(left_mouth)
    aligned_right_mouth = aligned(right_mouth)
    aligned_left_cheek = aligned(left_cheek)
    aligned_right_cheek = aligned(right_cheek)
    left_span = abs(aligned_nose[0] - aligned_left_cheek[0])
    right_span = abs(aligned_right_cheek[0] - aligned_nose[0])
    cheek_width = left_span + right_span
    if cheek_width < 1e-6:
        return _failure("invalid_geometry", "얼굴 위치를 계산하지 못했습니다.", quality)
    yaw_proxy = abs(left_span - right_span) / cheek_width
    if yaw_proxy > MAX_YAW_PROXY:
        return _failure("not_frontal", "가능하시다면 얼굴을 편안히 세우고 카메라를 바라봐 주시겠어요?", quality)

    if quality < MIN_QUALITY:
        return _failure("low_quality", "얼굴을 선명하게 확인하기 어렵습니다. 가능하실 때 주변 밝기를 확인해 주시겠어요?", quality)

    mouth_mid_y = (aligned_left_mouth[1] + aligned_right_mouth[1]) / 2
    features = {
        "mouth_tilt": round((aligned_right_mouth[1] - aligned_left_mouth[1]) / face_width, 4),
        "nose_center_offset": round(aligned_nose[0] / face_width, 4),
        "mouth_eye_distance": round(mouth_mid_y / face_width, 4),
        "head_roll_degrees": round(head_roll_degrees, 2),
        "yaw_proxy": round(yaw_proxy, 4),
        "landmark_stability": round(request.landmark_stability, 3),
        "measurement_quality": round(quality, 3),
    }
    change = {
        key: round(value - request.baseline_features[key], 4)
        for key, value in features.items()
        if key in request.baseline_features
    }
    return FaceResult(
        success=True,
        quality=round(quality, 3),
        features=features,
        change_from_baseline=change,
    )
