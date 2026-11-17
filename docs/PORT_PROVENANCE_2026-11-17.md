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
does not invent values. Controlled uploads remain blocked until the official JA
and EN values are configured.

## Validation gate status at initial port

- source identified: PASS
- JA local planner parity: PASS
- EN local planner parity: PASS
- Ubuntu Actions JA dry-run: PENDING
- Ubuntu Actions EN dry-run: PENDING
- JA OAuth check: PENDING secrets
- EN OAuth check: PENDING secrets
- controlled uploads: PENDING prior gates
- recurring schedules/public mode: intentionally disabled
