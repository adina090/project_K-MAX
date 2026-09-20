import unittest

from backend.app.pose_tool import Landmark, PoseMeasurementRequest, stretch_check


def valid_landmarks() -> list[Landmark]:
    landmarks = [
        Landmark(x=0.5, y=0.5, visibility=0.95, presence=0.95)
        for _ in range(33)
    ]
    landmarks[11] = Landmark(x=0.35, y=0.4, visibility=0.95, presence=0.95)
    landmarks[13] = Landmark(x=0.35, y=0.55, visibility=0.95, presence=0.95)
    landmarks[15] = Landmark(x=0.35, y=0.7, visibility=0.95, presence=0.95)
    landmarks[12] = Landmark(x=0.65, y=0.4, visibility=0.95, presence=0.95)
    landmarks[14] = Landmark(x=0.65, y=0.55, visibility=0.95, presence=0.95)
    landmarks[16] = Landmark(x=0.65, y=0.7, visibility=0.95, presence=0.95)
    return landmarks


class StretchCheckTests(unittest.TestCase):
    def test_valid_pose_returns_structured_features(self) -> None:
        result = stretch_check(
            PoseMeasurementRequest(
                landmarks=valid_landmarks(), sample_count=5, detected_sample_count=5
            )
        )

        self.assertTrue(result.success)
        self.assertGreaterEqual(result.quality, 0.65)
        self.assertEqual(result.features["left_arm_angle"], 180.0)
        self.assertIsNone(result.error)

    def test_browser_landmarks_without_presence_are_valid(self) -> None:
        landmarks = [
            Landmark(x=point.x, y=point.y, z=point.z, visibility=point.visibility)
            for point in valid_landmarks()
        ]

        result = stretch_check(
            PoseMeasurementRequest(
                landmarks=landmarks, sample_count=8, detected_sample_count=8
            )
        )

        self.assertTrue(result.success)
        self.assertGreaterEqual(result.quality, 0.65)

    def test_arm_angle_accounts_for_camera_aspect_ratio(self) -> None:
        landmarks = valid_landmarks()
        landmarks[11] = Landmark(x=0.25, y=0.25, visibility=0.95)
        landmarks[13] = Landmark(x=0.5, y=0.5, visibility=0.95)
        landmarks[15] = Landmark(x=0.75, y=0.25, visibility=0.95)

        result = stretch_check(
            PoseMeasurementRequest(
                landmarks=landmarks,
                sample_count=5,
                detected_sample_count=5,
                frame_width=1280,
                frame_height=720,
            )
        )

        self.assertTrue(result.success)
        self.assertAlmostEqual(result.features["left_arm_angle"], 121.28, places=2)

    def test_missing_pose_is_not_treated_as_abnormal(self) -> None:
        result = stretch_check(
            PoseMeasurementRequest(landmarks=[], sample_count=8, detected_sample_count=0)
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "no_pose")
        self.assertEqual(result.features, {})

    def test_occluded_arm_requests_retry(self) -> None:
        landmarks = valid_landmarks()
        landmarks[15].visibility = 0.2
        result = stretch_check(
            PoseMeasurementRequest(
                landmarks=landmarks, sample_count=5, detected_sample_count=5
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "low_visibility")

    def test_unstable_detection_requests_retry(self) -> None:
        result = stretch_check(
            PoseMeasurementRequest(
                landmarks=valid_landmarks(), sample_count=8, detected_sample_count=2
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "unstable_pose")

    def test_arm_outside_frame_requests_repositioning(self) -> None:
        landmarks = valid_landmarks()
        landmarks[16].x = 1.01
        result = stretch_check(
            PoseMeasurementRequest(
                landmarks=landmarks, sample_count=5, detected_sample_count=5
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "out_of_frame")


if __name__ == "__main__":
    unittest.main()
