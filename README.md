# sylo-allen-bradley

Sylo package: **Studio 5000 Logix Designer SDK wrapper** — controller
upload/download and `.acd`↔L5X export/import (`allen_bradley_sdk_*` tools).
**The SDK itself is not bundled and cannot be redistributed** — it ships with
the licensed Studio 5000 v36+ installation (Windows, Python 3.12 only) and
requires a valid Studio 5000 license.

Split out of the old monolith on 2026-09-09:

- **`sylo-plc-comms`** — CIP/OPC UA tag tools (`plc_comms_*`). No SDK required.
- **`sylo-logicforge`** — L5X parse/review/IO-scaffold, Parse Rules UI, bundled LogicForge backend, canonical download allowlist.
- This package — SDK tools only: `allen_bradley_sdk_upload_from_plc`, `allen_bradley_sdk_download_to_plc`, `allen_bradley_sdk_export_l5x`, `allen_bradley_sdk_import_l5x`.

## Logix Designer SDK wheel (not bundled)

The Rockwell-proprietary `logix_designer_sdk` Python wheel ships with your own
licensed Studio 5000 v36+ install. Resolution order (`scripts/_sdk_paths.py`):

1. `LOGIX_DESIGNER_SDK_WHEEL` environment variable — explicit wheel path
2. `LOGIX_DESIGNER_SDK_SITE` — unpacked SDK tree
3. A wheel dropped under `packages/sylo-logicforge/vendor/logicforge/` (local only, not committed)
4. Legacy sibling checkout (`~/Documents/GitHub/sylo-allen-bradley/`)
5. `LOGICFORGE_SOURCE` dev-checkout overlay
6. Rockwell install locations (`C:\Program Files (x86)\Rockwell Software\...`)

Without the SDK the package still loads — only the direct `.acd` operations
report that the SDK is missing. Use `sylo-plc-comms` for live tag reads/writes
(no SDK) and `sylo-logicforge` for L5X parse/IO-scaffold work.

## Downloads are allowlist-gated

`allen_bradley_sdk_download_to_plc` is the only tool that writes to a live
controller project. It is hard-gated by the operator-managed allowlist whose
canonical file lives in `sylo-logicforge`
(`packages/sylo-logicforge/assets/download-allowlist.json`) — the agent cannot
download to any IP not present and enabled there.