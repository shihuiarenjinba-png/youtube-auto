from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.run_ad_pipeline import ALLOWED_MODES, lane_card_check, marketing_lines


ROOT = Path(__file__).resolve().parents[1]


class PipelineSafetyTests(unittest.TestCase):
    def test_public_mode_is_not_available_during_validation(self):
        self.assertNotIn("public", ALLOWED_MODES)

    def test_lanes_have_distinct_expected_channels(self):
        config = json.loads((ROOT / "config" / "lanes.json").read_text(encoding="utf-8"))
        ja = config["languages"]["ja"]["expected_channel_id"]
        en = config["languages"]["en"]["expected_channel_id"]
        self.assertTrue(ja)
        self.assertTrue(en)
        self.assertNotEqual(ja, en)

    @patch.dict(os.environ, {}, clear=True)
    def test_upload_requires_cta_and_link(self):
        with self.assertRaises(RuntimeError):
            marketing_lines(require=True)

    def test_language_mismatch_fails_closed(self):
        with self.assertRaises(RuntimeError):
            lane_card_check([{"lang": "en"}], "ja")


if __name__ == "__main__":
    unittest.main()
