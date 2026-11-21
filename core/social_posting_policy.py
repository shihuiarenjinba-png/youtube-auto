"""Pure fail-closed policy helpers for future controlled social posting."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any


DAILY_CAPS = {"instagram": 2, "tiktok": 2}
MIN_POST_INTERVAL = timedelta(hours=3)


def content_fingerprint(
    *, campaign_id: str, source_hash: str, video_hash: str, platform: str, account_id: str
) -> str:
    values = (campaign_id, source_hash, video_hash, platform, account_id)
    if not all(str(value).strip() for value in values):
        raise ValueError("fingerprint fields must all be non-empty")
    raw = "|".join(str(value).strip() for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def idempotency_key(**values: str) -> str:
    return "social-ad-" + content_fingerprint(**values)


def choose_round_robin(accounts: list[dict[str, Any]], history: list[dict[str, Any]]) -> dict[str, Any]:
    advertising = [row for row in accounts if row.get("purpose") == "advertising"]
    if not advertising:
        raise ValueError("no advertising account is available")
    last_used: dict[str, datetime] = {}
    for row in history:
        account_id = str(row.get("account_id") or "")
        value = row.get("posted_at")
        if account_id and isinstance(value, datetime):
            last_used[account_id] = max(last_used.get(account_id, value), value)
    return min(
        advertising,
        key=lambda row: (last_used.get(str(row["account_id"]), datetime.min), str(row["account_id"])),
    )


def validate_preflight(
    *,
    campaign: dict[str, Any],
    account: dict[str, Any],
    platform: str,
    media_valid: bool,
    duplicate_found: bool,
    capacity_ok: bool,
    posts_today: int,
    last_posted_at: datetime | None,
    now: datetime,
) -> None:
    checks = {
        "HOLD_CAMPAIGN_NOT_ACTIVE": campaign.get("status") == "ACTIVE",
        "HOLD_OFFICIAL_URL_MISSING": bool(campaign.get("official_url")),
        "HOLD_GROUNDING_NOT_PASSED": campaign.get("grounding_status") == "PASS",
        "HOLD_CTA_URL_MISMATCH": bool(campaign.get("cta_url"))
        and campaign.get("cta_url") in {
            campaign.get("official_url"),
            campaign.get("store_url"),
            *(campaign.get("source_urls") or []),
        },
        "HOLD_ACCOUNT_NOT_ADVERTISING": account.get("purpose") == "advertising",
        "HOLD_MARKET_MISMATCH": account.get("market") == campaign.get("market"),
        "HOLD_PLATFORM_MISMATCH": account.get("platform") == platform,
        "HOLD_MEDIA_INVALID": media_valid,
        "HOLD_DUPLICATE_CONTENT": not duplicate_found,
        "HOLD_PLATFORM_CAPACITY": capacity_ok,
        "HOLD_DAILY_CAPACITY": posts_today < DAILY_CAPS.get(platform, 0),
        "HOLD_MINIMUM_INTERVAL": last_posted_at is None or now - last_posted_at >= MIN_POST_INTERVAL,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(",".join(failed))
