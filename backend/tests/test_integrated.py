import tempfile
import unittest
from pathlib import Path

from backend.app.agent import AgentEvaluateRequest, AgentOrchestrator, RuleBasedDecisionSession
from backend.app.conversation import ConversationService, ConversationStore, NextConversationAction
from backend.app.face_tool import FaceLandmark, FaceMeasurementRequest, face_check
from backend.app.pose_tool import Landmark, PoseMeasurementRequest, stretch_check
from backend.app.pose_store import PoseDataStore


def pose_landmarks():
    points = [Landmark(x=0.5, y=0.5, visibility=0.95) for _ in range(33)]
    for index, x in ((11, 0.35), (13, 0.35), (15, 0.35), (12, 0.65), (14, 0.65), (16, 0.65)):
        points[index] = Landmark(x=x, y={11: 0.4, 12: 0.4, 13: 0.55, 14: 0.55, 15: 0.7, 16: 0.7}[index], visibility=0.95)
    return points


class ConversationGenerator:
    provider = "local_fallback"

    def opening_question(self, recent_history):
        return "오늘 하루는 어떠셨나요?"

    def next_action(self, conversation, response):
        return NextConversationAction(action="finish", message="이야기해 주셔서 고마워요.")


class IntegratedScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.pose_store = PoseDataStore(Path(self.temp.name) / "pose")

    def tearDown(self):
        self.temp.cleanup()

    def test_morning_normal_pose_finishes_agent_flow(self):
        measurement = stretch_check(PoseMeasurementRequest(landmarks=pose_landmarks(), sample_count=8, detected_sample_count=8))
        decision = AgentOrchestrator(self.pose_store, session_factory=lambda context: RuleBasedDecisionSession(context)).evaluate(
            AgentEvaluateRequest(tool_name="stretch_check", tool_result=measurement.model_dump())
        )
        self.assertTrue(measurement.success)
        self.assertEqual(decision.action, "finish")

    def test_pose_change_requests_face_tool(self):
        decision = AgentOrchestrator(self.pose_store, session_factory=lambda context: RuleBasedDecisionSession(context)).evaluate(
            AgentEvaluateRequest(tool_name="stretch_check", tool_result={
                "success": True, "quality": 0.95, "features": {},
                "change_from_baseline": {"available": True, "significant_change": True},
            })
        )
        self.assertEqual(decision.action, "request_tool")
        self.assertEqual(decision.next_tool, "face_check")

    def test_periodic_text_conversation_finishes(self):
        service = ConversationService(ConversationStore(Path(self.temp.name) / "conversations"), ConversationGenerator())
        started = service.start_conversation("event-integrated-1")
        follow_up = service.respond(started.conversation_id, "오늘은 산책을 하면서 기분이 좋아졌어요.")
        finished = service.respond(started.conversation_id, "더 할 말은 없어요.")
        self.assertEqual(follow_up.action, "follow_up")
        self.assertEqual(finished.action, "finish")

    def test_face_tool_returns_quality_and_change(self):
        points = [FaceLandmark(x=0.5, y=0.5) for _ in range(468)]
        points[1] = FaceLandmark(x=0.5, y=0.55)
        points[33] = FaceLandmark(x=0.35, y=0.4)
        points[263] = FaceLandmark(x=0.65, y=0.4)
        points[61] = FaceLandmark(x=0.42, y=0.62)
        points[291] = FaceLandmark(x=0.58, y=0.62)
        points[234] = FaceLandmark(x=0.25, y=0.52)
        points[454] = FaceLandmark(x=0.75, y=0.52)
        result = face_check(FaceMeasurementRequest(landmarks=points, baseline_features={"mouth_tilt": 0.1}))
        self.assertTrue(result.success)
        self.assertIn("mouth_tilt", result.change_from_baseline)


if __name__ == "__main__":
    unittest.main()
