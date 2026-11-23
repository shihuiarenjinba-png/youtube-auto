"""Persistent, fail-closed ledger for advertising social posts.

The ledger is stored as a versioned JSON file in this repository. A reservation is
committed before any external media or post write. An uncertain submission remains
blocked until manually reconciled; it is never silently retried.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests

from .social_posting_policy import validate_preflight


LEDGER_PATH = "data/social_post_ledger.json"
ACTIVE_STATUSES = {
    "RESERVED",
    "MEDIA_UPLOADED",
    "SUBMISSION_UNKNOWN",
    "CREATED",
    "PUBLISHED",
    "FAILED",
}
ALLOWED_TRANSITIONS = {
    "RESERVED": {
        "MEDIA_UPLOADED",
        "ABORTED_BEFORE_POST",
        "SUBMISSION_UNKNOWN",
        "CREATED",
        "PUBLISHED",
        "FAILED",
    },
    "MEDIA_UPLOADED": {
        "ABORTED_BEFORE_POST",
        "SUBMISSION_UNKNOWN",
        "CREATED",
        "PUBLISHED",
        "FAILED",
    },
    "CREATED": {"CREATED", "SUBMISSION_UNKNOWN", "PUBLISHED", "FAILED"},
    "SUBMISSION_UNKNOWN": {
        "SUBMISSION_UNKNOWN",
        "CREATED",
        "PUBLISHED",
        "FAILED",
    },
    "PUBLISHED": {"PUBLISHED"},
    "FAILED": {"FAILED"},
    "ABORTED_BEFORE_POST": {"ABORTED_BEFORE_POST"},
}


class SocialLedgerHold(RuntimeError):
    """Raised when a durable posting ledger check or write cannot be trusted."""


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timestamp_for_record(record: dict[str, Any]) -> datetime | None:
    for key in ("published_at", "updated_at", "reserved_at"):
        parsed = _parse_timestamp(record.get(key))
        if parsed is not None:
            return parsed
    return None


def ledger_policy_state(
    ledger: dict[str, Any],
    *,
    campaign_id: str,
    video_sha256: str,
    platform: str,
    account_id: str,
    idempotency_key_sha256: str,
    now: datetime,
) -> dict[str, Any]:
    records = ledger.get("records")
    if not isinstance(records, list):
        raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_RECORDS_INVALID")
    relevant: list[tuple[dict[str, Any], datetime]] = []
    duplicate_found = False

    for record in records:
        if not isinstance(record, dict):
            raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_RECORD_INVALID")
        status = str(record.get("status") or "").upper()
        if status not in ACTIVE_STATUSES and status != "ABORTED_BEFORE_POST":
            raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_STATUS_UNKNOWN")
        if status not in ACTIVE_STATUSES:
            continue
        same_target = (
            str(record.get("platform") or "").lower() == platform
            and str(record.get("account_id") or "") == account_id
        )
        if not same_target:
            continue

        if (
            str(record.get("idempotency_key_sha256") or "") == idempotency_key_sha256
            or str(record.get("video_sha256") or "") == video_sha256
        ):
            duplicate_found = True

        timestamp = _timestamp_for_record(record)
        if timestamp is not None:
            relevant.append((record, timestamp))

    now_utc = now.astimezone(timezone.utc)
    posts_today = sum(1 for _, timestamp in relevant if timestamp.date() == now_utc.date())
    last_posted_at = max((timestamp for _, timestamp in relevant), default=None)
    return {
        "duplicate_found": duplicate_found,
        "posts_today": posts_today,
        "last_posted_at": last_posted_at,
    }


class GitHubSocialPostLedger:
    """GitHub Contents API-backed ledger; all writes are explicit and fail closed."""

    def __init__(
        self,
        *,
        token: str,
        repository: str,
        branch: str,
        path: str = LEDGER_PATH,
        timeout: int = 30,
    ):
        if not token.strip():
            raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_TOKEN_MISSING")
        if not repository.strip() or "/" not in repository:
            raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_REPOSITORY_INVALID")
        if not branch.strip():
            raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_BRANCH_MISSING")
        self.token = token.strip()
        self.repository = repository.strip()
        self.branch = branch.strip()
        self.path = path
        self.timeout = timeout
        self.api_url = (
            "https://api.github.com/repos/"
            + self.repository
            + "/contents/"
            + quote(self.path, safe="/")
        )
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "advertising-social-post-ledger/1.0",
        }

    @classmethod
    def from_environment(cls) -> "GitHubSocialPostLedger":
        return cls(
            token=os.environ.get("SOCIAL_LEDGER_TOKEN", ""),
            repository=os.environ.get("GITHUB_REPOSITORY", ""),
            branch=os.environ.get("GITHUB_REF_NAME", ""),
        )

    def _read(self) -> tuple[dict[str, Any], str]:
        try:
            response = requests.get(
                self.api_url,
                headers=self.headers,
                params={"ref": self.branch},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_READ_NETWORK") from exc
        if response.status_code != 200:
            raise SocialLedgerHold(f"HOLD_SOCIAL_LEDGER_READ_HTTP_{response.status_code}")
        try:
            payload = response.json()
            raw = base64.b64decode(payload["content"], validate=False)
            ledger = json.loads(raw.decode("utf-8"))
            sha = str(payload["sha"])
        except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
            raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_FORMAT_INVALID") from exc
        if not isinstance(ledger, dict) or ledger.get("schema_version") != 1:
            raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_SCHEMA_UNSUPPORTED")
        if not isinstance(ledger.get("records"), list):
            raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_RECORDS_INVALID")
        return ledger, sha

    def _write(self, ledger: dict[str, Any], sha: str, message: str) -> None:
        rendered = json.dumps(ledger, ensure_ascii=False, indent=2) + "\n"
        encoded = base64.b64encode(rendered.encode("utf-8")).decode("ascii")
        payload = {
            "message": message,
            "content": encoded,
            "sha": sha,
            "branch": self.branch,
        }
        try:
            response = requests.put(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_WRITE_NETWORK") from exc
        if response.status_code != 200:
            raise SocialLedgerHold(f"HOLD_SOCIAL_LEDGER_WRITE_HTTP_{response.status_code}")

    def verify_writable(self) -> dict[str, Any]:
        """Read and safely update ledger metadata to verify GitHub Contents write access."""
        ledger, sha = self._read()
        verified_at = datetime.now(timezone.utc).isoformat()
        ledger["last_verified_at"] = verified_at
        self._write(
            ledger,
            sha,
            "Verify advertising social post ledger write access without posting [no-social-write]",
        )
        return {
            "status": "SOCIAL_POST_LEDGER_WRITE_OK",
            "repository": self.repository,
            "branch": self.branch,
            "ledger_path": self.path,
            "record_count": len(ledger["records"]),
            "last_verified_at": verified_at,
            "repository_write_performed": True,
            "media_upload_performed": False,
            "social_post_performed": False,
            "youtube_write_performed": False,
            "zodiac_write_performed": False,
        }

    def reserve_post(
        self,
        *,
        record: dict[str, Any],
        campaign: dict[str, Any],
        account: dict[str, Any],
        platform: str,
        capacity_ok: bool,
        now: datetime,
    ) -> dict[str, Any]:
        ledger, sha = self._read()
        state = ledger_policy_state(
            ledger,
            campaign_id=str(record["campaign_id"]),
            video_sha256=str(record["video_sha256"]),
            platform=platform,
            account_id=str(record["account_id"]),
            idempotency_key_sha256=str(record["idempotency_key_sha256"]),
            now=now,
        )
        validate_preflight(
            campaign=campaign,
            account=account,
            platform=platform,
            media_valid=True,
            duplicate_found=state["duplicate_found"],
            capacity_ok=capacity_ok,
            posts_today=state["posts_today"],
            last_posted_at=state["last_posted_at"],
            now=now,
        )

        record = dict(record)
        record["status"] = "RESERVED"
        record["reserved_at"] = now.astimezone(timezone.utc).isoformat()
        record["updated_at"] = record["reserved_at"]
        existing_matches = [
            (index, existing)
            for index, existing in enumerate(ledger["records"])
            if isinstance(existing, dict)
            and existing.get("idempotency_key_sha256") == record["idempotency_key_sha256"]
        ]
        if len(existing_matches) > 1:
            raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_IDEMPOTENCY_KEY_NOT_UNIQUE")
        if existing_matches:
            index, existing = existing_matches[0]
            if str(existing.get("status") or "").upper() != "ABORTED_BEFORE_POST":
                raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_IDEMPOTENCY_KEY_EXISTS")
            ledger["records"][index] = record
        else:
            ledger["records"].append(record)
        self._write(
            ledger,
            sha,
            "Reserve advertising social post before external write [social-ledger]",
        )
        return record

    def update_post(self, idempotency_key_sha256: str, **updates: Any) -> dict[str, Any]:
        allowed_fields = {
            "status",
            "media_upload_performed",
            "media_uploaded_at",
            "social_post_created",
            "zernio_post_id",
            "platform_post_id",
            "post_status",
            "published_url",
            "published_url_verified",
            "published_at",
            "updated_at",
            "failure_code",
        }
        if not updates or set(updates) - allowed_fields:
            raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_UPDATE_FIELDS_INVALID")

        ledger, sha = self._read()
        matches = [
            row
            for row in ledger["records"]
            if isinstance(row, dict)
            and row.get("idempotency_key_sha256") == idempotency_key_sha256
        ]
        if len(matches) != 1:
            raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_RECORD_NOT_EXACTLY_ONE")
        record = matches[0]
        current_status = str(record.get("status") or "").upper()
        next_status = str(updates.get("status", current_status)).upper()
        if next_status not in ALLOWED_TRANSITIONS.get(current_status, set()):
            raise SocialLedgerHold("HOLD_SOCIAL_LEDGER_STATUS_TRANSITION_INVALID")
        record.update(updates)
        record["status"] = next_status
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write(
            ledger,
            sha,
            "Update advertising social post ledger state [social-ledger]",
        )
        return dict(record)
