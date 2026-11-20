from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.advertising_rag import (  # noqa: E402
    GroundedExtractor,
    PublicHttpsFetcher,
    RagHold,
    generate_grounded_content,
    source_as_dict,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Advertising URL-grounded RAG dry-run")
    parser.add_argument("--market", choices=("jp", "us"), required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--source-url", required=True)
    args = parser.parse_args()
    if not args.campaign_id.strip():
        raise RuntimeError("HOLD_CAMPAIGN_ID_MISSING")

    try:
        final_url, body, html = PublicHttpsFetcher().fetch(args.source_url)
        source = GroundedExtractor().extract(
            campaign_id=args.campaign_id.strip(),
            requested_url=args.source_url,
            final_url=final_url,
            body=body,
            html=html,
        )
        content = generate_grounded_content(source, market=args.market)
    except RagHold as exc:
        print(json.dumps({
            "status": str(exc),
            "campaign_id": args.campaign_id.strip(),
            "upload_performed": False,
            "social_post_performed": False,
            "fallback_performed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({
        "status": "RAG_DRY_RUN_PASS",
        "upload_performed": False,
        "social_post_performed": False,
        "source": source_as_dict(source),
        "generated_content": content,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
