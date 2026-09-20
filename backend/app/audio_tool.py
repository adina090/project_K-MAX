import io
import os
from pathlib import Path
import re
import subprocess
import tempfile

from pydantic import BaseModel


MAX_AUDIO_BYTES = 10 * 1024 * 1024
MIN_DURATION_SECONDS = 0.8
MAX_DURATION_SECONDS = 60.0
SUPPORTED_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4"}
TRANSCRIPTION_NOISE_MARKERS = {"(끝)", "[끝]", "(음악)", "[음악]", "(박수)", "[박수]", "(침묵)", "[침묵]"}


def clean_transcript(text: str) -> str:
    for marker in TRANSCRIPTION_NOISE_MARKERS:
        text = text.replace(marker, " ")
    lines = []
    for raw_line in text.replace("\r", "\n").split("\n"):
        line = " ".join(raw_line.strip().split())
        if line:
            lines.append(line)
    return re.sub(r"\s+([,.!?])", r"\1", " ".join(lines)).strip()


class TranscriptResult(BaseModel):
    success: bool
    transcript: str
    duration: float
    error: dict | None = None


class OpenAIWhisperTranscriber:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        from openai import OpenAI

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        self.client = OpenAI(api_key=key)
        self.model = model or os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1")

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> str:
        audio_file = io.BytesIO(audio)
        audio_file.name = filename
        response = self.client.audio.transcriptions.create(
            file=audio_file,
            model=self.model,
            language="ko",
            response_format="json",
        )
        return str(getattr(response, "text", "") or "").strip()


class LocalWhisperCppTranscriber:
    def __init__(self, binary: str | None = None, model: str | None = None, timeout_seconds: float | None = None):
        project_dir = Path(__file__).resolve().parents[2]
        self.binary = Path(binary or os.environ.get(
            "WHISPER_CPP_BINARY",
            project_dir / ".local" / "whisper.cpp" / "build" / "bin" / "whisper-cli",
        ))
        self.model = Path(model or os.environ.get(
            "WHISPER_CPP_MODEL",
            project_dir / ".local" / "whisper.cpp" / "models" / "ggml-small-q5_1.bin",
        ))
        self.timeout_seconds = float(timeout_seconds or os.environ.get("WHISPER_LOCAL_TIMEOUT_SECONDS", "120"))

    @property
    def configured(self) -> bool:
        return self.binary.is_file() and os.access(self.binary, os.X_OK) and self.model.is_file()

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> str:
        if not self.configured:
            raise RuntimeError("Local Whisper binary or model is not installed")

        suffixes = {
            "audio/webm": ".webm",
            "audio/ogg": ".ogg",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/mpeg": ".mp3",
            "audio/mp4": ".m4a",
        }
        suffix = suffixes.get(content_type.split(";", 1)[0].lower(), Path(filename).suffix or ".audio")
        with tempfile.TemporaryDirectory(prefix="health-whisper-") as directory:
            work_dir = Path(directory)
            source = work_dir / f"source{suffix}"
            wav = work_dir / "recording.wav"
            output_prefix = work_dir / "transcript"
            source.write_bytes(audio)

            subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(source),
                 "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)],
                check=True,
                capture_output=True,
                timeout=30,
            )
            subprocess.run(
                [str(self.binary), "-m", str(self.model), "-f", str(wav), "-l", "ko",
                 "-otxt", "-of", str(output_prefix)],
                check=True,
                capture_output=True,
                timeout=self.timeout_seconds,
            )
            transcript_file = output_prefix.with_suffix(".txt")
            return transcript_file.read_text(encoding="utf-8").strip() if transcript_file.exists() else ""


class AudioTranscriptionService:
    def __init__(self, transcriber=None):
        self.transcriber = transcriber

    @property
    def configured(self) -> bool:
        if self.transcriber is not None:
            return True
        if self.backend == "local":
            return LocalWhisperCppTranscriber().configured
        return bool(os.environ.get("OPENAI_API_KEY"))

    @property
    def backend(self) -> str:
        return os.environ.get("WHISPER_BACKEND", "openai").strip().lower()

    def _create_transcriber(self):
        if self.backend == "local":
            return LocalWhisperCppTranscriber()
        if self.backend == "openai":
            return OpenAIWhisperTranscriber()
        raise RuntimeError(f"Unsupported WHISPER_BACKEND: {self.backend}")

    def transcribe(self, audio: bytes, filename: str, content_type: str, duration: float) -> TranscriptResult:
        if content_type.split(";", 1)[0].lower() not in SUPPORTED_TYPES:
            return self._failure(duration, "unsupported_format", "지원하지 않는 오디오 형식입니다.")
        if len(audio) > MAX_AUDIO_BYTES:
            return self._failure(duration, "file_too_large", "오디오 파일이 너무 큽니다.")
        if duration < MIN_DURATION_SECONDS:
            return self._failure(duration, "too_short", "죄송하지만 말씀을 충분히 듣지 못했습니다. 조금만 더 길게 말씀해 주시겠어요?")
        if duration > MAX_DURATION_SECONDS:
            return self._failure(duration, "too_long", "말씀은 잘 들었습니다. 녹음은 60초 이내로 부탁드립니다.")
        if not audio:
            return self._failure(duration, "silence", "말씀을 듣지 못했습니다. 괜찮으실 때 다시 말씀해 주시겠어요?")
        if not self.configured:
            return self._failure(duration, "not_configured", "음성 인식 엔진이 설치되거나 설정되지 않았습니다.")
        try:
            transcriber = self.transcriber or self._create_transcriber()
            transcript = clean_transcript(transcriber.transcribe(audio, filename, content_type))
        except Exception:
            return self._failure(duration, "transcription_failed", "죄송하지만 말씀을 인식하지 못했습니다. 괜찮으실 때 다시 말씀해 주시겠어요?")
        if not transcript:
            return self._failure(duration, "silence", "죄송하지만 말씀을 확인하지 못했습니다. 괜찮으실 때 다시 말씀해 주시겠어요?")
        return TranscriptResult(success=True, transcript=transcript, duration=round(duration, 2))

    @staticmethod
    def _failure(duration: float, code: str, message: str) -> TranscriptResult:
        return TranscriptResult(success=False, transcript="", duration=round(duration, 2), error={"code": code, "message": message})
