import api from './axiosInstance';
import { getActiveTenantId } from './catalogApi';

// ============================================================================
// Types (mirror backend/workspace-service dto/DealResponse.java, DealUpsertRequest.java)
// ============================================================================

export const DEAL_STAGES = ['PROSPECTING', 'QUALIFIED', 'PROPOSAL', 'NEGOTIATION', 'WON', 'LOST'] as const;
export type DealStage = (typeof DEAL_STAGES)[number];

export interface DealContact {
  name: string;
  email?: string | null;
  role?: string | null;
  phone?: string | null;
}

/** A quote sent for the deal. The sales agent links the quotes it creates. */
export interface DealQuote {
  number: string;
  total?: number | null;
  currency?: string | null;
  link?: string | null; // Google Drive, or a knowledge-vault page inside the app
  created_at?: string | null;
}

export interface Deal {
  deal_id: string;
  workspace_id: string;
  title: string;
  company: string;
  stage: DealStage;
  amount: number | null;
  currency: string | null;
  expected_close_date: string | null; // YYYY-MM-DD
  next_step: string | null;
  notes: string | null;
  contacts: DealContact[];
  quotes: DealQuote[];
  source: 'MANUAL' | 'AGENT'; // who created it
  owner_profile_id: string | null;
  owner_name: string | null;
  can_delete: boolean; // its owner, or a workspace owner or admin
  closed_at: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Every field of a deal: saving replaces the whole deal. */
export interface DealInput {
  title: string;
  company: string;
  stage: DealStage;
  amount: number | null;
  currency: string;
  expected_close_date: string | null;
  next_step: string | null;
  notes: string | null;
  contacts: DealContact[];
  quotes: DealQuote[];
}

export interface ListDealsParams {
  stage?: DealStage;
  q?: string;
  mine?: boolean;
  limit?: number;
}

// ============================================================================
// API
// ============================================================================

function dealsPath(): string {
  const workspaceId = getActiveTenantId();
  if (!workspaceId) {
    throw new Error('Pick or create a workspace first.');
  }
  return `/workspaces/${workspaceId}/deals`;
}

export const dealsApi = {
  list: async (params: ListDealsParams = {}): Promise<Deal[]> => {
    const response = await api.get<Deal[]>(dealsPath(), {
      params: { ...params, q: params.q?.trim() || undefined, mine: params.mine || undefined },
    });
    return response.data;
  },

  get: async (dealId: string): Promise<Deal> => {
    const response = await api.get<Deal>(`${dealsPath()}/${encodeURIComponent(dealId)}`);
    return response.data;
  },

  /**
   * Create a deal under a new id, or replace one. Pass the version the edit started from: if
   * someone (or the agent) saved the deal since, the server refuses with 409 instead of
   * overwriting their change.
   */
  save: async (dealId: string, input: DealInput, expectedVersion?: number): Promise<Deal> => {
    const response = await api.put<Deal>(`${dealsPath()}/${encodeURIComponent(dealId)}`, {
      ...input,
      expected_version: expectedVersion ?? null,
    });
    return response.data;
  },

  remove: async (dealId: string, expectedVersion: number): Promise<void> => {
    await api.delete(`${dealsPath()}/${encodeURIComponent(dealId)}`, { params: { expected_version: expectedVersion } });
  },
};

/** A new deal's id. The page may be served over plain http on a LAN, where crypto.randomUUID is unavailable. */
export function newDealId(): string {
  if (typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function isDealConflict(error: unknown): boolean {
  return (error as { response?: { status?: number } })?.response?.status === 409;
}

/** Human-readable message for a deals error response. */
export function describeDealError(error: unknown): string {
  const response = (error as { response?: { status?: number; data?: { message?: string } } })?.response;
  if (!response) {
    return error instanceof Error && error.message !== 'Network Error' ? error.message : 'Deals could not be reached.';
  }
  if (response.status === 403) {
    return response.data?.message || 'You can’t change deals in this workspace.';
  }
  return response.data?.message || 'Deals could not be reached.';
}
