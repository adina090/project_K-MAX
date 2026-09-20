from pathlib import Path
import os

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .agent import AgentEvaluateRequest, AgentOrchestrator, AgentDecision
from .conversation import (
    ConversationReplyRequest,
    ConversationResult,
    ConversationService,
    ConversationStartRequest,
    ConversationStore,
    ConversationTimeoutRequest,
)
from .audio_tool import MAX_AUDIO_BYTES, AudioTranscriptionService, TranscriptResult
from .chat import ChatRequest, ChatResponse, GeminiChatResponder, local_response
from .face_tool import FaceMeasurementRequest, FaceResult, face_check
from .pose_store import FaceBaselineSampleRequest, PoseBaselineSampleRequest, PoseDataStore
from .pose_tool import PoseMeasurementRequest, PoseResult, stretch_check
from .scheduler import PeriodicScheduler, SchedulerClaim, SchedulerStatus
from .storage import read_items, write_items

app = FastAPI(title="Test Project API")
pose_store = PoseDataStore(Path(__file__).resolve().parent.parent / "data")
agent = AgentOrchestrator(pose_store)
scheduler = PeriodicScheduler(
    Path(__file__).resolve().parent.parent / "data" / "scheduler" / "state.json"
)
conversation_service = ConversationService(
    ConversationStore(Path(__file__).resolve().parent.parent / "data" / "conversations")
)
audio_transcription_service = AudioTranscriptionService()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health_check() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "gemini_configured": agent.gemini_configured,
        "openai_configured": bool(os.environ.get("OPENAI_API_KEY")),
        "transcription_backend": audio_transcription_service.backend,
        "transcription_configured": audio_transcription_service.configured,
    }


@app.get("/api/items")
def get_items() -> list[dict]:
    return read_items()


@app.post("/api/items", status_code=201)
def replace_items(items: list[dict]) -> list[dict]:
    write_items(items)
    return items


@app.post("/api/tools/stretch-check", response_model=PoseResult)
def run_stretch_check(request: PoseMeasurementRequest) -> PoseResult:
    result = stretch_check(request)
    if result.success:
        result.change_from_baseline = pose_store.compare_to_baseline(result.features)
        pose_store.save_measurement(result.model_dump())
        scheduler.start_after_morning()
    return result


@app.post("/api/tools/face-check", response_model=FaceResult)
def run_face_check(request: FaceMeasurementRequest) -> FaceResult:
    result = face_check(request)
    if result.success:
        result.change_from_baseline = pose_store.compare_face_to_baseline(result.features)
        pose_store.save_face_measurement(result.model_dump())
    return result


@app.post("/api/agent/evaluate", response_model=AgentDecision)
def evaluate_agent(request: AgentEvaluateRequest) -> AgentDecision:
    try:
        return agent.evaluate(request)
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/scheduler/status", response_model=SchedulerStatus)
def get_scheduler_status() -> SchedulerStatus:
    return scheduler.get_status()


@app.post("/api/scheduler/claim", response_model=SchedulerClaim)
def claim_scheduler_event() -> SchedulerClaim:
    return scheduler.claim_due_event()


@app.post("/api/conversation/start", response_model=ConversationResult)
def start_conversation(request: ConversationStartRequest) -> ConversationResult:
    try:
        return conversation_service.start_conversation(
            request.event_id,
            request.measurement_context,
            request.routine_mode,
        )
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/conversation/respond", response_model=ConversationResult)
def respond_to_conversation(request: ConversationReplyRequest) -> ConversationResult:
    try:
        return conversation_service.respond(
            request.conversation_id,
            request.response,
            request.input_mode,
            request.duration,
        )
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/conversation/timeout", response_model=ConversationResult)
def timeout_conversation(request: ConversationTimeoutRequest) -> ConversationResult:
    try:
        return conversation_service.timeout(request.conversation_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    if not os.environ.get("GEMINI_API_KEY"):
        return local_response(request.message)
    try:
        return GeminiChatResponder().respond(request)
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Gemini chat failed: {error}") from error


@app.post("/api/audio/transcribe", response_model=TranscriptResult)
async def transcribe_audio(
    file: UploadFile = File(...),
    duration: float = Form(...),
    conversation_id: str = Form(...),
) -> TranscriptResult:
    audio = await file.read(MAX_AUDIO_BYTES + 1)
    result = audio_transcription_service.transcribe(
        audio=audio,
        filename=file.filename or "recording.webm",
        content_type=file.content_type or "application/octet-stream",
        duration=duration,
    )
    # The transcript is committed only when the client accepts voice input and
    # submits it to /api/conversation/respond. Text input can therefore safely
    # supersede an in-flight voice transcription without saving stale speech.
    return result


@app.get("/api/pose/baseline")
def get_pose_baseline() -> dict:
    return pose_store.get_baseline()


@app.post("/api/pose/baseline/samples", status_code=201)
def add_pose_baseline_sample(request: PoseBaselineSampleRequest) -> dict:
    try:
        return pose_store.add_baseline_sample(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/face/baseline")
def get_face_baseline() -> dict:
    return pose_store.get_face_baseline()


@app.post("/api/face/baseline/samples", status_code=201)
def add_face_baseline_sample(request: FaceBaselineSampleRequest) -> dict:
    try:
        return pose_store.add_face_baseline_sample(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
