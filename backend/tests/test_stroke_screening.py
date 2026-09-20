import unittest

from backend.app.stroke_screening import (
    assess_response,
    classify_screening_response,
    screening_question,
    summarize_measurements,
)


def result(changed_features=()):
    features = {
        key: {"changed": key in changed_features}
        for key in ("arm_angle_difference", "wrist_height_difference", "mouth_tilt", "nose_center_offset")
    }
    return {
        "success": True,
        "change_from_baseline": {"available": True, "features": features},
    }


class StrokeScreeningTests(unittest.TestCase):
    def test_pose_and_face_changes_create_combined_confirmation(self):
        summary = summarize_measurements({
            "pose": result(("wrist_height_difference",)),
            "face": result(("mouth_tilt",)),
        })
        question = screening_question(summary)
        self.assertTrue(summary.pose_signal)
        self.assertTrue(summary.face_signal)
        self.assertIn("팔과 얼굴", question)

    def test_head_position_change_is_not_treated_as_face_droop(self):
        summary = summarize_measurements({"face": result(("nose_center_offset",))})
        self.assertFalse(summary.face_signal)
        self.assertIsNone(screening_question(summary))

    def test_yes_to_measurement_confirmation_is_urgent(self):
        summary = summarize_measurements({"pose": result(("wrist_height_difference",))})
        assessment = assess_response("네", summary)
        self.assertTrue(assessment.urgent)
        self.assertIn("팔", assessment.reason)

    def test_negative_answer_is_not_urgent(self):
        summary = summarize_measurements({"face": result(("mouth_tilt",))})
        self.assertFalse(assess_response("아니요, 그런 증상은 없어요.", summary).urgent)
        self.assertEqual(classify_screening_response("아니요, 그런 증상은 없어요.", summary), "negative")

    def test_unrelated_screening_answer_is_unclear(self):
        summary = summarize_measurements({"pose": result(("wrist_height_difference",))})
        self.assertEqual(classify_screening_response("오늘 점심 키보드 좋아", summary), "unclear")

    def test_non_negating_okay_phrase_does_not_hide_a_symptom(self):
        summary = summarize_measurements({})
        assessment = assess_response("괜찮지 않고 갑자기 말하기가 어려워요.", summary)
        self.assertTrue(assessment.urgent)

    def test_explicit_speech_difficulty_is_urgent_without_camera_signal(self):
        summary = summarize_measurements({})
        assessment = assess_response("갑자기 말하기가 어려워요.", summary)
        self.assertTrue(assessment.urgent)
        self.assertIn("말하기", assessment.reason)

    def test_transcription_error_is_not_a_symptom(self):
        summary = summarize_measurements({})
        self.assertFalse(assess_response("음성 인식이 잘 안 돼요.", summary).urgent)


if __name__ == "__main__":
    unittest.main()
