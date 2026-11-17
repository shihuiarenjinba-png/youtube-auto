"""Fail-closed YouTube client for short-lived GitHub Actions runners.

Credentials are constructed only from environment variables. No authorized-user
JSON or refreshed access token is written to disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    # Proven JA/EN refresh tokens were issued with the full YouTube scope.
    # OAuth refresh cannot replace a token's original grant with readonly.
    "https://www.googleapis.com/auth/youtube",
)
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required GitHub Actions secret is missing: {name}")
    return value


@dataclass(frozen=True)
class ChannelIdentity:
    channel_id: str
    title: str


class ActionsYouTubeClient:
    """Refresh-token YouTube client with an exact channel identity gate."""

    def __init__(self, expected_channel_id: str):
        if not expected_channel_id.strip():
            raise RuntimeError("Expected YouTube channel ID is empty")
        self.expected_channel_id = expected_channel_id.strip()
        self._service = None

    def _credentials(self) -> Credentials:
        credentials = Credentials(
            token=None,
            refresh_token=_required_env("YOUTUBE_REFRESH_TOKEN"),
            token_uri=TOKEN_URI,
            client_id=_required_env("YOUTUBE_CLIENT_ID"),
            client_secret=_required_env("YOUTUBE_CLIENT_SECRET"),
            scopes=list(SCOPES),
        )
        credentials.refresh(Request())
        return credentials

    def service(self):
        if self._service is None:
            self._service = build(
                "youtube",
                "v3",
                credentials=self._credentials(),
                cache_discovery=False,
            )
        return self._service

    def check_identity(self) -> ChannelIdentity:
        response = self.service().channels().list(
            part="snippet,contentDetails",
            mine=True,
            maxResults=1,
        ).execute()
        items = response.get("items") or []
        if len(items) != 1:
            raise RuntimeError("OAuth identity did not return exactly one YouTube channel")
        actual = str(items[0].get("id", ""))
        if actual != self.expected_channel_id:
            raise RuntimeError(
                "OAuth channel mismatch: authenticated channel does not match the configured lane"
            )
        return ChannelIdentity(
            channel_id=actual,
            title=str((items[0].get("snippet") or {}).get("title", "")),
        )

    def _uploads_playlist_id(self) -> str:
        response = self.service().channels().list(
            part="contentDetails",
            mine=True,
            maxResults=1,
        ).execute()
        items = response.get("items") or []
        if len(items) != 1 or items[0].get("id") != self.expected_channel_id:
            raise RuntimeError("Cannot resolve uploads playlist for the configured lane")
        playlist = (
            (items[0].get("contentDetails") or {})
            .get("relatedPlaylists", {})
            .get("uploads", "")
        )
        if not playlist:
            raise RuntimeError("YouTube uploads playlist is missing")
        return playlist

    def existing_markers(self, wanted: Iterable[str], scan_limit: int = 50) -> set[str]:
        """Return requested idempotency markers already present on this channel."""
        wanted_set = {marker for marker in wanted if marker}
        if not wanted_set:
            return set()
        playlist_id = self._uploads_playlist_id()
        response = self.service().playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=min(max(scan_limit, 1), 50),
        ).execute()
        video_ids = [
            str((item.get("contentDetails") or {}).get("videoId", ""))
            for item in response.get("items") or []
        ]
        video_ids = [video_id for video_id in video_ids if video_id]
        if not video_ids:
            return set()
        videos = self.service().videos().list(
            part="snippet,status",
            id=",".join(video_ids),
            maxResults=len(video_ids),
        ).execute()
        found: set[str] = set()
        for item in videos.get("items") or []:
            description = str((item.get("snippet") or {}).get("description", ""))
            found.update(marker for marker in wanted_set if marker in description)
        return found

    def upload(
        self,
        *,
        video_path: Path,
        title: str,
        description: str,
        tags: Optional[List[str]],
        privacy: str,
    ) -> Dict[str, Any]:
        if privacy not in {"private", "unlisted", "public"}:
            raise ValueError(f"Unsupported privacy value: {privacy}")
        if not video_path.is_file() or video_path.stat().st_size <= 0:
            raise RuntimeError("Validated MP4 is missing before upload")
        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": (tags or [])[:30],
                "categoryId": "22",
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }
        request = self.service().videos().insert(
            part="snippet,status",
            body=body,
            media_body=MediaFileUpload(
                str(video_path),
                chunksize=8 * 1024 * 1024,
                resumable=True,
                mimetype="video/mp4",
            ),
        )
        response = None
        while response is None:
            _, response = request.next_chunk()
        video_id = str((response or {}).get("id", ""))
        if not video_id:
            raise RuntimeError("YouTube upload completed without a video ID")
        verified = self.service().videos().list(
            part="snippet,status",
            id=video_id,
            maxResults=1,
        ).execute()
        items = verified.get("items") or []
        if len(items) != 1:
            raise RuntimeError("Uploaded video could not be verified")
        actual_privacy = str((items[0].get("status") or {}).get("privacyStatus", ""))
        if actual_privacy != privacy:
            raise RuntimeError("Uploaded video privacy does not match the requested privacy")
        return {
            "video_id": video_id,
            "url": f"https://youtu.be/{video_id}",
            "privacy": actual_privacy,
        }
