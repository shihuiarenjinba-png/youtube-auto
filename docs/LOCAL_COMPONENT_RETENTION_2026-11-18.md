# Local component retention classification — 2026-11-18

This document is classification only. No local file, credential, source tree,
asset, output, log, backup, or scheduled task was deleted or moved.

## Classification meanings

- `KEEP_PRODUCTION_SOURCE`: still authoritative for operating evidence,
  recovery, parity checks, or credentials that must remain local.
- `KEEP_SELLABLE`: potentially reusable in a distributable product after
  secrets, account identifiers, and customer-specific data are removed.
- `KEEP_REUSABLE_AUTOMATION`: useful implementation or operational automation
  that should be preserved independently of the current deployment.
- `CLOUD_MIGRATED`: functionality has a GitHub Actions implementation, but the
  source copy remains preserved until cloud operation is fully accepted.
- `DELETE_CANDIDATE`: non-authoritative generated/cache material that may be
  reviewed later. This label is not deletion approval.

## Classified components

| Local component | Classification | Reason / boundary |
| --- | --- | --- |
| `C:\Users\aaron\Desktop\auto-shorts-studio` | `KEEP_PRODUCTION_SOURCE`, `KEEP_SELLABLE`, `KEEP_REUSABLE_AUTOMATION` | Proven live JA/EN generation and upload source. Preserve until scheduled cloud operation is accepted; package only after removing secrets and account-specific data. |
| `auto-shorts-studio\core`, `tools`, `assets`, `presets`, `ui` | `KEEP_SELLABLE`, `KEEP_REUSABLE_AUTOMATION` | Generators, templates, composition, BGM selection, and UI components have reuse/product value. |
| `C:\Users\aaron\Desktop\auto-blogger` | `KEEP_PRODUCTION_SOURCE`, `KEEP_REUSABLE_AUTOMATION` | Existing content, Blogger, social, dashboard, and Windows operational source remains an independent recovery/reference system. |
| `auto-blogger\src`, `scripts`, `assets`, `data`, `docs`, `tests` | `KEEP_PRODUCTION_SOURCE`, `KEEP_REUSABLE_AUTOMATION` | Current local automation, mapping, evidence, and validation source. |
| `auto-blogger\vendor\shorts_factory` source and non-secret assets | `KEEP_PRODUCTION_SOURCE`, `KEEP_SELLABLE`, `KEEP_REUSABLE_AUTOMATION` | Separate video/uploader implementation and account-link tooling may be reused; do not package local credentials or generated customer/account data. |
| Local `.env`, `credentials`, OAuth/token/client-secret files and backups | `KEEP_PRODUCTION_SOURCE` | Sensitive recovery/authentication material. Never copy into a product, repository, artifact, or log. No deletion until account migration and recovery policy are separately approved. |
| `auto-blogger\worktrees\youtube-auto` | `CLOUD_MIGRATED`, `KEEP_REUSABLE_AUTOMATION`, `KEEP_SELLABLE` | GitHub-hosted JA/EN generation, YouTube validation upload, Zernio media transfer, and scheduled-path validation implementation. Public/marketing/social-post production is not yet approved. |
| Windows launchers and Task Scheduler scripts | `KEEP_PRODUCTION_SOURCE`, `KEEP_REUSABLE_AUTOMATION` | Preserve as rollback and operational reference until cloud schedules and controlled social posting are fully proven. |
| Production logs, output media, data snapshots, and backups | `KEEP_PRODUCTION_SOURCE` | Evidence or recovery value is not yet audited. Retention/deletion requires a separate decision. |
| `.pytest_cache`, `.ruff_cache`, `__pycache__`, `.runtime_tmp`, and test-temporary directories | `DELETE_CANDIDATE` | Re-creatable cache/test material only. Nothing is deleted under this classification. |

## Current no-delete decision

All `KEEP_*` and `CLOUD_MIGRATED` components remain in place. Even
`DELETE_CANDIDATE` components remain untouched until a separate, explicit
retention and deletion approval identifies exact paths.
