# youtube-auto

Guarded, evidence-based advertising pipeline for the product campaigns in this
repository. This is not an unrestricted or autonomous bulk-publishing system.

## Verified operating boundaries

- No cron or autonomous posting schedule is enabled.
- YouTube OAuth checks are read-only; this repository has not verified or enabled
  a YouTube upload path for these app campaigns.
- The durable social-post ledger reserves each controlled post before external
  media transfer and records the outcome.
- A controlled Daymark AI JP Instagram Reel was published and confirmed through
  the posting provider as `published`:
  https://www.instagram.com/reel/DgFxrMlkffI/
- The new ledger path has been exercised for that JP Instagram post. Historical
  Instagram and TikTok posts were reconciled read-only; that is not the same as
  testing a new TikTok post through the current ledger path.
- No Zodiac account writes are permitted.
- English/US posting and autonomous product rotation are not validated.

External posting is guarded by the operational branch, explicit workflow
conditions, account identity checks, the persistent ledger, and idempotency.
A successful test post must not be interpreted as permission for unrestricted
campaign publishing.

## Daymark AI — truthful product scope

The current campaign dataset lists Windows 10 or Windows 11 (x64) and
Microsoft Edge WebView2 Runtime as system requirements. Ads must describe it as
a Windows PC app and must not imply that the app itself runs on macOS, iPhone,
or Android.

Local Ollama text assistance is optional. The core diary, habit, calendar,
search, and backup functions are described as usable without AI.

The current fixed CTA is a Microsoft Store search URL, not a confirmed direct
product-detail URL:

https://apps.microsoft.com/search?query=Daymark%20AI

Always call it a Microsoft Store search link. Do not call it a direct install
link, and do not publish a price without rechecking the exact product listing.

See [Daymark AI advertising and video-production plan](docs/DAYMARK_AI_ADS_AND_VIDEO_PRODUCTION.md).

## Video production status

The currently verified renderer creates a portrait MP4 from four existing
application screenshots, crossfades the cards, and adds a local BGM asset. It
does **not** currently generate scene images through an image API or narration
through a speech/voice API.

The target API image-generation plus voice-generation route remains the
intended production direction. The current screenshot/BGM renderer is only a
temporary fallback and must not be presented as the target or described as an
AI-generated image-and-voice video. The plan documents the stages and safety
gates required before the API route is enabled.

## Social account namespaces

`config/account_namespaces.json` separates advertising accounts from the
quarantined Zodiac accounts. The legacy Zodiac configuration is historical
reference only and has a `DENY_ALL_WRITES` policy.

## Advertising GitHub Actions secrets

The active workflow recognizes only:

- `AD_YOUTUBE_CLIENT_ID_JP`
- `AD_YOUTUBE_CLIENT_SECRET_JP`
- `AD_YOUTUBE_REFRESH_TOKEN_JP`
- `AD_YOUTUBE_CLIENT_ID_US`
- `AD_YOUTUBE_CLIENT_SECRET_US`
- `AD_YOUTUBE_REFRESH_TOKEN_US`

Legacy `YOUTUBE_*` secrets are not treated as equivalent. Their presence does
not enable the advertising YouTube upload path.

Zernio social credentials are scoped by the configured advertising account
lanes. Secrets must never be printed or committed.
