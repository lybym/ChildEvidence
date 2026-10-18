/**
 * ChildEvidence growth-support seam verification core (Issue #13).
 *
 * Pure, deterministic control logic for the three candidate support steps from
 * docs/design/growth-support-mvp/contracts.md §3 (prepare → validate → record)
 * plus a session audit tool. Synthetic only: every scope, subject, method and
 * record shipped in this file is a `demo-*` fixture. Nothing here grants real
 * publication eligibility, real research support or real child access.
 *
 * The core never interprets the child, never invents research support
 * (`evidence_refs` stays empty) and never lets an unknown condition pass as
 * true (contracts.md §1.2). Unknown values are preserved in the result.
 */

export const SUPPORT_INPUT_SCHEMA_VERSION = 'ce.support-input.draft-0.1'
export const SUPPORT_RESULT_SCHEMA_VERSION = 'ce.support-result.draft-0.1'
export const RECORD_RECEIPT_SCHEMA_VERSION = 'ce.support-record.draft-0.1'

export const ALLOWED_ACTION_KINDS = [
  'ask_clarification',
  'offer_choice',
  'explain_with_support',
  'propose_activity',
  'request_feedback',
  'pause',
  'suggest_human_help',
]

export const OBSERVATION_KINDS = [
  'child_self_report',
  'adult_report',
  'host_observation',
  'model_inference',
]

export const OUTCOME_KINDS = ['executed', 'declined', 'failed', 'cancelled', 'unknown']

export const SUPPORT_RESULT_STATUS = [
  'needs_information',
  'proposal_ready',
  'paused',
  'out_of_scope',
  'blocked',
  'degraded',
]

/**
 * JSON Schema subset used for registry-facing tool parameters and outputs.
 * Kept inside the subset enforced by the installed host (@deepseek-ai/dsh-tools
 * `assertSupportedJsonSchema`): type / properties / required / enum / items.
 */
export const SUPPORT_INPUT_SCHEMA = {
  type: 'object',
  required: ['schema_version', 'request_id', 'session_ref', 'actor', 'subject_ref', 'response_audience', 'intent'],
  properties: {
    schema_version: { type: 'string', enum: [SUPPORT_INPUT_SCHEMA_VERSION] },
    request_id: { type: 'string' },
    session_ref: { type: 'string' },
    actor: {
      type: 'object',
      required: ['role', 'principal_ref'],
      properties: {
        role: { type: 'string', enum: ['child', 'parent', 'teacher'] },
        principal_ref: { type: 'string' },
      },
    },
    subject_ref: { type: 'string' },
    response_audience: { type: 'string', enum: ['child', 'parent', 'teacher'] },
    authorization_ref: { type: 'string' },
    intent: { type: 'string' },
    task: { type: 'object' },
    observations: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'kind', 'statement', 'source_event_ref'],
        properties: {
          id: { type: 'string' },
          kind: { type: 'string', enum: OBSERVATION_KINDS },
          statement: { type: 'string' },
          source_event_ref: { type: 'string' },
        },
      },
    },
    input_quality: { type: 'object' },
    context_snapshot: { type: 'object' },
    state_revision: { type: 'integer' },
    capabilities: { type: 'object' },
    asset_lock: { type: 'object' },
  },
}

export const SUPPORT_RESULT_SCHEMA = {
  type: 'object',
  required: ['schema_version', 'request_id', 'status', 'validation', 'provenance'],
  properties: {
    schema_version: { type: 'string', enum: [SUPPORT_RESULT_SCHEMA_VERSION] },
    request_id: { type: 'string' },
    session_ref: { type: 'string' },
    subject_ref: { type: 'string' },
    status: { type: 'string', enum: SUPPORT_RESULT_STATUS },
    understanding: { type: 'object' },
    next_action: { type: 'object' },
    presentation_constraints: { type: 'object' },
    review_plan: { type: 'object' },
    validation: { type: 'object' },
    provenance: { type: 'object' },
  },
}

export const PROPOSAL_SCHEMA = {
  type: 'object',
  required: ['request_id', 'session_ref', 'subject_ref', 'authorization_ref', 'state_revision', 'proposal'],
  properties: {
    request_id: { type: 'string' },
    session_ref: { type: 'string' },
    subject_ref: { type: 'string' },
    authorization_ref: { type: 'string' },
    state_revision: { type: 'integer' },
    proposal: {
      type: 'object',
      required: ['action_id', 'action_kind', 'content', 'method_ref'],
      properties: {
        action_id: { type: 'string' },
        action_kind: { type: 'string' },
        content: { type: 'string' },
        method_ref: { type: 'string' },
      },
    },
    prior_decline: {
      type: 'object',
      properties: { declined: { type: 'boolean' } },
    },
  },
}

export const RECORD_RECEIPT_SCHEMA = {
  type: 'object',
  required: ['schema_version', 'request_id', 'action_id', 'subject_ref', 'receipt', 'validation'],
  properties: {
    schema_version: { type: 'string', enum: [RECORD_RECEIPT_SCHEMA_VERSION] },
    request_id: { type: 'string' },
    action_id: { type: 'string' },
    session_ref: { type: 'string' },
    subject_ref: { type: 'string' },
    receipt: {
      type: 'object',
      required: ['outcome_kind', 'success_written', 'idempotent'],
      properties: {
        outcome_kind: { type: 'string' },
        success_written: { type: 'boolean' },
        idempotent: { type: 'boolean' },
        record_count_for_subject: { type: 'integer' },
        revision_after: { type: 'integer' },
      },
    },
    validation: { type: 'object' },
  },
}

export const SESSION_AUDIT_SCHEMA = {
  type: 'object',
  required: ['scope_subject_ref', 'controlled_call_count', 'calls', 'uncontrolled_request_hint', 'validation'],
  properties: {
    scope_subject_ref: { type: 'string' },
    session_ref: { type: 'string' },
    request_id: { type: 'string' },
    controlled_call_count: { type: 'integer' },
    calls: { type: 'array' },
    uncontrolled_request_hint: { type: 'boolean' },
    validation: { type: 'object' },
  },
}

/** Demo-only defaults; overridable through the bundle patch / profile patch config. */
export const DEFAULT_CONFIG = {
  receipt_dir: null,
  authorized_scopes: [
    { scope_ref: 'demo-host-scope-A', subject_ref: 'demo-learner-A', allow: ['prepare', 'validate', 'record', 'audit'] },
    { scope_ref: 'demo-host-scope-B', subject_ref: 'demo-learner-B', allow: ['prepare', 'validate', 'record', 'audit'] },
    { scope_ref: 'demo-host-scope-A-observer', subject_ref: 'demo-learner-A', allow: ['prepare', 'audit'] },
  ],
  methods: [
    {
      ref: 'demo-method-clarify@1',
      basis_kind: 'design_choice',
      intents: ['help_with_current_task'],
      action_kinds: ['ask_clarification', 'offer_choice'],
      required_info: ['task_understanding'],
      unknowns: ['child_understanding_of_task', 'attempts_so_far'],
    },
    {
      ref: 'demo-method-explore@1',
      basis_kind: 'design_choice',
      intents: ['explore_interest'],
      action_kinds: ['offer_choice', 'request_feedback'],
      required_info: [],
      unknowns: ['interest_persistence_vs_novelty'],
    },
  ],
}

const ABORTED_VALIDATION = Object.freeze({
  status: 'aborted',
  purpose: 'synthetic_evaluation',
  eligible_for_real_user_delivery: false,
})

function passedValidation() {
  return { status: 'passed_structural_checks', purpose: 'synthetic_evaluation', eligible_for_real_user_delivery: false }
}

function failedValidation() {
  return { status: 'failed_structural_checks', purpose: 'synthetic_evaluation', eligible_for_real_user_delivery: false }
}

function supportResult({ requestId, sessionRef, subjectRef, status, understanding, nextAction, validation }) {
  const result = {
    schema_version: SUPPORT_RESULT_SCHEMA_VERSION,
    request_id: requestId,
    status,
    understanding: understanding ?? { observation_refs: [], candidate_explanations: [], unknowns: [] },
    validation: validation ?? passedValidation(),
    provenance: { pack_version: 'demo-only', basis_kind: 'design_choice', evidence_refs: [] },
  }
  if (sessionRef !== undefined) result.session_ref = sessionRef
  if (subjectRef !== undefined) result.subject_ref = subjectRef
  if (nextAction !== undefined) result.next_action = nextAction
  return result
}

function blockedResult(requestId, code, message, extra) {
  const result = supportResult({
    requestId,
    status: 'blocked',
    validation: { ...failedValidation(), failure_code: code, failure_message: message },
  })
  return Object.assign(result, extra ?? {})
}

function abortedResult(requestId, message) {
  return supportResult({
    requestId,
    status: 'blocked',
    understanding: { observation_refs: [], candidate_explanations: [], unknowns: [] },
    validation: { ...ABORTED_VALIDATION, failure_message: message },
  })
}

function isNonEmptyString(value) {
  return typeof value === 'string' && value.length > 0
}

function isPlainObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Abortable sleep used by the verification knobs. Resolves `false` when the
 * signal aborted, `true` after the delay. Never throws for cancellation.
 */
export function delayAbortably(ms, signal) {
  if (!Number.isInteger(ms) || ms <= 0) return Promise.resolve(true)
  if (signal?.aborted) return Promise.resolve(false)
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      cleanup()
      resolve(true)
    }, ms)
    const onAbort = () => {
      cleanup()
      resolve(false)
    }
    function cleanup() {
      clearTimeout(timer)
      signal?.removeEventListener?.('abort', onAbort)
    }
    signal?.addEventListener?.('abort', onAbort, { once: true })
  })
}

/**
 * Create a verification core instance. All state is in-memory and scoped to
 * the returned object; growth records for real hosts are owned by the host,
 * not by this plugin (contracts.md §5).
 */
export function createCore(mergedConfig) {
  const config = mergedConfig
  const scopes = new Map()
  for (const scope of config.authorized_scopes ?? []) {
    if (isNonEmptyString(scope.scope_ref)) scopes.set(scope.scope_ref, scope)
  }
  const methods = new Map()
  for (const method of config.methods ?? []) {
    if (isNonEmptyString(method.ref)) methods.set(method.ref, method)
  }
  /** request_id -> prepared request state */
  const requests = new Map()
  /** request_id -> validated proposal */
  const proposals = new Map()
  /** subject_ref -> array of outcome receipts */
  const recordsBySubject = new Map()
  /** chronological controlled-call log */
  const calls = []

  /** Resolve the caller's host-granted scope and required capability. */
  function resolveScope(authorizationRef, capability, requestId) {
    if (!isNonEmptyString(authorizationRef)) {
      return {
        error: blockedResult(
          requestId,
          'missing_authorization',
          'authorization_ref is required; a self-reported role never grants access (contracts.md §2)'
        ),
      }
    }
    const scope = scopes.get(authorizationRef)
    if (!scope) {
      return {
        error: blockedResult(
          requestId,
          'unknown_authorization_scope',
          `authorization_ref ${JSON.stringify(authorizationRef)} is not a scope granted by the host configuration`
        ),
      }
    }
    if (!(scope.allow ?? []).includes(capability)) {
      return {
        error: blockedResult(requestId, 'scope_not_permitted', `scope ${JSON.stringify(authorizationRef)} does not allow ${JSON.stringify(capability)}`),
      }
    }
    return { scope }
  }

  /** Returns `{ code, message }` for the first structural violation, else null. */
  function structuralInputChecks(input) {
    if (!isPlainObject(input)) return { code: 'invalid_input', message: 'input must be an object' }
    for (const field of SUPPORT_INPUT_SCHEMA.required) {
      if (input[field] === undefined) return { code: 'invalid_input', message: `missing required field: ${field}` }
    }
    if (input.schema_version !== SUPPORT_INPUT_SCHEMA_VERSION) {
      return {
        code: 'unsupported_schema_version',
        message: `unsupported schema_version: ${JSON.stringify(input.schema_version)} (expected ${SUPPORT_INPUT_SCHEMA_VERSION})`,
      }
    }
    for (const field of ['request_id', 'session_ref', 'subject_ref', 'intent']) {
      if (!isNonEmptyString(input[field])) return { code: 'invalid_input', message: `field ${field} must be a non-empty string` }
    }
    if (!isPlainObject(input.actor) || !isNonEmptyString(input.actor.principal_ref)) {
      return { code: 'invalid_input', message: 'actor.principal_ref must be a non-empty string' }
    }
    if (!['child', 'parent', 'teacher'].includes(input.actor.role)) {
      return { code: 'invalid_input', message: `actor.role ${JSON.stringify(input.actor?.role)} is not a known role` }
    }
    if (!['child', 'parent', 'teacher'].includes(input.response_audience)) {
      return { code: 'invalid_input', message: `response_audience ${JSON.stringify(input.response_audience)} is not a known audience` }
    }
    if (input.state_revision !== undefined && (!Number.isInteger(input.state_revision) || input.state_revision < 0)) {
      return { code: 'invalid_input', message: 'state_revision must be a non-negative integer' }
    }
    if (input.observations !== undefined) {
      if (!Array.isArray(input.observations)) return { code: 'invalid_input', message: 'observations must be an array' }
      for (const observation of input.observations) {
        if (!isPlainObject(observation)) return { code: 'invalid_input', message: 'each observation must be an object' }
        for (const field of ['id', 'kind', 'statement', 'source_event_ref']) {
          if (!isNonEmptyString(observation[field])) return { code: 'invalid_input', message: `observation.${field} must be a non-empty string` }
        }
      }
    }
    return null
  }

  /**
   * Step 1 — validate the unified input and return the structured result.
   * Enforces: schema version, host-granted scope binding, subject isolation,
   * observation vocabulary, unknown preservation, demo method coverage.
   */
  function prepareSupport(input, { signal } = {}) {
    if (signal?.aborted) {
      return Promise.resolve(abortedResult(input?.request_id, 'signal aborted before prepare'))
    }
    const structural = structuralInputChecks(input)
    if (structural) {
      return Promise.resolve(blockedResult(isPlainObject(input) ? input.request_id : undefined, structural.code, structural.message))
    }
    const scopeCheck = resolveScope(input.authorization_ref, 'prepare', input.request_id)
    if (scopeCheck.error) return Promise.resolve(scopeCheck.error)
    if (scopeCheck.scope.subject_ref !== input.subject_ref) {
      return Promise.resolve(
        blockedResult(
          input.request_id,
          'subject_scope_mismatch',
          `scope ${JSON.stringify(input.authorization_ref)} binds subject ${JSON.stringify(scopeCheck.scope.subject_ref)}, not ${JSON.stringify(input.subject_ref)}`
        )
      )
    }

    const unknowns = []
    const observationRefs = []
    for (const observation of input.observations ?? []) {
      observationRefs.push(observation.id)
      if (!OBSERVATION_KINDS.includes(observation.kind)) {
        unknowns.push(`observation ${observation.id} has unknown kind ${observation.kind} (preserved, not treated as evidence)`)
      }
    }
    const ambiguities = Array.isArray(input.input_quality?.ambiguities) ? input.input_quality.ambiguities : []

    const method = (config.methods ?? []).find((candidate) => (candidate.intents ?? []).includes(input.intent))
    if (!method) {
      calls.push({ kind: 'prepare', request_id: input.request_id, session_ref: input.session_ref, subject_ref: input.subject_ref, outcome: 'out_of_scope' })
      return Promise.resolve(
        supportResult({
          requestId: input.request_id,
          sessionRef: input.session_ref,
          subjectRef: input.subject_ref,
          status: 'out_of_scope',
          understanding: {
            observation_refs: observationRefs,
            candidate_explanations: [],
            unknowns: [...unknowns, `intent ${JSON.stringify(input.intent)} is outside the synthetic demo method scope`],
          },
        })
      )
    }

    requests.set(input.request_id, {
      session_ref: input.session_ref,
      subject_ref: input.subject_ref,
      scope_ref: input.authorization_ref,
      state_revision: input.state_revision ?? 0,
      method_ref: method.ref,
    })

    // Demo heuristic (synthetic only): unresolved ambiguities and missing demo
    // required info both lead to needs_information instead of a proposal.
    const missingInfo = (method.required_info ?? []).filter((item) => {
      if (item === 'task_understanding') {
        const taskContent = input.task?.content
        return !(typeof taskContent === 'string' && taskContent.length > 0)
      }
      return true
    })
    let status
    if (ambiguities.length > 0) {
      status = 'needs_information'
      unknowns.push(...ambiguities.map((item) => `ambiguity: ${item}`))
    } else if (missingInfo.length > 0) {
      status = 'needs_information'
      unknowns.push(...missingInfo.map((item) => `missing info: ${item}`))
    } else {
      status = 'proposal_ready'
    }

    calls.push({ kind: 'prepare', request_id: input.request_id, session_ref: input.session_ref, subject_ref: input.subject_ref, outcome: status })
    const result = supportResult({
      requestId: input.request_id,
      sessionRef: input.session_ref,
      subjectRef: input.subject_ref,
      status,
      understanding: {
        observation_refs: observationRefs,
        candidate_explanations: [],
        unknowns: [...(method.unknowns ?? []), ...unknowns],
      },
    })
    if (status === 'proposal_ready' || status === 'needs_information') {
      result.next_action = {
        kind: method.action_kinds[0],
        content: 'demo-placeholder: the model drafts the real content through the controlled flow',
        method_ref: method.ref,
      }
      result.presentation_constraints = { profile_ref: 'demo-profile@1', audience: input.response_audience }
      result.review_plan = { trigger: 'after_response', observe: ['对题目要求的表达（合成）'], on_decline: 'pause' }
    }
    return Promise.resolve(result)
  }

  /**
   * Step 3 — validate a model-proposed action against the controlled flow.
   * Enforces: prepare ran first, revision match, action vocabulary, method
   * membership, prior-decline pause, unknown preservation.
   */
  function validateProposal(args, { signal } = {}) {
    if (signal?.aborted) {
      return Promise.resolve(abortedResult(args?.request_id, 'signal aborted before validate'))
    }
    if (!isPlainObject(args) || !isNonEmptyString(args.request_id)) {
      return Promise.resolve(blockedResult(undefined, 'invalid_input', 'validate args must include request_id'))
    }
    const proposal = args.proposal
    if (!isPlainObject(proposal)) {
      return Promise.resolve(blockedResult(args.request_id, 'invalid_input', 'proposal must be an object'))
    }
    const scopeCheck = resolveScope(args.authorization_ref, 'validate', args.request_id)
    if (scopeCheck.error) return Promise.resolve(scopeCheck.error)
    if (scopeCheck.scope.subject_ref !== args.subject_ref) {
      return Promise.resolve(
        blockedResult(
          args.request_id,
          'subject_scope_mismatch',
          `scope ${JSON.stringify(args.authorization_ref)} binds subject ${JSON.stringify(scopeCheck.scope.subject_ref)}, not ${JSON.stringify(args.subject_ref)}`
        )
      )
    }

    const request = requests.get(args.request_id)
    if (!request) {
      return Promise.resolve(
        blockedResult(args.request_id, 'prepare_required', 'no prepared request for this request_id; the controlled flow starts at ce_prepare_support')
      )
    }
    if (args.subject_ref !== request.subject_ref || args.session_ref !== request.session_ref) {
      return Promise.resolve(blockedResult(args.request_id, 'subject_scope_mismatch', 'validate session/subject do not match the prepared request'))
    }
    if (args.state_revision !== request.state_revision) {
      return Promise.resolve(
        blockedResult(args.request_id, 'revision_conflict', `state_revision ${JSON.stringify(args.state_revision)} does not match prepared ${request.state_revision}`)
      )
    }
    if (!isNonEmptyString(proposal.action_id)) return Promise.resolve(blockedResult(args.request_id, 'invalid_input', 'proposal.action_id must be a non-empty string'))
    if (!isNonEmptyString(proposal.content)) return Promise.resolve(blockedResult(args.request_id, 'invalid_input', 'proposal.content must be a non-empty string'))
    if (!ALLOWED_ACTION_KINDS.includes(proposal.action_kind)) {
      const result = blockedResult(
        args.request_id,
        'unknown_action_kind',
        `action_kind ${JSON.stringify(proposal.action_kind)} is outside the limited action vocabulary (preserved, not executed)`
      )
      result.understanding.unknowns.push(`unknown action_kind: ${proposal.action_kind}`)
      return Promise.resolve(result)
    }
    const method = methods.get(proposal.method_ref)
    if (!method) {
      return Promise.resolve(
        blockedResult(args.request_id, 'unknown_method_ref', `method_ref ${JSON.stringify(proposal.method_ref)} is not a configured demo method (no fabricated support)`)
      )
    }
    if (!(method.action_kinds ?? []).includes(proposal.action_kind)) {
      return Promise.resolve(
        blockedResult(args.request_id, 'action_not_in_method', `method ${method.ref} does not allow action_kind ${JSON.stringify(proposal.action_kind)}`)
      )
    }

    if (args.prior_decline?.declined === true) {
      calls.push({ kind: 'validate', request_id: args.request_id, session_ref: args.session_ref, subject_ref: args.subject_ref, outcome: 'paused_prior_decline' })
      return Promise.resolve(
        supportResult({
          requestId: args.request_id,
          sessionRef: args.session_ref,
          subjectRef: args.subject_ref,
          status: 'paused',
          understanding: {
            observation_refs: [],
            candidate_explanations: [],
            unknowns: ['prior decline signal present; no proposal stored'],
          },
        })
      )
    }

    proposals.set(args.request_id, { ...proposal, subject_ref: args.subject_ref, session_ref: args.session_ref })
    calls.push({ kind: 'validate', request_id: args.request_id, session_ref: args.session_ref, subject_ref: args.subject_ref, outcome: 'proposal_ready' })
    return Promise.resolve(
      supportResult({
        requestId: args.request_id,
        sessionRef: args.session_ref,
        subjectRef: args.subject_ref,
        status: 'proposal_ready',
        understanding: {
          observation_refs: [],
          candidate_explanations: [{ id: 'demo-echo-proposal', statement: `demo echo of validated proposal ${proposal.action_id}`, status: 'unconfirmed' }],
          unknowns: [...(method.unknowns ?? [])],
        },
        nextAction: { kind: proposal.action_kind, content: proposal.content, method_ref: method.ref },
      })
    )
  }

  /**
   * Step 5 — record the real outcome receipt. Idempotent per
   * (request_id, action_id) — a replay returns the ORIGINAL stored outcome,
   * never the replayed claim; `expected_revision` performs the host-write
   * concurrency check from contracts.md §5; cancelled/failed/declined/unknown
   * outcomes are recorded without a success row; execution requires a
   * validated proposal.
   */
  async function recordOutcome(args, { signal } = {}) {
    if (signal?.aborted) {
      return blockedReceipt(args, 'aborted', ABORTED_VALIDATION)
    }
    if (!isPlainObject(args) || !isNonEmptyString(args.request_id) || !isNonEmptyString(args.action_id)) {
      return blockedReceipt(args, 'invalid_input')
    }
    const outcome = args.outcome
    if (!isPlainObject(outcome) || !OUTCOME_KINDS.includes(outcome.kind)) {
      return blockedReceipt(args, 'invalid_outcome_kind')
    }
    if (!Number.isInteger(args.expected_revision)) {
      return blockedReceipt(args, 'invalid_input')
    }
    const scopeCheck = resolveScope(args.authorization_ref, 'record', args.request_id)
    if (scopeCheck.error) return blockedReceipt(args, scopeCheck.error.validation.failure_code)
    if (scopeCheck.scope.subject_ref !== args.subject_ref) {
      return blockedReceipt(args, 'subject_scope_mismatch')
    }

    const request = requests.get(args.request_id)
    if (!request) return blockedReceipt(args, 'prepare_required')
    if (args.subject_ref !== request.subject_ref || args.session_ref !== request.session_ref) {
      return blockedReceipt(args, 'subject_scope_mismatch')
    }

    // Idempotent replay comes BEFORE the revision gate: an at-least-once
    // retry of an already-recorded (request_id, action_id) must return the
    // ORIGINAL receipt even when its expected_revision is now stale. A
    // replay writes nothing, so the §5 concurrency check keeps protecting
    // first writes only (round-2 review P2-1; contracts.md §3.5 重试必须幂等).
    const dedupKey = `${args.request_id}\u0000${args.action_id}`
    if (request.recordedKeys?.has(dedupKey)) {
      const existing = (recordsBySubject.get(args.subject_ref) ?? []).find((entry) => entry.dedup_key === dedupKey)
      calls.push({ kind: 'record', request_id: args.request_id, session_ref: args.session_ref, subject_ref: args.subject_ref, outcome: 'idempotent_replay' })
      // A replay echoes the ORIGINAL stored receipt; a differing outcome.kind
      // in the replayed call must not overwrite or contradict it (review P2-3).
      return receiptResult(args, existing?.receipt.outcome_kind ?? outcome.kind, {
        success_written: existing?.receipt.success_written ?? false,
        idempotent: true,
        record_count_for_subject: (recordsBySubject.get(args.subject_ref) ?? []).length,
        revision_after: request.state_revision,
      })
    }

    if (args.expected_revision !== request.state_revision) {
      return blockedReceipt(args, 'revision_conflict')
    }
    const proposal = proposals.get(args.request_id)
    if (!proposal) return blockedReceipt(args, 'unvalidated_outcome')
    if (proposal.action_id !== args.action_id) {
      return blockedReceipt(args, 'unknown_action_id')
    }

    if (args.delay_ms !== undefined) {
      if (!Number.isInteger(args.delay_ms) || args.delay_ms < 0 || args.delay_ms > 5000) {
        return blockedReceipt(args, 'invalid_delay_ms')
      }
      const completed = await delayAbortably(args.delay_ms, signal)
      if (!completed) return blockedReceipt(args, 'aborted', ABORTED_VALIDATION)
    }

    const success = outcome.kind === 'executed'
    request.recordedKeys ??= new Set()
    request.recordedKeys.add(dedupKey)
    if (success) request.state_revision += 1

    const subjectRecords = recordsBySubject.get(args.subject_ref) ?? []
    subjectRecords.push({
      dedup_key: dedupKey,
      receipt: {
        outcome_kind: outcome.kind,
        success_written: success,
        detail: typeof outcome.detail === 'string' ? outcome.detail : null,
      },
    })
    recordsBySubject.set(args.subject_ref, subjectRecords)

    calls.push({ kind: 'record', request_id: args.request_id, session_ref: args.session_ref, subject_ref: args.subject_ref, outcome: outcome.kind })
    return receiptResult(args, outcome.kind, {
      success_written: success,
      idempotent: false,
      record_count_for_subject: subjectRecords.length,
      revision_after: request.state_revision,
    })
  }

  /**
   * Blocked receipt: reports the caller-attributable truth only. Counters
   * are included only when a VERIFIED authorization covers the claimed
   * subject — a scope that exists, allows `record`, and binds exactly the
   * subject of the existing request. A self-reported `subject_ref` alone
   * never attributes (round-2 review P1-1): unauthorized paths omit the
   * counters entirely instead of disclosing another subject's state. The
   * top-level fields always satisfy RECORD_RECEIPT_SCHEMA, with `''` for
   * unclaimed strings (round-2 review P2-2).
   */
  function blockedReceipt(args, code, validationOverride) {
    const requestId = isPlainObject(args) && typeof args.request_id === 'string' ? args.request_id : ''
    const actionId = isPlainObject(args) && typeof args.action_id === 'string' ? args.action_id : ''
    const subjectRef = isPlainObject(args) && typeof args.subject_ref === 'string' ? args.subject_ref : ''
    const request = requestId !== '' ? requests.get(requestId) : undefined
    let attributable = false
    if (subjectRef !== '' && request !== undefined && request.subject_ref === subjectRef) {
      const scopeCheck = resolveScope(isPlainObject(args) ? args.authorization_ref : undefined, 'record', requestId)
      attributable = !scopeCheck.error && scopeCheck.scope.subject_ref === subjectRef
    }
    const receipt = {
      outcome_kind: 'blocked',
      success_written: false,
      idempotent: false,
    }
    if (attributable) {
      receipt.record_count_for_subject = (recordsBySubject.get(subjectRef) ?? []).length
      receipt.revision_after = request.state_revision
    }
    return {
      schema_version: RECORD_RECEIPT_SCHEMA_VERSION,
      request_id: requestId,
      action_id: actionId,
      subject_ref: subjectRef,
      receipt,
      validation: validationOverride ?? { ...failedValidation(), failure_code: code },
    }
  }

  function receiptResult(args, outcomeKind, receipt) {
    const inner = {
      outcome_kind: outcomeKind,
      success_written: receipt.success_written,
      idempotent: receipt.idempotent,
    }
    if (receipt.record_count_for_subject !== undefined) inner.record_count_for_subject = receipt.record_count_for_subject
    if (receipt.revision_after !== undefined) inner.revision_after = receipt.revision_after
    return {
      schema_version: RECORD_RECEIPT_SCHEMA_VERSION,
      request_id: args.request_id,
      action_id: args.action_id,
      session_ref: args.session_ref,
      subject_ref: args.subject_ref,
      receipt: inner,
      validation: passedValidation(),
    }
  }

  /**
   * Session audit. Reports only what the controlled tool seam observed. A
   * request_id with zero controlled calls gets `uncontrolled_request_hint`;
   * the audit can never see calls that never happened, so it detects — it
   * does not enforce — the controlled entry.
   */
  function sessionAudit(args, { signal } = {}) {
    if (signal?.aborted) {
      return Promise.resolve({
        scope_subject_ref: '',
        controlled_call_count: 0,
        calls: [],
        uncontrolled_request_hint: false,
        validation: ABORTED_VALIDATION,
      })
    }
    if (!isPlainObject(args)) args = {}
    const scopeCheck = resolveScope(args.authorization_ref, 'audit', args.request_id)
    if (scopeCheck.error) {
      return Promise.resolve({
        scope_subject_ref: '',
        controlled_call_count: 0,
        calls: [],
        uncontrolled_request_hint: false,
        validation: { ...failedValidation(), failure_code: scopeCheck.error.validation.failure_code },
      })
    }
    const scope = scopeCheck.scope
    const visible = calls.filter(
      (call) =>
        call.subject_ref === scope.subject_ref &&
        (args.session_ref === undefined || call.session_ref === args.session_ref) &&
        (args.request_id === undefined || call.request_id === args.request_id)
    )
    return Promise.resolve({
      scope_subject_ref: scope.subject_ref,
      session_ref: args.session_ref,
      request_id: args.request_id,
      controlled_call_count: visible.length,
      calls: visible.map((call, index) => ({ index, ...call })),
      uncontrolled_request_hint: args.request_id !== undefined && visible.length === 0,
      validation: passedValidation(),
    })
  }

  return {
    config,
    prepareSupport,
    validateProposal,
    recordOutcome,
    sessionAudit,
    /** Verification introspection — not exposed as a tool. */
    _state: { requests, proposals, recordsBySubject, calls },
  }
}
