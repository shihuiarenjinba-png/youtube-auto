from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from core.ad_voice import AdVoiceHold, generate_narration_audio, probe_audio_duration


class AdVoiceTests(unittest.TestCase):
    def test_edge_tts_generates_mp3_without_api_key(self):
        class FakeCommunicate:
            def __init__(self, *, text, voice, rate, pitch, volume):
                self.text = text
                self.voice = voice
                self.rate = rate
                self.pitch = pitch
                self.volume = volume

            async def save(self, output_path):
                Path(output_path).write_bytes(b"ID3" + b"x" * 2048)

        fake_edge_tts = SimpleNamespace(Communicate=FakeCommunicate)
        with TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "narration.mp3"
            with patch.dict(sys.modules, {"edge_tts": fake_edge_tts}):
                result = generate_narration_audio(
                    "広告音声のテストです。",
                    output,
                    voice_id="ja-JP-NanamiNeural",
                )
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 1024)
            self.assertEqual(result["provider"], "Microsoft Edge TTS")
            self.assertEqual(result["voice_id"], "ja-JP-NanamiNeural")

    def test_empty_narration_fails_closed(self):
        with TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(AdVoiceHold, "HOLD_AD_NARRATION_TEXT_EMPTY"):
                generate_narration_audio("  ", Path(temp_dir) / "empty.mp3")

    def test_missing_audio_fails_closed_before_probe(self):
        with TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(AdVoiceHold, "HOLD_AD_NARRATION_FILE_MISSING"):
                probe_audio_duration(Path(temp_dir) / "missing.mp3")


if __name__ == "__main__":
    unittest.main()
