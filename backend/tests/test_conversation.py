import tempfile
import unittest
from pathlib import Path

from backend.app.conversation import (
    ConversationService,
    ConversationStore,
    NextConversationAction,
    build_text_context,
)


class FakeGenerator:
    provider = "gemini"

    def __init__(self):
        self.opening_calls = 0
        self.received_history = []

    def opening_question(self, recent_history):
        self.opening_calls += 1
        self.received_history = recent_history
        return "오늘 하루 중 기억에 남는 일을 이야기해 주세요."

    def next_action(self, conversation, response):
        if "갑자기" in response:
            return NextConversationAction(
                action="finish",
                message="즉시 도움을 요청해 주세요.",
                urgent_concern=True,
                concern_reason="갑작스러운 말하기 어려움이 보고되었습니다.",
            )
        if len(response) < 8:
            return NextConversationAction(action="follow_up", message="어떤 점이 가장 기억에 남았나요?")
        if "키보드" in response:
            return NextConversationAction(
                action="follow_up",
                message="답변을 정확히 이해하지 못했어요. 다시 말씀해 주시겠어요?",
                response_relevant=False,
            )
        return NextConversationAction(action="finish", message="이야기해 주셔서 고마워요.")


class ConversationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = ConversationStore(Path(self.temporary_directory.name))
        self.generator = FakeGenerator()
        self.service = ConversationService(self.store, self.generator)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_start_requests_user_recording_and_saves_history(self) -> None:
        result = self.service.start_conversation("event-12345678")

        self.assertEqual(result.action, "ask")
        self.assertTrue(result.recording_requested)
        self.assertEqual(result.provider, "gemini")
        self.assertEqual(len(self.store.recent()), 1)

    def test_same_scheduler_event_reuses_question(self) -> None:
        first = self.service.start_conversation("event-12345678")
        second = self.service.start_conversation("event-12345678")

        self.assertEqual(first.conversation_id, second.conversation_id)
        self.assertEqual(self.generator.opening_calls, 1)

    def test_recent_history_is_given_to_next_conversation(self) -> None:
        self.service.start_conversation("event-12345678")
        self.service.start_conversation("event-abcdefgh")

        self.assertEqual(len(self.generator.received_history), 1)
        self.assertIn("agent_question", self.generator.received_history[0])

    def test_conversation_continues_until_user_says_no_more(self) -> None:
        started = self.service.start_conversation("event-12345678")
        follow_up = self.service.respond(started.conversation_id, "좋아요")
        continued = self.service.respond(started.conversation_id, "조금 더 이야기할게요")
        finished = self.service.respond(started.conversation_id, "더 할 말은 없어요")

        self.assertEqual(follow_up.action, "follow_up")
        self.assertTrue(follow_up.recording_requested)
        self.assertEqual(continued.action, "follow_up")
        self.assertEqual(finished.action, "finish")
        self.assertFalse(finished.recording_requested)

    def test_text_context_is_saved_without_audio_data(self) -> None:
        started = self.service.start_conversation("event-12345678")
        self.service.respond(started.conversation_id, "오늘은 산책을 했어요.")

        record = self.store.get(started.conversation_id)
        self.assertEqual(record["context_analysis"]["input_mode"], "text")
        self.assertNotIn("audio", record["context_analysis"])

    def test_text_context_contains_question_response_and_recent_turns(self) -> None:
        context = build_text_context(
            {"agent_question": "오늘 기분은 어때요?", "turns": [{"role": "agent", "message": "오늘 기분은 어때요?"}]},
            "괜찮아요.",
        )

        self.assertEqual(context["current_question"], "오늘 기분은 어때요?")
        self.assertEqual(context["text_response"], "괜찮아요.")
        self.assertEqual(context["voice_features"], {})
        self.assertIsNone(context["measurement_quality"])

    def test_text_context_uses_latest_agent_follow_up_as_current_question(self) -> None:
        context = build_text_context(
            {
                "agent_question": "오늘 기분은 어때요?",
                "turns": [
                    {"role": "agent", "message": "오늘 기분은 어때요?"},
                    {"role": "user", "message": "좋아요."},
                    {"role": "agent", "message": "무엇이 가장 좋았나요?"},
                ],
            },
            "산책이 좋았어요.",
        )
        self.assertEqual(context["current_question"], "무엇이 가장 좋았나요?")

    def test_first_response_always_offers_fifteen_second_follow_up(self) -> None:
        started = self.service.start_conversation("event-12345678")
        result = self.service.respond(started.conversation_id, "오늘은 산책을 오래 했어요.", "voice")

        self.assertEqual(result.action, "follow_up")
        self.assertEqual(result.recording_limit_seconds, 15)
        self.assertIn("혹시 더 들려주실 말씀이 있으신가요?", result.message)
        record = self.store.get(started.conversation_id)
        self.assertEqual(record["context_analysis"]["input_mode"], "voice")

    def test_follow_up_timeout_finishes_conversation(self) -> None:
        started = self.service.start_conversation("event-12345678")
        self.service.respond(started.conversation_id, "오늘은 산책을 오래 했어요.", "voice")
        finished = self.service.timeout(started.conversation_id)

        self.assertEqual(finished.action, "finish")
        self.assertFalse(finished.recording_requested)

    def test_explicit_sudden_symptom_sets_urgent_alert(self) -> None:
        started = self.service.start_conversation("event-12345678")
        result = self.service.respond(started.conversation_id, "갑자기 말하기가 어려워요.", "voice")

        self.assertTrue(result.urgent_alert)
        self.assertEqual(result.action, "finish")

    def test_combined_measurement_change_uses_fixed_confirmation_question(self) -> None:
        measurement_context = {
            "pose": {
                "success": True,
                "change_from_baseline": {
                    "available": True,
                    "features": {"wrist_height_difference": {"changed": True}},
                },
            },
            "face": {
                "success": True,
                "change_from_baseline": {
                    "available": True,
                    "features": {"mouth_tilt": {"changed": True}},
                },
            },
        }
        started = self.service.start_conversation("event-screening-1", measurement_context)
        self.assertIn("팔과 얼굴", started.message)

        urgent = self.service.respond(started.conversation_id, "네", "voice")
        self.assertTrue(urgent.urgent_alert)
        self.assertEqual(urgent.action, "finish")

    def test_unrelated_screening_answer_repeats_fixed_confirmation(self) -> None:
        measurement_context = {
            "pose": {
                "success": True,
                "change_from_baseline": {
                    "available": True,
                    "features": {"wrist_height_difference": {"changed": True}},
                },
            },
        }
        started = self.service.start_conversation("event-screening-2", measurement_context)
        repeated = self.service.respond(started.conversation_id, "오늘 점심 키보드 좋아", "voice")

        self.assertEqual(repeated.action, "follow_up")
        self.assertIn("‘있어요’", repeated.message)
        self.assertNotIn("점심", repeated.message)

    def test_two_context_mismatches_request_additional_checks_when_conversation_ends(self) -> None:
        started = self.service.start_conversation("event-context-issues", routine_mode="periodic")
        self.service.respond(started.conversation_id, "오늘 점심 키보드 좋아", "voice")
        second = self.service.respond(started.conversation_id, "키보드 점심 창문", "voice")
        finished = self.service.respond(started.conversation_id, "없어요", "voice")

        self.assertEqual(second.action, "follow_up")
        self.assertTrue(second.needs_additional_checks)
        self.assertEqual(finished.action, "finish")
        self.assertTrue(finished.needs_additional_checks)

    def test_multiple_voice_transcripts_are_preserved(self) -> None:
        started = self.service.start_conversation("event-12345678")
        self.store.save_transcript(started.conversation_id, "첫 번째 답변", 3.0)
        self.store.save_transcript(started.conversation_id, "두 번째 답변", 2.0)

        record = self.store.get(started.conversation_id)
        self.assertEqual(len(record["voice_transcripts"]), 2)
        self.assertEqual(record["voice_transcripts"][0]["transcript"], "첫 번째 답변")

    def test_voice_transcript_is_saved_only_when_response_is_accepted(self) -> None:
        started = self.service.start_conversation("event-voice-accepted")
        self.service.respond(started.conversation_id, "오늘은 산책을 했습니다.", "voice", 3.2)

        record = self.store.get(started.conversation_id)
        self.assertEqual(len(record["voice_transcripts"]), 1)
        self.assertEqual(record["voice_transcripts"][0]["transcript"], "오늘은 산책을 했습니다.")
        self.assertEqual(record["voice_transcripts"][0]["duration"], 3.2)


if __name__ == "__main__":
    unittest.main()
