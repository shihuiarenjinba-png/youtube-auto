# Daymark AI — truthful advertising and video-production plan

Updated: 2026-11-24

## Product facts to state in advertising

- The current campaign dataset identifies Daymark AI as a Windows PC app.
- The documented system requirements are Windows 10 or Windows 11 (x64) and Microsoft Edge WebView2 Runtime.
- The campaign's stable CTA is the Microsoft Store search URL:
  https://apps.microsoft.com/search?query=Daymark%20AI
- This is a **search results URL**, not a verified direct product-detail URL. Advertising must say “Search for Daymark AI in Microsoft Store”; do not label it a direct install or product-detail link.
- The product includes optional local Ollama-assisted text support. The campaign states that diary, habits, calendar, search, and backup functions work without AI.
- Do not advertise Daymark AI as a Mac, iPhone, or Android app. Ollama itself supports macOS, but that does not make this Windows app a macOS app.
- Do not state a price unless the exact product-detail listing is checked at publication time.

## What the verified Instagram Reel actually is

The controlled post published at:

https://www.instagram.com/reel/DgFxrMlkffI/

was created by the current local renderer. The renderer verifies four existing app screenshots, creates four portrait review cards, crossfades them into an MP4, and adds a local BGM asset. Its video probe requires H.264, 1080×1920, an audio stream, and a 10–15 second duration.

This is a real video post, but it is **not** an AI-generated image-and-voice video. The currently verified path does not call an image-generation API or a text-to-speech / voice-generation API. Do not describe this test Reel as having AI-generated scenes or narration.

## Intended production route — preserve, do not replace

The intended richer production route remains:

1. Ground the ad script in verified app features, screenshots, compatibility, and CTA.
2. Generate scene images through a configured image-generation API.
3. Generate narration / voice audio through a configured speech or voice API.
4. Compose the generated visuals, narration, optional BGM, subtitles, transitions, disclosure, and fixed CTA into a vertical video.
5. Run visual, audio, duration, codec, compatibility-claim, disclosure, and URL checks.
6. Reserve the publication in the durable social-post ledger before media transfer.
7. Upload and publish only through the existing account-scoped, idempotent, guarded posting path.

The current screenshot-plus-BGM renderer is a **temporary, explicitly identified fallback**, not a replacement for the API image-and-voice route.

## Conditions before enabling image / voice API generation

- Choose and configure the actual image and speech providers; provider names and credentials are not assumed here.
- Keep secrets in GitHub Actions secrets or a secure runtime secret store; never log them.
- Add request budgets, per-video cost limits, timeouts, bounded retries, and output-hash caching.
- Record provider/model, request parameters, source hash, output hashes, and generation timestamps as evidence.
- Fail closed if provider configuration, output validation, or budget checks fail. Do not silently fall back to a different generation route.
- Keep API-generated assets and the current screenshot fallback as separate modes so that an ad cannot be mislabeled as AI-generated.

## Honest caption template

広告｜自社製品の紹介

日記・体調・生活習慣をWindows PCに記録。過去の記録を検索でき、任意でローカルOllamaによる文章補助や日記への質問も利用できます。

対応環境（Windows PC）：Windows 10またはWindows 11（x64）、Microsoft Edge WebView2 Runtime

AI補助機能：任意のローカルOllamaによる文章補助と日記への質問

日記、習慣、カレンダー、検索、バックアップはAIなしで利用できます。

入手先：Microsoft Storeで「Daymark AI」を検索（Windows PC向け）
https://apps.microsoft.com/search?query=Daymark%20AI

※リンクはMicrosoft Store内の検索結果を開きます。現時点で直接の商品詳細ページURLとしては案内しません。
