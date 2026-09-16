# AGENTS.md — sylo-allen-bradley

## What this repo is

An **MCP server package** (v0.2.0+). The pi TypeScript extension was removed —
the tools are **not** library functions you can import or shell out to ad hoc.
They are exposed over the **Model Context Protocol** and require an **MCP
client** (Claude Code, Codex, pi via pi-mcp-adapter, any MCP-compatible
harness) to call them.

## Registering the server

- **Claude Code**: git clone this repo — it reads the root `.mcp.json`
  (server name `allen-bradley`). Approve the project server when prompted on
  first use. The MCP server itself is stdlib-only.
- **Codex**: `codex mcp add allen-bradley -- python server/server.py`
- **pi**: `pi install npm:sylo-allen-bradley` — pi-mcp-adapter auto-registers
  the bundled `.mcp.json` (declared as `pi.mcp` in package.json). Set
  `toolPrefix: "none"` in adapter settings so tool names stay exactly
  `allen_bradley_sdk_*`.

Python: the MCP server runs on any 3.10+; the wrapped SDK scripts run on the
**SDK Python 3.12** (`SYLO_SDK_PYTHON` env or `py -3.12` on Windows) and need
the licensed Studio 5000 v36+ Logix Designer SDK wheel (resolution order in
`scripts/_sdk_paths.py`). Without it, tools load but report the SDK missing.

## The tools (server name: `allen-bradley`)

| Tool | Purpose | Gated |
|---|---|---|
| `allen_bradley_sdk_upload_from_plc` | pull controller project into offline `.acd` (read-only toward PLC) | — |
| `allen_bradley_sdk_download_to_plc` | push working `.acd` to controller (Rockwell "download") | **download allowlist** |
| `allen_bradley_sdk_export_l5x` | `.acd` → `.L5X` export (save_as, detailed_l5x) | — |
| `allen_bradley_sdk_import_l5x` | partial import of L5X fragment into `.acd` (XPath-scoped) | — |

Source of truth for schemas/args: `server/server.py` (thin MCP wrapper) and
`scripts/*.py` (real logic; JSON-out contract). Parse exported L5X with
sylo-logicforge (`logicforge_parse_l5x`), not here.

## Rules for AI working on this repo

- **Never edit the download allowlist** (canonical copy lives in
  sylo-logicforge) — operator-managed, enforced in Python before the SDK even
  loads. `allen_bradley_sdk_download_to_plc` is the only tool that writes to
  a live controller project.
- The SDK's `StdOutEventLogger` can print INFO lines before the scripts'
  JSON — the wrapper parses trailing JSON. Keep that behavior.
- Tool names are referenced verbatim in skills/docs — keep them identical if
  you change the tool surface, and update wrapper + script together.
- Windows: the wrapper spawns script subprocesses with `stdin=DEVNULL` —
  inheriting the MCP stdio pipe makes the child's `Py_Initialize` lseek block
  forever. Keep that flag if you touch `server/server.py`.
- Verify changes with an MCP stdio client (list tools + validation/refusal
  paths). Full live verification requires a licensed Studio 5000 machine.