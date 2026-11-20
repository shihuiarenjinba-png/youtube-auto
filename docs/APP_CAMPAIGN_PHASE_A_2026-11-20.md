# Application advertising Campaign Phase A — 2026-11-20

## Safety boundary

This phase is evidence collection, grounded content generation, and local video
review only. It does not expose a YouTube upload mode, a Zernio media-transfer
mode, or an Instagram/TikTok post-creation mode. The workflow has no schedule.
Zodiac credentials and channel IDs remain `DENY_ALL_WRITES`.

## Advertising social identities

The six explicitly approved accounts in `config/social_lanes.json` are assigned
to the `advertising.social` namespace and each lane/account has
`purpose=advertising`. JP and US are disjoint and `fallback_policy=DENY`.

- JP Instagram: `6a9799d277555aae01bd18c1`, `6a97e50d77555aae01bf3321`
- JP TikTok: `6a97712377555aae01bbe410`, `6a97e53877555aae01bf3417`
- US Instagram: `6a97a82b77555aae01bd7b83`
- US TikTok: `6a979de977555aae01bd41ca`

Health/capacity remains read-only. Account approval does not by itself activate
posting.

## Application inventory result

| Product | Evidence found | Campaign decision |
|---|---|---|
| Daymark AI | official help/privacy/support site, local Store listing metadata, version metadata, five screenshots | JP DRAFT dataset created; RAG/video review PASS; posting HOLD |
| Data Shaper | GitHub repository with one-line README only | `HOLD_INSUFFICIENT_SOURCE_EVIDENCE` |
| DemandScope | no authoritative product source located | `HOLD_INSUFFICIENT_SOURCE_EVIDENCE` |
| NamiData | no authoritative product source located | `HOLD_INSUFFICIENT_SOURCE_EVIDENCE` |
| Folio AI / RAG | GitHub repository with one-line README only | `HOLD_INSUFFICIENT_SOURCE_EVIDENCE` |
| StatFlow | GitHub repository with one-line README only | `HOLD_INSUFFICIENT_SOURCE_EVIDENCE` |

No URL, price, release state, feature, or CTA was inferred for an insufficient
product.

## Daymark AI dataset

Dataset: `data/app_campaigns/daymark-ai-jp.json`

- campaign: `daymark-ai-jp-20261120`
- app ID: `OkinawaDesktopTools.DaymarkAI`
- market/language: `JP` / `ja`
- status: `DRAFT`
- official source URLs: help home, privacy, support
- CTA: official help home only
- Store URL: empty
- price: `null`
- screenshots: five repository files, each SHA-256 pinned
- local evidence: Store listing and product metadata, each SHA-256 pinned
- rotation ledger fields: present, all unposted (`null`)

Posting stays blocked by:

- `HOLD_STORE_NOT_PUBLISHED`
- `HOLD_PRICE_NOT_CONFIRMED`

## Grounded RAG evidence

The real local Phase A run fetched all three official HTTPS pages and returned
`APP_CAMPAIGN_RAG_DRY_RUN_PASS`. Raw page hashes are recorded for every fetch.
The hosting wrapper changes raw HTML between requests, so duplicate protection
must use the normalized evidence hash, not the volatile wrapper hash.

- stable normalized evidence SHA-256:
  `a95201a5afdeaf384291e8848c5d38cd374627b1dd8ad3251f860bcd3719423a`
- generated videos during RAG dry-run: 0
- media uploads: 0
- social posts: 0
- YouTube writes: 0
- zodiac writes: 0

Generated copy uses only Store-listing statements and the official URL. It does
not state a price, current availability, ranking, review count, discount, or any
other unsupported claim.

## Local vertical video review

The existing `core/card_video.py`, MoviePy/FFmpeg compositor, deterministic BGM
picker, screenshots, and local BGM were reused. The dedicated generator validates
the dataset/review identity and every screenshot hash before rendering. The
review file is not an upload input unless its grounding status is `PASS`.

- result: `LOCAL_APP_AD_VIDEO_PASS`
- format: H.264, 1080x1920, 30 fps
- audio: AAC, present
- duration: 12.0 seconds
- cards: 4
- BGM: `lofi_warm.wav`
- local review video SHA-256:
  `872ae2c39e7cd1bfb61d90aea14ecf0cec212831cc6a2a91e963394f872c5e94`
- media upload performed: false
- social post created/performed: false/false
- YouTube write performed: false
- zodiac write performed: false

The MP4 remains only in the gitignored local `output/app_campaigns` review area.
Temporary card PNGs are deleted in `finally`. No video or review JSON is uploaded
as a GitHub artifact.

## Controlled-post policy implemented but inactive

`core/social_posting_policy.py` provides fail-closed preflight checks for ACTIVE
Campaign status, approved CTA/source, grounding, advertising account purpose,
market/platform match, valid media, duplicate fingerprint, capacity, two posts
per market/platform/day, and a three-hour minimum interval. Account selection is
deterministic round-robin. These checks do not connect to `/v1/posts`; controlled
post creation remains unimplemented and HOLD.

## Next gate

Phase B Zernio temporary-media transfer is not authorized for this Campaign
while it is DRAFT. Before any transfer or post, confirm an official live sales
or product URL and the release/price facts, update the Campaign to reviewed
ACTIVE state, rerun Phase A, and obtain human approval of the rendered video.
