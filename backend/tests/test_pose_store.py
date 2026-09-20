import tempfile
import unittest
from pathlib import Path

from backend.app.pose_store import FaceBaselineSampleRequest, PoseBaselineSampleRequest, PoseDataStore


def pose_features(angle_difference: float = 2.0, wrist_difference: float = 0.01) -> dict[str, float]:
    return {
        "left_arm_angle": 170.0,
        "right_arm_angle": 168.0,
        "arm_angle_difference": angle_difference,
        "left_arm_height": 0.22,
        "right_arm_height": 0.21,
        "wrist_height_difference": wrist_difference,
        "measurement_quality": 0.95,
    }


def face_features(mouth_tilt: float = 0.01) -> dict[str, float]:
    return {
        "mouth_tilt": mouth_tilt,
        "nose_center_offset": 0.01,
        "mouth_eye_distance": 0.7,
        "measurement_quality": 0.95,
    }


class PoseDataStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = PoseDataStore(Path(self.temporary_directory.name))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_baseline_is_initially_unavailable(self) -> None:
        baseline = self.store.get_baseline()
        comparison = self.store.compare_to_baseline(pose_features())

        self.assertFalse(baseline["exists"])
        self.assertFalse(baseline["ready"])
        self.assertFalse(comparison["available"])

    def test_three_samples_create_baseline(self) -> None:
        for _ in range(3):
            baseline = self.store.add_baseline_sample(
                PoseBaselineSampleRequest(features=pose_features())
            )

        self.assertTrue(baseline["ready"])
        self.assertEqual(baseline["sample_count"], 3)
        self.assertEqual(baseline["summary"]["arm_angle_difference"]["mean"], 2.0)

    def test_similar_pose_is_within_personal_range(self) -> None:
        for value in (1.0, 2.0, 3.0):
            self.store.add_baseline_sample(
                PoseBaselineSampleRequest(features=pose_features(angle_difference=value))
            )

        comparison = self.store.compare_to_baseline(pose_features(angle_difference=4.0))

        self.assertTrue(comparison["available"])
        self.assertFalse(comparison["significant_change"])

    def test_large_left_right_difference_is_reported_as_change(self) -> None:
        for value in (1.0, 2.0, 3.0):
            self.store.add_baseline_sample(
                PoseBaselineSampleRequest(features=pose_features(angle_difference=value))
            )

        comparison = self.store.compare_to_baseline(pose_features(angle_difference=30.0))

        self.assertTrue(comparison["significant_change"])
        self.assertTrue(comparison["features"]["arm_angle_difference"]["changed"])

    def test_measurement_is_appended_to_daily_history(self) -> None:
        self.store.save_measurement({"success": True, "quality": 0.9})
        history_files = list((Path(self.temporary_directory.name) / "history").glob("*.json"))

        self.assertEqual(len(history_files), 1)
        self.assertIn("pose_measurements", history_files[0].read_text(encoding="utf-8"))

    def test_three_face_samples_create_comparable_baseline(self) -> None:
        for value in (0.0, 0.01, 0.02):
            baseline = self.store.add_face_baseline_sample(
                FaceBaselineSampleRequest(features=face_features(value))
            )

        comparison = self.store.compare_face_to_baseline(face_features(0.2))
        self.assertTrue(baseline["ready"])
        self.assertTrue(comparison["available"])
        self.assertTrue(comparison["significant_change"])

    def test_face_measurement_is_appended_to_daily_history(self) -> None:
        self.store.save_face_measurement({"success": True, "quality": 0.9})
        history = self.store.get_recent_history(1)[0]
        self.assertIn("face_measurements", history)

if __name__ == "__main__":
    unittest.main()
