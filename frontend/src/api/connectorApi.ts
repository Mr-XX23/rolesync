import api from './axiosInstance';

export interface ConnectResponse {
  status: string;
  source: string;
  user_id: string;
  trigger_id: string;
  redirect_url?: string | null;
  connection_state?: string;
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

export interface GmailConfig {
  max_emails_per_sync: number;
  categories: string[];
  sync_window_days: number;
  auto_sync_interval_minutes: number;
  sync_frequency?: string;
  max_attachment_size_mb: number;
  auto_sync_enabled?: boolean;
  webhook_enabled?: boolean;
}

export interface GmailConnectionDetails {
  connection_id: string;
  tenant_id: string;
  user_id: string;
  account_email: string;
  status: 'Available' | 'Configuration Required' | 'Connected' | 'Syncing' | 'Waiting for Next Auto Sync' | 'Up to Date' | 'Partial Success' | 'Failed' | 'Paused' | 'Disconnected';
  config: GmailConfig;
  backfill_state: {
    is_backfill_complete: boolean;
    oldest_synced_timestamp: string | null;
    next_page_token: string | null;
    total_eligible_discovered: number;
    total_synced_so_far: number;
  };
  lock: {
    is_locked: boolean;
    locked_by_job_id: string | null;
    locked_at: string | null;
    expires_at: string | null;
  };
  current_progress: string;
  webhook_trigger_id?: string | null;
  last_successful_sync_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface GmailStatusResponse {
  status: string;
  connection: GmailConnectionDetails;
}

export interface GmailActivityItem {
  message_id?: string;
  subject?: string;
  sender?: string;
  status: 'SUCCESS' | 'PARTIAL_SUCCESS' | 'SKIPPED' | 'FAILED';
  attachment_summary?: string;
  error_message?: string | null;
  file_id?: string;
  filename?: string;
  name?: string;
  mime_type?: string;
  file_size?: number;
  synced_at?: string;
}


export interface GmailActivity {
  activity_id: string;
  job_id: string;
  connection_id: string;
  tenant_id: string;
  trigger_type: 'INITIAL_SYNC' | 'AUTO_SYNC' | 'MANUAL_SYNC' | 'RESYNC' | 'WEBHOOK';
  status: 'RUNNING' | 'COMPLETED' | 'PARTIAL_SUCCESS' | 'FAILED';
  started_at: string;
  completed_at?: string | null;
  metrics: {
    total_discovered: number;
    processed: number;
    succeeded: number;
    skipped: number;
    failed: number;
  };
  items: GmailActivityItem[];
}

export interface GmailActivitiesResponse {
  status: string;
  connection_id: string;
  activities: GmailActivity[];
}

export const connectorApi = {
  connectSource: async (source: string, userId: string, callbackUrl?: string): Promise<ConnectResponse> => {
    const payload: { user_id: string; callback_url?: string } = {
      user_id: userId,
    };
    if (callbackUrl) {
      payload.callback_url = callbackUrl;
    }
    const response = await api.post<ConnectResponse>(`/connectors/${source}/connect`, payload);
    return response.data;
  },

  reconcileSource: async (source: string, tenantId: string, liveDocs: any[] = []): Promise<ReconcileResponse> => {
    const response = await api.post<ReconcileResponse>(`/connectors/${source}/reconcile`, {
      tenant_id: tenantId,
      live_docs: liveDocs,
    });
    return response.data;
  },

  // Unified Status API for All 5 Connectors
  getAllConnectorsStatus: async (userId: string = 'usr_active'): Promise<{ status: string; connections: Record<string, any> }> => {
    const response = await api.get<{ status: string; connections: Record<string, any> }>(`/connectors/status?user_id=${userId}`);
    return response.data;
  },

  // Gmail Specific APIs
  getGmailStatus: async (userId: string = 'usr_active'): Promise<GmailStatusResponse> => {
    const response = await api.get<GmailStatusResponse>(`/connectors/gmail/status?user_id=${userId}`);
    return response.data;
  },

  saveGmailConfig: async (
    userId: string,
    maxEmailsPerSync: number,
    categories: string[],
    syncWindowDays: number = 180,
    autoSyncIntervalMinutes: number = 30,
    syncFrequency: string = '30m'
  ): Promise<any> => {
    const response = await api.post(`/connectors/gmail/config`, {
      user_id: userId,
      max_emails_per_sync: maxEmailsPerSync,
      categories: categories,
      sync_window_days: syncWindowDays,
      auto_sync_interval_minutes: autoSyncIntervalMinutes,
      sync_frequency: syncFrequency,
    });
    return response.data;
  },

  updateAutoSyncSchedule: async (
    source: string,
    userId: string,
    syncFrequency: string,
    intervalMinutes?: number,
    autoSyncEnabled?: boolean,
    webhookEnabled?: boolean
  ): Promise<any> => {
    const response = await api.post(`/connectors/${source.toLowerCase()}/auto-sync`, {
      user_id: userId,
      sync_frequency: syncFrequency,
      interval_minutes: intervalMinutes,
      auto_sync_enabled: autoSyncEnabled,
      webhook_enabled: webhookEnabled,
    });
    return response.data;
  },

  triggerGmailSyncNow: async (userId: string = 'usr_active'): Promise<any> => {
    const response = await api.post(`/connectors/gmail/sync-now`, {
      user_id: userId,
    });
    return response.data;
  },

  triggerGmailResync: async (userId: string = 'usr_active'): Promise<any> => {
    const response = await api.post(`/connectors/gmail/resync`, {
      user_id: userId,
    });
    return response.data;
  },

  getGmailActivities: async (userId: string = 'usr_active', limit: number = 20): Promise<GmailActivitiesResponse> => {
    const response = await api.get<GmailActivitiesResponse>(`/connectors/gmail/activities?user_id=${userId}&limit=${limit}`);
    return response.data;
  },

  // Google Drive Specific APIs
  getGDriveStatus: async (userId: string = 'usr_active'): Promise<any> => {
    const response = await api.get<any>(`/connectors/gdrive/status?user_id=${userId}`);
    return response.data;
  },

  saveGDriveConfig: async (
    userId: string,
    maxFilesPerSync: number,
    categories: string[],
    autoSyncIntervalMinutes: number = 30,
    syncFrequency: string = '30m'
  ): Promise<any> => {
    const response = await api.post(`/connectors/gdrive/config`, {
      user_id: userId,
      max_files_per_sync: maxFilesPerSync,
      categories: categories,
      auto_sync_interval_minutes: autoSyncIntervalMinutes,
      sync_frequency: syncFrequency,
    });
    return response.data;
  },

  triggerGDriveSyncNow: async (userId: string = 'usr_active'): Promise<any> => {
    const response = await api.post(`/connectors/gdrive/sync-now`, {
      user_id: userId,
    });
    return response.data;
  },

  triggerGDriveResync: async (userId: string = 'usr_active'): Promise<any> => {
    const response = await api.post(`/connectors/gdrive/resync`, {
      user_id: userId,
    });
    return response.data;
  },

  getGDriveActivities: async (userId: string = 'usr_active', limit: number = 20): Promise<any> => {
    const response = await api.get<any>(`/connectors/gdrive/activities?user_id=${userId}&limit=${limit}`);
    return response.data;
  },

  getSourceActivities: async (source: string, userId: string = 'usr_active', limit: number = 20): Promise<GmailActivitiesResponse> => {
    const response = await api.get<GmailActivitiesResponse>(`/connectors/${source}/activities?user_id=${userId}&limit=${limit}`);
    return response.data;
  },

  disconnectGmail: async (userId: string = 'usr_active'): Promise<any> => {
    const response = await api.post(`/connectors/gmail/disconnect`, {
      user_id: userId,
    });
    return response.data;
  },

  disconnectSource: async (source: string, userId: string = 'usr_active'): Promise<any> => {
    const response = await api.post(`/connectors/${source}/disconnect`, {
      user_id: userId,
    });
    return response.data;
  },

  getSourceDataSummary: async (source: string, userId: string = 'usr_active'): Promise<any> => {
    const response = await api.get(`/connectors/${source}/data-summary?user_id=${userId}`);
    return response.data;
  },

  purgeSourceData: async (source: string, userId: string = 'usr_active'): Promise<any> => {
    const response = await api.delete(`/connectors/${source}/data?user_id=${userId}`);
    return response.data;
  },

};

export default connectorApi;
