# Code Owner Handoff — YouTube Auto Production Pipeline

> **Safety correction — 2026-11-20:** The zodiac implementation copied after
> this handoff is not the advertising source. Do not use zodiac channels,
> content, OAuth credentials, or upload paths for advertising. Current rules
> and verified advertising candidates are documented in
> `ADVERTISING_REMAP_AUDIT_2026-11-20.md`.

Date: 2026-11-17 JST  
Repository: `shihuiarenjinba-png/youtube-auto`  
Default branch: `main`

## Objective

Turn this repository into the production GitHub Actions replacement for the existing working YouTube advertising automation.

The target is not a new design from scratch. **Locate the current proven advertising/video-generation/upload implementation and port/copy it into this repository with minimal behavioral changes first.**

The GitHub-hosted runner should perform the work so the user's Windows PC can remain powered off and does not need to retain generated advertisement videos.

## Existing scaffold

The repository currently contains:

- `README.md`
- `.github/workflows/youtube-ad-pipeline.yml`
- `scripts/run_ad_pipeline.py`
- `config/channels.example.json`
- `.gitignore`

Current behavior is intentionally safe:

- manual `workflow_dispatch` only
- dry-run only
- no production upload implementation
- no schedules enabled
- no secrets committed
- JA and EN lanes represented separately

Do not remove these safety properties until the corresponding gates below pass.

## Critical source rule

Do **not** assume the older repositories named:

- `YouTube-Automation-`
- `YouTube-Automation-with-Gmail-`
- `YouTube-Automation-with-blogger-and-gmail`

contain the production source. At handoff time their GitHub roots contain only README files.

Find the actual currently working source used by the user's existing automatic advertising uploader, including local source if necessary. Copy the proven logic instead of rebuilding from memory.

## Required production architecture

The final system should be conceptually:

```
GitHub schedule / manual dispatch
        |
        v
GitHub-hosted Ubuntu runner
        |
        +--> load JA or EN lane configuration
        +--> obtain/generate ad assets
        +--> generate final video using the proven pipeline / ffmpeg
        +--> generate language-correct metadata
        +--> authenticate to YouTube with GitHub Secrets
        +--> upload
        +--> verify API response / video ID
        +--> delete temporary generated media
        +--> exit
```

Do not store final MP4s permanently in Git unless explicitly required.

## Japanese and English separation

JA and EN are separate production lanes.

Each lane must independently define at minimum:

- copy/text language
- narration or audio language if applicable
- title
- description
- links / CTA
- tags / category where used
- thumbnail logic where used
- YouTube channel/account mapping
- refresh token mapping
- schedule
- generated file naming
- failure/retry state

A failure in JA must not corrupt or block EN, and vice versa.

## Schedule requirement

After validation, enable GitHub Actions scheduled execution.

Requirements:

1. JA and EN must post at **different times**.
2. Use explicit, documented schedule values.
3. Avoid relying on the user's Windows Task Scheduler.
4. Manual dispatch must remain available for QA/recovery.
5. Add concurrency protection so two uploads for the same lane cannot race.
6. Do not enable final recurring public publishing until controlled validation uploads pass.

Prefer off-peak cron minutes rather than exact top-of-hour values when practical.

## Secret handling

Never commit credentials or tokens.

Expected secret naming baseline:

- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN_JA`
- `YOUTUBE_REFRESH_TOKEN_EN`

If the proven implementation uses a different secure OAuth design, adapt names as necessary but document them in README.

No secret value may appear in:

- repository files
- workflow YAML
- logs
- artifacts
- screenshots
- issue/PR text

## GitHub Actions constraints

Target `ubuntu-latest` unless a proven dependency requires another runner.

Keep the workflow within free standard GitHub-hosted runner capabilities.

Do not add paid runners or paid cloud services.

Install only the dependencies needed by the proven pipeline. Prefer system ffmpeg / Python packages over heavyweight containers when possible.

## Validation sequence

Complete in this order:

1. **Source parity**
   - identify the current working advertising uploader
   - document exact source/provenance
   - copy/port it into this repo

2. **Generation parity**
   - reproduce one existing JA advertisement
   - reproduce one existing EN advertisement
   - compare expected video/audio/text behavior

3. **GitHub Actions dry-run**
   - JA dry-run PASS
   - EN dry-run PASS
   - ffmpeg/media generation PASS
   - generated file is valid and non-zero
   - no secret leakage

4. **OAuth validation**
   - read credentials exclusively from GitHub Secrets
   - refresh/access token flow PASS
   - no token printed to logs

5. **Controlled upload validation**
   - first JA upload: private or unlisted
   - first EN upload: private or unlisted
   - capture returned video IDs
   - verify title/description/language/video/audio/thumbnail/links

6. **Production scheduling**
   - set separate JA and EN posting times
   - run at least one scheduled-path dry-run/test
   - only then enable normal advertisement publishing behavior

## Failure behavior

The workflow must fail closed.

If any of the following are missing or invalid, do not publish:

- required asset
- required metadata
- OAuth credential
- refresh-token exchange
- generated video validation
- target channel/lane identity
- upload API success response

Return a clear non-zero failure and useful log message without leaking secrets.

Do not silently switch JA to EN credentials or vice versa.

## Cost constraint

User requirement: **no paid infrastructure**.

Use standard free GitHub Actions/public-repository execution where permitted.

Do not introduce paid SaaS, paid runner, paid storage, or always-on cloud VM without explicit approval.

## Definition of done

This work is complete only when:

- production source is copied from the actual proven implementation
- JA generation succeeds on GitHub Actions
- EN generation succeeds on GitHub Actions
- JA controlled YouTube upload succeeds
- EN controlled YouTube upload succeeds
- language/channel separation is verified
- separate automatic schedules are configured
- a scheduled production-path run succeeds
- repository contains no secrets
- PC-local execution is no longer required for normal scheduled posting
- generated media is cleaned up after successful upload

## Reporting back

Report:

- source used for the port
- branch and exact HEAD SHA
- workflow names
- JA schedule
- EN schedule
- GitHub Secret names required
- dry-run run IDs/results
- controlled upload video IDs and privacy state
- production schedule test result
- remaining HOLD items, if any

Do not claim completion from workflow syntax alone. Completion requires successful generation and controlled upload evidence for both languages.
