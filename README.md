# youtube-auto

Safe GitHub Actions validation scaffold for URL-grounded advertising. The
repository is intentionally **not armed for posting**.

## Current safety state

- Manual `workflow_dispatch` only; no cron/schedule trigger.
- No private, unlisted, public, or social-media upload mode.
- YouTube identity checks are read-only (`channels.list(mine=true)`).
- Zernio checks are read-only health/capacity requests; no `/v1/posts` or media
  transfer is reachable from the workflow.
- No credential is written to disk, committed, logged, or uploaded as an
  artifact.

## Account namespaces

`config/account_namespaces.json` separates the systems:

- `zodiac.ja` / `zodiac.en`: audit-only, `DENY_ALL_WRITES`.
- `advertising.jp`: local account 3, expected advertising channel
  `UC4n0nR7IBwN1KKr9T32RP_w`.
- `advertising.us`: local account 2, channel unknown,
  `HOLD_US_AD_ACCOUNT_NOT_CONFIRMED`.

The legacy zodiac configuration remains only as a quarantined historical
reference in `config/lanes.json`. It is not an advertising lane and has no active
execution entry point.

## Workflow modes

Workflow: `Advertising Pipeline - Safe Validation`

- `advertising-oauth-check`: verifies one exact advertising channel with
  advertising-only secrets; no upload.
- `rag-dry-run`: fetches one public HTTPS source, extracts evidence, and produces
  grounded review JSON; no YouTube or social credential is supplied.
- `social-check`: reads Zernio identity/health/TikTok capacity only.

The former zodiac pipeline entry point exits non-zero with
`HOLD_LEGACY_ZODIAC_PIPELINE_ISOLATED`.

## Advertising GitHub Actions secrets

The active workflow recognizes only:

- `AD_YOUTUBE_CLIENT_ID_JP`
- `AD_YOUTUBE_CLIENT_SECRET_JP`
- `AD_YOUTUBE_REFRESH_TOKEN_JP`
- `AD_YOUTUBE_CLIENT_ID_US`
- `AD_YOUTUBE_CLIENT_SECRET_US`
- `AD_YOUTUBE_REFRESH_TOKEN_US`

Legacy `YOUTUBE_*_JA/EN` secrets are not referenced. There is no JP/US or
zodiac/advertising fallback.

Zernio read-only checks use:

- `ZERNIO_API_KEY_JP_1`
- `ZERNIO_API_KEY_JP_2`
- `ZERNIO_API_KEY_US_1`

## URL-grounded RAG

The implementation in `core/advertising_rag.py` is adapted from the existing
`auto-blogger` fetch/extract/grounding path. It validates every redirect and
accepts public HTTPS only. Output retains:

- `campaign_id`
- `source_url`
- `canonical_url`
- `generated_from_source_hash`
- visible source facts and evidence snippets
- grounded hook, summary, value proposition, key points, CTA, script, caption,
  and hashtags

Unavailable claims remain absent. Insufficient evidence fails with
`HOLD_INSUFFICIENT_SOURCE_EVIDENCE`.

Local example (no posting):

```powershell
python scripts/run_advertising_rag.py `
  --market jp `
  --campaign-id example-001 `
  --source-url https://example.com/product
```

## Corrected provenance

The earlier `auto-shorts-studio` port is a zodiac implementation, not the
advertising source. Its historical upload evidence is not an advertising PASS.
See `docs/ADVERTISING_REMAP_AUDIT_2026-11-20.md` and the correction banner in
`docs/PORT_PROVENANCE_2026-11-17.md`.
