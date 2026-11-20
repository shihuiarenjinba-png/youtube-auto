# Advertising remap audit — 2026-11-20

## Safety decision

- Zodiac JA `UCCuMoJvZvdeUTdLaZR5tzPw`: audit-only, all writes denied.
- Zodiac EN `UCeyLvckqiM7eYMgKOAh_OkA`: audit-only, all writes denied.
- Legacy `YOUTUBE_*_JA/EN` GitHub secrets are not trusted for advertising and
  are not referenced by the active workflow.
- The workflow has no `schedule` trigger and exposes no YouTube or Zernio write
  mode.

Historical read-only Actions evidence confirms the legacy secret identity:

- run `44038471189`: JA actual channel `UCCuMoJvZvdeUTdLaZR5tzPw`, upload false.
- run `44038475250`: EN actual channel `UCeyLvckqiM7eYMgKOAh_OkA`, upload false.

Both IDs are zodiac IDs, so the legacy GitHub secrets are classified as zodiac
credentials and are prohibited from every advertising path.

## Advertising identity evidence

The authoritative local source is `C:\Users\aaron\Desktop\auto-blogger`.

| Namespace | Local account | Token mapping | Read-only result | Decision |
|---|---:|---|---|---|
| `advertising.jp` | 3 | `vendor/shorts_factory/token_3.json` | Channel `UC4n0nR7IBwN1KKr9T32RP_w`, title `ラッスン17`; token hash unchanged | local identity PASS; GitHub AD secrets not yet registered |
| `advertising.us` | 2 | expected `vendor/shorts_factory/token_2.json` | live token missing; isolated/invalid candidates return `invalid_grant` | `HOLD_US_AD_ACCOUNT_NOT_CONFIRMED` |

No OAuth reauthorization was performed. No token or client-secret value was
printed, copied, committed, or stored as an artifact.

## GitHub secret namespaces

Advertising uses only these names:

- `AD_YOUTUBE_CLIENT_ID_JP`
- `AD_YOUTUBE_CLIENT_SECRET_JP`
- `AD_YOUTUBE_REFRESH_TOKEN_JP`
- `AD_YOUTUBE_CLIENT_ID_US`
- `AD_YOUTUBE_CLIENT_SECRET_US`
- `AD_YOUTUBE_REFRESH_TOKEN_US`

There is no cross-market or zodiac fallback. Missing or mismatched identity is a
non-zero HOLD before any generation or write operation.

## URL-grounded advertising dry-run

The implementation is adapted from the existing `auto-blogger` safe HTTP
fetcher, fact extractor, and grounding checks. It now retains:

- campaign ID, requested source URL, canonical URL, and SHA-256 source hash
- page title, meta description, visible body, product/service name
- features, benefits, prices, campaigns, restrictions, CTA links, and evidence
- grounded hook, summary, value proposition, key points, script, caption, and
  hashtags

Only public HTTPS URLs are accepted. Localhost, private/non-global addresses,
credentials in URLs, non-HTML responses, oversized bodies, and unsafe redirect
targets fail closed. Missing evidence returns
`HOLD_INSUFFICIENT_SOURCE_EVIDENCE`.

## Social account audit

Configured JP/US Zernio accounts are technically connected and healthy, and the
TikTok accounts reported available capacity during the read-only audit. Their
profiles do not prove an advertising-only purpose, so social post creation stays
HOLD. The active workflow uses health/capacity GET requests only.

## Current phase

- Phase 1 local advertising identity: JP PASS, US HOLD.
- GitHub fail-closed proof: run `44705623403`, exact HEAD
  `1cc00ad6555a8b1d20a3c79b74cb45ca30c7e1e4`. All safety tests passed; the
  JP advertising identity job then stopped on missing
  `AD_YOUTUBE_REFRESH_TOKEN_JP`. No legacy-secret fallback, generation, upload,
  social action, or opposite-market job occurred.
- Phase 2 RAG dry-run implementation: implemented. The only registered Campaign
  (`General Data Analyzer`, JP) was attempted twice against its stored official
  HTTPS URL and returned HTTP 503 both times. Result:
  `HOLD_SOURCE_HTTP_503`; no fallback, generation, or posting occurred.
- Phase 3 human review: HOLD.
- Phase 4+ YouTube uploads: HOLD, zero uploads in the corrected phase.
- Instagram/TikTok posting: HOLD, zero posts in the corrected phase.
- Schedule: disabled.
