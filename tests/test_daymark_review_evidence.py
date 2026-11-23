from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path


from core.app_ad_video import AppVideoHold, sha256_file, write_video_review_bundle


class DaymarkReviewEvidenceTests(unittest.TestCase):
    def test_bundle_records_exact_source_images_cards_video_and_local_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = root / "assets" / "advertising" / "daymark-ai"
            bgm_dir = root / "assets" / "bgm"
            cards_dir = root / "work" / "cards"
            assets.mkdir(parents=True)
            bgm_dir.mkdir(parents=True)
            cards_dir.mkdir(parents=True)

            screenshot_rows = []
            for index in range(5):
                path = assets / f"source-{index + 1:02d}.png"
                path.write_bytes(b"png-source-" + str(index).encode("ascii"))
                screenshot_rows.append({
                    "path": str(path.relative_to(root)),
                    "sha256": sha256_file(path),
                })

            card_paths = []
            for index in range(4):
                path = cards_dir / f"card-{index + 1:02d}.png"
                path.write_bytes(b"png-card-" + str(index).encode("ascii"))
                card_paths.append(path)

            video_path = root / "work" / "preview.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_bytes(b"test-video-bytes" * 128)
            bgm = bgm_dir / "local-track.mp3"
            bgm.write_bytes(b"test-bgm-bytes")

            campaign = {
                "campaign_id": "daymark-test",
                "app_id": "OkinawaDesktopTools.DaymarkAI",
                "product_name": "Daymark AI",
                "screenshots": screenshot_rows,
            }
            content = {
                "campaign_id": "daymark-test",
                "generated_from_source_hash": "a" * 64,
                "evidence_hash": "b" * 64,
            }
            validation = {
                "video_sha256": sha256_file(video_path),
                "bgm_name": bgm.name,
                "codec": "h264",
                "width": 1080,
                "height": 1920,
                "audio_codec": "aac",
                "duration_seconds": 12.0,
            }
            bundle = root / "review-bundle"

            evidence_path = write_video_review_bundle(
                campaign,
                content,
                root=root,
                cards_dir=cards_dir,
                video_path=video_path,
                evidence_dir=bundle,
                validation=validation,
            )

            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["review_status"], "REVIEW_REQUIRED_NOT_PUBLISHED_BY_PREVIEW_JOB")
            self.assertEqual(len(evidence["source_assets"]), 5)
            self.assertEqual([row["used_in_video"] for row in evidence["source_assets"]], [True, True, True, True, False])
            self.assertEqual(len(evidence["rendered_cards"]), 4)
            self.assertEqual(evidence["generation"]["image_generation_api_used"], False)
            self.assertEqual(evidence["generation"]["voice_generation_api_used"], False)
            self.assertFalse(evidence["publication"]["performed"])
            self.assertEqual(evidence["video"]["sha256"], validation["video_sha256"])
            self.assertTrue((bundle / "daymark-ai-review.mp4").is_file())
            self.assertTrue((bundle / "audio" / "local-track.mp3").is_file())
            for row in evidence["source_assets"]:
                copied = bundle / row["bundle_path"]
                self.assertTrue(copied.is_file())
                self.assertEqual(sha256_file(copied), row["sha256"])

    def test_bundle_rejects_video_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_dir = root / "assets" / "advertising" / "daymark-ai"
            cards_dir = root / "cards"
            bgm_dir = root / "assets" / "bgm"
            source_dir.mkdir(parents=True)
            cards_dir.mkdir()
            bgm_dir.mkdir()
            rows = []
            for index in range(4):
                image_path = source_dir / f"screen-{index}.png"
                image_path.write_bytes(b"png-screen-" + str(index).encode("ascii"))
                rows.append({"path": str(image_path.relative_to(root)), "sha256": sha256_file(image_path)})
            for index in range(4):
                (cards_dir / f"card-{index + 1:02d}.png").write_bytes(b"png-card-" + str(index).encode("ascii"))
            video = root / "preview.mp4"
            video.write_bytes(b"x" * 2048)
            (bgm_dir / "music.mp3").write_bytes(b"bgm")

            with self.assertRaisesRegex(AppVideoHold, "HOLD_REVIEW_BUNDLE_VIDEO_HASH_MISMATCH"):
                write_video_review_bundle(
                    {"campaign_id": "c", "screenshots": rows},
                    {"campaign_id": "c"},
                    root=root,
                    cards_dir=cards_dir,
                    video_path=video,
                    evidence_dir=root / "bundle",
                    validation={"video_sha256": "0" * 64, "bgm_name": "music.mp3"},
                )

    def test_preview_workflow_is_separate_from_approved_posting(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "youtube-ad-pipeline.yml").read_text(encoding="utf-8")
        preview_script = (root / "scripts" / "preview_app_campaign_video.py").read_text(encoding="utf-8")
        self.assertIn("daymark-video-review-preview:", workflow)
        self.assertIn("[daymark-review-preview]", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)
        self.assertIn("retention-days: 7", workflow)
        self.assertIn("[phase-c-instagram-approved]", workflow)
        self.assertIn("[phase-c-tiktok-approved]", workflow)
        self.assertNotIn("create_video_post_now", preview_script)
        self.assertNotIn("ActionsZernioClient", preview_script)
        self.assertIn('"posting_performed": False', preview_script)
        self.assertIn('"zernio_called": False', preview_script)


if __name__ == "__main__":
    unittest.main()
