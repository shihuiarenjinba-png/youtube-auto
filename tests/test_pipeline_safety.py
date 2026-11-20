from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from core.advertising_rag import (
    GroundedExtractor,
    RagHold,
    generate_grounded_content,
    validate_public_https,
)


ROOT = Path(__file__).resolve().parents[1]
ZODIAC_IDS = {"UCCuMoJvZvdeUTdLaZR5tzPw", "UCeyLvckqiM7eYMgKOAh_OkA"}


class PipelineSafetyTests(unittest.TestCase):
    def test_namespaces_are_explicit_and_zodiac_is_audit_only(self):
        config = json.loads((ROOT / "config" / "account_namespaces.json").read_text(encoding="utf-8"))
        self.assertEqual(config["zodiac"]["write_policy"], "DENY_ALL_WRITES")
        self.assertIs(config["zodiac"]["audit_only"], True)
        self.assertEqual({config["zodiac"][lane]["channel_id"] for lane in ("ja", "en")}, ZODIAC_IDS)
        self.assertEqual(config["advertising"]["fallback_policy"], "DENY")

    def test_advertising_channels_never_use_zodiac_ids(self):
        config = json.loads((ROOT / "config" / "account_namespaces.json").read_text(encoding="utf-8"))
        jp = config["advertising"]["jp"]
        us = config["advertising"]["us"]
        self.assertEqual(jp["local_account_number"], "3")
        self.assertEqual(jp["expected_channel_id"], "UC4n0nR7IBwN1KKr9T32RP_w")
        self.assertNotIn(jp["expected_channel_id"], ZODIAC_IDS)
        self.assertEqual(us["local_account_number"], "2")
        self.assertEqual(us["expected_channel_id"], "")
        self.assertEqual(us["identity_status"], "HOLD_US_AD_ACCOUNT_NOT_CONFIRMED")

    def test_workflow_has_no_schedule_or_write_mode(self):
        workflow = (ROOT / ".github" / "workflows" / "youtube-ad-pipeline.yml").read_text(encoding="utf-8")
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("videos.insert", workflow)
        self.assertNotIn("--mode private", workflow)
        self.assertNotIn("--mode unlisted", workflow)
        self.assertNotIn("--mode public", workflow)
        self.assertNotIn("social-media-upload", workflow)
        self.assertNotIn("upload_social_media_probe.py", workflow)

    def test_workflow_uses_only_advertising_youtube_secret_namespace(self):
        workflow = (ROOT / ".github" / "workflows" / "youtube-ad-pipeline.yml").read_text(encoding="utf-8")
        for market in ("JP", "US"):
            self.assertIn(f"secrets.AD_YOUTUBE_CLIENT_ID_{market}", workflow)
            self.assertIn(f"secrets.AD_YOUTUBE_CLIENT_SECRET_{market}", workflow)
            self.assertIn(f"secrets.AD_YOUTUBE_REFRESH_TOKEN_{market}", workflow)
        self.assertNotIn("secrets.YOUTUBE_CLIENT_ID_", workflow)
        self.assertNotIn("secrets.YOUTUBE_CLIENT_SECRET_", workflow)
        self.assertNotIn("secrets.YOUTUBE_REFRESH_TOKEN_", workflow)

    def test_read_only_identity_module_has_no_write_surface(self):
        source = (ROOT / "core" / "read_only_youtube.py").read_text(encoding="utf-8")
        self.assertNotIn("videos().insert", source)
        self.assertNotIn("MediaFileUpload", source)
        self.assertNotIn(".upload(", source)
        self.assertIn("channels().list", source)

    def test_legacy_pipeline_entry_is_fail_closed(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_ad_pipeline.py")], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HOLD_LEGACY_ZODIAC_PIPELINE_ISOLATED", result.stderr)

    @patch("core.advertising_rag.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))])
    def test_public_https_url_passes(self, _mock):
        validate_public_https("https://example.com/product")

    def test_non_https_and_local_urls_fail_closed(self):
        for url in ("http://example.com", "file:///tmp/a", "https://localhost/a"):
            with self.subTest(url=url), self.assertRaises(RagHold):
                validate_public_https(url)

    @patch("core.advertising_rag.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))])
    def test_private_ip_resolution_fails_closed(self, _mock):
        with self.assertRaises(RagHold):
            validate_public_https("https://public-looking.example/product")

    @patch("core.advertising_rag.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))])
    def test_source_grounding_fields_and_content(self, _mock):
        html = (ROOT / "tests" / "fixtures" / "product_page.html").read_text(encoding="utf-8")
        body = html.encode("utf-8")
        source = GroundedExtractor().extract(
            campaign_id="campaign-001",
            requested_url="https://example.com/product?utm_source=test",
            final_url="https://example.com/product",
            body=body,
            html=html,
        )
        content = generate_grounded_content(source, market="jp")
        self.assertEqual(source.campaign_id, "campaign-001")
        self.assertEqual(source.canonical_url, "https://example.com/product")
        self.assertEqual(len(source.generated_from_source_hash), 64)
        self.assertEqual(content["generated_from_source_hash"], source.generated_from_source_hash)
        self.assertEqual(content["source_url"], source.source_url)
        self.assertIn("CSV", " ".join(content["key_points"]))
        self.assertTrue(all(item["url"].startswith("https://example.com/") for item in source.ctas))
        self.assertNotIn("No.1", json.dumps(content, ensure_ascii=False))
        self.assertNotIn("50%", json.dumps(content, ensure_ascii=False))

    def test_social_markets_and_accounts_never_overlap(self):
        config = json.loads((ROOT / "config" / "social_lanes.json").read_text(encoding="utf-8"))
        ja = config["languages"]["ja"]
        en = config["languages"]["en"]
        self.assertEqual(ja["market"], "JP")
        self.assertEqual(en["market"], "US")
        ja_ids = {row["account_id"] for platform in ("instagram", "tiktok") for row in ja[platform]}
        en_ids = {row["account_id"] for platform in ("instagram", "tiktok") for row in en[platform]}
        self.assertTrue(ja_ids.isdisjoint(en_ids))

    def test_zernio_workflow_is_read_only(self):
        workflow = (ROOT / ".github" / "workflows" / "youtube-ad-pipeline.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/check_social_accounts.py", workflow)
        self.assertNotIn("/v1/posts", workflow)
        self.assertNotIn("/media/presign", workflow)

    def test_rag_runner_reports_hold_without_fallback(self):
        runner = (ROOT / "scripts" / "run_advertising_rag.py").read_text(encoding="utf-8")
        self.assertIn('"fallback_performed": False', runner)
        self.assertIn("except RagHold", runner)

    def test_legacy_zodiac_lanes_are_quarantined(self):
        config = json.loads((ROOT / "config" / "lanes.json").read_text(encoding="utf-8"))
        self.assertEqual(config["namespace"], "zodiac-quarantine")
        self.assertEqual(config["write_policy"], "DENY_ALL_WRITES")
        self.assertTrue(all(lane["schedule"] == "DISABLED" for lane in config["languages"].values()))


if __name__ == "__main__":
    unittest.main()
