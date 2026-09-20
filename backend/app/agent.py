import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, Field

from .pose_store import PoseDataStore
from .prompts import load_agent_prompt

logger = logging.getLogger(__name__)

AGENT_PROMPT = load_agent_prompt()

# Voice/STT is intentionally disabled for the current text-first flow.
REQUESTABLE_TOOLS = ("stretch_check", "face_check")


class AgentEvaluateRequest(BaseModel):
    tool_name: str
    tool_result: dict[str, Any]
    user_message: str | None = None


class AgentDecision(BaseModel):
    action: Literal["finish", "retry", "ask_user", "request_tool"]
    reason: str = Field(min_length=1, max_length=240)
    user_message: str = Field(min_length=1, max_length=500)
    next_tool: str | None = None
    provider: Literal["gemini", "local_fallback"]
    tool_trace: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


class DecisionSession(Protocol):
    provider: Literal["gemini", "local_fallback"]

    def next_call(self, tool_response: dict[str, Any] | None = None) -> ToolCall:
        ...


TOOL_DECLARATIONS = [
    {
        "name": "finish",
        "description": "현재 확인을 안전하게 종료한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "user_message": {"type": "string"},
            },
            "required": ["reason", "user_message"],
        },
    },
    {
        "name": "retry",
        "description": "측정 품질이 부족해 같은 Tool을 다시 요청한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "user_message": {"type": "string"},
            },
            "required": ["reason", "user_message"],
        },
    },
    {
        "name": "get_history",
        "description": "판단에 필요한 최근 JSON 측정 이력을 조회한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 30},
                "reason": {"type": "string"},
            },
            "required": ["days", "reason"],
        },
    },
    {
        "name": "ask_user",
        "description": "판단에 꼭 필요한 정보를 사용자에게 짧게 질문한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["question", "reason"],
        },
    },
    {
        "name": "request_tool",
        "description": "필요한 최소 측정 Tool 하나를 사용자 화면에 요청한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "enum": list(REQUESTABLE_TOOLS)},
                "reason": {"type": "string"},
                "user_message": {"type": "string"},
            },
            "required": ["tool_name", "reason", "user_message"],
        },
    },
]


class GeminiDecisionSession:
    provider: Literal["gemini"] = "gemini"

    def __init__(self, context: dict[str, Any]):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")

        try:
            from google import genai
            from google.genai import types
        except ImportError as error:
            raise RuntimeError("google-genai is not installed") from error

        self._types = types
        self._client = genai.Client(api_key=api_key)
        self._model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        self._contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text="다음 Tool 결과를 평가하세요:\n"
                        + json.dumps(context, ensure_ascii=False)
                    )
                ],
            )
        ]
        declarations = [types.FunctionDeclaration(**item) for item in TOOL_DECLARATIONS]
        self._config = types.GenerateContentConfig(
            system_instruction=AGENT_PROMPT,
            temperature=0.1,
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            ),
        )
        self._last_call_name: str | None = None

    def next_call(self, tool_response: dict[str, Any] | None = None) -> ToolCall:
        if tool_response is not None:
            if not self._last_call_name:
                raise RuntimeError("Tool response has no matching function call")
            self._contents.append(
                self._types.Content(
                    role="tool",
                    parts=[
                        self._types.Part.from_function_response(
                            name=self._last_call_name,
                            response={"result": tool_response},
                        )
                    ],
                )
            )

        response = self._client.models.generate_content(
            model=self._model,
            contents=self._contents,
            config=self._config,
        )
        if not response.function_calls:
            raise RuntimeError("Gemini did not select an Agent function")

        self._contents.append(response.candidates[0].content)
        function_call = response.function_calls[0]
        self._last_call_name = function_call.name
        return ToolCall(function_call.name, dict(function_call.args or {}))


class RuleBasedDecisionSession:
    provider: Literal["local_fallback"] = "local_fallback"

    def __init__(self, context: dict[str, Any]):
        self._context = context

    def next_call(self, tool_response: dict[str, Any] | None = None) -> ToolCall:
        result = self._context.get("tool_result", {})
        tool_name = self._context.get("tool_name")
        quality = float(result.get("quality", 0.0) or 0.0)
        minimum_quality = 0.55 if tool_name == "face_check" else 0.65
        if not result.get("success") or quality < minimum_quality:
            return ToolCall(
                "retry",
                {
                    "reason": "측정 품질이 충분하지 않습니다.",
                    "user_message": "번거로우시겠지만 측정 상태를 확인하신 뒤 한 번 더 진행해 주시겠어요?",
                },
            )

        comparison = result.get("change_from_baseline") or {}
        if tool_name == "face_check":
            if comparison.get("available") and comparison.get("significant_change"):
                return ToolCall(
                    "ask_user",
                    {
                        "reason": "개인 기준과 비교해 얼굴 비대칭 수치 변화가 있습니다.",
                        "question": "혹시 평소와 다르게 얼굴이 불편하시거나 말씀하시기 어려운 점이 있으신가요?",
                    },
                )
            if not comparison.get("available"):
                return ToolCall(
                    "finish",
                    {
                        "reason": "유효한 얼굴 측정을 저장했으며 개인 기준을 수집 중입니다.",
                        "user_message": "얼굴 확인을 마쳤습니다. 더 정확한 확인을 위해 어르신의 평소 기준을 차근차근 준비하고 있습니다.",
                    },
                )
            return ToolCall(
                "finish",
                {
                    "reason": "얼굴 측정값이 개인 기준 범위 안에 있습니다.",
                    "user_message": "얼굴 확인을 마쳤습니다. 평소 기준과 비교했을 때 큰 변화는 보이지 않습니다.",
                },
            )

        if comparison.get("available") and comparison.get("significant_change"):
            return ToolCall(
                "request_tool",
                {
                    "tool_name": "face_check",
                    "reason": "개인 기준과 비교해 자세 수치 변화가 있습니다.",
                    "user_message": "평소와 다른 자세 변화가 보여, 안전을 위해 한 가지를 더 확인하겠습니다.",
                },
            )

        return ToolCall(
            "finish",
            {
                "reason": "유효한 자세 측정에서 큰 변화가 확인되지 않았습니다.",
                "user_message": "자세 확인을 마쳤습니다. 오늘도 무리하지 마시고 편안하게 움직이시기 바랍니다.",
            },
        )


SessionFactory = Callable[[dict[str, Any]], DecisionSession]


class AgentOrchestrator:
    def __init__(
        self,
        pose_store: PoseDataStore,
        session_factory: SessionFactory | None = None,
        max_steps: int = 4,
    ):
        self.pose_store = pose_store
        self.session_factory = session_factory
        self.max_steps = max_steps

    @property
    def gemini_configured(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY"))

    def _create_session(self, context: dict[str, Any]) -> DecisionSession:
        if self.session_factory:
            return self.session_factory(context)
        if self.gemini_configured:
            return GeminiDecisionSession(context)
        return RuleBasedDecisionSession(context)

    def evaluate(self, request: AgentEvaluateRequest) -> AgentDecision:
        context = request.model_dump()
        session = self._create_session(context)
        trace: list[str] = []
        tool_response = None

        for _ in range(self.max_steps):
            call = session.next_call(tool_response)
            trace.append(call.name)
            arguments = call.arguments

            if call.name == "get_history":
                days = int(arguments.get("days", 7))
                tool_response = {
                    "success": True,
                    "days": days,
                    "history": self.pose_store.get_recent_history(days),
                }
                continue

            decision = self._terminal_decision(
                call,
                provider=session.provider,
                current_tool=request.tool_name,
                trace=trace,
            )
            logger.info("Agent action=%s reason=%s", decision.action, decision.reason)
            return decision

        return AgentDecision(
            action="retry",
            reason="Agent 도구 선택 횟수 제한에 도달했습니다.",
            user_message="죄송하지만 확인을 마치지 못했습니다. 편하실 때 잠시 후 다시 시도해 주시겠어요?",
            next_tool=request.tool_name,
            provider=session.provider,
            tool_trace=trace,
        )

    @staticmethod
    def _terminal_decision(
        call: ToolCall,
        provider: Literal["gemini", "local_fallback"],
        current_tool: str,
        trace: list[str],
    ) -> AgentDecision:
        arguments = call.arguments
        reason = str(arguments.get("reason") or "다음 행동을 선택했습니다.")[:240]

        if call.name == "finish":
            return AgentDecision(
                action="finish",
                reason=reason,
                user_message=str(arguments.get("user_message") or "확인을 마쳤습니다.")[:500],
                provider=provider,
                tool_trace=trace,
            )
        if call.name == "retry":
            return AgentDecision(
                action="retry",
                reason=reason,
                user_message=str(arguments.get("user_message") or "번거로우시겠지만 한 번 더 측정해 주시겠어요?")[:500],
                next_tool=current_tool,
                provider=provider,
                tool_trace=trace,
            )
        if call.name == "ask_user":
            return AgentDecision(
                action="ask_user",
                reason=reason,
                user_message=str(arguments.get("question") or "괜찮으시다면 현재 상태를 말씀해 주시겠어요?")[:500],
                provider=provider,
                tool_trace=trace,
            )
        if call.name == "request_tool":
            tool_name = str(arguments.get("tool_name") or "")
            if tool_name not in REQUESTABLE_TOOLS:
                raise ValueError(f"Agent requested unknown tool: {tool_name}")
            return AgentDecision(
                action="request_tool",
                reason=reason,
                user_message=str(arguments.get("user_message") or "추가 확인이 필요합니다.")[:500],
                next_tool=tool_name,
                provider=provider,
                tool_trace=trace,
            )
        raise ValueError(f"Unknown Agent function: {call.name}")
