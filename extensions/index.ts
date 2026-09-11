/**
 * sylo-allen-bradley — Studio 5000 Logix Designer SDK wrapper.
 *
 * Controller upload/download and .acd ↔ L5X export/import via the Rockwell
 * Logix Designer SDK. The SDK itself is NOT bundled — it ships with the
 * licensed Studio 5000 v36+ install (wheel via LOGIX_DESIGNER_SDK_WHEEL /
 * LOGIX_DESIGNER_SDK_SITE / vendor drop-spot). Split out of the old
 * sylo-allen-bradley monolith on 2026-09-09: PLC comms moved to
 * sylo-plc-comms, L5X parse/IO-scaffold to sylo-logicforge.
 */
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

import type { ExtensionAPI } from '@earendil-works/pi-coding-agent'
import { Type } from 'typebox'

const execFileAsync = promisify(execFile)

const PACKAGE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SCRIPTS_DIR = path.join(PACKAGE_ROOT, 'scripts')

type ToolContentBlock = { type: 'text'; text: string }

// All registered tools are SDK-backed — run them on the SDK Python (3.12) so
// logix_designer_sdk imports (SYLO_SDK_PYTHON / py -3.12 on Windows).
const SDK_SCRIPTS = new Set([
  'sdk_export_l5x.py',
  'sdk_import_l5x.py',
  'sdk_upload_from_plc.py',
  'sdk_download_to_plc.py',
])

function resolvePythonInvocation(sdk = false): { command: string; prefixArgs: string[] } {
  if (sdk) {
    const sdkPython = process.env.SYLO_SDK_PYTHON?.trim()
    if (sdkPython) {
      return { command: sdkPython, prefixArgs: [] }
    }
    if (process.platform === 'win32') {
      return { command: 'py', prefixArgs: ['-3.12'] }
    }
  }

  const envPython = process.env.SYLO_PYTHON?.trim()
  if (envPython) {
    return { command: envPython, prefixArgs: [] }
  }
  return { command: process.platform === 'win32' ? 'python' : 'python3', prefixArgs: [] }
}

function toolError(text: string): { content: ToolContentBlock[] } {
  return { content: [{ type: 'text', text }] }
}

/**
 * Scripts emit JSON as the last thing on stdout, but the Logix Designer SDK's
 * StdOutEventLogger can print INFO lines before it. Parse the trailing JSON
 * object instead of assuming the whole stream is JSON.
 */
function parseTrailingJson(stdout: string): Record<string, unknown> | null {
  const trimmed = stdout.trim()
  if (!trimmed) return null
  try {
    return JSON.parse(trimmed) as Record<string, unknown>
  } catch {
    /* fall through — find last JSON object in mixed output */
  }
  let idx = trimmed.lastIndexOf('\n{')
  while (idx >= 0) {
    const candidate = trimmed.slice(idx + 1)
    try {
      return JSON.parse(candidate) as Record<string, unknown>
    } catch {
      idx = trimmed.lastIndexOf('\n{', idx - 1)
    }
  }
  return null
}

function tail(text: string, lines = 12): string {
  return text.trim().split('\n').slice(-lines).join('\n').trim()
}

type ExecOutput = { stdout: string; stderr: string }

async function execScript(
  scriptName: string,
  args: string[],
  timeoutMs: number,
): Promise<ExecOutput> {
  const scriptPath = path.join(SCRIPTS_DIR, scriptName)
  const { command, prefixArgs } = resolvePythonInvocation(SDK_SCRIPTS.has(scriptName))
  const sdk = SDK_SCRIPTS.has(scriptName)
  return execFileAsync(command, [...prefixArgs, scriptPath, ...args], {
    cwd: PACKAGE_ROOT,
    maxBuffer: 32 * 1024 * 1024,
    windowsHide: true,
    timeout: timeoutMs,
    env: {
      ...process.env,
      ...(sdk && process.platform === 'win32' && !process.env.SYLO_PYTHON
        ? { PYTHONIOENCODING: 'utf-8' }
        : {}),
    },
  })
}

async function runPythonScript(
  scriptName: string,
  args: string[],
  timeoutMs = 120_000,
): Promise<{ content: ToolContentBlock[] }> {
  try {
    const { stdout, stderr } = await execScript(scriptName, args, timeoutMs)
    const parsed = parseTrailingJson(stdout) as
      | { ok?: boolean; error?: string; operator_chat?: string }
      | null
    if (!parsed) {
      return toolError(tail(stdout) || stderr.trim() || `${scriptName} produced no output`)
    }
    if (parsed.ok === false) {
      return toolError(parsed.error ?? `${scriptName} failed`)
    }
    if (typeof parsed.operator_chat === 'string' && parsed.operator_chat.trim()) {
      return { content: [{ type: 'text', text: parsed.operator_chat.trim() }] }
    }
    return { content: [{ type: 'text', text: JSON.stringify(parsed, null, 2) }] }
  } catch (err) {
    // Non-zero exit: scripts print {"ok": false, "error": ...} before exiting 1 —
    // surface that instead of Node's generic "Command failed" message.
    const e = err as NodeJS.ErrnoException & { stdout?: string; stderr?: string }
    const parsed = typeof e.stdout === 'string' ? parseTrailingJson(e.stdout) : null
    if (parsed && typeof parsed.error === 'string' && parsed.error.trim()) {
      return toolError(parsed.error.trim())
    }
    const detail = [
      typeof e.stdout === 'string' ? tail(e.stdout) : '',
      typeof e.stderr === 'string' ? tail(e.stderr) : '',
    ]
      .filter(Boolean)
      .join('\n')
    const message = err instanceof Error ? err.message : String(err)
    return toolError(detail ? `${message}\n${detail}` : message)
  }
}

export default function syloAllenBradleySdkExtension(pi: ExtensionAPI): void {
  pi.registerTool({
    name: 'allen_bradley_sdk_upload_from_plc',
    label: 'Allen-Bradley SDK upload from PLC',
    description:
      'Windows + Logix Designer SDK: pull the controller project into a new offline `.acd` (Rockwell "upload"). ' +
      'Pass controller `ip` or full `comm_path`. Saves to `output_path` and/or creates a run folder. ' +
      'Read-only toward the PLC — there is no upload-to-PLC risk; downloads are separate. ' +
      'Follow with allen_bradley_sdk_export_l5x to read logic.',
    parameters: Type.Object({
      ip: Type.Optional(
        Type.String({ description: 'Controller IPv4 address (e.g. 192.168.1.10)' }),
      ),
      comm_path: Type.Optional(
        Type.String({
          description:
            'Full Rockwell communications path (overrides ip), e.g. AB_ETHIP-1\\10.0.0.1\\Backplane\\0',
        }),
      ),
      output_path: Type.Optional(Type.String({ description: 'Output .acd file path' })),
      run_dir: Type.Optional(Type.String({ description: 'Existing run folder from logicforge_run_prepare' })),
      project_dir: Type.Optional(
        Type.String({ description: 'Create runs/<run-id>/ and save working/<PLC_*.acd>' }),
      ),
      run_id: Type.Optional(Type.String({ description: 'Run id when using project_dir' })),
    }),
    async execute(_toolCallId, params) {
      const ip = String(params.ip ?? '').trim()
      const commPath = String(params.comm_path ?? '').trim()
      if (!ip && !commPath) {
        return toolError('allen_bradley_sdk_upload_from_plc requires ip and/or comm_path.')
      }
      const args: string[] = []
      if (ip) args.push('--ip', ip)
      if (commPath) args.push('--comm-path', commPath)
      const output = String(params.output_path ?? '').trim()
      const runDir = String(params.run_dir ?? '').trim()
      const projectDir = String(params.project_dir ?? '').trim()
      const runId = String(params.run_id ?? '').trim()
      if (output) args.push('--output', output)
      if (runDir) args.push('--run-dir', runDir)
      if (projectDir) args.push('--project-dir', projectDir)
      if (runId) args.push('--run-id', runId)
      if (!output && !runDir && !projectDir) {
        return toolError(
          'allen_bradley_sdk_upload_from_plc requires output_path, run_dir, and/or project_dir for the saved .acd.',
        )
      }
      return runPythonScript('sdk_upload_from_plc.py', args, 600_000)
    },
  })

  pi.registerTool({
    name: 'allen_bradley_sdk_download_to_plc',
    label: 'Allen-Bradley SDK download to PLC',
    description:
      'Windows + Logix Designer SDK: push the working .acd project to a controller (Rockwell "download"). ' +
      'GATED by the operator-managed download allowlist — the agent cannot download to any IP not present ' +
      'and enabled there, even with operator permission, and cannot edit the allowlist. ' +
      'Auto-switches the controller to Program mode first if the key is in REM; refuses if the key is in hard RUN. ' +
      'Leaves the controller in the configured post_download_mode (Program or Run) when the key is in REM.',
    parameters: Type.Object({
      ip: Type.Optional(
        Type.String({ description: 'Controller IPv4 address — must be in the download allowlist' }),
      ),
      comm_path: Type.Optional(
        Type.String({
          description:
            'Full Rockwell communications path (overrides ip), e.g. AB_ETHIP-1\\10.0.0.1\\Backplane\\0',
        }),
      ),
      acd_path: Type.Optional(Type.String({ description: 'Working .acd to push (or use run_dir)' })),
      run_dir: Type.Optional(
        Type.String({ description: 'Run folder from logicforge_run_prepare (uses working/*.dev.acd)' }),
      ),
    }),
    async execute(_toolCallId, params) {
      const ip = String(params.ip ?? '').trim()
      const commPath = String(params.comm_path ?? '').trim()
      if (!ip && !commPath) {
        return toolError('allen_bradley_sdk_download_to_plc requires ip and/or comm_path.')
      }
      const args: string[] = []
      if (ip) args.push('--ip', ip)
      if (commPath) args.push('--comm-path', commPath)
      const acd = String(params.acd_path ?? '').trim()
      const runDir = String(params.run_dir ?? '').trim()
      if (acd) args.push('--acd', acd)
      if (runDir) args.push('--run-dir', runDir)
      if (!acd && !runDir) {
        return toolError('allen_bradley_sdk_download_to_plc requires acd_path and/or run_dir.')
      }
      return runPythonScript('sdk_download_to_plc.py', args, 600_000)
    },
  })

  pi.registerTool({
    name: 'allen_bradley_sdk_export_l5x',
    label: 'Allen-Bradley SDK export ACD to L5X',
    description:
      'Windows + Logix Designer SDK: export `.acd` → `.L5X` (save_as, detailed_l5x) so the agent can read and edit project logic as XML. Pass run_dir or acd + output paths. Set LOGIX_DESIGNER_SDK_WHEEL if import fails. Parse the export with logicforge_parse_l5x (sylo-logicforge).',
    parameters: Type.Object({
      acd_path: Type.Optional(Type.String({ description: 'Path to .acd (or use run_dir working copy)' })),
      output_path: Type.Optional(Type.String({ description: 'Output .l5x; default run_dir/exports/iter-0/controller.l5x' })),
      run_dir: Type.Optional(Type.String({ description: 'Run folder from logicforge_run_prepare' })),
      detailed_l5x: Type.Optional(Type.Boolean({ description: 'Default true' })),
    }),
    async execute(_toolCallId, params) {
      const args: string[] = []
      const acd = String(params.acd_path ?? '').trim()
      const output = String(params.output_path ?? '').trim()
      const runDir = String(params.run_dir ?? '').trim()
      if (acd) args.push('--acd', acd)
      if (output) args.push('--output', output)
      if (runDir) args.push('--run-dir', runDir)
      if (params.detailed_l5x === false) args.push('--no-detailed-l5x')
      if (!acd && !runDir) {
        return toolError('allen_bradley_sdk_export_l5x requires acd_path and/or run_dir.')
      }
      return runPythonScript('sdk_export_l5x.py', args, 300_000)
    },
  })

  pi.registerTool({
    name: 'allen_bradley_sdk_import_l5x',
    label: 'Allen-Bradley SDK partial import L5X',
    description:
      'Windows + Logix Designer SDK: partial_import_from_xml_file — merge an L5X fragment (tags, routines, modules, etc.) into `.acd`. Default XPath Controller/Tags; use scoped XPath for programs/routines.',
    parameters: Type.Object({
      l5x_path: Type.String({ description: 'L5X fragment path' }),
      run_dir: Type.Optional(Type.String({ description: 'Run folder (uses the working .acd copy)' })),
      acd_path: Type.Optional(Type.String({ description: 'Target .acd (overrides run_dir working copy)' })),
      xpath: Type.Optional(Type.String({ description: 'Default Controller/Tags' })),
    }),
    async execute(_toolCallId, params) {
      const l5x = String(params.l5x_path ?? '').trim()
      if (!l5x) return toolError('allen_bradley_sdk_import_l5x requires l5x_path.')
      const args = ['--l5x', l5x]
      const runDir = String(params.run_dir ?? '').trim()
      const acd = String(params.acd_path ?? '').trim()
      const xpath = String(params.xpath ?? '').trim()
      if (runDir) args.push('--run-dir', runDir)
      if (acd) args.push('--acd', acd)
      if (xpath) args.push('--xpath', xpath)
      if (!runDir && !acd) {
        return toolError('allen_bradley_sdk_import_l5x requires run_dir and/or acd_path.')
      }
      return runPythonScript('sdk_import_l5x.py', args, 300_000)
    },
  })
}