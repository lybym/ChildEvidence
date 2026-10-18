/**
 * Live-verification helper (Issue #13): validate the plugin's registry-facing
 * schemas and the contracts.md §2.1 example input against the REAL host
 * validator (@deepseek-ai/dsh-tools).
 *
 * Validator resolution (no machine-specific path is stored in version
 * control; AGENTS.md #12):
 *   1. explicit argument — an isolated DSH profile directory whose
 *      node_modules contains @deepseek-ai/dsh-tools, or a direct path to the
 *      dsh-tools lib/index.js;
 *   2. `CE_DSH_TOOLS_LIB` environment variable — direct path to the
 *      dsh-tools lib/index.js;
 *   3. the locally installed DeepSeek Harness payload, derived at runtime
 *      from `$env:LOCALAPPDATA` (read-only).
 *
 * NOTE: the installed app ships its packages inside an `.asar` archive that
 * ONLY the host runtime (Electron-as-node) can read. With plain `node`,
 * candidate 3 is invisible (`existsSync` returns false); either run this
 * script through the host runtime (see the failure diagnostic) or point
 * `CE_DSH_TOOLS_LIB` at an unpacked copy, e.g. an isolated profile that has
 * dsh-tools installed.
 *
 * Prints the resolved validator path and its package version as provenance.
 * Exits 0 when every assertion passes; any mismatch prints the violation and
 * exits 1. Requires no network and no model credentials.
 */

import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

function buildCandidates(arg) {
  const candidates = []
  if (arg) {
    if (arg.endsWith('.js')) {
      candidates.push({ label: `explicit path (${arg})`, lib: arg })
    } else {
      candidates.push({
        label: `explicit profile (${arg})`,
        lib: join(arg, 'node_modules', '@deepseek-ai', 'dsh-tools', 'lib', 'index.js'),
      })
    }
  }
  const envLib = process.env.CE_DSH_TOOLS_LIB
  if (envLib) {
    candidates.push({ label: 'env CE_DSH_TOOLS_LIB', lib: envLib })
  }
  const localAppData = process.env.LOCALAPPDATA
  if (localAppData) {
    candidates.push({
      label: 'installed DeepSeek Harness payload ($LOCALAPPDATA, read-only)',
      lib: join(
        localAppData,
        'Programs',
        'DeepSeek Harness',
        'resources',
        'app.asar',
        'dsh',
        'node_modules',
        '@deepseek-ai',
        'dsh-tools',
        'lib',
        'index.js'
      ),
    })
  }
  return candidates
}

async function resolveHost() {
  const attempts = []
  for (const candidate of buildCandidates(process.argv[2])) {
    if (!existsSync(candidate.lib)) {
      attempts.push(`${candidate.label}: not found by this runtime`)
      continue
    }
    try {
      const host = await import(pathToFileURL(candidate.lib).href)
      const expected = ['assertSupportedJsonSchema', 'validateJsonSchemaValue']
      const missing = expected.filter((name) => typeof host[name] !== 'function')
      if (missing.length > 0) {
        attempts.push(`${candidate.label}: missing exports ${missing.join(', ')}`)
        continue
      }
      let version = 'unknown'
      try {
        version = JSON.parse(readFileSync(join(candidate.lib, '..', '..', 'package.json'), 'utf8')).version
      } catch {
        // Provenance is best-effort; the validator itself is what matters.
      }
      return { host, lib: candidate.lib, version, attempts }
    } catch (error) {
      attempts.push(`${candidate.label}: import failed (${error.message})`)
    }
  }
  return { host: null, lib: null, version: null, attempts }
}

const resolved = await resolveHost()
if (!resolved.host) {
  console.error('dsh-tools could not be resolved. Attempts:')
  for (const attempt of resolved.attempts) console.error(`  - ${attempt}`)
  console.error(
    'Fixes: pass an isolated profile directory that has dsh-tools installed, set CE_DSH_TOOLS_LIB to an unpacked\n' +
      'dsh-tools lib/index.js, or run this script through the host runtime, which can read the installed .asar\n' +
      'payload (plain Node cannot):\n' +
      '  $env:ELECTRON_RUN_AS_NODE = "1"\n' +
      '  & "$env:LOCALAPPDATA\\Programs\\DeepSeek Harness\\DeepSeek Harness.exe" --expose-internals \\\n' +
      '      plugins\\growth-support-seams\\tools\\validate-with-host.mjs'
  )
  process.exit(1)
}
const host = resolved.host
console.log(`validator: ${resolved.lib}`)
console.log(`dsh-tools version: ${resolved.version}`)

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
