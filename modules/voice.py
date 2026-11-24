"""On-device speech endpoints for the MIST intercom and embodied world.

Incoming audio is transcribed with local whisper.cpp; only the transcript is passed to
Colony's existing CI conversation path. Replies are synthesized locally with Kokoro TTS.
No microphone audio is uploaded or persisted.
"""
from __future__ import annotations

import base64
import hashlib
import io
import pathlib
import shutil
import subprocess
import tempfile
import threading
import wave

import store
from bridge import talk_to_ci

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "voice"
MODEL = DATA / "models" / "ggml-base.en.bin"
WHISPER = pathlib.Path("/opt/homebrew/bin/whisper-cli")
KOKORO_PYTHON = DATA / "venv" / "bin" / "python"
KOKORO_SCRIPT = ROOT / "kokoro_speak.py"
KOKORO_MODEL = DATA / "kokoro-v1.0.onnx"
KOKORO_VOICES = DATA / "voices-v1.0.bin"
MAX_AUDIO_BYTES = 6 * 1024 * 1024
MAX_AUDIO_SECONDS = 60
VOICE_BY_CI = {
    "vesper": ("af_heart", "warm American"),
    "kestrel": ("bm_george", "measured British"),
    "fathom": ("bf_emma", "bright British"),
    "morrow": ("am_fenrir", "low American"),
    "tessellate": ("af_sky", "light American"),
    "aster": ("am_michael", "clear American"),
}
VOICE_POOL = [
    ("af_heart", "warm American"), ("bm_george", "measured British"),
    ("bf_emma", "bright British"), ("am_fenrir", "low American"),
    ("af_sky", "light American"), ("am_michael", "clear American"),
    ("af_bella", "expressive American"), ("am_adam", "steady American"),
    ("bf_lily", "soft British"), ("am_puck", "animated American"),
]
_gate = threading.BoundedSemaphore(1)


def voice_for(name: str) -> tuple[str, str]:
    """Give each known CI a stable voice; assign new names deterministically."""
    key = (name or "").strip().lower()
    if key in VOICE_BY_CI:
        return VOICE_BY_CI[key]
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return VOICE_POOL[int.from_bytes(digest[:4], "big") % len(VOICE_POOL)]


def transcribe(audio: bytes) -> str:
    if len(audio) < 44 or len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("Audio must be a WAV recording no larger than 6 MB.")
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
                raise ValueError("Expected mono 16-bit 16 kHz WAV audio.")
            if not 0 < wav.getnframes() <= 16000 * MAX_AUDIO_SECONDS:
                raise ValueError("Recording must be between 1 and 60 seconds.")
    except (wave.Error, EOFError) as exc:
        raise ValueError("Could not read the recording as WAV audio.") from exc

    executable = WHISPER if WHISPER.is_file() else pathlib.Path(shutil.which("whisper-cli") or "")
    if not executable.is_file():
        raise RuntimeError("Local speech recognition is not installed (whisper-cli missing).")
    if not MODEL.is_file():
        raise RuntimeError("The local English speech model is missing from the console data directory.")

    DATA.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="input-", dir=DATA) as tmp:
        audio_path = pathlib.Path(tmp) / "input.wav"
        audio_path.write_bytes(audio)
        try:
            proc = subprocess.run(
                [str(executable), "-m", str(MODEL), "-f", str(audio_path),
                 "-l", "en", "-nt", "-np", "-t", "4"],
                capture_output=True, text=True, timeout=90, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Local transcription timed out. Try a shorter recording.") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "whisper-cli failed").strip()[-500:]
            raise RuntimeError("Local transcription failed: " + detail)
        text = (proc.stdout or "").strip()
        if not text:
            raise ValueError("No speech was recognized. Try speaking closer to the microphone.")
        return text


def _synthesize(text: str, voice: str) -> str:
    if not KOKORO_PYTHON.is_file() or not KOKORO_SCRIPT.is_file():
        raise RuntimeError("Local Kokoro voice engine is not installed.")
    if not KOKORO_MODEL.is_file() or not KOKORO_VOICES.is_file():
        raise RuntimeError("Local Kokoro model files are missing.")
    DATA.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="reply-", dir=DATA) as tmp:
        wav = pathlib.Path(tmp) / "reply.wav"
        try:
            result = subprocess.run(
                [str(KOKORO_PYTHON), str(KOKORO_SCRIPT), str(KOKORO_MODEL),
                 str(KOKORO_VOICES), voice, str(wav), text[:1400]],
                capture_output=True, text=True, timeout=180, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Local Kokoro speech generation timed out.") from exc
        if result.returncode != 0 or not wav.is_file():
            detail = (result.stderr or result.stdout or "Kokoro synthesis failed").strip()[-500:]
            raise RuntimeError("Local Kokoro synthesis failed: " + detail)
        return base64.b64encode(wav.read_bytes()).decode("ascii")


def turn(name: str, audio: bytes) -> tuple[int, dict]:
    if not _gate.acquire(blocking=False):
        return 429, {"error": "Another voice turn is in progress. Try again shortly."}
    try:
        try:
            transcript = transcribe(audio)
        except ValueError as exc:
            return 400, {"error": str(exc)}
        except RuntimeError as exc:
            return 503, {"error": str(exc)}

        result = talk_to_ci(name, transcript)
        if "error" in result:
            return result.get("status", 502), {"error": result["error"], "transcript": transcript}
        saved = store.save_exchange(result)
        voice_id, voice_label = voice_for(saved["ci"])
        payload = dict(saved, transcript=transcript, audio_mime="audio/wav",
                       voice_name=voice_id, voice_label=voice_label)
        try:
            payload["audio_base64"] = _synthesize(saved["reply"], voice_id)
        except RuntimeError as exc:
            payload["voice_error"] = str(exc)
        return 200, payload
    finally:
        _gate.release()
