# youtube-auto

GitHub Actions port of the proven local JA/EN YouTube card-video uploader.

## Safety state

The repository is still in the validation phase:

- validation cron definitions are present; GitHub runs them only from the default branch
- `workflow_dispatch` remains available, including the same scheduled-path gate
- `public` is not an available workflow mode
- dry-runs receive no OAuth secrets
- JA and EN secure jobs receive only their own refresh token
- OAuth must resolve to the exact configured channel ID before generation/upload
- `private` uploads are validation-only and intentionally ignore marketing CTA/link variables
- `unlisted` uploads require valid lane-specific CTA and public HTTPS product links
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
- `private`: controlled validation upload; marketing CTA/link variables are intentionally ignored and a validation-only notice is used
- `unlisted`: controlled marketing-path upload; valid CTA and public HTTPS product URL are required
- `scheduled-validation`: manually exercises the same timezone gate and private one-item jobs used by cron

Scheduled jobs remain private validation only. Public upload stays unavailable,
and the unlisted marketing path remains on hold until official CTA/URLs exist.

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

These remain unset until the official CTA and URLs are confirmed. Dry-run,
OAuth-check, private validation, and scheduled private validation do not use
them. The unlisted marketing path fails closed without valid values.

## Instagram and TikTok validation

The proven Zernio account mapping is also represented as strict JA/JP and EN/US
lanes. `social-check` is read-only: it checks account identity, `can_post`, token
health, reconnect state, and TikTok `canPostMore`. `social-dry-run` adds the full
Chrome/MoviePy/FFmpeg video-generation validation in the same workflow run.
Neither mode creates a social post. A separate `social-media-upload` validation mode generates one proven MP4, re-checks the strict lane/account health, and uploads the file only to Zernio temporary media storage. It never calls the post-creation endpoint and therefore does not publish to Instagram or TikTok. The returned media URL is not printed; only hashes/host metadata are logged.

Required repository secrets for this check:

- `ZERNIO_API_KEY_JP_1`
- `ZERNIO_API_KEY_JP_2`
- `ZERNIO_API_KEY_US_1`

These are three different keys. No key or account falls back across markets.
Social publishing remains disabled until official CTA/URLs and controlled tests
are complete.

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

## Private validation schedules

- JA: 05:00 Asia/Tokyo (`0 20 * * *` UTC on the previous UTC date)
- EN: 05:00 America/New_York (`0 9 * * *` and `0 10 * * *` UTC candidates)

New York alternates between UTC-4 and UTC-5. The scheduled workflow accepts both
UTC candidates and uses `scripts/schedule_gate.py` so only the candidate matching
05:00 New York time proceeds. The JA candidate similarly selects only the JA
lane. Every selected scheduled validation runs fail-closed tests, uses lane-fixed
OAuth/channel checks, and requests exactly one private upload. GitHub cron may
start later under load. GitHub executes scheduled workflows from the default
branch only; a feature branch can validate the identical path by dispatching
`scheduled-validation` with the corresponding cron expression.

## Durability note

Refresh tokens can still be revoked, a Google OAuth consent app left in testing
can issue short-lived refresh tokens, and GitHub may disable schedules after
extended repository inactivity. The pipeline detects these conditions and stops
without publishing; no software can truthfully guarantee an account will run
literally forever without monitoring.
