/**
 * Tool definitions wiring the controlled core to the DSH tools registry
 * contract (@deepseek-ai/dsh-tools): name, description, parameters schema,
 * output { schema, render }, cooperative-cancel-aware execute.
 *
 * Plain definition objects are used on purpose: the installed host registry
 * accepts them and this keeps the plugin dependency-free, so `pnpm add
 * file:` installs fully offline.
 */

import {
  PROPOSAL_SCHEMA,
  RECORD_RECEIPT_SCHEMA,
  SESSION_AUDIT_SCHEMA,
  SUPPORT_INPUT_SCHEMA,
  SUPPORT_RESULT_SCHEMA,
} from './controlled-core.js'

const SYNTHETIC_NOTICE =
  'Synthetic seam-verification fixture (ChildEvidence Issue #13). demo-* data only; no real child, research or publication authority.'

function renderJson(_args, value) {
  return [{ type: 'text', text: JSON.stringify(value, null, 2) }]
}

export function buildPrepareTool(core) {
  return {
    name: 'ce_prepare_support',
    description: `${SYNTHETIC_NOTICE} Validate the unified support input (ce.support-input.draft-0.1) against the host-granted scope and demo methods; returns a structured SupportResult or a blocked result with a failure code.`,
    parameters: SUPPORT_INPUT_SCHEMA,
    output: { schema: SUPPORT_RESULT_SCHEMA, render: renderJson },
    execute(args, exec) {
      return core.prepareSupport(args, { signal: exec?.signal })
    },
  }
}

export function buildValidateTool(core) {
  return {
    name: 'ce_validate_support_proposal',
    description: `${SYNTHETIC_NOTICE} Validate a model-proposed action (limited vocabulary, demo method membership, revision match, prior-decline pause). Requires a prepared request from ce_prepare_support.`,
    parameters: PROPOSAL_SCHEMA,
    output: { schema: SUPPORT_RESULT_SCHEMA, render: renderJson },
    execute(args, exec) {
      return core.validateProposal(args, { signal: exec?.signal })
    },
  }
}

export function buildRecordTool(core) {
  return {
    name: 'ce_record_support_outcome',
    description: `${SYNTHETIC_NOTICE} Record the real outcome receipt for a validated action. Requires expected_revision (contracts.md §5 host-write concurrency check); idempotent per (request_id, action_id) — replays echo the original stored outcome; cancelled/failed/declined/unknown outcomes never write a success row. delay_ms is a verification-only cooperative-cancel knob (max 5000).`,
    parameters: {
      type: 'object',
      required: ['request_id', 'session_ref', 'subject_ref', 'authorization_ref', 'action_id', 'expected_revision', 'outcome'],
      properties: {
        request_id: { type: 'string' },
        session_ref: { type: 'string' },
        subject_ref: { type: 'string' },
        authorization_ref: { type: 'string' },
        action_id: { type: 'string' },
        expected_revision: { type: 'integer' },
        delay_ms: { type: 'integer' },
        outcome: {
          type: 'object',
          required: ['kind'],
          properties: {
            kind: { type: 'string', enum: ['executed', 'declined', 'failed', 'cancelled', 'unknown'] },
            detail: { type: 'string' },
          },
        },
      },
    },
    output: { schema: RECORD_RECEIPT_SCHEMA, render: renderJson },
    execute(args, exec) {
      return core.recordOutcome(args, { signal: exec?.signal })
    },
  }
}

export function buildAuditTool(core) {
  return {
    name: 'ce_session_audit',
    description: `${SYNTHETIC_NOTICE} Report the controlled calls this plugin observed for a session/request, filtered by the caller's host scope. Detects (never enforces) a request that bypassed the controlled entry.`,
    parameters: {
      type: 'object',
      required: ['authorization_ref'],
      properties: {
        authorization_ref: { type: 'string' },
        session_ref: { type: 'string' },
        request_id: { type: 'string' },
      },
    },
    output: { schema: SESSION_AUDIT_SCHEMA, render: renderJson },
    isConcurrencySafe() {
      return true
    },
    execute(args, exec) {
      return core.sessionAudit(args, { signal: exec?.signal })
    },
  }
}
