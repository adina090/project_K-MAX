import json
import os
import re
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from .stroke_screening import (
    assess_response,
    classify_screening_response,
    screening_question,
    summarize_measurements,
)


class ConversationStartRequest(BaseModel):
    event_id: str = Field(min_length=8, max_length=128)
    measurement_context: dict[str, Any] = Field(default_factory=dict)
    routine_mode: Literal["morning", "periodic"] = "morning"


class ConversationReplyRequest(BaseModel):
    conversation_id: str = Field(min_length=8, max_length=128)
    response: str = Field(min_length=1, max_length=2000)
    input_mode: Literal["text", "voice"] = "text"
    duration: float | None = Field(default=None, ge=0.0, le=60.0)


class ConversationTimeoutRequest(BaseModel):
    conversation_id: str = Field(min_length=8, max_length=128)


class ConversationResult(BaseModel):
    success: bool = True
    conversation_id: str
    message: str
    action: Literal["ask", "follow_up", "finish"]
    recording_requested: bool
    recording_limit_seconds: int | None = None
    urgent_alert: bool = False
    urgent_message: str | None = None
    needs_additional_checks: bool = False
    routine_mode: Literal["morning", "periodic"] = "morning"
    provider: Literal["gemini", "local_fallback"]


class QuestionDraft(BaseModel):
    message: str = Field(min_length=5, max_length=300)


class NextConversationAction(BaseModel):
    action: Literal["follow_up", "finish"]
    message: str = Field(min_length=2, max_length=300)
    urgent_concern: bool = False
    concern_reason: str = Field(default="", max_length=300)
    response_relevant: bool = True
    context_concern: bool = False


class ConversationGenerator(Protocol):
    provider: Literal["gemini", "local_fallback"]

    def opening_question(self, recent_history: list[dict[str, Any]]) -> str:
        ...

    def next_action(self, conversation: dict[str, Any], response: str) -> NextConversationAction:
        ...


CONVERSATION_PROMPT = """
당신의 이름은 '동행이'이며, K-MAX 프로젝트의 AI 건강 동반자다.
자신을 소개하거나 지칭할 때는 반드시 '동행이'라는 이름을 사용하고 다른 이름을 만들지 않는다.
어르신께서 편안하게 한두 문장 이상 말씀하시도록 돕는다.
- 어르신을 한 분의 성인으로 존중하고 항상 정중하고 자연스러운 존댓말을 사용한다.
- 반말, 훈계조, 유아를 대하듯 단순화한 표현, 재촉하거나 명령하는 표현은 사용하지 않는다.
- 답변을 재촉하지 않으며, 선택권을 존중하는 부드러운 표현을 사용한다.
- 의료 진단 질문보다 식사, 기분, 하루 일과 같은 자연스러운 일상 질문을 우선한다.
- 최근 질문과 같은 문장을 반복하지 않는다.
- 한 번에 질문 하나만 하고 쉬운 한국어를 사용한다.
- 답변이 충분하면 짧게 공감하고 대화를 마친다.
- 답변이 너무 짧거나 의미가 불분명할 때만 후속 질문을 한다.
- 답변의 맥락 연결 여부를 현재 질문과 이전 대화만으로 판단한다.
- 현재 질문과 관계없는 답변을 다른 주제의 정상 답변으로 해석하지 않는다.
- 전사문이 불분명하거나 현재 질문과 무관하면 이해했다고 꾸미지 말고 같은 내용을 쉽게 다시 확인한다.
- response_relevant는 답변이 최신 질문과 자연스럽게 연결될 때만 true다.
- context_concern은 두 차례 이상 문맥 연결이 매우 어렵거나 사용자가 갑작스러운 이해·표현 어려움을 직접 보일 때만 true다.
- 음성 특징이나 의료적 판단이 제공되지 않은 경우 임의로 추정하지 않는다.
- 진단이나 위급 상황을 추측하지 않는다.
- 답변에 자연스럽게 공감하고 짧고 따뜻하게 응답한다.
- 긴급 여부는 서버의 고정된 FAST 선별 규칙이 최종 결정하므로 임의로 urgent_concern을 설정하지 않는다.
- 단순한 전사 오류, 짧은 답변, 측정값 하나만으로 질환을 추측하지 않는다.
""".strip()


END_CONVERSATION_PATTERNS = (
    r"^(?:아니요?|아뇨|없어|없어요|없습니다|없다|그만|끝|됐어|됐어요)[,.!~\s]*$",
    r"^(?:더\s*)?(?:할\s*말(?:이|은)?)?\s*없(?:어|어요|습니다)[,.!~\s]*$",
)


def wants_to_end_conversation(response: str) -> bool:
    normalized = " ".join(response.strip().lower().split())
    return any(re.search(pattern, normalized) for pattern in END_CONVERSATION_PATTERNS)


def build_text_context(conversation: dict[str, Any], response: str) -> dict[str, Any]:
    """Build the context sent to the conversation model without raw audio."""
    turns = conversation.get("turns", [])
    latest_agent_message = next(
        (turn.get("message", "") for turn in reversed(turns) if turn.get("role") == "agent"),
        conversation.get("agent_question", ""),
    )
    return {
        "current_question": latest_agent_message,
        "text_response": response,
        "recent_turns": turns[-6:],
        "voice_features": conversation.get("voice_features", {}),
        "measurement_quality": conversation.get("measurement_quality"),
        "measurement_context": conversation.get("measurement_context", {}),
    }


class GeminiConversationGenerator:
    provider: Literal["gemini"] = "gemini"

    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        try:
            from google import genai
            from google.genai import types
        except ImportError as error:
            raise RuntimeError("google-genai is not installed") from error
        self._client = genai.Client(api_key=api_key)
        self._types = types
        self._model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    def _generate(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=self._types.GenerateContentConfig(
                system_instruction=CONVERSATION_PROMPT,
                temperature=0.3,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        if response.parsed is not None:
            return response.parsed
        return schema.model_validate_json(response.text)

    def opening_question(self, recent_history: list[dict[str, Any]]) -> str:
        recent_questions = [item.get("agent_question", "") for item in recent_history[-5:]]
        draft = self._generate(
            "주기적 확인 대화를 시작할 질문을 하나 생성하세요.\n최근 질문: "
            + json.dumps(recent_questions, ensure_ascii=False),
            QuestionDraft,
        )
        return draft.message

    def next_action(self, conversation: dict[str, Any], response: str) -> NextConversationAction:
        return self._generate(
            "현재 대화와 사용자의 새 답변을 보고 후속 질문 또는 종료를 선택하세요.\n"
            + json.dumps(build_text_context(conversation, response), ensure_ascii=False),
            NextConversationAction,
        )


class LocalConversationGenerator:
    provider: Literal["local_fallback"] = "local_fallback"
    QUESTIONS = (
        "오늘 식사는 어떠셨나요? 기억에 남는 음식이 있으시면 편하게 말씀해 주세요.",
        "오늘 하루 중 가장 기억에 남는 일이 있으셨다면 편하게 들려주시겠어요?",
        "지금 기분은 어떠신가요? 괜찮으시다면 그렇게 느끼신 이유도 들려주세요.",
    )

    def opening_question(self, recent_history: list[dict[str, Any]]) -> str:
        used = {item.get("agent_question") for item in recent_history[-3:]}
        return next((question for question in self.QUESTIONS if question not in used), self.QUESTIONS[0])

    def next_action(self, conversation: dict[str, Any], response: str) -> NextConversationAction:
        if len(response.strip()) < 8:
            return NextConversationAction(
                action="follow_up",
                message="괜찮으시다면 조금 더 자세히 말씀해 주실 수 있을까요?",
            )
        return NextConversationAction(
            action="finish",
            message="말씀해 주셔서 감사합니다. 다음 확인 시간에 다시 찾아뵙겠습니다.",
        )


class ConversationStore:
    def __init__(self, root: Path):
        self.root = root
        self.index_file = root / "index.json"
        self._lock = Lock()

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        with path.open(encoding="utf-8") as file:
            return json.load(file)

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = path.with_suffix(path.suffix + ".tmp")
        temporary_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary_file.replace(path)

    def find_by_event(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            index = self._read_json(self.index_file, {})
            relative_path = index.get(event_id)
            if not relative_path:
                return None
            return self._read_json(self.root / relative_path, None)

    def get(self, conversation_id: str) -> dict[str, Any]:
        with self._lock:
            matches = list(self.root.glob(f"*/{conversation_id}.json"))
            if not matches:
                raise ValueError("Conversation was not found")
            return self._read_json(matches[0], {})

    def recent(self, limit: int = 5) -> list[dict[str, Any]]:
        with self._lock:
            paths = sorted(self.root.glob("*/*.json"), reverse=True)[:limit]
            return [self._read_json(path, {}) for path in reversed(paths)]

    def create(
        self,
        event_id: str,
        question: str,
        provider: str,
        measurement_context: dict[str, Any] | None = None,
        screening_context: dict[str, Any] | None = None,
        routine_mode: Literal["morning", "periodic"] = "morning",
    ) -> dict[str, Any]:
        now = datetime.now().astimezone()
        conversation_id = uuid4().hex
        record = {
            "conversation_id": conversation_id,
            "event_id": event_id,
            "timestamp": now.isoformat(timespec="seconds"),
            "agent_question": question,
            "transcript": "",
            "voice_features": {},
            "comparison_to_baseline": {},
            "context_summary": "",
            "next_action": "awaiting_response",
            "urgent_alert": False,
            "urgent_message": None,
            "provider": provider,
            "measurement_context": measurement_context or {},
            "screening_context": screening_context or {},
            "routine_mode": routine_mode,
            "context_issue_count": 0,
            "voice_concern": False,
            "follow_up_count": 0,
            "turns": [{"role": "agent", "message": question}],
        }
        relative_path = Path(now.date().isoformat()) / f"{conversation_id}.json"
        with self._lock:
            index = self._read_json(self.index_file, {})
            existing_path = index.get(event_id)
            if existing_path:
                return self._read_json(self.root / existing_path, {})
            self._write_json(self.root / relative_path, record)
            index[event_id] = str(relative_path)
            self._write_json(self.index_file, index)
        return record

    def add_response(
        self,
        conversation_id: str,
        response: str,
        next_action: NextConversationAction,
        input_mode: Literal["text", "voice"] = "text",
    ) -> dict[str, Any]:
        with self._lock:
            matches = list(self.root.glob(f"*/{conversation_id}.json"))
            if not matches:
                raise ValueError("Conversation was not found")
            path = matches[0]
            record = self._read_json(path, {})
            record.setdefault("turns", []).extend(
                [
                    {"role": "user", "message": response},
                    {"role": "agent", "message": next_action.message},
                ]
            )
            if next_action.action == "follow_up":
                record["follow_up_count"] = int(record.get("follow_up_count", 0)) + 1
            issue_count = 0 if next_action.response_relevant else int(record.get("context_issue_count", 0)) + 1
            record["context_issue_count"] = issue_count
            if next_action.context_concern or issue_count >= 2:
                record["voice_concern"] = True
            record["next_action"] = (
                "awaiting_response" if next_action.action == "follow_up" else "finished"
            )
            record["context_analysis"] = {
                "input_mode": input_mode,
                "response_length": len(response.strip()),
                "action": next_action.action,
            }
            if next_action.urgent_concern:
                record["urgent_alert"] = True
                record["urgent_message"] = next_action.concern_reason or "갑작스러운 신경학적 증상에 대한 추가 확인이 필요합니다."
            self._write_json(path, record)
            return record

    def finish_without_response(self, conversation_id: str) -> dict[str, Any]:
        with self._lock:
            matches = list(self.root.glob(f"*/{conversation_id}.json"))
            if not matches:
                raise ValueError("Conversation was not found")
            path = matches[0]
            record = self._read_json(path, {})
            message = "추가로 하실 말씀은 없는 것으로 확인했습니다. 다음 확인 시간에 다시 찾아뵙겠습니다."
            record.setdefault("turns", []).append({"role": "agent", "message": message})
            record["next_action"] = "finished"
            record["context_analysis"] = {
                "input_mode": "voice_timeout",
                "response_length": 0,
                "action": "finish",
            }
            self._write_json(path, record)
            return record

    def save_transcript(self, conversation_id: str, transcript: str, duration: float) -> None:
        with self._lock:
            matches = list(self.root.glob(f"*/{conversation_id}.json"))
            if not matches:
                raise ValueError("Conversation was not found")
            path = matches[0]
            record = self._read_json(path, {})
            record["transcript"] = transcript
            record["transcript_duration"] = round(duration, 2)
            record.setdefault("voice_transcripts", []).append(
                {
                    "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "transcript": transcript,
                    "duration": round(duration, 2),
                }
            )
            self._write_json(path, record)


class ConversationService:
    def __init__(
        self,
        store: ConversationStore,
        generator: ConversationGenerator | None = None,
    ):
        self.store = store
        self.generator = generator or (
            GeminiConversationGenerator()
            if os.environ.get("GEMINI_API_KEY")
            else LocalConversationGenerator()
        )

    def start_conversation(
        self,
        event_id: str,
        measurement_context: dict[str, Any] | None = None,
        routine_mode: Literal["morning", "periodic"] = "morning",
    ) -> ConversationResult:
        existing = self.store.find_by_event(event_id)
        if existing:
            return self._result_from_record(existing)

        screening = summarize_measurements(measurement_context)
        fixed_question = screening_question(screening)
        history = self.store.recent(5)
        question = fixed_question or self.generator.opening_question(history)
        record = self.store.create(
            event_id,
            question,
            self.generator.provider,
            measurement_context,
            screening.as_dict(),
            routine_mode,
        )
        return self._result_from_record(record)

    def respond(
        self,
        conversation_id: str,
        response: str,
        input_mode: Literal["text", "voice"] = "text",
        duration: float | None = None,
    ) -> ConversationResult:
        conversation = self.store.get(conversation_id)
        if conversation.get("next_action") == "finished":
            return self._result_from_record(conversation)

        if input_mode == "voice" and duration is not None:
            self.store.save_transcript(conversation_id, response, duration)

        screening = summarize_measurements(conversation.get("measurement_context"))
        symptom_assessment = assess_response(response, screening)
        screening_response = (
            classify_screening_response(response, screening)
            if screening.needs_confirmation
            else None
        )
        screening_unclear = screening_response == "unclear"
        end_requested = wants_to_end_conversation(response) or screening_response == "negative"
        if symptom_assessment.urgent:
            generated = NextConversationAction(
                action="finish",
                message="갑작스러운 뇌졸중 위험 신호일 수 있어 염려됩니다. 증상이 시작된 시간을 확인하시고 지금 바로 119에 연락해 주시기 바랍니다.",
                urgent_concern=True,
                concern_reason=symptom_assessment.reason,
            )
        elif end_requested:
            generated = NextConversationAction(
                action="finish",
                message="알겠습니다. 말씀해 주셔서 감사합니다. 다음 확인 시간에 다시 찾아뵙겠습니다.",
            )
        elif screening_unclear:
            generated = NextConversationAction(
                action="follow_up",
                message="죄송하지만 말씀을 정확히 이해하지 못했습니다. 안내드린 증상이 있으시면 ‘있어요’, 없으시면 ‘없어요’라고 말씀해 주시겠어요?",
            )
        else:
            generated = self.generator.next_action(conversation, response).model_copy(update={
                "urgent_concern": False,
                "concern_reason": "",
            })
        follow_up_count = int(conversation.get("follow_up_count", 0))
        if generated.urgent_concern:
            next_action = generated.model_copy(update={"action": "finish"})
        elif end_requested:
            next_action = generated.model_copy(update={"action": "finish"})
        elif screening_unclear:
            next_action = generated.model_copy(update={"action": "follow_up", "response_relevant": False})
        else:
            follow_up_prompt = "혹시 더 들려주실 말씀이 있으신가요?"
            message = generated.message.rstrip()
            if follow_up_prompt not in message:
                message = f"{message[:300 - len(follow_up_prompt) - 1]} {follow_up_prompt}"
            next_action = generated.model_copy(update={"action": "follow_up", "message": message})
        record = self.store.add_response(conversation_id, response, next_action, input_mode)
        return ConversationResult(
            conversation_id=conversation_id,
            message=next_action.message,
            action=next_action.action,
            recording_requested=next_action.action == "follow_up",
            recording_limit_seconds=15 if next_action.action == "follow_up" else None,
            urgent_alert=bool(record.get("urgent_alert")),
            urgent_message=record.get("urgent_message"),
            needs_additional_checks=bool(record.get("voice_concern")),
            routine_mode=record.get("routine_mode", "morning"),
            provider=self.generator.provider,
        )

    def timeout(self, conversation_id: str) -> ConversationResult:
        record = self.store.finish_without_response(conversation_id)
        return self._result_from_record(record)

    @staticmethod
    def _result_from_record(record: dict[str, Any]) -> ConversationResult:
        finished = record.get("next_action") == "finished"
        turns = record.get("turns", [])
        message = turns[-1]["message"] if turns else record.get("agent_question", "")
        return ConversationResult(
            conversation_id=record["conversation_id"],
            message=message,
            action="finish" if finished else "ask",
            recording_requested=not finished,
            recording_limit_seconds=None if finished else 30,
            urgent_alert=bool(record.get("urgent_alert")),
            urgent_message=record.get("urgent_message"),
            needs_additional_checks=bool(record.get("voice_concern")),
            routine_mode=record.get("routine_mode", "morning"),
            provider=record.get("provider", "local_fallback"),
        )
