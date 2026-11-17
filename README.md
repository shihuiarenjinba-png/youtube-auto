# youtube-auto

GitHub Actions based YouTube advertisement automation scaffold.

## Current safety state

This repository is intentionally initialized in **manual + dry-run only** mode.

- No scheduled publishing is enabled yet.
- No YouTube credentials are stored in the repository.
- No upload is performed by the scaffold.
- The production implementation must be copied from the existing working YouTube advertising pipeline and verified before schedules are enabled.

## Target architecture

1. GitHub Actions starts a short-lived Ubuntu runner.
2. Existing production video-generation logic is ported into this repository.
3. Japanese and English advertisements are generated independently.
4. Japanese and English schedules use different posting times.
5. YouTube OAuth credentials are read only from GitHub Actions Secrets.
6. Generated media is uploaded directly to YouTube and removed from the runner after success.
7. No long-term video artifact storage is required unless debugging is explicitly enabled.

## Required production gates

Before enabling schedules:

- Reproduce the current working advertisement output.
- Separate JA and EN metadata, narration/text, assets and schedules.
- Verify ffmpeg/media generation on ubuntu-latest.
- Verify a full dry-run for both languages.
- Verify YouTube OAuth refresh and upload with GitHub Secrets.
- Perform one controlled private/unlisted upload per language.
- Confirm title, description, links, thumbnail, audio, video and language.
- Only then enable automatic public advertising uploads.

## Secret names

Production code should reference secret names only. Do not commit values.

- YOUTUBE_CLIENT_ID
- YOUTUBE_CLIENT_SECRET
- YOUTUBE_REFRESH_TOKEN_JA
- YOUTUBE_REFRESH_TOKEN_EN

If both languages intentionally use one channel/account, document that decision and use the minimum required secret set.

## Entry point

Current scaffold:

```bash
python scripts/run_ad_pipeline.py --language ja --dry-run
python scripts/run_ad_pipeline.py --language en --dry-run
```

The code-owner should replace the scaffold internals with the proven existing production pipeline while preserving the safety gates above.
