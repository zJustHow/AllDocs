import io
import tempfile
import wave
from pathlib import Path
from threading import Event, Lock

from faster_whisper import WhisperModel
from piper import PiperVoice

from app.config import Settings, get_settings

_whisper_lock = Lock()
_whisper_model: WhisperModel | None = None
_whisper_ready_event = Event()
_piper_lock = Lock()
_piper_voices: dict[str, PiperVoice] = {}


def warm_whisper(settings: Settings | None = None) -> None:
    """Load Whisper at startup so the first /ws/voice request is not blocked."""
    _get_whisper(settings or get_settings())


def is_whisper_ready() -> bool:
    return _whisper_model is not None


def wait_whisper_ready(timeout: float | None = None) -> bool:
    if _whisper_model is not None:
        return True
    return _whisper_ready_event.wait(timeout)


def _audio_suffix(mime_type: str | None, audio_bytes: bytes) -> str:
    if mime_type:
        base = mime_type.split(";")[0].strip().lower()
        mapping = {
            "audio/webm": ".webm",
            "audio/mp4": ".mp4",
            "audio/m4a": ".m4a",
            "audio/aac": ".aac",
            "audio/ogg": ".ogg",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
        }
        if base in mapping:
            return mapping[base]
    if len(audio_bytes) >= 4 and audio_bytes[:4] == b"RIFF":
        return ".wav"
    if len(audio_bytes) >= 4 and audio_bytes[:4] == b"fLaC":
        return ".flac"
    if len(audio_bytes) >= 8 and audio_bytes[4:8] == b"ftyp":
        return ".mp4"
    if len(audio_bytes) >= 4 and audio_bytes[:4] == b"OggS":
        return ".ogg"
    return ".webm"


def _get_whisper(settings: Settings) -> WhisperModel:
    global _whisper_model
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                device = settings.whisper_device
                if device == "auto":
                    device = "cuda"
                _whisper_model = WhisperModel(
                    settings.whisper_model,
                    device=device,
                    compute_type=settings.whisper_compute_type,
                )
                _whisper_ready_event.set()
    return _whisper_model


def _resolve_piper_model(settings: Settings, lang: str) -> Path:
    model_name = settings.piper_zh_model if lang.startswith("zh") else settings.piper_en_model
    model_dir = Path(settings.piper_model_dir)
    onnx_path = model_dir / f"{model_name}.onnx"
    if not onnx_path.exists():
        raise FileNotFoundError(
            f"Piper model not found: {onnx_path}. "
            f"Download from https://github.com/rhasspy/piper/releases"
        )
    return onnx_path


def _get_piper_voice(settings: Settings, lang: str) -> PiperVoice:
    key = "zh" if lang.startswith("zh") else "en"
    if key not in _piper_voices:
        with _piper_lock:
            if key not in _piper_voices:
                model_path = _resolve_piper_model(settings, lang)
                _piper_voices[key] = PiperVoice.load(model_path)
    return _piper_voices[key]


class SpeechService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def transcribe(
        self,
        audio_bytes: bytes,
        language: str | None = None,
        mime_type: str | None = None,
    ) -> dict:
        model = _get_whisper(self.settings)
        suffix = _audio_suffix(mime_type, audio_bytes)

        def run_transcribe(vad_filter: bool) -> tuple[str, object]:
            with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
                tmp.write(audio_bytes)
                tmp.flush()
                segments, info = model.transcribe(
                    tmp.name,
                    language=language,
                    vad_filter=vad_filter,
                    beam_size=1,
                )
            text = "".join(segment.text for segment in segments).strip()
            return text, info

        text, info = run_transcribe(vad_filter=True)
        if not text:
            text, info = run_transcribe(vad_filter=False)

        detected_lang = info.language or "zh"
        return {
            "text": text,
            "language": detected_lang,
            "duration": info.duration,
        }

    def synthesize(self, text: str, lang: str = "zh") -> bytes:
        voice = _get_piper_voice(self.settings, lang)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            voice.synthesize_wav(text, wav_file)
        return buffer.getvalue()
