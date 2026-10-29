"""Text-to-speech through the ElevenLabs API.

The key comes from ELEVENLABS_API_KEY (backend/.env or the environment). Without it the
recap text still works; only the audio endpoint answers 503.
"""

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # "George", one of ElevenLabs' premade voices
DEFAULT_MODEL_ID = "eleven_multilingual_v2"


class VoiceNotConfigured(RuntimeError):
    pass


class VoiceError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(os.getenv("ELEVENLABS_API_KEY"))


def speak(text: str) -> bytes:
    """MP3 audio of `text`, read by the configured voice."""
    key = os.getenv("ELEVENLABS_API_KEY")
    if not key:
        raise VoiceNotConfigured("No ElevenLabs API key. Set ELEVENLABS_API_KEY in backend/.env (see .env.example).")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_ID
    try:
        r = httpx.post(
            API_URL.format(voice_id=voice_id),
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": key, "Accept": "audio/mpeg"},
            json={"text": text, "model_id": os.getenv("ELEVENLABS_MODEL_ID") or DEFAULT_MODEL_ID},
            timeout=30,
        )
    except httpx.HTTPError as e:
        raise VoiceError(f"Couldn't reach ElevenLabs ({e}).") from e
    if r.status_code != 200:
        raise VoiceError(f"ElevenLabs returned {r.status_code}: {r.text[:200]}")
    return r.content
