"""Grounded Japanese narration audio generation for advertising videos."""

from __future__ import annotations

import asyncio
from pathlib import Path


class AdVoiceHold(ValueError):
    """Fail-closed TTS generation or validation error."""


def generate_narration_audio(
    text: str,
    output_path: Path,
    *,
    voice_id: str = "ja-JP-NanamiNeural",
    rate: str = "-5%",
    pitch: str = "+0Hz",
) -> dict[str, str | int]:
    """Generate speech with Microsoft Edge TTS; no API key is required."""
    narration = str(text or "").strip()
    if not narration:
        raise AdVoiceHold("HOLD_AD_NARRATION_TEXT_EMPTY")
    if not voice_id or len(voice_id) > 100:
        raise AdVoiceHold("HOLD_AD_NARRATION_VOICE_INVALID")

    try:
        import edge_tts
        output_path.parent.mkdir(parents=True, exist_ok=True)

        async def synthesize() -> None:
            communicate = edge_tts.Communicate(
                text=narration,
                voice=voice_id,
                rate=rate,
                pitch=pitch,
                volume="+0%",
            )
            await communicate.save(str(output_path))

        asyncio.run(synthesize())
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        raise AdVoiceHold("HOLD_AD_NARRATION_GENERATION_FAILED") from exc

    if not output_path.is_file() or output_path.stat().st_size < 1024:
        output_path.unlink(missing_ok=True)
        raise AdVoiceHold("HOLD_AD_NARRATION_OUTPUT_INVALID")

    return {
        "provider": "Microsoft Edge TTS",
        "voice_id": voice_id,
        "bytes": output_path.stat().st_size,
    }


def probe_audio_duration(path: Path) -> float:
    """Read generated audio duration using MoviePy/FFmpeg."""
    if not path.is_file() or path.stat().st_size < 1024:
        raise AdVoiceHold("HOLD_AD_NARRATION_FILE_MISSING")
    try:
        from moviepy import AudioFileClip
        clip = AudioFileClip(str(path))
        try:
            duration = float(clip.duration or 0)
        finally:
            clip.close()
    except Exception as exc:
        raise AdVoiceHold("HOLD_AD_NARRATION_PROBE_FAILED") from exc
    if duration <= 0:
        raise AdVoiceHold("HOLD_AD_NARRATION_DURATION_INVALID")
    return duration
