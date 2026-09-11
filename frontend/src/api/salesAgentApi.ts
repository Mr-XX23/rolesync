import api from './axiosInstance';
import { getActiveTenantId } from './catalogApi';

// ============================================================================
// Types (mirror backend/sales-agent-engine app/api/*.py)
// ============================================================================

export type SessionStatus = 'RUNNING' | 'AWAITING_APPROVAL' | 'DONE' | 'FAILED' | 'HALTED';
export type ApprovalStatus = 'PENDING' | 'APPROVED' | 'EDITED' | 'REJECTED' | 'EXPIRED';

export interface SessionSummary {
  id: string;
  title: string | null;
  status: SessionStatus;
  mode: string;
  started_at: string;
  ended_at: string | null;
  workspace_context_id: string;
}

export interface TranscriptItem {
  kind: 'user' | 'assistant' | 'tool_call' | 'tool_result';
  text?: string | null;
  tool?: string | null;
  call_id?: string | null;
  args?: Record<string, unknown> | null;
  outcome?: string | null;
  summary?: string | null;
  error?: string | null;
}

export interface PendingAction {
  id: string;
  session_id: string;
  agent: string;
  tool: string;
  args: Record<string, unknown>;
  edited_args: Record<string, unknown> | null;
  preview: Record<string, unknown>;
  status: ApprovalStatus;
  expires_at: string;
  resolved_by: string | null;
  resolved_at: string | null;
  decision_note: string | null;
  created_at: string;
}

export interface SessionDetail extends SessionSummary {
  transcript: TranscriptItem[]; // as of the session's last pause or finish
  pending_approvals: PendingAction[];
  last_event_id: string; // follow events after this id to catch up from that point
}

export type AgentEventType =
  | 'user_message'
  | 'step_started'
  | 'token'
  | 'tool_call'
  | 'tool_result'
  | 'awaiting_approval'
  | 'approval_resolved'
  | 'progress'
  | 'done'
  | 'error';

/** Fields the engine puts in an event's `data`, by event type. */
export interface AgentEventData {
  step?: string; // step_started
  text?: string; // token, user_message
  reset?: boolean; // token: discard the partial answer (model failover)
  call_id?: string; // tool_call, tool_result, awaiting_approval
  agent?: string;
  tool?: string;
  args?: Record<string, unknown>;
  pending_action_id?: string; // awaiting_approval, approval_resolved
  preview?: Record<string, unknown>;
  expires_at?: string;
  reason?: string;
  status?: string; // approval_resolved
  outcome?: string; // tool_result
  summary?: string | null;
  error?: string | null;
  final_answer?: string; // done
  message?: string; // error
}

/** The SSE envelope: `{type, session_id, data, ts}`. */
export interface AgentEvent {
  id: string; // stream position, used to resume after a reconnect
  type: AgentEventType;
  session_id: string;
  data: AgentEventData;
  ts: string;
}

export type Decision = 'approve' | 'edit' | 'reject';

// ============================================================================
// API
// ============================================================================

const BASE = '/sales-agent';

function tenantHeaders() {
  return { 'X-Tenant-Id': getActiveTenantId() };
}

export const salesAgentApi = {
  startChat: async (message: string, sessionId?: string | null) => {
    const response = await api.post<{ session_id: string; status: SessionStatus; events_url: string }>(
      `${BASE}/chat`,
      { message, session_id: sessionId ?? null },
      { headers: tenantHeaders() }
    );
    return response.data;
  },

  listSessions: async (): Promise<SessionSummary[]> => {
    const response = await api.get<SessionSummary[]>(`${BASE}/sessions`, { headers: tenantHeaders() });
    return response.data;
  },

  getSession: async (sessionId: string): Promise<SessionDetail> => {
    const response = await api.get<SessionDetail>(`${BASE}/sessions/${sessionId}`, { headers: tenantHeaders() });
    return response.data;
  },

  decide: async (
    actionId: string,
    decision: Decision,
    options: { args?: Record<string, unknown>; note?: string } = {}
  ): Promise<PendingAction> => {
    const response = await api.post<PendingAction>(
      `${BASE}/approvals/${actionId}/decision`,
      { decision, args: options.args ?? null, note: options.note || null },
      { headers: tenantHeaders() }
    );
    return response.data;
  },

  /**
   * SSE URL for a session. EventSource cannot send custom headers; the engine takes the
   * workspace from the session itself and authenticates with the access_token cookie.
   */
  eventsUrl: (sessionId: string, afterEventId?: string | null): string => {
    const base = `${api.defaults.baseURL}${BASE}/sessions/${sessionId}/events`;
    return afterEventId ? `${base}?last_event_id=${encodeURIComponent(afterEventId)}` : base;
  },
};

/** Human-readable message for an engine error response. */
export function describeAgentError(error: unknown): string {
  const response = (error as { response?: { status?: number; data?: { message?: string } } })?.response;
  if (response?.status === 403) {
    return 'You are not a member of the active workspace. Pick or create a workspace first.';
  }
  if (response?.status === 429) {
    return response.data?.message || 'Too many agent runs are in progress. Try again shortly.';
  }
  return response?.data?.message || 'The sales agent could not be reached.';
}
