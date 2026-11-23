from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.social_post_ledger import GitHubSocialPostLedger, SocialLedgerHold  # noqa: E402


def main() -> int:
    try:
        result = GitHubSocialPostLedger.from_environment().verify_writable()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (SocialLedgerHold, OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({
            "status": str(exc) if str(exc).startswith("HOLD_") else "HOLD_SOCIAL_POST_LEDGER_CHECK_FAILED",
            "repository_write_performed": False,
            "media_upload_performed": False,
            "social_post_performed": False,
            "youtube_write_performed": False,
            "zodiac_write_performed": False,
        }, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
