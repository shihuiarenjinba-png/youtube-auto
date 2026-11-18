from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.run_ad_pipeline import (
    ALLOWED_MARKER_NAMESPACES,
    ALLOWED_MODES,
    lane_card_check,
    marketing_lines,
)
from scripts.schedule_gate import selected_cron, should_run


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

    @patch.dict(
        os.environ,
        {"AD_CTA": "正式な日本語CTA", "AD_LINK": "正式なJA商品URL"},
        clear=True,
    )
    def test_placeholder_marketing_values_fail_closed(self):
        with self.assertRaises(RuntimeError):
            marketing_lines(require=True)

    @patch.dict(
        os.environ,
        {"AD_CTA": "詳しくはこちら", "AD_LINK": "https://example.com/product"},
        clear=True,
    )
    def test_absolute_https_marketing_values_pass(self):
        self.assertEqual(
            marketing_lines(require=True),
            ["詳しくはこちら", "https://example.com/product"],
        )

    def test_private_mode_ignores_marketing_variables_in_pipeline(self):
        pipeline = (ROOT / "scripts" / "run_ad_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('if args.mode == "private":', pipeline)
        self.assertIn("広告CTA・商品URLは意図的に未使用です", pipeline)
        self.assertIn("Marketing CTA/product URL intentionally omitted.", pipeline)
        self.assertIn('marketing_lines(require=args.mode == "unlisted")', pipeline)

    def test_language_mismatch_fails_closed(self):
        with self.assertRaises(RuntimeError):
            lane_card_check([{"lang": "en"}], "ja")

    def test_workflow_uses_distinct_oauth_clients(self):
        workflow = (ROOT / ".github" / "workflows" / "youtube-ad-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("secrets.YOUTUBE_CLIENT_ID_JA", workflow)
        self.assertIn("secrets.YOUTUBE_CLIENT_SECRET_JA", workflow)
        self.assertIn("secrets.YOUTUBE_CLIENT_ID_EN", workflow)
        self.assertIn("secrets.YOUTUBE_CLIENT_SECRET_EN", workflow)
        self.assertNotIn("secrets.YOUTUBE_CLIENT_ID }}", workflow)
        self.assertNotIn("secrets.YOUTUBE_CLIENT_SECRET }}", workflow)

    def test_ja_five_am_cron(self):
        self.assertEqual(selected_cron("ja", datetime(2026, 11, 18).date()), "0 20 * * *")

    def test_new_york_five_am_tracks_dst(self):
        winter = datetime(2026, 1, 15, 10, tzinfo=timezone.utc)
        summer = datetime(2026, 7, 15, 9, tzinfo=timezone.utc)
        self.assertTrue(should_run("en", "0 10 * * *", winter))
        self.assertFalse(should_run("en", "0 9 * * *", winter))
        self.assertTrue(should_run("en", "0 9 * * *", summer))
        self.assertFalse(should_run("en", "0 10 * * *", summer))

    def test_schedule_gate_selects_only_the_correct_lane(self):
        ja_time = datetime(2026, 11, 18, 20, tzinfo=timezone.utc)
        en_winter_time = datetime(2026, 11, 18, 10, tzinfo=timezone.utc)
        self.assertTrue(should_run("ja", "0 20 * * *", ja_time))
        self.assertFalse(should_run("en", "0 20 * * *", ja_time))
        self.assertTrue(should_run("en", "0 10 * * *", en_winter_time))
        self.assertFalse(should_run("ja", "0 10 * * *", en_winter_time))

    def test_scheduled_path_is_private_one_item_and_lane_fixed(self):
        workflow = (ROOT / ".github" / "workflows" / "youtube-ad-pipeline.yml").read_text(
            encoding="utf-8"
        )
        for cron in ('cron: "0 20 * * *"', 'cron: "0 9 * * *"', 'cron: "0 10 * * *"'):
            self.assertIn(cron, workflow)
        self.assertIn("python scripts/schedule_gate.py --language ja", workflow)
        self.assertIn("python scripts/schedule_gate.py --language en", workflow)
        self.assertIn("--language ja --mode private --max-videos 1", workflow)
        self.assertIn("--language en --mode private --max-videos 1", workflow)
        self.assertEqual(
            ALLOWED_MARKER_NAMESPACES,
            ("youtube-auto", "youtube-auto-scheduled-validation"),
        )
        self.assertEqual(workflow.count("--marker-namespace youtube-auto-scheduled-validation"), 2)
        self.assertIn("secrets.YOUTUBE_REFRESH_TOKEN_JA", workflow)
        self.assertIn("secrets.YOUTUBE_REFRESH_TOKEN_EN", workflow)
        self.assertIn("Run fail-closed safety tests before scheduled validation upload", workflow)
        self.assertNotIn("--mode public", workflow)

    def test_social_markets_and_accounts_never_overlap(self):
        config = json.loads((ROOT / "config" / "social_lanes.json").read_text(encoding="utf-8"))
        ja = config["languages"]["ja"]
        en = config["languages"]["en"]
        self.assertEqual(ja["market"], "JP")
        self.assertEqual(en["market"], "US")
        ja_ids = {row["account_id"] for platform in ("instagram", "tiktok") for row in ja[platform]}
        en_ids = {row["account_id"] for platform in ("instagram", "tiktok") for row in en[platform]}
        self.assertTrue(ja_ids)
        self.assertTrue(en_ids)
        self.assertTrue(ja_ids.isdisjoint(en_ids))

    def test_social_dry_run_cannot_enter_youtube_upload_jobs(self):
        workflow = (ROOT / ".github" / "workflows" / "youtube-ad-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("inputs.mode != 'social-dry-run'", workflow)
        self.assertIn("inputs.mode == 'dry-run' || inputs.mode == 'social-dry-run'", workflow)

    def test_social_media_upload_cannot_enter_youtube_upload_jobs(self):
        workflow = (ROOT / ".github" / "workflows" / "youtube-ad-pipeline.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- social-media-upload", workflow)
        self.assertGreaterEqual(workflow.count("inputs.mode != 'social-media-upload'"), 2)
        self.assertIn("ja-social-media-upload:", workflow)
        self.assertIn("en-social-media-upload:", workflow)

    def test_social_media_probe_never_creates_post(self):
        probe = (ROOT / "scripts" / "upload_social_media_probe.py").read_text(encoding="utf-8")
        self.assertNotIn("/posts", probe)
        self.assertIn('"social_post_created": False', probe)
        self.assertIn('"social_post_performed": False', probe)
        self.assertIn('"generated_video_count": 1', probe)
        self.assertIn('"temporary_media_removed": True', probe)
        self.assertIn('"account_health_passed": True', probe)
        self.assertIn('"tiktok_capacity_passed": True', probe)

    def test_zernio_probe_uses_presigned_media_upload_only(self):
        client = (ROOT / "core" / "actions_zernio.py").read_text(encoding="utf-8")
        self.assertIn('"/media/presign"', client)
        self.assertNotIn('"/posts"', client)
        self.assertIn('"presign_succeeded": True', client)
        self.assertIn('"presigned_put_succeeded": True', client)


if __name__ == "__main__":
    unittest.main()
