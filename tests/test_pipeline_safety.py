from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import hashlib
import contextlib
import io
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
from core.social_post_ledger import GitHubSocialPostLedger, SocialLedgerHold, ledger_policy_state
from scripts.reconcile_advertising_social_posts import (  # noqa: E402
    ReconciliationHold,
    build_reconciliation_result,
    resolve_advertising_account,
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
        self.assertEqual(us["known_channel_handle"], "sleepdeep.knowledge")
        self.assertEqual(us["identity_status"], "HOLD_US_AD_CHANNEL_ID_DISCOVERY_REQUIRED")

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


    def test_us_discovery_mode_is_read_only_and_requires_pinning_for_normal_check(self):
        workflow = (ROOT / ".github" / "workflows" / "youtube-ad-pipeline.yml").read_text(encoding="utf-8")
        runner = (ROOT / "scripts" / "audit_advertising_youtube.py").read_text(encoding="utf-8")
        self.assertIn("advertising-oauth-discovery", workflow)
        self.assertIn("--discover", workflow)
        self.assertIn('parser.add_argument("--discover"', runner)
        self.assertIn("ADVERTISING_OAUTH_DISCOVERY_PASS", runner)
        self.assertIn('"write_performed": False', runner)
        self.assertNotIn("videos().insert", runner)

    def test_us_discovery_execution_and_zodiac_hold(self):
        from core.read_only_youtube import ReadOnlyChannelIdentity
        from scripts import audit_advertising_youtube as audit

        output = io.StringIO()
        with patch.object(audit, "ReadOnlyYouTubeIdentityClient") as client_class, \
             patch.object(sys, "argv", ["audit_advertising_youtube.py", "--market", "us", "--discover"]), \
             contextlib.redirect_stdout(output):
            client_class.return_value.check.return_value = ReadOnlyChannelIdentity("UCexampleAdvertising", "sleepdeep.knowledge")
            self.assertEqual(audit.main(), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "ADVERTISING_OAUTH_DISCOVERY_PASS")
        self.assertEqual(result["actual_channel_id"], "UCexampleAdvertising")
        self.assertEqual(result["actual_channel_title"], "sleepdeep.knowledge")
        self.assertFalse(result["identity_pinned"])
        self.assertFalse(result["write_performed"])

        for zodiac_id in ZODIAC_IDS:
            with self.subTest(zodiac_id=zodiac_id), \
                 patch.object(audit, "ReadOnlyYouTubeIdentityClient") as client_class, \
                 patch.object(sys, "argv", ["audit_advertising_youtube.py", "--market", "us", "--discover"]):
                client_class.return_value.check.return_value = ReadOnlyChannelIdentity(zodiac_id, "zodiac")
                with self.assertRaisesRegex(RuntimeError, "HOLD_ZODIAC_OAUTH_PRESENTED_TO_ADVERTISING_LANE"):
                    audit.main()

    def test_us_normal_check_holds_until_expected_channel_is_pinned(self):
        from scripts import audit_advertising_youtube as audit

        with patch.object(audit, "ReadOnlyYouTubeIdentityClient") as client_class, \
             patch.object(sys, "argv", ["audit_advertising_youtube.py", "--market", "us"]):
            with self.assertRaisesRegex(RuntimeError, "HOLD_US_AD_CHANNEL_ID_DISCOVERY_REQUIRED"):
                audit.main()
            client_class.assert_not_called()

    def test_discovery_is_us_only(self):
        from scripts import audit_advertising_youtube as audit

        with patch.object(audit, "ReadOnlyYouTubeIdentityClient") as client_class, \
             patch.object(sys, "argv", ["audit_advertising_youtube.py", "--market", "jp", "--discover"]):
            with self.assertRaisesRegex(RuntimeError, "HOLD_ADVERTISING_DISCOVERY_US_ONLY"):
                audit.main()
            client_class.assert_not_called()

    def test_jp_identity_check_requires_exact_channel_id(self):
        from core.read_only_youtube import ReadOnlyChannelIdentity
        from scripts import audit_advertising_youtube as audit

        for channel_id, expected_status in (
            ("UC4n0nR7IBwN1KKr9T32RP_w", "ADVERTISING_OAUTH_IDENTITY_PASS"),
            ("UCdifferent", "HOLD_ADVERTISING_CHANNEL_ID_MISMATCH"),
        ):
            with self.subTest(channel_id=channel_id), \
                 patch.object(audit, "ReadOnlyYouTubeIdentityClient") as client_class, \
                 patch.object(sys, "argv", ["audit_advertising_youtube.py", "--market", "jp"]), \
                 contextlib.redirect_stdout(io.StringIO()):
                client_class.return_value.check.return_value = ReadOnlyChannelIdentity(channel_id, "ラッスン17")
                if channel_id == "UC4n0nR7IBwN1KKr9T32RP_w":
                    self.assertEqual(audit.main(), 0)
                else:
                    with self.assertRaisesRegex(RuntimeError, expected_status):
                        audit.main()

    def test_identity_runner_never_prints_credentials(self):
        source = (ROOT / "scripts" / "audit_advertising_youtube.py").read_text(encoding="utf-8")
        identity = (ROOT / "core" / "read_only_youtube.py").read_text(encoding="utf-8")
        self.assertNotIn("print(", identity)
        self.assertNotIn("json.dump", identity)
        self.assertIn('"https://www.googleapis.com/auth/youtube.readonly"', identity)
        self.assertNotIn('"client_secret":', source)
        self.assertNotIn('"refresh_token":', source)
        self.assertNotIn("print(required_env(", identity)

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





    def test_campaign_registry_contains_six_targets_and_truthful_namidata_limit(self):
        registry = json.loads((ROOT / "data" / "app_campaigns" / "campaign_registry.json").read_text(encoding="utf-8"))
        campaigns = registry["campaigns"]
        self.assertEqual(len(campaigns), 6)
        names = {row["product_name"] for row in campaigns}
        self.assertEqual(
            names,
            {"Daymark AI", "Folio AI", "STRATEGY MARKET", "STRATEGY MARKET US", "DemandScope", "NamiData Lab"},
        )
        nami = next(row for row in campaigns if row["product_name"] == "NamiData Lab")
        self.assertTrue(nami["limited_availability"])
        self.assertIsNone(nami["exact_remaining_count"])
        self.assertIn("提供数に上限", nami["availability_notice_ja"])

    def test_grounded_content_preserves_limited_availability_without_fake_count(self):
        dataset = {
            "grounding_status": "PASS",
            "campaign_id": "nami-test",
            "app_id": "namidata-lab",
            "market": "JP",
            "language": "ja",
            "source_urls": ["https://example.com"],
            "source_hashes": ["a" * 64],
            "generated_from_source_hash": "b" * 64,
            "evidence_hash": "c" * 64,
            "product_name": "NamiData Lab",
            "description": "データ分析を支援します。",
            "features": ["相関分析", "回帰分析", "レポート出力"],
            "cta_url": "https://example.com",
            "posting_eligible": True,
            "hold_reasons": [],
            "limited_availability": True,
            "availability_notice_ja": "提供数に上限があります。",
        }
        content = generate_app_ad_content(dataset)
        self.assertTrue(content["limited_availability"])
        self.assertIn("提供数に上限があります。", content["caption"])
        self.assertNotRegex(content["caption"], r"残り\s*\d+")

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
        self.assertIn("platformPostUrl", source)
        self.assertIn("platform_post_id", source)
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



    def test_social_post_reconciliation_extracts_public_url_and_native_id(self):
        response = {
            "post": {
                "status": "published",
                "platforms": [{
                    "platform": "instagram",
                    "accountId": "ig-ad-1",
                    "status": "published",
                    "platformPostId": "native-123",
                    "platformPostUrl": "https://www.instagram.com/reel/ABC123/",
                    "publishedAt": "2026-11-21T19:07:26Z",
                }],
            }
        }
        result = build_reconciliation_result(
            response, platform="instagram", account_id="ig-ad-1", zernio_post_id="zernio-post-1"
        )
        self.assertEqual(result["status"], "SOCIAL_POST_PUBLISHED_URL_CONFIRMED")
        self.assertEqual(result["platform_post_id"], "native-123")
        self.assertEqual(result["account_verification_source"], "zernio_post_response")
        self.assertEqual(result["published_url"], "https://www.instagram.com/reel/ABC123/")
        self.assertTrue(result["public_url_confirmed"])
        self.assertTrue(result["read_only"])
        self.assertFalse(result["write_performed"])

    def test_tiktok_published_without_resolved_url_is_reported_as_pending(self):
        response = {
            "post": {
                "platforms": [{
                    "platform": "tiktok",
                    "accountId": "tt-ad-1",
                    "status": "published",
                    "platformPostId": "",
                    "publishedUrl": "",
                }],
            }
        }
        result = build_reconciliation_result(
            response, platform="tiktok", account_id="tt-ad-1", zernio_post_id="zernio-post-2"
        )
        self.assertEqual(result["status"], "SOCIAL_POST_PUBLISHED_URL_PENDING")
        self.assertFalse(result["public_url_confirmed"])
        self.assertFalse(result["write_performed"])

    def test_social_post_reconciliation_rejects_wrong_platform_or_account(self):
        response = {
            "post": {
                "platforms": [{
                    "platform": "instagram",
                    "accountId": "another-account",
                    "status": "published",
                    "platformPostUrl": "https://www.instagram.com/p/ABC123/",
                }],
            }
        }
        with self.assertRaisesRegex(ReconciliationHold, "HOLD_POST_ACCOUNT_PLATFORM_MISMATCH"):
            build_reconciliation_result(
                response, platform="instagram", account_id="expected-account", zernio_post_id="zernio-post-3"
            )

    def test_social_reconciliation_account_resolution_is_advertising_scoped(self):
        config = json.loads((ROOT / "config" / "social_lanes.json").read_text(encoding="utf-8"))
        account = resolve_advertising_account(
            config, language="ja", platform="instagram", account_id="6a9799d277555aae01bd18c1"
        )
        self.assertEqual(account["market"], "JP")
        self.assertEqual(account["credential_env"], "ZERNIO_API_KEY_1")
        with self.assertRaisesRegex(ReconciliationHold, "HOLD_ACCOUNT_NOT_EXACTLY_ONE"):
            resolve_advertising_account(
                config, language="ja", platform="instagram", account_id="not-an-ad-account"
            )

    def test_social_reconciliation_workflow_is_read_only_and_market_scoped(self):
        workflow = (ROOT / ".github" / "workflows" / "youtube-ad-pipeline.yml").read_text(encoding="utf-8")
        runner = (ROOT / "scripts" / "reconcile_advertising_social_posts.py").read_text(encoding="utf-8")
        self.assertIn("social-post-reconcile", workflow)
        self.assertIn("social-jp-post-reconcile", workflow)
        self.assertIn("social-us-post-reconcile", workflow)
        self.assertIn("social-jp-instagram-historical-reconcile", workflow)
        self.assertIn("social-jp-tiktok-historical-reconcile", workflow)
        self.assertIn("[reconcile-instagram]", workflow)
        self.assertIn("[reconcile-tiktok]", workflow)
        self.assertIn("client.get_post(args.post_id)", runner)
        self.assertNotIn("create_video_post_now", runner)
        self.assertNotIn("requests.post", runner)
        self.assertIn('"write_performed": False', runner)


    def test_post_response_account_id_omission_requires_explicit_historical_provenance(self):
        response = {
            "post": {
                "platforms": [{
                    "platform": "instagram",
                    "status": "published",
                    "platformPostId": "native-456",
                    "platformPostUrl": "https://www.instagram.com/p/XYZ456/",
                }],
            }
        }
        with self.assertRaisesRegex(ReconciliationHold, "HOLD_POST_ACCOUNT_ID_NOT_RETURNED"):
            build_reconciliation_result(
                response, platform="instagram", account_id="ig-ad-1", zernio_post_id="zernio-post-4"
            )
        result = build_reconciliation_result(
            response,
            platform="instagram",
            account_id="ig-ad-1",
            zernio_post_id="zernio-post-4",
            allow_account_id_omission=True,
        )
        self.assertEqual(result["status"], "SOCIAL_POST_PUBLISHED_URL_CONFIRMED")
        self.assertEqual(result["account_verification_source"], "original_creation_run_arguments")
        self.assertFalse(result["write_performed"])


    def test_social_post_reconciliation_matches_nested_zernio_account_object(self):
        response = {
            "post": {
                "platforms": [{
                    "platform": "instagram",
                    "accountId": {
                        "_id": "ig-ad-1",
                        "displayName": "Advertising Instagram",
                    },
                    "status": "published",
                    "platformPostId": "native-nested-1",
                    "platformPostUrl": "https://www.instagram.com/p/NESTED123/",
                }],
            }
        }
        result = build_reconciliation_result(
            response,
            platform="instagram",
            account_id="ig-ad-1",
            zernio_post_id="zernio-post-nested",
        )
        self.assertEqual(result["status"], "SOCIAL_POST_PUBLISHED_URL_CONFIRMED")
        self.assertEqual(result["account_verification_source"], "zernio_post_response")
        self.assertEqual(result["published_url"], "https://www.instagram.com/p/NESTED123/")


    def test_historical_post_ledger_contains_both_verified_public_posts(self):
        ledger = json.loads((ROOT / "data" / "social_post_ledger.json").read_text(encoding="utf-8"))
        self.assertEqual(ledger["schema_version"], 1)
        self.assertEqual(len(ledger["records"]), 2)
        by_platform = {row["platform"]: row for row in ledger["records"]}
        for platform, expected_url in (
            ("instagram", "https://www.instagram.com/reel/DgA8UtNikNx/"),
            ("tiktok", "https://www.tiktok.com/@nice_a17/video/7710703558940790017"),
        ):
            row = by_platform[platform]
            self.assertEqual(row["status"], "PUBLISHED")
            self.assertTrue(row["published_url_verified"])
            self.assertEqual(row["published_url"], expected_url)
            self.assertTrue(row["social_post_created"])

    def test_persistent_ledger_blocks_same_media_for_same_advertising_account(self):
        ledger = json.loads((ROOT / "data" / "social_post_ledger.json").read_text(encoding="utf-8"))
        instagram = next(row for row in ledger["records"] if row["platform"] == "instagram")
        state = ledger_policy_state(
            ledger,
            campaign_id=instagram["campaign_id"],
            video_sha256=instagram["video_sha256"],
            platform="instagram",
            account_id=instagram["account_id"],
            idempotency_key_sha256=instagram["idempotency_key_sha256"],
            now=datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(state["duplicate_found"])
        self.assertEqual(state["posts_today"], 0)
        self.assertEqual(state["last_posted_at"].date().isoformat(), "2026-11-21")

    def test_persistent_ledger_reservation_is_committed_before_any_post_write(self):
        empty_ledger = {"schema_version": 1, "records": []}
        encoded = base64.b64encode(json.dumps(empty_ledger).encode("utf-8")).decode("ascii")

        class FakeResponse:
            status_code = 200

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        record = {
            "idempotency_key_sha256": "a" * 64,
            "campaign_id": "ledger-test",
            "app_id": "test-app",
            "product_name": "Test App",
            "market": "JP",
            "language": "ja",
            "platform": "instagram",
            "account_id": "ig-test-account",
            "source_hash": "b" * 64,
            "evidence_hash": "c" * 64,
            "video_sha256": "d" * 64,
            "store_url": "https://example.com",
            "media_upload_performed": False,
            "social_post_created": False,
        }
        campaign = {
            "status": "ACTIVE",
            "official_url": "https://example.com",
            "source_urls": ["https://example.com"],
            "store_url": "https://example.com",
            "cta_url": "https://example.com",
            "market": "JP",
            "grounding_status": "PASS",
        }
        account = {"purpose": "advertising", "market": "JP", "platform": "instagram"}
        ledger = GitHubSocialPostLedger(
            token="test-token",
            repository="owner/repo",
            branch="test-branch",
        )
        with patch(
            "core.social_post_ledger.requests.get",
            return_value=FakeResponse({"sha": "old-sha", "content": encoded}),
        ), patch(
            "core.social_post_ledger.requests.put",
            return_value=FakeResponse({"content": {"sha": "new-sha"}}),
        ) as put:
            reserved = ledger.reserve_post(
                record=record,
                campaign=campaign,
                account=account,
                platform="instagram",
                capacity_ok=True,
                now=datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(reserved["status"], "RESERVED")
        self.assertTrue(reserved["reserved_at"])
        self.assertEqual(put.call_count, 1)
        body = put.call_args.kwargs["json"]
        persisted = json.loads(base64.b64decode(body["content"]).decode("utf-8"))
        self.assertEqual(persisted["records"][0]["status"], "RESERVED")
        self.assertEqual(body["branch"], "test-branch")

    def test_controlled_post_runner_reserves_ledger_before_media_upload_and_social_post(self):
        source = (ROOT / "scripts" / "post_app_campaign_instagram_test.py").read_text(encoding="utf-8")
        self.assertLess(source.index("ledger.reserve_post("), source.index("client.upload_temp_media(output)"))
        self.assertLess(source.index("client.upload_temp_media(output)"), source.index("client.create_video_post_now("))
        self.assertIn("GitHubSocialPostLedger.from_environment()", source)
        self.assertIn('"ledger_recorded": True', source)
        self.assertIn('"ABORTED_BEFORE_POST"', source)
        self.assertIn('"SUBMISSION_UNKNOWN"', source)

    def test_phase_c_jobs_have_scoped_contents_write_for_the_ledger_only(self):
        workflow = (ROOT / ".github" / "workflows" / "youtube-ad-pipeline.yml").read_text(encoding="utf-8")
        self.assertEqual(workflow.count("SOCIAL_LEDGER_TOKEN: ${{ github.token }}"), 3)
        self.assertGreaterEqual(workflow.count("permissions:\n      contents: write"), 2)
        self.assertIn("group: advertising-social-ledger-${{ github.ref }}", workflow)


    def test_ledger_daily_cap_and_minimum_interval_use_account_history(self):
        ledger = {
            "schema_version": 1,
            "records": [
                {
                    "status": "PUBLISHED",
                    "platform": "instagram",
                    "account_id": "ig-account",
                    "video_sha256": "a" * 64,
                    "reserved_at": "2026-11-23T10:15:00+00:00",
                },
                {
                    "status": "RESERVED",
                    "platform": "instagram",
                    "account_id": "ig-account",
                    "video_sha256": "b" * 64,
                    "reserved_at": "2026-11-23T11:30:00+00:00",
                },
            ],
        }
        state = ledger_policy_state(
            ledger,
            campaign_id="new-campaign",
            video_sha256="c" * 64,
            platform="instagram",
            account_id="ig-account",
            idempotency_key_sha256="d" * 64,
            now=datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc),
        )
        self.assertFalse(state["duplicate_found"])
        self.assertEqual(state["posts_today"], 2)
        self.assertEqual(state["last_posted_at"].isoformat(), "2026-11-23T11:30:00+00:00")

    def test_aborted_before_post_reservation_does_not_permanently_block_retry(self):
        ledger = {
            "schema_version": 1,
            "records": [{
                "status": "ABORTED_BEFORE_POST",
                "platform": "instagram",
                "account_id": "ig-account",
                "video_sha256": "a" * 64,
                "idempotency_key_sha256": "b" * 64,
                "reserved_at": "2026-11-23T10:15:00+00:00",
            }],
        }
        state = ledger_policy_state(
            ledger,
            campaign_id="new-campaign",
            video_sha256="a" * 64,
            platform="instagram",
            account_id="ig-account",
            idempotency_key_sha256="b" * 64,
            now=datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc),
        )
        self.assertFalse(state["duplicate_found"])
        self.assertEqual(state["posts_today"], 0)
        self.assertIsNone(state["last_posted_at"])

    def test_ledger_rejects_status_regression(self):
        stored = {
            "schema_version": 1,
            "records": [{
                "idempotency_key_sha256": "a" * 64,
                "status": "PUBLISHED",
                "platform": "instagram",
                "account_id": "ig-account",
            }],
        }
        encoded = base64.b64encode(json.dumps(stored).encode("utf-8")).decode("ascii")

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"sha": "ledger-sha", "content": encoded}

        ledger = GitHubSocialPostLedger(
            token="test-token", repository="owner/repo", branch="test-branch"
        )
        with patch("core.social_post_ledger.requests.get", return_value=FakeResponse()):
            with self.assertRaisesRegex(SocialLedgerHold, "HOLD_SOCIAL_LEDGER_STATUS_TRANSITION_INVALID"):
                ledger.update_post("a" * 64, status="CREATED")

    def test_published_url_capture_only_accepts_platform_domains(self):
        source = (ROOT / "scripts" / "post_app_campaign_instagram_test.py").read_text(encoding="utf-8")
        self.assertIn('"instagram": "instagram.com"', source)
        self.assertIn('"tiktok": "tiktok.com"', source)
        self.assertIn("parsed.scheme == \"https\"", source)
        self.assertIn('host.endswith("." + allowed_domain)', source)


    def test_ledger_write_probe_updates_only_metadata_and_never_posts(self):
        current_ledger = json.loads((ROOT / "data" / "social_post_ledger.json").read_text(encoding="utf-8"))
        encoded = base64.b64encode(json.dumps(current_ledger).encode("utf-8")).decode("ascii")

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"sha": "ledger-sha", "content": encoded}

        ledger = GitHubSocialPostLedger(
            token="test-token", repository="owner/repo", branch="test-branch"
        )
        with patch("core.social_post_ledger.requests.get", return_value=FakeResponse()), patch(
            "core.social_post_ledger.requests.put",
            return_value=FakeResponse(),
        ) as put:
            result = ledger.verify_writable()

        self.assertEqual(result["status"], "SOCIAL_POST_LEDGER_WRITE_OK")
        self.assertTrue(result["repository_write_performed"])
        self.assertFalse(result["media_upload_performed"])
        self.assertFalse(result["social_post_performed"])
        self.assertFalse(result["youtube_write_performed"])
        self.assertFalse(result["zodiac_write_performed"])
        persisted = json.loads(base64.b64decode(put.call_args.kwargs["json"]["content"]).decode("utf-8"))
        self.assertEqual(persisted["last_verified_at"], result["last_verified_at"])
        self.assertEqual(persisted["records"], current_ledger["records"])

    def test_workflow_ledger_write_check_has_no_social_write_surface(self):
        workflow = (ROOT / ".github" / "workflows" / "youtube-ad-pipeline.yml").read_text(encoding="utf-8")
        runner = (ROOT / "scripts" / "check_social_post_ledger.py").read_text(encoding="utf-8")
        self.assertIn("social-ledger-check", workflow)
        self.assertIn("[ledger-write-check]", workflow)
        self.assertIn("social-ledger-write-check:", workflow)
        self.assertIn("SOCIAL_LEDGER_TOKEN: ${{ github.token }}", workflow)
        self.assertIn("scripts/check_social_post_ledger.py", workflow)
        self.assertNotIn("create_video_post_now", runner)
        self.assertNotIn("requests.post", runner)
        self.assertIn('"social_post_performed": False', runner)

if __name__ == "__main__":
    unittest.main()
