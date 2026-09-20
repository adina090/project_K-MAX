import os
from typing import Any

from pydantic import BaseModel, Field

from .prompts import load_agent_prompt


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    recent_messages: list[dict[str, Any]] = Field(default_factory=list, max_length=10)


class ChatResponse(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    provider: str


CHAT_PROMPT = """
당신의 이름은 '동행이'이며, K-MAX 프로젝트의 AI 건강 동반자다.
사용자에게 자신을 소개하거나 지칭할 때는 반드시 '동행이'라는 이름을 사용하고 다른 이름을 만들지 않는다.
홀로 생활하시거나 건강 돌봄이 필요한 어르신의 건강 확인을 따뜻하게 돕는다.
어르신을 한 분의 성인으로 존중하며, 항상 정중하고 자연스러운 존댓말로 답한다.
반말, 훈계조, 유아를 대하듯 단순화한 표현, 재촉하거나 명령하는 표현은 사용하지 않는다.
사용자의 질문에 한국어로 짧고 명확하게 답하되, 먼저 말씀을 경청하고 필요한 경우 공감의 말을 건넨다.
측정 결과가 없는 경우 의료 진단이나 수치를 추측하지 않는다.
사용자가 측정 중이면 현재 측정 단계와 다음 행동을 선택권이 느껴지는 표현으로 쉽게 설명한다.
뇌졸중 등 질병을 확정하지 말고, 확인이 필요한 사실과 안전한 다음 행동만 안내한다.
""".strip()


class GeminiChatResponder:
    provider = "gemini"

    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        from google import genai
        from google.genai import types

        self.client = genai.Client(api_key=api_key)
        self.types = types
        self.model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    def respond(self, request: ChatRequest) -> ChatResponse:
        prompt = "최근 대화:\n" + str(request.recent_messages[-10:]) + "\n사용자 메시지:\n" + request.message
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=self.types.GenerateContentConfig(
                system_instruction=CHAT_PROMPT + "\n\n" + load_agent_prompt(),
                temperature=0.5,
                response_mime_type="application/json",
                response_schema=ChatResponse,
            ),
        )
        if response.parsed is not None:
            return response.parsed
        return ChatResponse.model_validate_json(response.text)


def local_response(message: str) -> ChatResponse:
    return ChatResponse(
        message="말씀해 주신 내용을 확인했습니다. 건강 확인이 필요하실 때 화면의 안내를 따라 편안히 진행해 주세요.",
        provider="local_fallback",
    )
