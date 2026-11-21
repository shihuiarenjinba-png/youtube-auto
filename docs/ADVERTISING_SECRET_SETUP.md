# Advertising YouTube secret setup

This repository never stores advertising OAuth secret values in tracked files.

## Supported flow

1. Read a confirmed local advertising OAuth token JSON, or prompt securely.
2. Send only these values to GitHub Actions Secrets:
   - AD_YOUTUBE_CLIENT_ID_JP
   - AD_YOUTUBE_CLIENT_SECRET_JP
   - AD_YOUTUBE_REFRESH_TOKEN_JP
   - US equivalents only after the US advertising identity is confirmed.
3. Dispatch the read-only advertising OAuth audit.
4. Require exact channel ID match before any upload path can be enabled.

## JP one-command setup

From PowerShell on the Windows machine that has the confirmed advertising account 3 token:

powershell -ExecutionPolicy Bypass -File .\scripts\configure_advertising_youtube_secrets.ps1 -Market jp

Default JP source:

C:\Users\aaron\Desktop\auto-blogger\vendor\shorts_factory\token_3.json

Expected advertising JP channel:

UC4n0nR7IBwN1KKr9T32RP_w

The script does not print or commit client ID, client secret, or refresh token. Secret values are sent to GitHub CLI through stdin.

## Manual secure input

If the local token file should not be read automatically:

powershell -ExecutionPolicy Bypass -File .\scripts\configure_advertising_youtube_secrets.ps1 -Market jp -PromptInsteadOfTokenFile

The three values are entered as SecureString prompts and are not echoed.

## US

US advertising remains HOLD until account 2 identity is confirmed. The script refuses an implicit US token path.

## Safety boundaries

- Zodiac channel IDs are prohibited in the advertising audit.
- Legacy YOUTUBE_* secrets are not used by the active advertising workflow.
- This setup script dispatches advertising-oauth-check only.
- advertising-oauth-check performs channels.list only and never uploads.
- No public/private/unlisted upload is enabled by running this setup.
- token*.json and client_secret*.json are ignored by git.
