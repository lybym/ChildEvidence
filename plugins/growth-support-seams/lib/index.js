/**
 * ChildEvidence growth-support seam verification plugin for DSH (Issue #13).
 *
 * Cordis object plugin (name / inject / apply), matching the shipped bundle
 * module shape (e.g. @deepseek-ai/dsh-headless). Registers four synthetic
 * controlled-flow tools into ctx.tools and, when `receipt_dir` is configured,
 * writes load/unload receipts so plugin load and dispose are observable
 * without a model call.
 *
 * Dependencies: none. The host supplies `tools` (dsh-tools) and the loader.
 */

import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { createCore, DEFAULT_CONFIG } from './controlled-core.js'
import { buildAuditTool, buildPrepareTool, buildRecordTool, buildValidateTool } from './tool-definitions.js'

export const name = 'ce-growth-support-seams'

export const inject = ['tools']

export const TOOL_NAMES = [
  'ce_prepare_support',
  'ce_validate_support_proposal',
  'ce_record_support_outcome',
  'ce_session_audit',
]

function writeJsonReceipt(dir, fileName, payload) {
  try {
    mkdirSync(dir, { recursive: true })
    writeFileSync(join(dir, fileName), `${JSON.stringify(payload, null, 2)}\n`, 'utf8')
    return true
  } catch {
    // Receipts are verification observability, never a functional dependency.
    return false
  }
}

/**
 * @param ctx - Cordis plugin context (host provides ctx.tools from dsh-tools).
 * @param config - bundle patch / profile patch config: { receipt_dir?,
 *   authorized_scopes?, methods? }.
 */
export function apply(ctx, config = {}) {
  const merged = {
    ...DEFAULT_CONFIG,
    ...config,
  }
  const core = createCore(merged)

  // Registration disposers are owned by the plugin fiber (host side effect);
  // the plugin keeps no reference of its own.
  for (const definition of [
    buildPrepareTool(core),
    buildValidateTool(core),
    buildRecordTool(core),
    buildAuditTool(core),
  ]) {
    ctx.tools.register(definition)
  }

  const receiptDir = typeof merged.receipt_dir === 'string' && merged.receipt_dir.length > 0 ? merged.receipt_dir : null
  let unloadWritten = false
  const writeUnloadReceipt = () => {
    if (!receiptDir || unloadWritten) return
    unloadWritten = true
    writeJsonReceipt(receiptDir, 'unload-receipt.json', {
      plugin: name,
      event: 'unload',
      at: new Date().toISOString(),
      tools_registered: TOOL_NAMES.length,
    })
  }
  const writeLoadReceipt = () => {
    if (!receiptDir) return
    writeJsonReceipt(receiptDir, 'load-receipt.json', {
      plugin: name,
      event: 'load',
      at: new Date().toISOString(),
      tools_registered: TOOL_NAMES,
      demo_scopes: (merged.authorized_scopes ?? []).length,
      demo_methods: (merged.methods ?? []).length,
    })
  }

  // Fiber-scoped teardown notification. The 'internal/plugin' event contract is
  // internal to Cordis, so it is guarded and paired with a process-exit
  // fallback: the unload receipt stays observable even if the event contract
  // changes. This layering is itself a documented verification finding.
  try {
    ctx.on('internal/plugin', () => {
      writeUnloadReceipt()
    })
  } catch {
    // Non-fatal: the process-exit fallback still writes the receipt.
  }
  process.once('exit', () => {
    writeUnloadReceipt()
  })

  writeLoadReceipt()
}
