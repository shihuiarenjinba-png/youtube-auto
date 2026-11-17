"""Read-only Zernio health client for GitHub Actions validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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

    def _post_json(self, path: str, *, body: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/{path.lstrip('/')}",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "youtube-auto-social-validator/1.0",
            },
            json=body,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise ZernioValidationError(f"Zernio POST failed with HTTP {response.status_code}")
        value = response.json()
        if not isinstance(value, dict):
            raise ZernioValidationError("Zernio response is not a JSON object")
        return value

    def upload_temp_media(self, path: Path) -> dict[str, Any]:
        if not path.is_file() or path.stat().st_size < 1024:
            raise ZernioValidationError("Media probe file is missing or too small")
        presigned = self._post_json(
            "/media/presign",
            body={
                "filename": path.name,
                "contentType": "video/mp4",
                "size": path.stat().st_size,
            },
        )
        upload_url = str(presigned.get("uploadUrl") or "")
        public_url = str(presigned.get("publicUrl") or "")
        storage_key = str(presigned.get("key") or "")
        if urlparse(upload_url).scheme != "https":
            raise ZernioValidationError("Zernio upload URL is not HTTPS")
        parsed_public = urlparse(public_url)
        host = (parsed_public.hostname or "").lower()
        if parsed_public.scheme != "https" or not host.endswith("zernio.com"):
            raise ZernioValidationError("Zernio public media URL is unexpected")

        with path.open("rb") as handle:
            response = requests.put(
                upload_url,
                headers={"Content-Type": "video/mp4"},
                data=handle,
                timeout=max(self.timeout, 300),
            )
        if response.status_code >= 400:
            raise ZernioValidationError(
                f"Zernio presigned media upload failed with HTTP {response.status_code}"
            )
        return {
            "public_url": public_url,
            "storage_key": storage_key,
            "expires_in": int(presigned.get("expiresIn") or 0),
            "bytes": path.stat().st_size,
        }

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
