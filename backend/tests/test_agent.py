import tempfile
import unittest
from pathlib import Path

from backend.app.agent import (
    AgentEvaluateRequest,
    AgentOrchestrator,
    RuleBasedDecisionSession,
    ToolCall,
)
from backend.app.pose_store import PoseDataStore


def pose_result(*, success: bool = True, quality: float = 0.95, changed: bool = False) -> dict:
    return {
        "success": success,
        "quality": quality,
        "features": {"left_arm_angle": 170.0, "right_arm_angle": 169.0},
        "change_from_baseline": {
            "available": True,
            "significant_change": changed,
        },
        "error": None if success else {"code": "low_visibility"},
    }


class FakeSession:
    provider = "gemini"

    def __init__(self, calls: list[ToolCall]):
        self.calls = iter(calls)
        self.responses = []

    def next_call(self, tool_response=None) -> ToolCall:
        self.responses.append(tool_response)
        return next(self.calls)


class AgentOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = PoseDataStore(Path(self.temporary_directory.name))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def evaluate_with(self, result: dict):
        return AgentOrchestrator(
            self.store,
            session_factory=lambda context: RuleBasedDecisionSession(context),
        ).evaluate(
            AgentEvaluateRequest(tool_name="stretch_check", tool_result=result)
        )

    def test_normal_pose_finishes(self) -> None:
        decision = self.evaluate_with(pose_result())

        self.assertEqual(decision.action, "finish")
        self.assertIsNone(decision.next_tool)

    def test_changed_pose_requests_additional_tool(self) -> None:
        decision = self.evaluate_with(pose_result(changed=True))

        self.assertEqual(decision.action, "request_tool")
        self.assertEqual(decision.next_tool, "face_check")

    def test_low_quality_data_retries_current_tool(self) -> None:
        decision = self.evaluate_with(pose_result(quality=0.4))

        self.assertEqual(decision.action, "retry")
        self.assertEqual(decision.next_tool, "stretch_check")

    def test_changed_face_asks_user_instead_of_using_pose_message(self) -> None:
        decision = AgentOrchestrator(
            self.store,
            session_factory=lambda context: RuleBasedDecisionSession(context),
        ).evaluate(AgentEvaluateRequest(
            tool_name="face_check",
            tool_result={
                "success": True,
                "quality": 0.95,
                "features": {"mouth_tilt": 0.1},
                "change_from_baseline": {"available": True, "significant_change": True},
            },
        ))

        self.assertEqual(decision.action, "ask_user")
        self.assertIn("얼굴", decision.user_message)

    def test_history_tool_result_is_returned_to_agent_loop(self) -> None:
        session = FakeSession(
            [
                ToolCall("get_history", {"days": 3, "reason": "최근 변화 확인"}),
                ToolCall("finish", {"reason": "변화 없음", "user_message": "확인을 마쳤습니다."}),
            ]
        )
        orchestrator = AgentOrchestrator(self.store, session_factory=lambda _: session)

        decision = orchestrator.evaluate(
            AgentEvaluateRequest(tool_name="stretch_check", tool_result=pose_result())
        )

        self.assertEqual(decision.action, "finish")
        self.assertEqual(decision.tool_trace, ["get_history", "finish"])
        self.assertTrue(session.responses[1]["success"])


if __name__ == "__main__":
    unittest.main()
