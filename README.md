# youtube-auto

GitHub Actions port of the proven local JA/EN YouTube card-video uploader.

## Safety state

The repository is still in the validation phase:

- manual `workflow_dispatch` only; schedules are not enabled
- `public` is not an available workflow mode
- dry-runs receive no OAuth secrets
- JA and EN secure jobs receive only their own refresh token
- OAuth must resolve to the exact configured channel ID before generation/upload
- controlled uploads require both a lane-specific CTA and link
- generated PNG/MP4 files are deleted before the runner exits and are not uploaded as artifacts

## Proven source

The copied implementation comes from the live local checkout at
`C:\Users\aaron\Desktop\auto-shorts-studio`, whose Git HEAD was
`c26df2ddca3e65dea411f4efbfd935303ed98292` during the port. The live log
`logs/auto_upload_2026-11-17.log` records four successful JA uploads followed by
four successful EN uploads on 2026-11-17, with zero generation/upload errors.

The port reuses its fortune/card planning, JA/EN copy, HTML templates, Chromium
rendering model, MoviePy/FFmpeg composition, BGM assets, and YouTube resumable
upload behavior. See `docs/PORT_PROVENANCE_2026-11-17.md` for the exact boundary.

## Workflow

Workflow: `YouTube Ad Pipeline - Validation`

Manual modes:

- `dry-run`: generate, encode, run `ffprobe`, and delete media; no secrets supplied
- `oauth-check`: refresh OAuth and verify the exact lane channel; no generation/upload
- `private`: controlled private upload
- `unlisted`: controlled unlisted upload

Public upload and schedules stay unavailable until both controlled uploads and a
scheduled-path test pass.

## Required GitHub Actions secrets

- `YOUTUBE_CLIENT_ID_JA`
- `YOUTUBE_CLIENT_SECRET_JA`
- `YOUTUBE_CLIENT_ID_EN`
- `YOUTUBE_CLIENT_SECRET_EN`
- `YOUTUBE_REFRESH_TOKEN_JA`
- `YOUTUBE_REFRESH_TOKEN_EN`

The proven JA and EN credentials use different OAuth clients. Do not reuse one
lane's client ID/secret for the other lane. The current production refresh
tokens were issued with these scopes:

- `https://www.googleapis.com/auth/youtube.upload`
- `https://www.googleapis.com/auth/youtube`

No JA-to-EN or EN-to-JA token fallback exists.

## Required GitHub Actions variables for uploads

- `AD_CTA_JA`
- `AD_LINK_JA`
- `AD_CTA_EN`
- `AD_LINK_EN`

These remain unset until the official CTA and URLs are confirmed. Dry-runs do
not require them; upload modes fail closed without them.

## Fixed lane identities

- JA: proven local route `main`, channel `UCCuMoJvZvdeUTdLaZR5tzPw`
- EN: proven local route `english`, channel `UCeyLvckqiM7eYMgKOAh_OkA`

Channel IDs are public identifiers and are committed only as identity gates.

## Local dry-run

Install Python dependencies, FFmpeg/ffprobe, and Chrome/Chromium, then run:

```bash
python scripts/run_ad_pipeline.py --language ja --mode dry-run --max-videos 1
python scripts/run_ad_pipeline.py --language en --mode dry-run --max-videos 1
```

`CHROME_PATH` may be set to an explicit Chrome/Chromium executable.

## Proposed schedules (not enabled)

- JA: 05:00 Asia/Tokyo (`0 20 * * *` UTC on the previous UTC date)
- EN: 05:00 America/New_York (`0 9 * * *` and `0 10 * * *` UTC candidates)

New York alternates between UTC-4 and UTC-5. The final scheduled workflow will
accept both UTC candidates and use a timezone-aware runtime gate so only the run
whose New York local hour is 05:00 proceeds. GitHub cron may start later under
load. These values are deliberately absent from the workflow until controlled
uploads pass.

## Durability note

Refresh tokens can still be revoked, a Google OAuth consent app left in testing
can issue short-lived refresh tokens, and GitHub may disable schedules after
extended repository inactivity. The pipeline detects these conditions and stops
without publishing; no software can truthfully guarantee an account will run
literally forever without monitoring.
