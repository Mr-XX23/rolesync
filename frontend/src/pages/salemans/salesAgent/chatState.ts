import type {
  AgentEvent,
  ApprovalStatus,
  PendingAction,
  SessionDetail,
  SessionStatus,
  TranscriptItem,
} from '../../../api/salesAgentApi';

/** An approval card: a write the agent is waiting on (or that was just decided). */
export interface ApprovalCardModel {
  id: string;
  tool: string;
  agent: string;
  args: Record<string, unknown>;
  preview: Record<string, unknown>;
  expiresAt: string;
  reason?: string;
  status: ApprovalStatus;
}

export interface ChatState {
  sessionId: string | null;
  status: SessionStatus | null;
  items: TranscriptItem[];
  draft: string; // assistant text streaming in right now
  step: string | null;
  approvals: ApprovalCardModel[];
  lastEventId: string | null;
  error: string | null;
}

export const emptyChat: ChatState = {
  sessionId: null,
  status: null,
  items: [],
  draft: '',
  step: null,
  approvals: [],
  lastEventId: null,
  error: null,
};

export type ChatAction =
  | { type: 'reset' }
  | { type: 'snapshot'; detail: SessionDetail }
  | { type: 'started'; sessionId: string; message: string }
  | { type: 'event'; event: AgentEvent }
  | { type: 'approval_decided'; action: PendingAction }
  | { type: 'failed'; message: string };

function fromPending(action: PendingAction): ApprovalCardModel {
  return {
    id: action.id,
    tool: action.tool,
    agent: action.agent,
    args: action.args,
    preview: action.preview,
    expiresAt: action.expires_at,
    status: action.status,
  };
}

function flushDraft(state: ChatState): ChatState {
  if (!state.draft.trim()) {
    return { ...state, draft: '' };
  }
  return { ...state, items: [...state.items, { kind: 'assistant', text: state.draft.trim() }], draft: '' };
}

function upsertApproval(approvals: ApprovalCardModel[], card: ApprovalCardModel): ApprovalCardModel[] {
  const others = approvals.filter((existing) => existing.id !== card.id);
  return [...others, card];
}

function applyEvent(state: ChatState, event: AgentEvent): ChatState {
  // Replayed events (at-least-once delivery around reconnects) are ignored by position.
  if (state.lastEventId && compareStreamIds(event.id, state.lastEventId) <= 0) {
    return state;
  }
  const next: ChatState = { ...state, lastEventId: event.id };
  const data = event.data || {};

  switch (event.type) {
    case 'step_started':
      return { ...next, status: 'RUNNING', step: String(data.step ?? 'working') };
    case 'token':
      if (data.reset) {
        return { ...next, draft: '' };
      }
      return { ...next, draft: next.draft + String(data.text ?? '') };
    case 'tool_call': {
      const flushed = flushDraft(next);
      return {
        ...flushed,
        step: `using ${data.tool ?? 'a tool'}`,
        items: [...flushed.items, { kind: 'tool_call', tool: data.tool, call_id: data.call_id, args: data.args }],
      };
    }
    case 'awaiting_approval':
      return {
        ...next,
        status: 'AWAITING_APPROVAL',
        step: null,
        approvals: upsertApproval(next.approvals, {
          id: String(data.pending_action_id),
          tool: String(data.tool),
          agent: String(data.agent),
          args: data.args ?? {},
          preview: data.preview ?? {},
          expiresAt: String(data.expires_at),
          reason: data.reason,
          status: 'PENDING',
        }),
      };
    case 'approval_resolved':
      return {
        ...next,
        status: 'RUNNING',
        approvals: next.approvals.map((card) =>
          card.id === String(data.pending_action_id) ? { ...card, status: data.status as ApprovalStatus } : card
        ),
      };
    case 'tool_result':
      return {
        ...next,
        items: [
          ...next.items,
          {
            kind: 'tool_result',
            tool: data.tool,
            call_id: data.call_id,
            outcome: data.outcome,
            summary: data.summary,
            error: data.error,
          },
        ],
      };
    case 'done': {
      const answer = String(data.final_answer ?? '').trim();
      const withDraft = next.draft.trim() ? flushDraft(next) : next;
      const lastItem = withDraft.items[withDraft.items.length - 1];
      const needsAnswer = answer && !(lastItem?.kind === 'assistant' && lastItem.text === answer);
      return {
        ...withDraft,
        status: 'DONE',
        step: null,
        items: needsAnswer ? [...withDraft.items, { kind: 'assistant', text: answer }] : withDraft.items,
        approvals: withDraft.approvals.filter((card) => card.status === 'PENDING'),
      };
    }
    case 'error':
      return { ...flushDraft(next), status: 'FAILED', step: null, error: String(data.message ?? 'The run failed') };
    default:
      return next;
  }
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'reset':
      return emptyChat;
    case 'snapshot':
      return {
        ...emptyChat,
        sessionId: action.detail.id,
        status: action.detail.status,
        items: action.detail.transcript,
        approvals: action.detail.pending_approvals.map(fromPending),
        lastEventId: action.detail.last_event_id,
      };
    case 'started':
      return {
        ...state,
        sessionId: action.sessionId,
        status: 'RUNNING',
        step: 'starting',
        error: null,
        draft: '',
        items: [...state.items, { kind: 'user', text: action.message }],
        approvals: state.approvals.filter((card) => card.status === 'PENDING'),
      };
    case 'event':
      if (action.event.session_id !== state.sessionId) {
        return state;
      }
      return applyEvent(state, action.event);
    case 'approval_decided':
      return {
        ...state,
        approvals: state.approvals.map((card) =>
          card.id === action.action.id ? { ...card, status: action.action.status } : card
        ),
      };
    case 'failed':
      return { ...state, error: action.message, step: null };
    default:
      return state;
  }
}

/** Redis stream ids look like `1726000000000-3`. */
export function compareStreamIds(a: string, b: string): number {
  const [aMs, aSeq] = a.split('-').map(Number);
  const [bMs, bSeq] = b.split('-').map(Number);
  return aMs === bMs ? aSeq - bSeq : aMs - bMs;
}
