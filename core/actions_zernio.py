"""Read-only Zernio health client for GitHub Actions validation."""

from __future__ import annotations

from typing import Any

import requests


class ZernioValidationError(RuntimeError):
    pass


class ActionsZernioClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 60):
        if not api_key.strip():
            raise ZernioValidationError("Required lane-specific Zernio secret is missing")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout

    def _get(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/{path.lstrip('/')}",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": "youtube-auto-social-validator/1.0",
            },
            params=params,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise ZernioValidationError(f"Zernio GET failed with HTTP {response.status_code}")
        value = response.json()
        if not isinstance(value, dict):
            raise ZernioValidationError("Zernio response is not a JSON object")
        return value

    def account_health(self, account_id: str) -> dict[str, Any]:
        value = self._get(f"/accounts/{account_id}/health")
        permissions = value.get("permissions") if isinstance(value.get("permissions"), dict) else {}
        token_status = value.get("tokenStatus") if isinstance(value.get("tokenStatus"), dict) else {}
        return {
            "account_id": value.get("accountId") or value.get("id") or value.get("_id") or "",
            "platform": value.get("platform") or "",
            "status": value.get("status") or "unknown",
            "can_post": bool(value.get("canPost") or permissions.get("canPost")),
            "token_valid": bool(value.get("tokenValid") or token_status.get("valid")),
            "needs_reconnect": bool(value.get("needsReconnect")),
            "issues": [str(issue) for issue in value.get("issues") or []][:10],
        }

    def tiktok_capacity(self, account_id: str) -> dict[str, Any]:
        value = self._get(
            f"/accounts/{account_id}/tiktok/creator-info",
            params={"mediaType": "video"},
        )
        creator = value.get("creator") if isinstance(value.get("creator"), dict) else {}
        limits = value.get("postingLimits") if isinstance(value.get("postingLimits"), dict) else {}
        can_post_more = creator.get("canPostMore")
        return {
            "can_post_more": can_post_more if isinstance(can_post_more, bool) else None,
            "max_video_duration_seconds": int(limits.get("maxVideoDurationSec") or 0),
        }
