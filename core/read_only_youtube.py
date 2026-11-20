"""Read-only YouTube OAuth identity inspection for advertising accounts.

This module intentionally exposes no upload or mutation method. Credentials are
constructed in memory and are never serialized to disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


TOKEN_URI = "https://oauth2.googleapis.com/token"
READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"HOLD_MISSING_ADVERTISING_SECRET:{name}")
    return value


@dataclass(frozen=True)
class ReadOnlyChannelIdentity:
    channel_id: str
    title: str


class ReadOnlyYouTubeIdentityClient:
    def __init__(self, *, client_id_env: str, client_secret_env: str, refresh_token_env: str):
        self.client_id_env = client_id_env
        self.client_secret_env = client_secret_env
        self.refresh_token_env = refresh_token_env

    def check(self) -> ReadOnlyChannelIdentity:
        credentials = Credentials(
            token=None,
            refresh_token=required_env(self.refresh_token_env),
            token_uri=TOKEN_URI,
            client_id=required_env(self.client_id_env),
            client_secret=required_env(self.client_secret_env),
            scopes=[READONLY_SCOPE],
        )
        credentials.refresh(Request())
        service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
        response = service.channels().list(part="snippet", mine=True, maxResults=1).execute()
        items = response.get("items") or []
        if len(items) != 1:
            raise RuntimeError("HOLD_OAUTH_IDENTITY_NOT_EXACTLY_ONE_CHANNEL")
        item = items[0]
        return ReadOnlyChannelIdentity(
            channel_id=str(item.get("id") or ""),
            title=str((item.get("snippet") or {}).get("title") or ""),
        )
