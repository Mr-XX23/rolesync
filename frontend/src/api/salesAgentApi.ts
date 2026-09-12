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

/** A web page, message or document a read's facts came from. */
export interface SourceLink {
  title: string;
  url: string;
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
  sources?: SourceLink[] | null;
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
  | 'halted' // a safety limit stopped the turn; ends it like done
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
  reason?: string; // awaiting_approval; halted: which safety limit
  status?: string; // approval_resolved
  outcome?: string; // tool_result
  summary?: string | null;
  error?: string | null;
  sources?: SourceLink[]; // tool_result: pages a read used, or links to what a write created
  final_answer?: string; // done, halted
  message?: string; // error, halted
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

/** Something the agent saved on its own while working (app/api/memory.py). */
export interface MemoryFact {
  id: string;
  text: string;
  saved_at: string | null;
  saved_by_me: boolean;
}

/** What the agent remembers about the rep (private to them), a customer or a deal (shared by the workspace). */
export interface MemoryView {
  about: 'rep' | 'account' | 'deal';
  key: string;
  name: string | null;
  facts: MemoryFact[]; // newest first
  version: number;
  updated_at: string | null;
}

export interface RememberedAccount {
  key: string;
  name: string;
  facts: number;
  updated_at: string | null;
}

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
      // The rep's time zone lets the agent schedule meetings at the times they mean.
      { message, session_id: sessionId ?? null, time_zone: browserTimeZone() },
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

  repMemory: async (): Promise<MemoryView> => {
    const response = await api.get<MemoryView>(`${BASE}/memory/rep`, { headers: tenantHeaders() });
    return response.data;
  },

  listRememberedAccounts: async (query?: string): Promise<RememberedAccount[]> => {
    const response = await api.get<RememberedAccount[]>(`${BASE}/memory/accounts`, {
      params: query?.trim() ? { q: query.trim() } : undefined,
      headers: tenantHeaders(),
    });
    return response.data;
  },

  /** By the company's name as written on a deal, or by its key from the list. */
  accountMemory: async (company: string): Promise<MemoryView> => {
    const response = await api.get<MemoryView>(`${BASE}/memory/account`, { params: { company }, headers: tenantHeaders() });
    return response.data;
  },

  dealMemory: async (dealId: string): Promise<MemoryView> => {
    const response = await api.get<MemoryView>(`${BASE}/memory/deals/${encodeURIComponent(dealId)}`, { headers: tenantHeaders() });
    return response.data;
  },

  /** Delete one remembered fact; returns what is remembered afterwards. */
  forgetFact: async (memory: MemoryView, factId: string): Promise<MemoryView> => {
    const owner =
      memory.about === 'rep'
        ? 'rep'
        : memory.about === 'account'
          ? `accounts/${encodeURIComponent(memory.key)}`
          : `deals/${encodeURIComponent(memory.key)}`;
    const response = await api.delete<MemoryView>(`${BASE}/memory/${owner}/facts/${encodeURIComponent(factId)}`, {
      headers: tenantHeaders(),
    });
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

function browserTimeZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

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
