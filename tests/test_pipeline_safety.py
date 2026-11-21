from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from core.advertising_rag import (
    GroundedExtractor,
    PublicHttpsFetcher,
    RagHold,
    generate_grounded_content,
    validate_public_https,
)
from core.app_campaigns import build_grounded_dataset, generate_app_ad_content, load_campaign
from core.app_ad_video import AppVideoHold, verify_screenshots
from core.social_posting_policy import content_fingerprint, choose_round_robin, validate_preflight


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

    def test_identity_runner_redacts_unexpected_oauth_errors(self):
        source = (ROOT / "scripts" / "audit_advertising_youtube.py").read_text(encoding="utf-8")
        self.assertIn("HOLD_OAUTH_READ_ONLY_CHECK_FAILED", source)
        self.assertIn('"fallback_performed": False', source)
        self.assertIn("raise SystemExit(2) from None", source)

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

    def test_html_meta_charset_prevents_japanese_mojibake(self):
        body = '<meta charset="utf-8"><title>日記と習慣</title>'.encode("utf-8")
        decoded = PublicHttpsFetcher._decode_html(body, "text/html", "ISO-8859-1")
        self.assertIn("日記と習慣", decoded)

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
        self.assertEqual(config["namespace"], "advertising.social")
        self.assertEqual(config["fallback_policy"], "DENY")
        for lane in (ja, en):
            self.assertEqual(lane["purpose"], "advertising")
            for platform in ("instagram", "tiktok"):
                self.assertTrue(all(row["purpose"] == "advertising" for row in lane[platform]))
                self.assertTrue(all(row["market"] == lane["market"] for row in lane[platform]))
                self.assertTrue(all(row["platform"] == platform for row in lane[platform]))

    @patch("core.advertising_rag.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))])
    def test_daymark_campaign_dataset_is_grounded_and_post_eligible(self, _mock):
        campaign = load_campaign(ROOT / "data" / "app_campaigns" / "daymark-ai-jp.json")

        class FakeFetcher:
            def fetch(self, url):
                html = '<html><head><meta charset="utf-8"><title>Daymark AI</title></head><body><main><h1>Daymark AI</h1><p>日記と習慣をWindows PC内に記録します。</p><p>ローカルAI補助は任意です。</p></main></body></html>'
                return url, html.encode("utf-8"), html

        grounded = build_grounded_dataset(campaign, fetcher=FakeFetcher())
        content = generate_app_ad_content(grounded)
        self.assertEqual(grounded["grounding_status"], "PASS")
        self.assertTrue(content["posting_eligible"])
        self.assertEqual(content["hold_reasons"], [])
        self.assertTrue(campaign["store_url"].startswith("https://apps.microsoft.com/"))
        self.assertEqual(content["cta_url"], campaign["store_url"])
        self.assertEqual(content["app_id"], "OkinawaDesktopTools.DaymarkAI")
        self.assertEqual(len(content["source_hashes"]), 3)

    def test_daymark_screenshot_hashes_match_dataset(self):
        campaign = json.loads((ROOT / "data" / "app_campaigns" / "daymark-ai-jp.json").read_text(encoding="utf-8"))
        verified = verify_screenshots(campaign, ROOT)
        self.assertEqual(len(verified), 5)

    def test_screenshot_hash_mismatch_fails_closed(self):
        campaign = json.loads((ROOT / "data" / "app_campaigns" / "daymark-ai-jp.json").read_text(encoding="utf-8"))
        campaign["screenshots"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(AppVideoHold, "HOLD_SCREENSHOT_HASH_MISMATCH"):
            verify_screenshots(campaign, ROOT)

    def test_local_video_runner_has_no_external_write_clients(self):
        source = (ROOT / "scripts" / "generate_app_ad_video.py").read_text(encoding="utf-8")
        self.assertNotIn("requests.post", source)
        self.assertNotIn("/v1/posts", source)
        self.assertNotIn("/media/presign", source)
        self.assertNotIn("videos().insert", source)
        self.assertNotIn("load_campaign(", source)
        self.assertIn("HOLD_REVIEW_DATASET_MISMATCH", source)

    def test_social_fingerprint_and_round_robin_are_deterministic(self):
        values = dict(campaign_id="c1", source_hash="s1", video_hash="v1", platform="instagram", account_id="a1")
        self.assertEqual(content_fingerprint(**values), content_fingerprint(**values))
        selected = choose_round_robin(
            [{"account_id": "a2", "purpose": "advertising"}, {"account_id": "a1", "purpose": "advertising"}],
            [],
        )
        self.assertEqual(selected["account_id"], "a1")

    def test_social_preflight_blocks_draft_campaign(self):
        from datetime import datetime
        with self.assertRaisesRegex(ValueError, "HOLD_CAMPAIGN_NOT_ACTIVE"):
            validate_preflight(
                campaign={"status": "DRAFT", "official_url": "https://example.com", "source_urls": ["https://example.com"], "cta_url": "https://example.com", "grounding_status": "PASS", "market": "JP"},
                account={"purpose": "advertising", "market": "JP", "platform": "instagram"},
                platform="instagram", media_valid=True, duplicate_found=False, capacity_ok=True,
                posts_today=0, last_posted_at=None, now=datetime(2026, 11, 20),
            )


    def test_phase_b_media_transfer_has_no_social_post_or_youtube_write(self):
        source = (ROOT / "scripts" / "transfer_app_campaign_media.py").read_text(encoding="utf-8")
        self.assertIn("upload_temp_media", source)
        self.assertNotIn("/v1/posts", source)
        self.assertNotIn("videos().insert", source)
        self.assertIn('"social_post_created": False', source)
        self.assertIn('"youtube_write_performed": False', source)
        self.assertIn('"zodiac_write_performed": False', source)


    def test_controlled_instagram_runner_is_single_account_and_no_youtube(self):
        source = (ROOT / "scripts" / "post_app_campaign_instagram_test.py").read_text(encoding="utf-8")
        self.assertIn('choices=["instagram", "tiktok"]', source)
        self.assertIn("HOLD_CONTROLLED_ACCOUNT_NOT_EXACTLY_ONE", source)
        self.assertIn("idempotency_key(", source)
        self.assertNotIn("videos().insert", source)
        self.assertIn('"youtube_write_performed": False', source)
        self.assertIn('"zodiac_write_performed": False', source)

    def test_zernio_controlled_post_uses_idempotency_header(self):
        source = (ROOT / "core" / "actions_zernio.py").read_text(encoding="utf-8")
        self.assertIn('"Idempotency-Key": idempotency_key', source)
        self.assertIn('"publishNow": True', source)
        self.assertIn('"platforms": [{"platform": platform, "accountId": account_id}]', source)

    def test_zernio_workflow_is_read_only(self):
        workflow = (ROOT / ".github" / "workflows" / "youtube-ad-pipeline.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/check_social_accounts.py", workflow)
        self.assertNotIn("/v1/posts", workflow)
        self.assertNotIn("/media/presign", workflow)
        self.assertIn("app-campaign-rag-dry-run", workflow)
        self.assertIn('test ! -e "$RUNNER_TEMP/daymark-ai-jp-review.json"', workflow)

    def test_app_campaign_rag_summary_reports_all_write_surfaces_false(self):
        runner = (ROOT / "scripts" / "run_app_campaign_rag.py").read_text(encoding="utf-8")
        for field in (
            '"media_upload_performed": False',
            '"social_post_created": False',
            '"social_post_performed": False',
            '"youtube_write_performed": False',
            '"zodiac_write_performed": False',
        ):
            self.assertIn(field, runner)

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
