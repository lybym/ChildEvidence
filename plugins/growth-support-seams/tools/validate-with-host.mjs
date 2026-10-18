/**
 * Live-verification helper (Issue #13): validate the plugin's registry-facing
 * schemas and the contracts.md §2.1 example input against the REAL host
 * validator (@deepseek-ai/dsh-tools).
 *
 * Usage:
 *   node tools/validate-with-host.mjs <profileDirOrToolsLibPath>
 *
 * The argument may be (a) an isolated DSH profile directory whose
 * node_modules contains @deepseek-ai/dsh-tools, (b) a direct path to the
 * dsh-tools lib/index.js, or (c) omitted/missing — then the helper falls back
 * to the locally installed DeepSeek Harness app payload (read-only).
 *
 * Exits 0 when every assertion passes; any mismatch prints the violation and
 * exits 1. Requires no network and no model credentials.
 */

import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const DEFAULT_APP_TOOLS_LIB =
  'C:/Users/lybym/AppData/Local/Programs/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-tools/lib/index.js'

const arg = process.argv[2]
let toolsLib = null
if (arg && existsSync(join(arg, 'node_modules', '@deepseek-ai', 'dsh-tools', 'lib', 'index.js'))) {
  toolsLib = join(arg, 'node_modules', '@deepseek-ai', 'dsh-tools', 'lib', 'index.js')
} else if (arg && existsSync(arg) && arg.endsWith('.js')) {
  toolsLib = arg
} else if (existsSync(DEFAULT_APP_TOOLS_LIB)) {
  toolsLib = DEFAULT_APP_TOOLS_LIB
}
if (!toolsLib) {
  console.error('dsh-tools not found: pass a profile directory or the dsh-tools lib/index.js path')
  process.exit(1)
}
const host = await import(pathToFileURL(toolsLib).href)

const schemas = {
  'support-input': JSON.parse(readFileSync(new URL('../schemas/support-input.schema.json', import.meta.url), 'utf8')),
  'support-result': JSON.parse(readFileSync(new URL('../schemas/support-result.schema.json', import.meta.url), 'utf8')),
  'proposal': JSON.parse(readFileSync(new URL('../schemas/proposal.schema.json', import.meta.url), 'utf8')),
  'record-args': JSON.parse(readFileSync(new URL('../schemas/record-args.schema.json', import.meta.url), 'utf8')),
  'record-receipt': JSON.parse(readFileSync(new URL('../schemas/record-receipt.schema.json', import.meta.url), 'utf8')),
  'session-audit': JSON.parse(readFileSync(new URL('../schemas/session-audit.schema.json', import.meta.url), 'utf8')),
}

let failures = 0
const check = (label, fn) => {
  try {
    fn()
    console.log(`PASS ${label}`)
  } catch (error) {
    failures += 1
    console.log(`FAIL ${label}: ${error.message}`)
  }
}

for (const [schemaName, schema] of Object.entries(schemas)) {
  const { $id, description, ...registryFacing } = schema
  check(`host assertSupportedJsonSchema(${schemaName})`, () => {
    host.assertSupportedJsonSchema(registryFacing)
  })
}

// The contracts.md §2.1 synthetic example must validate against the input
// schema with the host validator, and a mutated actor role must be rejected.
const exampleInput = {
  schema_version: 'ce.support-input.draft-0.1',
  request_id: 'demo-request-001',
  session_ref: 'demo-session-A',
  actor: { role: 'child', principal_ref: 'demo-principal-A' },
  subject_ref: 'demo-learner-A',
  response_audience: 'child',
  authorization_ref: 'demo-host-scope-A',
  intent: 'help_with_current_task',
  task: {
    kind: 'school_task',
    content: '合成题目：三组各有四个物品，一共有多少个？',
    source_ref: 'demo-host-event-01',
    content_verification: 'synthetic_fixture',
  },
  observations: [
    { id: 'demo-observation-01', kind: 'child_self_report', statement: '我不知道从哪里开始。', source_event_ref: 'demo-host-event-02' },
  ],
  input_quality: { ambiguities: [], confidence: null },
  context_snapshot: { observations: [], hypotheses: [], outcomes: [] },
  state_revision: 0,
  active_plan_ref: null,
  capabilities: { presentation: ['text', 'speech', 'web_activity'], action_receipts: true },
  asset_lock: { pack_version: 'demo-only', purpose: 'synthetic_evaluation' },
}

check('host validateJsonSchemaValue(contracts §2.1 example)', () => {
  const violations = host.validateJsonSchemaValue(schemas['support-input'], exampleInput, 'input')
  if (violations.length > 0) throw new Error(violations.join('; '))
})

check('host rejects a self-invented actor role', () => {
  const mutated = { ...exampleInput, actor: { role: 'guardian_override', principal_ref: 'demo-principal-A' } }
  const violations = host.validateJsonSchemaValue(schemas['support-input'], mutated, 'input')
  if (violations.length === 0) throw new Error('expected violations for unknown actor role')
})

console.log(failures === 0 ? 'ALL HOST-VALIDATION CHECKS PASSED' : `${failures} CHECK(S) FAILED`)
process.exit(failures === 0 ? 0 : 1)
