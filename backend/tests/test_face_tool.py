import math
import unittest

from backend.app.face_tool import FaceLandmark, FaceMeasurementRequest, face_check


def landmarks(**overrides):
    points = [FaceLandmark(x=0.5, y=0.5) for _ in range(468)]
    points[1] = FaceLandmark(x=0.5, y=0.55)
    points[33] = FaceLandmark(x=0.35, y=0.4)
    points[263] = FaceLandmark(x=0.65, y=0.4)
    points[61] = FaceLandmark(x=0.42, y=0.62)
    points[291] = FaceLandmark(x=0.58, y=0.62)
    points[234] = FaceLandmark(x=0.25, y=0.52)
    points[454] = FaceLandmark(x=0.75, y=0.52)
    for index, values in overrides.items():
        points[index] = FaceLandmark(**values)
    return points


class FaceToolTests(unittest.TestCase):
    def test_valid_face_returns_asymmetry_features(self):
        result = face_check(FaceMeasurementRequest(landmarks=landmarks()))
        self.assertTrue(result.success)
        self.assertIn("mouth_tilt", result.features)

    def test_missing_face_is_retryable(self):
        result = face_check(FaceMeasurementRequest(landmarks=[], detected_sample_count=0))
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "no_face")

    def test_low_visibility_is_reported(self):
        points = landmarks()
        points[61] = FaceLandmark(x=0.42, y=0.62, visibility=0.1)
        result = face_check(FaceMeasurementRequest(landmarks=points))
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "low_visibility")

    def test_baseline_difference_is_structured(self):
        result = face_check(FaceMeasurementRequest(landmarks=landmarks(), baseline_features={"mouth_tilt": 0.2}))
        self.assertIn("mouth_tilt", result.change_from_baseline)

    def test_browser_landmarks_without_visibility_are_valid(self):
        result = face_check(FaceMeasurementRequest(landmarks=landmarks(), sample_count=8, detected_sample_count=8))
        self.assertTrue(result.success)

    def test_unstable_landmarks_request_retry(self):
        result = face_check(FaceMeasurementRequest(landmarks=landmarks(), landmark_stability=0.4))
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "unstable_face")

    def test_moderate_landmark_movement_is_accepted(self):
        result = face_check(FaceMeasurementRequest(landmarks=landmarks(), landmark_stability=0.6))
        self.assertTrue(result.success)

    def test_four_of_eight_detected_frames_are_accepted(self):
        result = face_check(FaceMeasurementRequest(
            landmarks=landmarks(), sample_count=8, detected_sample_count=4, landmark_stability=1.0,
        ))
        self.assertTrue(result.success)

    def test_turned_face_requests_frontal_position(self):
        points = landmarks()
        points[1] = FaceLandmark(x=0.62, y=0.55)
        result = face_check(FaceMeasurementRequest(landmarks=points))
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "not_frontal")

    def test_large_head_roll_requests_frontal_position(self):
        points = landmarks()
        points[33] = FaceLandmark(x=0.35, y=0.32)
        points[263] = FaceLandmark(x=0.65, y=0.48)
        result = face_check(FaceMeasurementRequest(landmarks=points))
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "not_frontal")

    def test_moderate_head_roll_is_accepted_and_normalized(self):
        points = landmarks()
        points[33] = FaceLandmark(x=0.35, y=0.35)
        points[263] = FaceLandmark(x=0.65, y=0.45)
        result = face_check(FaceMeasurementRequest(landmarks=points))
        self.assertTrue(result.success)

    def test_small_head_roll_is_removed_from_mouth_tilt(self):
        points = landmarks()
        center_x, center_y = 0.5, 0.4
        angle = math.radians(10)
        cosine, sine = math.cos(angle), math.sin(angle)
        for index in (1, 10, 33, 61, 152, 234, 263, 291, 454):
            point = points[index]
            dx, dy = point.x - center_x, point.y - center_y
            points[index] = FaceLandmark(
                x=center_x + dx * cosine - dy * sine,
                y=center_y + dx * sine + dy * cosine,
            )

        result = face_check(FaceMeasurementRequest(landmarks=points))
        self.assertTrue(result.success)
        self.assertAlmostEqual(result.features["mouth_tilt"], 0.0, places=3)


if __name__ == "__main__":
    unittest.main()
