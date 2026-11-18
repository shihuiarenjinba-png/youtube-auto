# Production source provenance — 2026-11-17

## Source selected

The proven source is the live Windows checkout:

`C:\Users\aaron\Desktop\auto-shorts-studio`

Observed Git metadata at port time:

- remote: `https://github.com/tsuhasqni-pixel/auto-shorts-studio.git`
- branch: `main`
- HEAD: `c26df2ddca3e65dea411f4efbfd935303ed98292`

Files were copied from the live working directory, not reconstructed from the
old README-only repositories. The working checkout is newer in operational use
than its HEAD date, so the live files and live log are the behavioral authority.

## Operational evidence

`logs/auto_upload_2026-11-17.log` records this production run beginning at
06:00 JST:

- JA route `main`, privacy `public`: planned 4, uploaded 4, errors 0
- EN route `english`, privacy `public`: planned 4, uploaded 4, errors 0
- generated artifacts were cleaned after each successful upload

The safe route configuration maps:

- JA -> `main` -> `UCCuMoJvZvdeUTdLaZR5tzPw`
- EN -> `english` -> `UCeyLvckqiM7eYMgKOAh_OkA`

No token, client secret, or authorized-user JSON was copied.

## Reused implementation

The port copies and reuses:

- `core/auto_uploader.py`: date-based JA/EN content planning and metadata
- `core/zodiac_balance.py`: deterministic daily ranking balance
- `core/rag_factory.py`: card candidate generation
- `core/fortune_writer.py`: deterministic offline copy fallback
- `core/video_composer.py`, `core/card_video.py`, `core/audio_looper.py`: MoviePy/FFmpeg composition
- `core/bgm_picker.py` and six proven language-neutral BGM tracks
- JA/EN zodiac knowledge and ranking/spotlight HTML templates
- `tools/rag_starter/gen_fortune.py` and `gen_fortune_en.py`: original card builders

## Required Ubuntu adaptations

The behavior-preserving changes are:

1. Replace the hard-coded Windows `.venv\\Scripts\\python.exe` child process
   with an in-process call to the same card `build()` function.
2. Resolve Chrome/Chromium from `CHROME_PATH`/PATH instead of a fixed Edge path.
3. Replace the PC-local shared posting database with YouTube-side idempotency
   markers scoped by lane, JST date, and slot.
4. Construct OAuth credentials only from Actions environment variables and
   never write refreshed credentials to disk.
5. Verify the authenticated channel ID exactly before any secure run.
6. Disable Ollama in Actions and use the existing deterministic template/RAG
   fallback because GitHub-hosted runners do not provide the local Ollama model.
7. Validate every MP4 with `ffprobe` and delete temporary media in `finally`.

## Important content finding

The proven live uploader generates zodiac/fortune Shorts with nonverbal BGM. It
does not contain confirmed product campaign URLs or product-specific CTA data.
The Actions port therefore adds independent `AD_CTA_*` and `AD_LINK_*` gates but
does not invent values. `private` is a technical validation path and deliberately
omits marketing CTA/link values. The `unlisted` marketing path remains fail-closed
until official JA and EN values pass validation.

## Validation gate status

- source identified: PASS
- JA local planner parity: PASS
- EN local planner parity: PASS
- Ubuntu Actions JA dry-run: PASS (`44036371299`, original port HEAD)
- Ubuntu Actions EN dry-run: PASS (`44036380585`, original port HEAD)
- JA generated media: H.264, 1080x1920, 12.0s, audio present, 745650 bytes
- EN generated media: H.264, 1080x1920, 12.0s, audio present, 679217 bytes
- temporary media cleanup: PASS for both lanes
- uploads during dry-run: zero for both lanes
- proven OAuth client mapping: JA and EN use different client IDs/secrets
- proven token scopes (both lanes): `youtube.upload` + `youtube`
- JA OAuth check: PASS (`44038471189`), channel ID matched, upload false
- EN OAuth check: PASS (`44038475250`), channel ID matched, upload false
- local Zernio health: JP Instagram 2/2 ready, JP TikTok 2/2 ready,
  US Instagram 1/1 ready, US TikTok 1/1 ready
- local TikTok capacity: all three accounts `canPostMore=true`, max 600 seconds
- GitHub Zernio JP read-only check: PASS (`44108889923`), post false
- GitHub Zernio US read-only check: PASS (`44108901821`), post false
- GitHub JP social dry-run: PASS (`44109224974`), generated H.264
  1080x1920/12s/audio, Zernio health PASS, upload/post false, media removed
- GitHub US social dry-run: PASS (`44109231887`), generated H.264
  1080x1920/12s/audio, Zernio health PASS, upload/post false, media removed
- JA controlled private upload run `44113331556` (run HEAD `24aded6`): technical
  YouTube ingestion and processing PASS (`pYSGKyBINaU`, channel
  `UCCuMoJvZvdeUTdLaZR5tzPw`, private, one upload, H.264 1080x1920, 12 seconds,
  audio present, processing `succeeded`, upload `processed`, temporary media
  removed). This run predated private-mode marketing isolation and therefore is
  not evidence that the marketing metadata is production-ready.
- Private-mode marketing isolation was added in `5c54d52` and covered by the
  fail-closed tests added in `71593f7` / `7dc470f`. Private mode now uses an
  explicit validation notice and does not consume `AD_CTA_*` / `AD_LINK_*`.
- First EN private attempt `44192392768` (run HEAD `7dc470f`) was cancelled before
  safety tests, OAuth, generation, or upload because the runner stalled installing
  system dependencies. No video was uploaded in that attempt.
- Dependency installation was bounded and split in `bf6a395a710a1636e25376554c552bb456a55a19`.
- EN controlled private retry `44193823519` (run HEAD
  `bf6a395a710a1636e25376554c552bb456a55a19`): PASS. One video was uploaded:
  `jFtQQl3mByM`, channel `UCeyLvckqiM7eYMgKOAh_OkA`, privacy `private`, H.264
  1080x1920, 12 seconds, audio present, processing `succeeded`, upload `processed`,
  and temporary media removed. The stored description contains the EN private
  validation notice and no placeholder CTA/product URL.
- EN run log review: GitHub masking was active for all three OAuth environment
  values; no recognizable access token, refresh token, client secret, API key, or
  private-key pattern was found. The JA channel ID and JA secret names were absent.
- JA and EN GitHub Actions private upload routes: TECHNICAL PASS. This establishes
  generation, lane-fixed OAuth/channel verification, one-item upload, YouTube
  processing verification, and runner cleanup; it does not approve marketing
  content or public posting.
- OAuth validation gate: PASS for both JA and EN (see run IDs above)
- marketing-path (`unlisted`) controlled upload: HOLD. The EN private run still
  displayed literal `Official English CTA` / `Official EN product URL` repository
  variable values in the Actions environment. Private mode correctly ignored them,
  but all four official `AD_CTA_*` / `AD_LINK_*` values must be re-confirmed before
  any unlisted marketing test.
- recurring schedules/public mode: intentionally disabled

## Zernio temporary media transfer validation — 2026-11-18

The `social-media-upload` mode proves only this boundary:

`GitHub Actions -> one generated MP4 -> Zernio /media/presign -> presigned PUT`

It has no post-creation implementation and does not call `/v1/posts`. YouTube
secure jobs, the other market's media-upload job, social read-only jobs, and the
general dry-run job are skipped for each lane-specific run.

- Evidence hardening commit:
  `86fe22de80cb24b8a11c53b6e463a6605d29a0d7`. It makes account health,
  TikTok capacity, presign, PUT, one-video generation, and post-cleanup existence
  checks explicit in the fail-closed result.
- JP run `44313218261`: PASS at exact run HEAD
  `86fe22de80cb24b8a11c53b6e463a6605d29a0d7`; all 15 safety tests passed;
  account health 4/4 and TikTok capacity 2/2 passed; exactly one 743957-byte MP4
  was generated (H.264, 1080x1920, 12.0 seconds, audio present). The same probe
  MP4 was transferred once through each of the two JP credential scopes, so the
  temporary-media upload count was 2. Both presign and presigned PUT operations
  passed, the public host was `media.zernio.com`, and temporary runner media was
  removed and verified absent.
- US run `44313569027`: PASS at exact run HEAD
  `86fe22de80cb24b8a11c53b6e463a6605d29a0d7`; all 15 safety tests passed;
  account health 2/2 and TikTok capacity 1/1 passed; exactly one 676349-byte MP4
  was generated (H.264, 1080x1920, 12.0 seconds, audio present). The MP4 was
  transferred once through the US credential scope. Presign and presigned PUT
  passed, the public host was `media.zernio.com`, and temporary runner media was
  removed and verified absent.
- Both runs reported `zernio_media_upload_performed=true`,
  `social_post_created=false`, and `social_post_performed=false`.
- Logs contained only the public host plus SHA-256 digests for the public URL and
  storage key. No raw Zernio public URL or storage key was logged.
- GitHub masking was active for all lane-specific API-key environment values.
  Log review found no recognizable secret/API-key/private-key value, no posts
  endpoint, and no YouTube credential. Workflow and configuration map JP and US
  secrets independently with no cross-market fallback.
- `GitHub Actions -> video generation -> Zernio temporary media storage`:
  TECHNICAL PASS for JP and US.
- Instagram/TikTok controlled post creation: HOLD. No post was created during
  these runs, and controlled-post design/validation remains a separate next step.

## YouTube scheduled-path validation — 2026-11-18

The validation workflow defines these UTC cron candidates while retaining
`workflow_dispatch`:

- JA 05:00 `Asia/Tokyo`: `0 20 * * *`
- EN 05:00 `America/New_York`: `0 9 * * *` (EDT) and `0 10 * * *` (EST)

`scripts/schedule_gate.py` evaluates all three candidates against the lane's IANA
timezone. Tests cover JA selection, EN rejection at the JA cron, and both New York
DST offsets. A selected scheduled job is hard-coded to `private`, one item, its
own OAuth secrets, and its fixed channel identity. It runs the complete fail-closed
test suite before upload and uses a validation-only idempotency marker namespace.

- First manual JA same-path run `44319916674` at run HEAD `d89f8ef`: gate PASS,
  JA selected and EN rejected, OAuth/channel PASS, cleanup PASS, and upload count
  zero because the ordinary private marker for that date already existed. This
  confirmed existing idempotency but did not satisfy the one-video evidence gate.
- Scheduled validation marker isolation was added in
  `bcb3b1c000b83a3fd9a5b9933e3225d622c53bac` without changing the ordinary
  private/production marker namespace.
- JA same-path retry `44320456709` at exact run HEAD
  `bcb3b1c000b83a3fd9a5b9933e3225d622c53bac`: PASS. Gate selected JA only; all
  17 safety tests passed; one H.264 1080x1920, 12-second video with audio was
  generated; video `yxBamSaM9yE` was uploaded to channel
  `UCCuMoJvZvdeUTdLaZR5tzPw` as private; processing `succeeded`, upload
  `processed`, and temporary media cleanup passed.
- EN winter same-path run `44321228836` at exact run HEAD
  `bcb3b1c000b83a3fd9a5b9933e3225d622c53bac`: PASS. Gate rejected JA and selected
  EN for `0 10 * * *`; all 17 safety tests passed; one H.264 1080x1920, 12-second
  video with audio was generated; video `zTO5jBXTqSc` was uploaded to channel
  `UCeyLvckqiM7eYMgKOAh_OkA` as private; processing `succeeded`, upload
  `processed`, and temporary media cleanup passed.
- Both logs had GitHub secret masking active, contained no recognizable secret
  value, and contained no opposite-lane OAuth secret name or channel ID.
- Manual execution of the identical timezone-gated scheduled jobs: TECHNICAL PASS
  for JA and EN.
- Actual `event=schedule` trigger: PENDING default-branch integration and the next
  matching 05:00 window. GitHub does not run scheduled workflows from a feature
  branch, so the manual run IDs above must not be represented as cron-triggered.
- Public posting, unlisted marketing posting, and social post creation remain HOLD.
