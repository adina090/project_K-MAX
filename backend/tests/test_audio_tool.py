import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from backend.app.audio_tool import AudioTranscriptionService, LocalWhisperCppTranscriber, clean_transcript


class FakeTranscriber:
    def __init__(self, transcript="오늘은 괜찮아요."):
        self.transcript = transcript
        self.calls = 0

    def transcribe(self, audio, filename, content_type):
        self.calls += 1
        return self.transcript


class AudioToolTests(unittest.TestCase):
    def test_normal_speech(self):
        fake = FakeTranscriber()
        result = AudioTranscriptionService(fake).transcribe(b"audio" * 200, "recording.webm", "audio/webm", 2.0)
        self.assertTrue(result.success)
        self.assertEqual(result.transcript, "오늘은 괜찮아요.")

    def test_short_speech_does_not_call_api(self):
        fake = FakeTranscriber()
        result = AudioTranscriptionService(fake).transcribe(b"audio", "recording.webm", "audio/webm", 0.2)
        self.assertFalse(result.success)
        self.assertEqual(result.error["code"], "too_short")
        self.assertEqual(fake.calls, 0)

    def test_silence_is_retryable(self):
        result = AudioTranscriptionService(FakeTranscriber("")).transcribe(b"audio" * 200, "recording.webm", "audio/webm", 2.0)
        self.assertFalse(result.success)
        self.assertEqual(result.error["code"], "silence")

    def test_unsupported_format(self):
        result = AudioTranscriptionService(FakeTranscriber()).transcribe(b"audio", "recording.bin", "application/octet-stream", 2.0)
        self.assertFalse(result.success)
        self.assertEqual(result.error["code"], "unsupported_format")

    def test_whisper_noise_markers_are_removed(self):
        self.assertEqual(clean_transcript("(끝)\n(끝)\n없어!"), "없어!")
        self.assertEqual(clean_transcript("(끝) 없어!"), "없어!")

    def test_only_noise_markers_become_silence(self):
        result = AudioTranscriptionService(FakeTranscriber("(끝)\n(끝)" )).transcribe(
            b"audio" * 200, "recording.webm", "audio/webm", 2.0,
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error["code"], "silence")

    def test_local_whisper_converts_audio_and_reads_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "whisper-cli"
            model = root / "ggml-small-q5_1.bin"
            binary.touch(mode=0o755)
            model.touch()

            def fake_run(command, **kwargs):
                if command[0] == "ffmpeg":
                    Path(command[-1]).touch()
                else:
                    prefix = Path(command[command.index("-of") + 1])
                    prefix.with_suffix(".txt").write_text("오늘은 괜찮아요.", encoding="utf-8")

            transcriber = LocalWhisperCppTranscriber(str(binary), str(model))
            with patch("backend.app.audio_tool.subprocess.run", side_effect=fake_run) as run:
                transcript = transcriber.transcribe(b"audio", "recording.webm", "audio/webm")

            self.assertEqual(transcript, "오늘은 괜찮아요.")
            self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
