import api from './axiosInstance';

export interface ConnectResponse {
  status: string;
  source: string;
  user_id: string;
  trigger_id: string;
  redirect_url?: string | null;
}

export interface ReconcileResponse {
  status: string;
  source: string;
  tenant_id: string;
  report: {
    total_checked: number;
    missed_deletions_found: number;
    acl_drift_found: number;
    corrections_applied: number;
  };
}

export const connectorApi = {
  connectSource: async (source: string, userId: string): Promise<ConnectResponse> => {
    const response = await api.post<ConnectResponse>(`/connectors/${source}/connect`, {
      user_id: userId,
    });
    return response.data;
  },

  reconcileSource: async (source: string, tenantId: string, liveDocs: any[] = []): Promise<ReconcileResponse> => {
    const response = await api.post<ReconcileResponse>(`/connectors/${source}/reconcile`, {
      tenant_id: tenantId,
      live_docs: liveDocs,
    });
    return response.data;
  },
};

export default connectorApi;
