/**
 * Node self-check for the ce-growth-support-seams plugin (Issue #13).
 *
 * Runs offline with plain `node tests/self-check.mjs` (no third-party deps,
 * no host process, no network). It replicates the registry-side registration
 * contract of @deepseek-ai/dsh-tools (documented in the verification report),
 * exercises the controlled flow end to end, and validates every produced
 * result against the shipped subset schemas.
 *
 * The real-host schema validation (assertSupportedJsonSchema from the
 * installed DSH) runs separately via tools/validate-with-host.mjs against an
 * isolated profile's node_modules.
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, existsSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { apply, name as pluginName, inject, TOOL_NAMES } from '../lib/index.js'
import {
  createCore,
  DEFAULT_CONFIG,
  SUPPORT_INPUT_SCHEMA,
  SUPPORT_RESULT_SCHEMA,
  PROPOSAL_SCHEMA,
  RECORD_RECEIPT_SCHEMA,
  SESSION_AUDIT_SCHEMA,
  SUPPORT_INPUT_SCHEMA_VERSION,
  SUPPORT_RESULT_SCHEMA_VERSION,
  RECORD_RECEIPT_SCHEMA_VERSION,
} from '../lib/controlled-core.js'
import { buildPrepareTool, buildValidateTool, buildRecordTool, buildAuditTool } from '../lib/tool-definitions.js'

// ---------------------------------------------------------------------------
// Minimal subset-schema support: mirrors the host-side enforced subset
// (type / properties / required / enum / items) closely enough for this
// verification; the authoritative check runs against the installed host.
// ---------------------------------------------------------------------------

const SCHEMA_KEYS_ALLOWED = new Set(['type', 'properties', 'required', 'enum', 'items', 'description', '$id'])
const TYPE_NAMES = new Set(['string', 'number', 'integer', 'boolean', 'object', 'array', 'null'])

function assertSubsetSchema(node, path = 'schema') {
  assert.ok(typeof node === 'object' && node !== null && !Array.isArray(node), `${path} must be an object`)
  for (const key of Object.keys(node)) {
    assert.ok(SCHEMA_KEYS_ALLOWED.has(key), `${path}.${key} is outside the enforced subset`)
  }
  assert.ok(typeof node.type === 'string' && TYPE_NAMES.has(node.type), `${path}.type must be a known type name`)
  if (node.enum !== undefined) {
    assert.ok(Array.isArray(node.enum), `${path}.enum must be an array`)
  }
  if (node.required !== undefined) {
    assert.ok(Array.isArray(node.required) && node.required.every((item) => typeof item === 'string'), `${path}.required must be strings`)
  }
  if (node.properties !== undefined) {
    assert.ok(typeof node.properties === 'object' && node.properties !== null && !Array.isArray(node.properties), `${path}.properties must be an object`)
    for (const [key, child] of Object.entries(node.properties)) {
      assertSubsetSchema(child, `${path}.properties.${key}`)
    }
  }
  if (node.items !== undefined) {
    assertSubsetSchema(node.items, `${path}.items`)
  }
}

function validateAgainstSubset(schema, value, path = 'value') {
  if (schema.type === 'object') {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) return [`${path} must be an object`]
    const violations = []
    for (const field of schema.required ?? []) {
      if (value[field] === undefined) violations.push(`${path}.${field} is required`)
    }
    for (const [key, child] of Object.entries(schema.properties ?? {})) {
      if (value[key] === undefined) continue
      violations.push(...validateAgainstSubset(child, value[key], `${path}.${key}`))
    }
    return violations
  }
  if (schema.type === 'array') {
    if (!Array.isArray(value)) return [`${path} must be an array`]
    const violations = []
    value.forEach((item, index) => violations.push(...validateAgainstSubset(schema.items ?? {}, item, `${path}[${index}]`)))
    return violations
  }
  if (schema.type === 'integer') {
    if (!Number.isInteger(value)) return [`${path} must be an integer`]
    return []
  }
  if (value?.constructor !== { string: String, number: Number, boolean: Boolean }[schema.type]) {
    // number accepts integers too
    if (!(schema.type === 'number' && typeof value === 'number')) return [`${path} must be of type ${schema.type}`]
  }
  if (schema.enum !== undefined && !schema.enum.includes(value)) {
    return [`${path} must be one of ${JSON.stringify(schema.enum)}`]
  }
  return []
}

// ---------------------------------------------------------------------------
// Fake host context replicating the documented ctx.tools.register contract.
// ---------------------------------------------------------------------------

function createFakeCtx() {
  const tools = new Map()
  const listeners = new Map()
  const ctx = {
    tools: {
      register(definition) {
        assert.equal(definition.name === 'run_code', false, 'run_code is reserved')
        assert.equal(typeof definition.description, 'string', 'description required')
        assert.equal(typeof definition.execute, 'function', 'execute required')
        const output = definition.output
        assert.ok(output && typeof output === 'object', `tool "${definition.name}" must declare output`)
        assert.equal(typeof output.render, 'function', `tool "${definition.name}" output.render must be a function`)
        assertSubsetSchema(output.schema, `tool "${definition.name}" output.schema`)
        if (definition.timeoutMs !== undefined) {
          assert.ok(Number.isFinite(definition.timeoutMs) && definition.timeoutMs > 0, 'timeoutMs must be positive finite')
        }
        assertSubsetSchema(definition.parameters, `tool "${definition.name}" parameters`)
        tools.set(definition.name, definition)
        return () => tools.delete(definition.name)
      },
    },
    on(eventName, listener) {
      const hooks = listeners.get(eventName) ?? []
      hooks.push(listener)
      listeners.set(eventName, hooks)
      return () => {}
    },
  }
  ctx._tools = tools
  ctx._listeners = listeners
  return ctx
}

function makeCore() {
  return createCore({ ...DEFAULT_CONFIG })
}

function demoInput(overrides = {}) {
  return {
    schema_version: SUPPORT_INPUT_SCHEMA_VERSION,
    request_id: 'demo-request-001',
    session_ref: 'demo-session-A',
    actor: { role: 'child', principal_ref: 'demo-principal-A' },
    subject_ref: 'demo-learner-A',
    response_audience: 'child',
    authorization_ref: 'demo-host-scope-A',
    intent: 'help_with_current_task',
    task: { kind: 'school_task', content: '合成题目：三组各有四个物品，一共有多少个？', content_verification: 'synthetic_fixture' },
    observations: [
      { id: 'demo-observation-01', kind: 'child_self_report', statement: '我不知道从哪里开始。', source_event_ref: 'demo-host-event-02' },
    ],
    input_quality: { ambiguities: [], confidence: null },
    state_revision: 0,
    ...overrides,
  }
}

function demoValidate(core, overrides = {}) {
  return core.validateProposal({
    request_id: 'demo-request-001',
    session_ref: 'demo-session-A',
    subject_ref: 'demo-learner-A',
    authorization_ref: 'demo-host-scope-A',
    state_revision: 0,
    proposal: {
      action_id: 'demo-action-001',
      action_kind: 'ask_clarification',
      content: '你觉得这道题想让我们找出什么？（合成）',
      method_ref: 'demo-method-clarify@1',
    },
    ...overrides,
  })
}

async function runHappyPath(core) {
  const prepared = await core.prepareSupport(demoInput())
  assert.equal(prepared.status, 'proposal_ready', `prepare should be proposal_ready, got ${JSON.stringify(prepared)}`)
  const validated = await demoValidate(core)
  assert.equal(validated.status, 'proposal_ready')
  const receipt = await core.recordOutcome({
    request_id: 'demo-request-001',
    session_ref: 'demo-session-A',
    subject_ref: 'demo-learner-A',
    authorization_ref: 'demo-host-scope-A',
    action_id: 'demo-action-001',
    expected_revision: 0,
    outcome: { kind: 'executed', detail: 'demo receipt' },
  })
  return { prepared, validated, receipt }
}

test('plugin module exposes the documented Cordis object shape', () => {
  assert.equal(pluginName, 'ce-growth-support-seams')
  assert.deepEqual(inject, ['tools'])
  assert.equal(typeof apply, 'function')
  assert.deepEqual(TOOL_NAMES, [
    'ce_prepare_support',
    'ce_validate_support_proposal',
    'ce_record_support_outcome',
    'ce_session_audit',
  ])
})

test('embedded schemas match the shipped schema mirrors exactly (both directions)', () => {
  const mirrors = [
    [SUPPORT_INPUT_SCHEMA, '../schemas/support-input.schema.json'],
    [SUPPORT_RESULT_SCHEMA, '../schemas/support-result.schema.json'],
    [PROPOSAL_SCHEMA, '../schemas/proposal.schema.json'],
    [RECORD_RECEIPT_SCHEMA, '../schemas/record-receipt.schema.json'],
    [SESSION_AUDIT_SCHEMA, '../schemas/session-audit.schema.json'],
  ]
  const mirrorOnlyKeys = new Set(['description', '$id'])
  for (const [embedded, relative] of mirrors) {
    const mirror = JSON.parse(readFileSync(new URL(relative, import.meta.url), 'utf8'))
    const embeddedKeys = Object.keys(embedded).filter((key) => !mirrorOnlyKeys.has(key))
    const mirrorKeys = Object.keys(mirror).filter((key) => !mirrorOnlyKeys.has(key))
    assert.deepEqual(
      [...mirrorKeys].sort(),
      [...embeddedKeys].sort(),
      `${relative} carries content keys the embedded schema does not have (mirror-only drift)`
    )
    for (const key of embeddedKeys) {
      assert.deepEqual(embedded[key], mirror[key], `${relative} key ${key} drifts from the embedded schema`)
    }
    assertSubsetSchema(embedded)
  }
  // The record tool's registry-facing parameters must match their shipped mirror.
  const recordMirror = JSON.parse(readFileSync(new URL('../schemas/record-args.schema.json', import.meta.url), 'utf8'))
  const ctx = createFakeCtx()
  apply(ctx, {})
  const recordTool = ctx._tools.get('ce_record_support_outcome')
  assert.deepEqual(
    { ...recordTool.parameters, description: recordMirror.description, $id: recordMirror.$id },
    recordMirror,
    'record-args.schema.json drifts from the built tool parameters'
  )
  assert.equal(recordMirror.$id, 'ce.support-record-args.draft-0.1', 'record-args $id must not collide with the receipt schema_version')
})

test('apply registers the four controlled-flow tools through ctx.tools', () => {
  const ctx = createFakeCtx()
  apply(ctx, {})
  assert.deepEqual([...ctx._tools.keys()].sort(), [...TOOL_NAMES].sort())
})

test('AC2 happy path: unified input → tool → validation → structured host output', async () => {
  const core = makeCore()
  const { prepared, validated, receipt } = await runHappyPath(core)

  assert.equal(prepared.schema_version, SUPPORT_RESULT_SCHEMA_VERSION)
  assert.equal(prepared.provenance.evidence_refs.length, 0, 'no fabricated evidence')
  assert.equal(prepared.validation.eligible_for_real_user_delivery, false)
  assert.deepEqual(
    validateAgainstSubset(SUPPORT_RESULT_SCHEMA, prepared),
    [],
    `prepared result violates SupportResult schema`
  )
  assert.equal(validated.next_action.kind, 'ask_clarification')
  assert.equal(validated.next_action.method_ref, 'demo-method-clarify@1')
  assert.deepEqual(validateAgainstSubset(SUPPORT_RESULT_SCHEMA, validated), [])
  assert.equal(receipt.receipt.success_written, true)
  assert.equal(receipt.receipt.idempotent, false)
  assert.equal(receipt.receipt.revision_after, 1)
  assert.deepEqual(validateAgainstSubset(RECORD_RECEIPT_SCHEMA, receipt), [])
})

test('record is idempotent per (request_id, action_id)', async () => {
  const core = makeCore()
  await runHappyPath(core)
  const replay = await core.recordOutcome({
    request_id: 'demo-request-001',
    session_ref: 'demo-session-A',
    subject_ref: 'demo-learner-A',
    authorization_ref: 'demo-host-scope-A',
    action_id: 'demo-action-001',
    expected_revision: 1,
    outcome: { kind: 'executed' },
  })
  assert.equal(replay.receipt.idempotent, true)
  assert.equal(replay.receipt.success_written, true)
  assert.equal(replay.receipt.record_count_for_subject, 1, 'no duplicate record row')
})

test('idempotent replay echoes the ORIGINAL outcome, not the replayed claim (review P2-3)', async () => {
  const core = makeCore()
  await runHappyPath(core) // executed, success_written true, revision -> 1
  const replay = await core.recordOutcome({
    request_id: 'demo-request-001',
    session_ref: 'demo-session-A',
    subject_ref: 'demo-learner-A',
    authorization_ref: 'demo-host-scope-A',
    action_id: 'demo-action-001',
    expected_revision: 1,
    outcome: { kind: 'declined' },
  })
  assert.equal(replay.receipt.idempotent, true)
  assert.equal(replay.receipt.outcome_kind, 'executed', 'replay must return the stored original outcome_kind')
  assert.equal(replay.receipt.success_written, true, 'replay must return the stored original success_written')
  assert.equal(replay.receipt.record_count_for_subject, 1)
})

test('blocked record receipts report attributable state, never fabricated zeros (review P2-2, round 2)', async () => {
  const core = makeCore()
  await runHappyPath(core) // revision -> 1, one record row

  // Stale write of an UNRECORDED action: re-validate a second action at the
  // new revision, then record it with a stale expected_revision.
  const revalidated = await demoValidate(core, {
    state_revision: 1,
    proposal: { action_id: 'demo-action-002', action_kind: 'offer_choice', content: 'demo second action', method_ref: 'demo-method-clarify@1' },
  })
  assert.equal(revalidated.status, 'proposal_ready')
  const stale = await core.recordOutcome({
    request_id: 'demo-request-001',
    session_ref: 'demo-session-A',
    subject_ref: 'demo-learner-A',
    authorization_ref: 'demo-host-scope-A',
    action_id: 'demo-action-002',
    expected_revision: 0, // stale: request is now at revision 1
    outcome: { kind: 'executed' },
  })
  assert.equal(stale.validation.failure_code, 'revision_conflict', 'expected_revision mismatch is refused for first writes')
  assert.equal(stale.receipt.success_written, false)
  assert.equal(stale.receipt.revision_after, 1, 'real current revision, not a fabricated zero')
  assert.equal(stale.receipt.record_count_for_subject, 1, 'real current record count')
  assert.deepEqual(validateAgainstSubset(RECORD_RECEIPT_SCHEMA, stale), [], 'blocked receipt violates the receipt schema')

  const unknownRequest = await core.recordOutcome({
    request_id: 'demo-request-unknown',
    session_ref: 'demo-session-A',
    subject_ref: 'demo-learner-A',
    authorization_ref: 'demo-host-scope-A',
    action_id: 'demo-action-001',
    expected_revision: 0,
    outcome: { kind: 'executed' },
  })
  assert.equal(unknownRequest.validation.failure_code, 'prepare_required')
  assert.equal(unknownRequest.receipt.record_count_for_subject, undefined, 'counters omitted when not attributable')
  assert.equal(unknownRequest.receipt.revision_after, undefined, 'revision omitted when not attributable')
  assert.deepEqual(validateAgainstSubset(RECORD_RECEIPT_SCHEMA, unknownRequest), [])

  // The verified second action then records normally and advances the revision.
  const second = await core.recordOutcome({
    request_id: 'demo-request-001',
    session_ref: 'demo-session-A',
    subject_ref: 'demo-learner-A',
    authorization_ref: 'demo-host-scope-A',
    action_id: 'demo-action-002',
    expected_revision: 1,
    outcome: { kind: 'executed' },
  })
  assert.equal(second.receipt.success_written, true)
  assert.equal(second.receipt.revision_after, 2, 'each successful record advances the revision')
})

test('at-least-once retry: same-args retry of a successful record returns the original receipt (review P2-1, round 2)', async () => {
  const core = makeCore()
  const first = await runHappyPath(core) // executed at expected_revision 0, revision -> 1
  assert.equal(first.receipt.receipt.idempotent, false)

  const retry = await core.recordOutcome({
    request_id: 'demo-request-001',
    session_ref: 'demo-session-A',
    subject_ref: 'demo-learner-A',
    authorization_ref: 'demo-host-scope-A',
    action_id: 'demo-action-001',
    expected_revision: 0, // deliberately stale, exactly the original arguments
    outcome: { kind: 'executed' },
  })
  assert.equal(retry.receipt.idempotent, true, 'same-args retry must be recognized as a replay')
  assert.equal(retry.receipt.outcome_kind, 'executed')
  assert.equal(retry.receipt.success_written, true)
  assert.equal(retry.receipt.record_count_for_subject, 1, 'no duplicate record row')
  assert.equal(retry.receipt.revision_after, 1, 'replay writes nothing')
  assert.deepEqual(validateAgainstSubset(RECORD_RECEIPT_SCHEMA, retry), [])
})

test('unauthorized paths never disclose another subject\u2019s state (round-2 review P1-1)', async () => {
  const core = makeCore()
  await runHappyPath(core) // subject A state: 1 record row, revision 1

  const probes = [
    {
      label: 'legit scope for another subject',
      args: {
        request_id: 'demo-request-001',
        session_ref: 'demo-session-A',
        subject_ref: 'demo-learner-A', // claimed, but scope B binds learner-B
        authorization_ref: 'demo-host-scope-B',
        action_id: 'demo-action-001',
        expected_revision: 1,
        outcome: { kind: 'executed' },
      },
      expectedCode: 'subject_scope_mismatch',
    },
    {
      label: 'unknown scope',
      args: {
        request_id: 'demo-request-001',
        session_ref: 'demo-session-A',
        subject_ref: 'demo-learner-A',
        authorization_ref: 'demo-host-scope-not-real',
        action_id: 'demo-action-001',
        expected_revision: 1,
        outcome: { kind: 'executed' },
      },
      expectedCode: 'unknown_authorization_scope',
    },
    {
      label: 'scope without record capability',
      args: {
        request_id: 'demo-request-001',
        session_ref: 'demo-session-A',
        subject_ref: 'demo-learner-A',
        authorization_ref: 'demo-host-scope-A-observer',
        action_id: 'demo-action-001',
        expected_revision: 1,
        outcome: { kind: 'executed' },
      },
      expectedCode: 'scope_not_permitted',
    },
    {
      label: 'missing authorization',
      args: {
        request_id: 'demo-request-001',
        session_ref: 'demo-session-A',
        subject_ref: 'demo-learner-A',
        authorization_ref: undefined,
        action_id: 'demo-action-001',
        expected_revision: 1,
        outcome: { kind: 'executed' },
      },
      expectedCode: 'missing_authorization',
    },
  ]
  for (const probe of probes) {
    const receipt = await core.recordOutcome(probe.args)
    assert.equal(receipt.validation.failure_code, probe.expectedCode, probe.label)
    assert.equal(receipt.receipt.record_count_for_subject, undefined, `${probe.label}: subject-A record count must be omitted`)
    assert.equal(receipt.receipt.revision_after, undefined, `${probe.label}: subject-A revision must be omitted`)
    assert.equal(receipt.subject_ref, probe.args.subject_ref, 'top-level subject_ref always present for schema conformance')
    assert.deepEqual(validateAgainstSubset(RECORD_RECEIPT_SCHEMA, receipt), [], `${probe.label}: receipt must satisfy the receipt schema`)
  }
  assert.equal(core._state.recordsBySubject.get('demo-learner-A')?.length ?? 0, 1, 'no probe mutated subject-A state')
})

test('declined outcome is recorded without a success row (AC2 refusal case)', async () => {
  const core = makeCore()
  const prepared = await core.prepareSupport(demoInput())
  assert.equal(prepared.status, 'proposal_ready')
  const validated = await demoValidate(core)
  assert.equal(validated.status, 'proposal_ready')
  const declined = await core.recordOutcome({
    request_id: 'demo-request-001',
    session_ref: 'demo-session-A',
    subject_ref: 'demo-learner-A',
    authorization_ref: 'demo-host-scope-A',
    action_id: 'demo-action-001',
    expected_revision: 0,
    outcome: { kind: 'declined', detail: 'demo: child declined the offered choice' },
  })
  assert.equal(declined.receipt.outcome_kind, 'declined')
  assert.equal(declined.receipt.success_written, false)
  assert.equal(declined.receipt.revision_after, 0, 'decline does not advance state')
})

test('prior decline pauses the flow before a proposal is stored', async () => {
  const core = makeCore()
  await core.prepareSupport(demoInput())
  const paused = await demoValidate(core, { prior_decline: { declined: true } })
  assert.equal(paused.status, 'paused')
  const blocked = await core.recordOutcome({
    request_id: 'demo-request-001',
    session_ref: 'demo-session-A',
    subject_ref: 'demo-learner-A',
    authorization_ref: 'demo-host-scope-A',
    action_id: 'demo-action-001',
    expected_revision: 0,
    outcome: { kind: 'executed' },
  })
  assert.equal(blocked.validation.failure_code, 'unvalidated_outcome', 'paused flow leaves nothing to record')
})

test('controlled entry is enforced in order: validate without prepare is refused', async () => {
  const core = makeCore()
  const blocked = await demoValidate(core)
  assert.equal(blocked.status, 'blocked')
  assert.equal(blocked.validation.failure_code, 'prepare_required')
})

test('revision conflict is detected instead of silently applied', async () => {
  const core = makeCore()
  await core.prepareSupport(demoInput({ state_revision: 3 }))
  const stale = await demoValidate(core, { state_revision: 2 })
  assert.equal(stale.validation.failure_code, 'revision_conflict')
  const current = await demoValidate(core, { state_revision: 3 })
  assert.equal(current.status, 'proposal_ready')
})

test('unknown action kinds and unknown method refs are refused and preserved', async () => {
  const core = makeCore()
  await core.prepareSupport(demoInput())
  const unknownKind = await demoValidate(core, {
    proposal: { action_id: 'demo-action-002', action_kind: 'free_form_diagnosis', content: 'demo', method_ref: 'demo-method-clarify@1' },
  })
  assert.equal(unknownKind.status, 'blocked')
  assert.equal(unknownKind.validation.failure_code, 'unknown_action_kind')
  assert.ok(unknownKind.understanding.unknowns.some((item) => item.includes('free_form_diagnosis')), 'unknown value preserved')

  const unknownMethod = await demoValidate(core, {
    proposal: { action_id: 'demo-action-003', action_kind: 'ask_clarification', content: 'demo', method_ref: 'demo-method-not-real@9' },
  })
  assert.equal(unknownMethod.validation.failure_code, 'unknown_method_ref')
})

test('AC3/E01: ambiguities and missing info lead to needs_information, never a capability verdict', async () => {
  const core = makeCore()
  const ambiguous = await core.prepareSupport(demoInput({ input_quality: { ambiguities: ['题目要求不明确'], confidence: null } }))
  assert.equal(ambiguous.status, 'needs_information')
  assert.ok(ambiguous.understanding.unknowns.some((item) => item.includes('题目要求不明确')))

  const noTask = await core.prepareSupport(demoInput({ task: {} }))
  assert.equal(noTask.status, 'needs_information')
  assert.ok(noTask.understanding.unknowns.some((item) => item.includes('missing info: task_understanding')))
})

test('unknown observation kinds are preserved, not treated as evidence', async () => {
  const core = makeCore()
  const result = await core.prepareSupport(
    demoInput({
      observations: [
        { id: 'demo-observation-02', kind: 'voice_tone_inference', statement: 'demo unknown-source observation', source_event_ref: 'demo-host-event-03' },
      ],
    })
  )
  assert.ok(result.understanding.unknowns.some((item) => item.includes('voice_tone_inference')), 'unknown kind preserved in unknowns')
})

test('out-of-scope intent stops the demo flow honestly', async () => {
  const core = makeCore()
  const result = await core.prepareSupport(demoInput({ intent: 'unrelated_intent' }))
  assert.equal(result.status, 'out_of_scope')
  assert.equal(result.next_action, undefined)
})

test('authorization: self-report never grants access; scopes bind subjects', async () => {
  const core = makeCore()

  const noAuth = await core.prepareSupport(demoInput({ authorization_ref: undefined }))
  assert.equal(noAuth.validation.failure_code, 'missing_authorization')

  const unknownScope = await core.prepareSupport(demoInput({ authorization_ref: 'demo-host-scope-Z' }))
  assert.equal(unknownScope.validation.failure_code, 'unknown_authorization_scope')

  const mismatch = await core.prepareSupport(demoInput({ subject_ref: 'demo-learner-B' }))
  assert.equal(mismatch.validation.failure_code, 'subject_scope_mismatch')

  const observerRecord = await core.recordOutcome({
    request_id: 'demo-request-001',
    session_ref: 'demo-session-A',
    subject_ref: 'demo-learner-A',
    authorization_ref: 'demo-host-scope-A-observer',
    action_id: 'demo-action-001',
    expected_revision: 0,
    outcome: { kind: 'executed' },
  })
  assert.equal(observerValidation(observerRecord), 'scope_not_permitted')
})

function observerValidation(receipt) {
  return receipt.validation.failure_code
}

test('subject isolation: records and audit calls never cross subjects (AC3/E09/E10)', async () => {
  const core = makeCore()
  await runHappyPath(core)

  const auditA = await core.sessionAudit({ authorization_ref: 'demo-host-scope-A', session_ref: 'demo-session-A' })
  assert.equal(auditA.scope_subject_ref, 'demo-learner-A')
  assert.ok(auditA.controlled_call_count >= 3)
  assert.ok(auditA.calls.every((call) => call.subject_ref === 'demo-learner-A'))

  const auditB = await core.sessionAudit({ authorization_ref: 'demo-host-scope-B', session_ref: 'demo-session-A' })
  assert.equal(auditB.scope_subject_ref, 'demo-learner-B')
  assert.equal(auditB.controlled_call_count, 0, 'subject B sees none of subject A calls')

  const crossSubject = await core.recordOutcome({
    request_id: 'demo-request-001',
    session_ref: 'demo-session-A',
    subject_ref: 'demo-learner-A',
    authorization_ref: 'demo-host-scope-B',
    action_id: 'demo-action-001',
    expected_revision: 1,
    outcome: { kind: 'executed' },
  })
  assert.equal(crossSubject.validation.failure_code, 'subject_scope_mismatch')
  assert.equal(crossSubject.receipt.record_count_for_subject, undefined, 'cross-subject blocked receipt omits subject-A counters')
  assert.equal(crossSubject.receipt.revision_after, undefined, 'cross-subject blocked receipt omits subject-A revision')
})

test('E14 tool-miss detection: an orphan request reports zero controlled calls', async () => {
  const core = makeCore()
  await core.prepareSupport(demoInput())
  const audit = await core.sessionAudit({ authorization_ref: 'demo-host-scope-A', request_id: 'demo-request-orphan' })
  assert.equal(audit.controlled_call_count, 0)
  assert.equal(audit.uncontrolled_request_hint, true)
})

test('cancel is observable: aborted signal blocks prepare without state change', async () => {
  const core = makeCore()
  const controller = new AbortController()
  controller.abort()
  const blocked = await core.prepareSupport(demoInput(), { signal: controller.signal })
  assert.equal(blocked.validation.status, 'aborted')
  assert.equal(core._state.requests.size, 0, 'aborted prepare stores nothing')
  const later = await demoValidate(core)
  assert.equal(later.validation.failure_code, 'prepare_required')
})

test('cancel is observable: aborting mid-delay prevents the success row', async () => {
  const core = makeCore()
  await core.prepareSupport(demoInput({ request_id: 'demo-request-101' }))
  await core.validateProposal({
    request_id: 'demo-request-101',
    session_ref: 'demo-session-A',
    subject_ref: 'demo-learner-A',
    authorization_ref: 'demo-host-scope-A',
    state_revision: 0,
    proposal: { action_id: 'demo-action-102', action_kind: 'ask_clarification', content: 'demo', method_ref: 'demo-method-clarify@1' },
  })
  const controller = new AbortController()
  const pending = core.recordOutcome(
    {
      request_id: 'demo-request-101',
      session_ref: 'demo-session-A',
      subject_ref: 'demo-learner-A',
      authorization_ref: 'demo-host-scope-A',
      action_id: 'demo-action-102',
      expected_revision: 0,
      delay_ms: 200,
      outcome: { kind: 'executed' },
    },
    { signal: controller.signal }
  )
  setTimeout(() => controller.abort(), 20)
  const receipt = await pending
  assert.equal(receipt.validation.status, 'aborted')
  assert.equal(receipt.receipt.success_written, false)
  assert.equal(receipt.receipt.revision_after, 0, 'attributable counters reflect the untouched state')
  assert.equal(core._state.recordsBySubject.get('demo-learner-A')?.length ?? 0, 0, 'aborted outcome persists nothing')
})

test('schema_version upgrade is refused with a dedicated code (review test gap 1)', async () => {
  const core = makeCore()
  const upgraded = await core.prepareSupport(demoInput({ schema_version: 'ce.support-input.draft-0.2' }))
  assert.equal(upgraded.status, 'blocked')
  assert.equal(upgraded.validation.failure_code, 'unsupported_schema_version')
  assert.ok(upgraded.validation.failure_message.includes('ce.support-input.draft-0.2'))
  assert.equal(core._state.requests.size, 0, 'unsupported version stores no request state')
  const sameCore = await core.prepareSupport(demoInput())
  assert.equal(sameCore.status, 'proposal_ready', 'the core still accepts the supported version afterwards')
})

test('exit fallback listener is removed once the unload receipt is written (review P2-4)', () => {
  const dir = mkdtempSync(join(tmpdir(), 'ce-seam-exit-'))
  const baseline = process.listenerCount('exit')
  try {
    const ctx = createFakeCtx()
    apply(ctx, { receipt_dir: dir })
    assert.equal(process.listenerCount('exit'), baseline + 1, 'exit fallback registered while receipts are pending')

    const hooks = ctx._listeners.get('internal/plugin')
    hooks[0]()
    assert.equal(process.listenerCount('exit'), baseline, 'written unload receipt removes the exit fallback')

    const noReceiptCtx = createFakeCtx()
    apply(noReceiptCtx, {})
    assert.equal(process.listenerCount('exit'), baseline, 'no exit fallback when receipt_dir is not configured')
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('load/unload receipts are observable when receipt_dir is configured', () => {
  const dir = mkdtempSync(join(tmpdir(), 'ce-seam-receipts-'))
  try {
    const ctx = createFakeCtx()
    apply(ctx, { receipt_dir: dir })
    const load = JSON.parse(readFileSync(join(dir, 'load-receipt.json'), 'utf8'))
    assert.equal(load.plugin, pluginName)
    assert.equal(load.event, 'load')
    assert.deepEqual(load.tools_registered, TOOL_NAMES)

    const hooks = ctx._listeners.get('internal/plugin')
    assert.ok(Array.isArray(hooks) && hooks.length === 1, 'unload hook registered on the plugin teardown event')
    hooks[0]()
    const unload = JSON.parse(readFileSync(join(dir, 'unload-receipt.json'), 'utf8'))
    assert.equal(unload.event, 'unload')

    hooks[0]()
    assert.ok(existsSync(join(dir, 'unload-receipt.json')), 'repeat teardown does not rewrite the receipt')
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('tool definitions pass the replicated registry contract and render JSON text', async () => {
  const core = makeCore()
  for (const [builder, toolName] of [
    [buildPrepareTool, 'ce_prepare_support'],
    [buildValidateTool, 'ce_validate_support_proposal'],
    [buildRecordTool, 'ce_record_support_outcome'],
    [buildAuditTool, 'ce_session_audit'],
  ]) {
    const tool = builder(core)
    assert.equal(tool.name, toolName)
    const rendered = tool.output.render({}, { demo: true })
    assert.deepEqual(rendered, [{ type: 'text', text: JSON.stringify({ demo: true }, null, 2) }])
  }
  const ctx = createFakeCtx()
  apply(ctx, {})
  const audit = await ctx._tools.get('ce_session_audit').execute(
    { authorization_ref: 'demo-host-scope-A' },
    {}
  )
  assert.equal(audit.scope_subject_ref, 'demo-learner-A')
  const aborted = new AbortController()
  aborted.abort()
  const cancelledPrepare = await ctx._tools.get('ce_prepare_support').execute(demoInput(), { signal: aborted.signal })
  assert.equal(cancelledPrepare.validation.status, 'aborted')
})
