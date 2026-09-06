import React, { useState, useMemo, useEffect, useRef } from 'react';
import {
  FolderOpen,
  FileText,
  MessageSquare as SlackIcon,
  Power,
  Search,
  Plus,
  Settings,
  HelpCircle,
  X,
  Loader2,
  ChevronRight,
  ShieldCheck,
  RefreshCw,
  AlertCircle,
  Calendar as CalendarIcon,
  Mail as MailIcon,
  Activity,
  Clock,
  CheckCircle2,
} from 'lucide-react';
import { Button } from '../../../components/common/Button';
import { Input } from '../../../components/common/Input';
import { useAppSelector } from '../../../store';
import { useToast } from '../../../context/ToastContext';
import { connectorApi, type GmailConnectionDetails } from '../../../api/connectorApi';
import { ConnectorConfigModal } from './ConnectorConfigModal';
import { GmailSyncActivityModal } from './GmailSyncActivityModal';
import { AutoSyncModal } from './AutoSyncModal';

interface Integration {
  id: string;
  name: string;
  category: 'CRM' | 'Storage' | 'Productivity' | 'Databases' | 'Communication';
  status: 'Connected' | 'Available' | 'Configuration Required' | 'Syncing' | 'Waiting for Next Auto Sync' | 'Up to Date' | 'Partial Success' | 'Failed' | 'Paused' | 'Disconnected';
  description: string;
  icon: React.ComponentType<any>;
  iconColor: string;
  bgColor: string;
  details: string;
  syncFrequency: string;
  autoSyncEnabled?: boolean;
  webhookEnabled?: boolean;
  syncCaptured: number;
  syncSuccess: number;
  syncSkipped: number;
  syncFailed: number;
  logoUrl: string;
  currentProgress?: string;
  isLocked?: boolean;
}

export const isConnectedState = (status: string) => {
  return [
    'Connected',
    'Syncing',
    'Waiting for Next Auto Sync',
    'Up to Date',
    'Partial Success',
  ].includes(status);
};

export const isAuthorizedState = (status: string) => {
  return [
    'Configuration Required',
    'Connected',
    'Syncing',
    'Waiting for Next Auto Sync',
    'Up to Date',
    'Partial Success',
  ].includes(status);
};

const getInitialConnectorState = (id: string, defaultStatus: Integration['status'] = 'Available'): {
  status: Integration['status'];
  currentProgress: string;
  syncFrequency: string;
  autoSyncEnabled: boolean;
  webhookEnabled: boolean;
  syncCaptured: number;
  details: any;
} => {
  try {
    const raw = localStorage.getItem(`rolesync_${id}_connection`);
    const isConnectedFlag = localStorage.getItem(`rolesync_${id}_connected`) === 'true';
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed?.status && parsed.status !== 'Disconnected') {
        const captured = parsed.backfill_state?.total_synced_so_far ?? 0;
        const autoEnabled = parsed.config?.auto_sync_enabled ?? false;
        const webhookActive = parsed.config?.webhook_enabled ?? false;
        let freq = 'OFF';
        if (autoEnabled && (parsed.config?.auto_sync_interval_minutes || 0) > 0) {
          const mins = parsed.config.auto_sync_interval_minutes;
          if (mins === 1440) freq = '24H (2 AM)';
          else if (mins === 360) freq = '6H AUTO';
          else if (mins === 60) freq = '1H AUTO';
          else if (mins === 2) freq = '2M AUTO';
          else freq = `${mins}M AUTO`;
        }
        return {
          status: parsed.status as any,
          currentProgress: parsed.current_progress || '',
          syncFrequency: freq,
          autoSyncEnabled: autoEnabled,
          webhookEnabled: webhookActive,
          syncCaptured: captured,
          details: parsed,
        };
      }
    }
    if (isConnectedFlag) {
      return {
        status: 'Connected',
        currentProgress: '',
        syncFrequency: 'OFF',
        autoSyncEnabled: false,
        webhookEnabled: false,
        syncCaptured: 0,
        details: null,
      };
    }
  } catch (e) {
    // ignore parse errors
  }
  return {
    status: defaultStatus,
    currentProgress: '',
    syncFrequency: 'OFF',
    autoSyncEnabled: false,
    webhookEnabled: false,
    syncCaptured: 0,
    details: null,
  };
};

export const ExternalConnector: React.FC = () => {
  const toast = useToast();
  const { user } = useAppSelector((state) => state.auth);
  const activeUserId = user?.userId || user?.email || 'usr_active';

  const initialGmail = getInitialConnectorState('gmail', 'Available');
  const initialGDrive = getInitialConnectorState('gdrive', 'Available');
  const initialCalendar = getInitialConnectorState('calendar', 'Available');
  const initialSlack = getInitialConnectorState('slack', 'Available');
  const initialNotion = getInitialConnectorState('notion', 'Available');

  // Real Production Connectors (Gmail, Google Drive, Google Calendar, Slack, Notion)
  const [integrations, setIntegrations] = useState<Integration[]>([
    {
      id: 'gmail',
      name: 'Gmail',
      category: 'Communication',
      status: initialGmail.status,
      description: 'Sync email threads, customer correspondence, and attachment transcripts into your vector workspace.',
      icon: MailIcon,
      iconColor: 'text-red-500',
      bgColor: 'bg-red-50 dark:bg-red-950/30 border-red-200/50 dark:border-red-800/30',
      details: 'Sync inbox messages, customer correspondence threads, and attachments.',
      syncFrequency: initialGmail.syncFrequency,
      syncCaptured: initialGmail.syncCaptured,
      syncSuccess: initialGmail.syncCaptured,
      syncSkipped: 0,
      syncFailed: 0,
      logoUrl: 'https://res.cloudinary.com/dkmhskfmq/image/upload/v1787482194/gmail.svg',
      currentProgress: initialGmail.currentProgress,
    },
    {
      id: 'gdrive',
      name: 'Google Drive',
      category: 'Storage',
      status: initialGDrive.status,
      description: 'Automated document synchronization to index spreadsheets, contract PDFs, and slides into your vector workspace.',
      icon: FolderOpen,
      iconColor: 'text-blue-500',
      bgColor: 'bg-blue-50 dark:bg-blue-950/30 border-blue-200/50 dark:border-blue-800/30',
      details: 'Sync team spreadsheets, presentation slides, and shared documents.',
      syncFrequency: initialGDrive.syncFrequency,
      syncCaptured: initialGDrive.syncCaptured,
      syncSuccess: initialGDrive.syncCaptured,
      syncSkipped: 0,
      syncFailed: 0,
      logoUrl: 'https://res.cloudinary.com/dkmhskfmq/image/upload/v1787482194/google-drive.svg',
    },
    {
      id: 'calendar',
      name: 'Google Calendar',
      category: 'Productivity',
      status: initialCalendar.status,
      description: 'Synchronize client demos, recurring sales reviews, and meeting agenda transcripts into contextual memory.',
      icon: CalendarIcon,
      iconColor: 'text-emerald-500',
      bgColor: 'bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200/50 dark:border-emerald-800/30',
      details: 'Sync scheduled calls, customer meet notes, and calendar events.',
      syncFrequency: initialCalendar.syncFrequency,
      syncCaptured: initialCalendar.syncCaptured,
      syncSuccess: initialCalendar.syncCaptured,
      syncSkipped: 0,
      syncFailed: 0,
      logoUrl: 'https://res.cloudinary.com/dkmhskfmq/image/upload/v1787482184/google-calendar.svg',
    },
    {
      id: 'slack',
      name: 'Slack',
      category: 'Communication',
      status: initialSlack.status,
      description: 'Capture inbound lead threads, sales alerts, and internal channel problem-solving discussions into vector context.',
      icon: SlackIcon,
      iconColor: 'text-amber-500',
      bgColor: 'bg-amber-50 dark:bg-amber-950/30 border-amber-200/50 dark:border-amber-800/30',
      details: 'Sync public discussions, deal discussions, and client support channels.',
      syncFrequency: initialSlack.syncFrequency,
      syncCaptured: initialSlack.syncCaptured,
      syncSuccess: initialSlack.syncCaptured,
      syncSkipped: 0,
      syncFailed: 0,
      logoUrl: 'https://res.cloudinary.com/dkmhskfmq/image/upload/v1787482194/slack.svg',
    },
    {
      id: 'notion',
      name: 'Notion',
      category: 'Productivity',
      status: initialNotion.status,
      description: 'Map internal wikis, database boards, and procedural guidepages directly into Legacydb context embeddings.',
      icon: FileText,
      iconColor: 'text-neutral-700 dark:text-neutral-300',
      bgColor: 'bg-neutral-50 dark:bg-neutral-900/30 border-neutral-200/50 dark:border-neutral-800/30',
      details: 'Sync workspace directories, page trees, and markdown blocks.',
      syncFrequency: initialNotion.syncFrequency,
      syncCaptured: initialNotion.syncCaptured,
      syncSuccess: initialNotion.syncCaptured,
      syncSkipped: 0,
      syncFailed: 0,
      logoUrl: 'https://res.cloudinary.com/dkmhskfmq/image/upload/v1787482194/notion.svg',
    },
  ]);

  // UI Control States
  const [activeTab, setActiveTab] = useState<string>('All');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [activeConfigConnector, setActiveConfigConnector] = useState<Integration | null>(null);
  const [activeAutoSyncConnector, setActiveAutoSyncConnector] = useState<Integration | null>(null);
  const [selectedActivityConnector, setSelectedActivityConnector] = useState<Integration | null>(null);
  const [showActivityModal, setShowActivityModal] = useState<boolean>(false);
  const [showEnterpriseModal, setShowEnterpriseModal] = useState<boolean>(false);

  const [gmailDetails, setGmailDetails] = useState<GmailConnectionDetails | null>(initialGmail.details);
  const [allConnections, setAllConnections] = useState<Record<string, any>>({});
  const [lockNotice, setLockNotice] = useState<string | null>(null);

  // Connection Simulation States
  const [connectingId, setConnectingId] = useState<string | null>(null);
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);
  const [isDisconnecting, setIsDisconnecting] = useState<boolean>(false);
  const [activeSyncingId, setActiveSyncingId] = useState<string | null>(null);

  // Popup and OAuth Event Listeners Ref
  const oauthPopupRef = useRef<Window | null>(null);
  const popupWatcherRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const hasHandledAuthSuccessRef = useRef<boolean>(false);

  // Form State inside modals
  const [enterpriseDatabase, setEnterpriseDatabase] = useState<string>('');
  const [enterpriseMessage, setEnterpriseMessage] = useState<string>('');
  const [isSubmittingEnterprise, setIsSubmittingEnterprise] = useState<boolean>(false);

  // Helper to open a centered OAuth popup window
  const openOAuthPopup = (url: string, title: string = 'RoleSyncConnectorOAuth') => {
    const width = 600;
    const height = 700;
    const left = window.screenX + (window.outerWidth - width) / 2;
    const top = window.screenY + (window.outerHeight - height) / 2;

    if (oauthPopupRef.current && !oauthPopupRef.current.closed) {
      oauthPopupRef.current.focus();
      return oauthPopupRef.current;
    }

    const popup = window.open(
      url,
      'RoleSyncConnectorOAuth',
      `width=${width},height=${height},left=${left},top=${top},scrollbars=yes,status=yes,resizable=yes`
    );
    oauthPopupRef.current = popup;
    return popup;
  };

  // Fetch real status for ALL 5 connectors from backend
  const fetchAllConnectorsStatus = async () => {
    try {
      const res = await connectorApi.getAllConnectorsStatus(activeUserId);
      if (res?.connections) {
        const conns = res.connections;
        setAllConnections(conns);

        const gConn = conns.gmail;
        if (gConn) {
          setGmailDetails(gConn);
          if (isConnectedState(gConn.status)) {
            localStorage.setItem('rolesync_gmail_connection', JSON.stringify(gConn));
            localStorage.setItem('rolesync_gmail_connected', 'true');
          } else if (gConn.status === 'Disconnected') {
            localStorage.removeItem('rolesync_gmail_connection');
            localStorage.removeItem('rolesync_gmail_connected');
          }
        }

        const gdConn = conns.gdrive;
        if (gdConn) {
          if (isConnectedState(gdConn.status)) {
            localStorage.setItem('rolesync_gdrive_connection', JSON.stringify(gdConn));
            localStorage.setItem('rolesync_gdrive_connected', 'true');
          } else if (gdConn.status === 'Disconnected') {
            localStorage.removeItem('rolesync_gdrive_connection');
            localStorage.removeItem('rolesync_gdrive_connected');
          }
        }


        // Clear local syncing lock if backend has completed sync
        if (activeSyncingId) {
          const activeConn = conns[activeSyncingId];
          if (activeConn && activeConn.status !== 'Syncing' && !activeConn.lock?.is_locked && !activeConn.is_locked) {
            setActiveSyncingId(null);
          }
        }

        setIntegrations((prev) =>
          prev.map((item) => {
            const liveConn = conns[item.id];
            if (liveConn) {
              const isConn = isConnectedState(liveConn.status);
              const captured = liveConn.backfill_state?.total_synced_so_far ?? liveConn.sync_captured ?? 0;
              const isItemSyncing = liveConn.status === 'Syncing' || activeSyncingId === item.id;

              // Determine formatted sync frequency label
              let freqDisplay = 'OFF';
              const autoEnabled = liveConn.config?.auto_sync_enabled ?? false;
              const webhookActive = liveConn.config?.webhook_enabled ?? false;

              if ((isConn || liveConn.status === 'Configuration Required') && autoEnabled) {
                const interval = liveConn.config?.auto_sync_interval_minutes;
                const freqStr = (liveConn.config?.sync_frequency || liveConn.sync_frequency || '').toLowerCase();
                if (freqStr === 'off' || interval === 0) {
                  freqDisplay = 'OFF';
                } else if (freqStr === '24h' || interval === 1440) {
                  freqDisplay = '24H (2 AM)';
                } else if (freqStr === '6h' || interval === 360) {
                  freqDisplay = '6H AUTO';
                } else if (freqStr === '1h' || interval === 60) {
                  freqDisplay = '1H AUTO';
                } else if (freqStr === '2m' || interval === 2) {
                  freqDisplay = '2M AUTO';
                } else if (freqStr === '30m' || interval === 30) {
                  freqDisplay = '30M AUTO';
                } else if (interval && interval > 0) {
                  freqDisplay = `${interval}M AUTO`;
                } else {
                  freqDisplay = 'OFF';
                }
              }

              return {
                ...item,
                status: (isItemSyncing ? 'Syncing' : liveConn.status) as any,
                currentProgress: liveConn.current_progress || '',
                isLocked: liveConn.lock?.is_locked || liveConn.is_locked || false,
                syncCaptured: captured,
                syncSuccess: captured,
                syncFrequency: freqDisplay,
                autoSyncEnabled: autoEnabled,
                webhookEnabled: webhookActive,
              };
            }
            return item;
          })
        );
      }
    } catch (err) {
      console.warn('[ExternalConnector] Could not poll all connectors status:', err);
    }
  };

  // Listen for OAuth completion from popup callback window
  useEffect(() => {
    const handleAuthMessage = async (event: MessageEvent) => {
      if (event.data?.type === 'ROLESYNC_CONNECTOR_AUTH_SUCCESS') {
        if (hasHandledAuthSuccessRef.current) return;
        hasHandledAuthSuccessRef.current = true;

        let rawSource = (
          event.data.source ||
          sessionStorage.getItem('rolesync_oauth_connecting_source') ||
          localStorage.getItem('rolesync_oauth_connecting_source') ||
          connectingId ||
          ''
        ).toLowerCase().trim();

        if (rawSource === 'googledrive' || rawSource === 'google_drive') {
          rawSource = 'gdrive';
        } else if (rawSource === 'googlecalendar' || rawSource === 'google_calendar') {
          rawSource = 'calendar';
        }

        const sourceId = rawSource || 'gdrive';
        console.log(`[Frontend] Received OAuth authorization success for ${sourceId}, activeUserId=${activeUserId}`);

        sessionStorage.removeItem('rolesync_oauth_connecting_source');
        localStorage.removeItem('rolesync_oauth_connecting_source');

        // 1. Clean up popup & polling watcher
        if (popupWatcherRef.current) {
          clearInterval(popupWatcherRef.current);
          popupWatcherRef.current = null;
        }
        if (oauthPopupRef.current && !oauthPopupRef.current.closed) {
          oauthPopupRef.current.close();
        }
        oauthPopupRef.current = null;
        setConnectingId(null);

        // 2. Immediately reflect post-authorization state in UI and fetch latest backend status
        setIntegrations((prev) =>
          prev.map((c) => (c.id === sourceId ? { ...c, status: 'Configuration Required' } : c))
        );
        await fetchAllConnectorsStatus();

        // 3. Open Configuration Modal for the specific authorized connector
        const matchedItem = integrations.find((i) => i.id === sourceId);
        if (matchedItem) {
          setActiveConfigConnector({
            ...matchedItem,
            status: 'Configuration Required',
          });
          toast.success(
            `${matchedItem.name} connected successfully! Please choose your synchronization preferences.`,
            'Authorization Complete'
          );
        }
      }
    };


    window.addEventListener('message', handleAuthMessage);
    return () => {
      window.removeEventListener('message', handleAuthMessage);
      if (popupWatcherRef.current) {
        clearInterval(popupWatcherRef.current);
      }
    };
  }, [connectingId, integrations]);

  // Determine if any connector is actively syncing or in OAuth popup flow
  const isAnySyncingOrConnecting = useMemo(() => {
    return (
      Boolean(connectingId) ||
      Boolean(activeSyncingId) ||
      integrations.some((item) => item.status === 'Syncing')
    );
  }, [connectingId, activeSyncingId, integrations]);

  // Adaptive status polling: fast (3s) during sync/connect, relaxed (45s) when idle, paused when tab is hidden
  useEffect(() => {
    fetchAllConnectorsStatus();

    let intervalId: ReturnType<typeof setInterval> | null = null;

    const startAdaptivePolling = () => {
      if (intervalId) {
        clearInterval(intervalId);
        intervalId = null;
      }
      if (typeof document !== 'undefined' && document.hidden) {
        return;
      }
      const pollDelay = isAnySyncingOrConnecting ? 3000 : 45000;
      intervalId = setInterval(() => {
        if (typeof document !== 'undefined' && document.hidden) return;
        fetchAllConnectorsStatus();
      }, pollDelay);
    };

    const handleVisibilityChange = () => {
      if (typeof document !== 'undefined' && !document.hidden) {
        fetchAllConnectorsStatus();
        startAdaptivePolling();
      } else {
        if (intervalId) {
          clearInterval(intervalId);
          intervalId = null;
        }
      }
    };

    startAdaptivePolling();
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibilityChange);
    }

    return () => {
      if (intervalId) clearInterval(intervalId);
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibilityChange);
      }
    };
  }, [activeUserId, isAnySyncingOrConnecting]);

  // Dynamic stats calculated from active integrations
  const connectedCount = useMemo(() => {
    return integrations.filter(
      (item) =>
        item.status === 'Connected' ||
        item.status === 'Up to Date' ||
        item.status === 'Waiting for Next Auto Sync' ||
        item.status === 'Syncing' ||
        item.status === 'Partial Success'
    ).length;
  }, [integrations]);

  const totalIndexedFiles = useMemo(() => {
    return integrations
      .filter((item) => isConnectedState(item.status))
      .reduce((acc, item) => acc + (item.syncCaptured || 0), 0);
  }, [integrations]);

  // Filter & Search Logic
  const filteredIntegrations = useMemo(() => {
    return integrations.filter((item) => {
      const matchesTab = activeTab === 'All' || item.category === activeTab;
      const matchesSearch =
        item.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.description.toLowerCase().includes(searchQuery.toLowerCase());
      return matchesTab && matchesSearch;
    });
  }, [integrations, activeTab, searchQuery]);

  // Connect Source via API Gateway & Composio OAuth with Popup
  const handleToggleConnection = async (item: Integration) => {
    const { id, status: currentStatus } = item;

    if (currentStatus === 'Syncing' || activeSyncingId === id) {
      toast.warning('A sync is currently in progress. Please wait for synchronization to finish.', 'Sync In Progress');
      return;
    }

    if (id === 'gmail') {
      if (currentStatus === 'Available' || currentStatus === 'Disconnected') {
        hasHandledAuthSuccessRef.current = false;
        setConnectingId('gmail');
        sessionStorage.setItem('rolesync_oauth_connecting_source', 'gmail');
        localStorage.setItem('rolesync_oauth_connecting_source', 'gmail');
        try {
          const callbackUrl = `${window.location.origin}/connectors/callback?source=gmail`;
          const res = await connectorApi.connectSource('gmail', activeUserId, callbackUrl);

          if (res.redirect_url) {
            const popup = openOAuthPopup(res.redirect_url);

            // Start polling watcher to detect popup closure or completion fallback
            if (popupWatcherRef.current) clearInterval(popupWatcherRef.current);
            let pollCount = 0;
            popupWatcherRef.current = setInterval(async () => {
              pollCount += 1;
              if (!popup || popup.closed) {
                if (popupWatcherRef.current) clearInterval(popupWatcherRef.current);
                popupWatcherRef.current = null;
                oauthPopupRef.current = null;
                setConnectingId(null);

                // If handleAuthMessage already handled it, do nothing
                if (hasHandledAuthSuccessRef.current) {
                  return;
                }

                // Check final status upon close
                try {
                  const statusRes = await connectorApi.getGmailStatus(activeUserId);
                  if (statusRes?.connection && isAuthorizedState(statusRes.connection.status)) {
                    hasHandledAuthSuccessRef.current = true;
                    await fetchAllConnectorsStatus();
                    if (statusRes.connection.status === 'Configuration Required') {
                      setActiveConfigConnector({
                        ...item,
                        status: 'Configuration Required',
                      });
                    }
                    toast.success(
                      'Gmail authorized successfully! Please configure your sync preferences.',
                      'Authorization Complete'
                    );
                  } else {
                    setIntegrations((prev) =>
                      prev.map((c) => (c.id === 'gmail' ? { ...c, status: 'Available' } : c))
                    );
                    await fetchAllConnectorsStatus();
                  }
                } catch {
                  setIntegrations((prev) =>
                    prev.map((c) => (c.id === 'gmail' ? { ...c, status: 'Available' } : c))
                  );
                }
                return;
              }

              // Periodic status check fallback (every 3 seconds up to 90s)
              if (pollCount % 2 === 0) {
                if (hasHandledAuthSuccessRef.current) {
                  if (popupWatcherRef.current) clearInterval(popupWatcherRef.current);
                  popupWatcherRef.current = null;
                  return;
                }

                try {
                  const statusRes = await connectorApi.getGmailStatus(activeUserId);
                  if (statusRes?.connection && isAuthorizedState(statusRes.connection.status)) {
                    hasHandledAuthSuccessRef.current = true;
                    if (popupWatcherRef.current) clearInterval(popupWatcherRef.current);
                    popupWatcherRef.current = null;
                    if (popup && !popup.closed) popup.close();
                    oauthPopupRef.current = null;
                    setConnectingId(null);
                    await fetchAllConnectorsStatus();
                    if (statusRes.connection.status === 'Configuration Required') {
                      setActiveConfigConnector({
                        ...item,
                        status: 'Configuration Required',
                      });
                    }
                    toast.success(
                      'Gmail authorized successfully! Please configure your sync preferences.',
                      'Authorization Complete'
                    );
                  }
                } catch {
                  // Ignore transient network errors during poll
                }
              }
            }, 1500);
          }
        } catch (err: any) {
          console.error('[Frontend] Gmail connect error:', err);
          toast.error('Failed to initiate Gmail connection. Please try again.', 'Connection Error');
          setConnectingId(null);
        }
      } else if (currentStatus === 'Configuration Required') {
        setActiveConfigConnector(item);
      } else {
        setDisconnectingId('gmail');
      }
      return;
    }

    if (id === 'gdrive') {
      if (currentStatus === 'Available' || currentStatus === 'Disconnected') {
        hasHandledAuthSuccessRef.current = false;
        setConnectingId('gdrive');
        sessionStorage.setItem('rolesync_oauth_connecting_source', 'gdrive');
        localStorage.setItem('rolesync_oauth_connecting_source', 'gdrive');
        try {
          const callbackUrl = `${window.location.origin}/connectors/callback?source=gdrive`;
          const res = await connectorApi.connectSource('gdrive', activeUserId, callbackUrl);

          if (res.redirect_url) {
            const popup = openOAuthPopup(res.redirect_url);

            if (popupWatcherRef.current) clearInterval(popupWatcherRef.current);
            let pollCount = 0;
            popupWatcherRef.current = setInterval(async () => {
              pollCount += 1;
              if (!popup || popup.closed) {
                if (popupWatcherRef.current) clearInterval(popupWatcherRef.current);
                popupWatcherRef.current = null;
                oauthPopupRef.current = null;
                setConnectingId(null);

                if (hasHandledAuthSuccessRef.current) {
                  return;
                }

                try {
                  const statusRes = await connectorApi.getGDriveStatus(activeUserId);
                  if (statusRes?.connection && isAuthorizedState(statusRes.connection.status)) {
                    hasHandledAuthSuccessRef.current = true;
                    await fetchAllConnectorsStatus();
                    if (statusRes.connection.status === 'Configuration Required') {
                      setActiveConfigConnector({
                        ...item,
                        status: 'Configuration Required',
                      });
                    }
                    toast.success(
                      'Google Drive authorized successfully! Please configure your sync preferences.',
                      'Authorization Complete'
                    );
                  } else {
                    setIntegrations((prev) =>
                      prev.map((c) => (c.id === 'gdrive' ? { ...c, status: 'Available' } : c))
                    );
                    await fetchAllConnectorsStatus();
                  }
                } catch {
                  setIntegrations((prev) =>
                    prev.map((c) => (c.id === 'gdrive' ? { ...c, status: 'Available' } : c))
                  );
                }
                return;
              }

              if (pollCount % 2 === 0) {
                if (hasHandledAuthSuccessRef.current) {
                  if (popupWatcherRef.current) clearInterval(popupWatcherRef.current);
                  popupWatcherRef.current = null;
                  return;
                }

                try {
                  const statusRes = await connectorApi.getGDriveStatus(activeUserId);
                  if (statusRes?.connection && isAuthorizedState(statusRes.connection.status)) {
                    hasHandledAuthSuccessRef.current = true;
                    if (popupWatcherRef.current) clearInterval(popupWatcherRef.current);
                    popupWatcherRef.current = null;
                    if (popup && !popup.closed) popup.close();
                    oauthPopupRef.current = null;
                    setConnectingId(null);
                    await fetchAllConnectorsStatus();
                    if (statusRes.connection.status === 'Configuration Required') {
                      setActiveConfigConnector({
                        ...item,
                        status: 'Configuration Required',
                      });
                    }
                    toast.success(
                      'Google Drive authorized successfully! Please configure your sync preferences.',
                      'Authorization Complete'
                    );
                  }
                } catch {}
              }
            }, 1500);
          }
        } catch (err: any) {
          console.error('[Frontend] Google Drive connect error:', err);
          toast.error('Failed to initiate Google Drive connection. Please try again.', 'Connection Error');
          setConnectingId(null);
        }
      } else if (currentStatus === 'Configuration Required') {
        setActiveConfigConnector(item);
      } else {
        setDisconnectingId('gdrive');
      }
      return;
    }


    if (currentStatus === 'Available' || currentStatus === 'Disconnected') {
      setConnectingId(id);
      sessionStorage.setItem('rolesync_oauth_connecting_source', id);
      localStorage.setItem('rolesync_oauth_connecting_source', id);
      try {
        const callbackUrl = `${window.location.origin}/connectors/callback?source=${id}`;
        const res = await connectorApi.connectSource(id, activeUserId, callbackUrl);

        if (res.redirect_url) {
          const popup = openOAuthPopup(res.redirect_url);

          if (popupWatcherRef.current) clearInterval(popupWatcherRef.current);
          popupWatcherRef.current = setInterval(async () => {
            if (!popup || popup.closed) {
              if (popupWatcherRef.current) clearInterval(popupWatcherRef.current);
              popupWatcherRef.current = null;
              oauthPopupRef.current = null;
              setConnectingId(null);
              setIntegrations((prev) =>
                prev.map((c) => (c.id === id ? { ...c, status: 'Available' } : c))
              );
              await fetchAllConnectorsStatus();
            }
          }, 1500);
        }
      } catch (err: any) {
        console.error(`[Frontend] Connection failed for ${id}:`, err);
        toast.error(`Failed to initiate ${item.name} connection. Please try again.`, 'Connection Error');
        setConnectingId(null);
      }
    } else if (currentStatus === 'Configuration Required') {
      setActiveConfigConnector(item);
    } else {
      setDisconnectingId(id);
    }
  };

  // Confirm Disconnection Action (Revokes OAuth Token in Backend and Resets State)
  const confirmDisconnection = async () => {
    if (!disconnectingId || isDisconnecting) return;
    const targetId = disconnectingId;
    const targetItem = integrations.find((i) => i.id === targetId);
    if (targetItem?.status === 'Syncing' || activeSyncingId === targetId) {
      toast.warning('Cannot disconnect while a sync is in progress. Please wait for synchronization to finish.', 'Sync In Progress');
      setDisconnectingId(null);
      return;
    }
    setIsDisconnecting(true);

    try {
      // 1. Call backend API to revoke & invalidate OAuth token in Composio
      if (targetId === 'gmail') {
        await connectorApi.disconnectGmail(activeUserId);
        await fetchAllConnectorsStatus();
      } else {
        await connectorApi.disconnectSource(targetId, activeUserId);
      }

      // 2. Wipe local cached credentials and connection flags
      localStorage.removeItem(`rolesync_${targetId}_connection`);
      localStorage.removeItem(`rolesync_${targetId}_connected`);

      // 3. Reset frontend UI state to Available
      setIntegrations((prev) =>
        prev.map((item) =>
          item.id === targetId
            ? {
                ...item,
                status: 'Available',
                syncCaptured: 0,
                syncSuccess: 0,
                syncSkipped: 0,
                syncFailed: 0,
                currentProgress: '',
              }
            : item
        )
      );

      toast.info(`Disconnected ${targetId}. Saved vector memories remain preserved.`, 'Connector Disconnected');
      setDisconnectingId(null);
    } catch (err) {
      console.error(`[Frontend] Failed to disconnect ${targetId}:`, err);
      toast.error(`Failed to disconnect ${targetId}. Please try again.`, 'Disconnect Failed');
    } finally {
      setIsDisconnecting(false);
    }
  };

  // Trigger Manual Sync Now
  const triggerManualSync = async (id: string) => {
    setActiveSyncingId(id);
    setLockNotice(null);

    // Optimistically reflect 'Syncing' status immediately on the connector card
    setIntegrations((prev) =>
      prev.map((c) =>
        c.id === id
          ? {
              ...c,
              status: 'Syncing',
              currentProgress: c.currentProgress || 'Syncing...',
            }
          : c
      )
    );

    if (id === 'gmail') {
      try {
        await connectorApi.triggerGmailSyncNow(activeUserId);
        toast.info('Manual sync batch started for Gmail.', 'Sync Initiated');
        await fetchAllConnectorsStatus();
      } catch (err: any) {
        setActiveSyncingId(null);
        if (err?.response?.status === 409) {
          const msg = 'Your Gmail data is currently being processed. Please wait a moment before starting another sync.';
          setLockNotice(msg);
          toast.warning(msg, 'Sync In Progress');
        } else {
          console.error('[Frontend] Gmail manual sync error:', err);
          toast.error(err?.message || 'Failed to start Gmail sync.', 'Sync Failed');
        }
        await fetchAllConnectorsStatus();
      }
      return;
    }

    if (id === 'gdrive') {
      try {
        await connectorApi.triggerGDriveSyncNow(activeUserId);
        toast.info('Manual sync batch started for Google Drive.', 'Sync Initiated');
        await fetchAllConnectorsStatus();
      } catch (err: any) {
        setActiveSyncingId(null);
        if (err?.response?.status === 409) {
          const msg = 'Your Google Drive data is currently being processed. Please wait a moment before starting another sync.';
          setLockNotice(msg);
          toast.warning(msg, 'Sync In Progress');
        } else {
          console.error('[Frontend] GDrive manual sync error:', err);
          toast.error(err?.message || 'Failed to start Google Drive sync.', 'Sync Failed');
        }
        await fetchAllConnectorsStatus();
      }
      return;
    }

    try {
      await connectorApi.reconcileSource(id, 'tenant_default');
      toast.info(`Reconciliation sync started for ${id}.`, 'Sync Initiated');
      await fetchAllConnectorsStatus();
    } catch (err: any) {
      setActiveSyncingId(null);
      console.error(`[Frontend] Manual sync failed for ${id}:`, err);
      toast.error(`Sync failed for ${id}.`, 'Sync Failed');
      await fetchAllConnectorsStatus();
    }
  };

  // Universal Save Connector Configuration
  const handleSaveConnectorConfig = async (maxItems: number, categories: string[], syncFreq: string = 'REALTIME') => {
    if (!activeConfigConnector) return;
    const connId = activeConfigConnector.id;

    localStorage.setItem(`rolesync_${connId}_connected`, 'true');
    setIntegrations((prev) =>
      prev.map((item) =>
        item.id === connId
          ? {
              ...item,
              status: 'Syncing',
              syncFrequency: syncFreq.toUpperCase(),
            }
          : item
      )
    );
    setActiveSyncingId(connId);

    if (connId === 'gmail') {
      try {
        await connectorApi.saveGmailConfig(activeUserId, maxItems, categories);
        await fetchAllConnectorsStatus();
        toast.info('Initial synchronization initiated. Processing email batch in background...', 'Syncing Started');
      } catch (err: any) {
        console.error('[Frontend] Save Gmail config error:', err);
        toast.error('Failed to start sync. Please try again.', 'Sync Error');
        setActiveSyncingId(null);
        await fetchAllConnectorsStatus();
      }
    } else if (connId === 'gdrive') {
      try {
        await connectorApi.saveGDriveConfig(activeUserId, maxItems, categories);
        await fetchAllConnectorsStatus();
        toast.info('Initial synchronization initiated. Processing Google Drive documents in background...', 'Syncing Started');
      } catch (err: any) {
        console.error('[Frontend] Save GDrive config error:', err);
        toast.error('Failed to start sync. Please try again.', 'Sync Error');
        setActiveSyncingId(null);
        await fetchAllConnectorsStatus();
      }
    }
  };


  // Dedicated Save Auto-Sync Schedule & Webhooks Trigger
  const handleSaveAutoSyncSchedule = async (
    freq: string,
    intervalMinutes: number,
    autoSyncEnabled: boolean,
    webhookEnabled: boolean
  ) => {
    if (!activeAutoSyncConnector) return;
    const connId = activeAutoSyncConnector.id;

    await connectorApi.updateAutoSyncSchedule(
      connId,
      activeUserId,
      freq,
      intervalMinutes,
      autoSyncEnabled,
      webhookEnabled
    );

    let displayFreq = 'OFF';
    if (autoSyncEnabled && freq !== 'off') {
      if (freq === '24h') displayFreq = '24H (2 AM)';
      else if (freq === '6h') displayFreq = '6H AUTO';
      else if (freq === '1h') displayFreq = '1H AUTO';
      else if (freq === '2m') displayFreq = '2M AUTO';
      else displayFreq = '30M AUTO';
    }

    setIntegrations((prev) =>
      prev.map((item) =>
        item.id === connId
          ? {
              ...item,
              syncFrequency: displayFreq,
              autoSyncEnabled,
              webhookEnabled,
            }
          : item
      )
    );
    await fetchAllConnectorsStatus();
  };

  // Send Enterprise Integration Request
  const dispatchEnterpriseRequest = (e: React.FormEvent) => {
    e.preventDefault();
    if (!enterpriseDatabase || !enterpriseMessage) return;

    setIsSubmittingEnterprise(true);
    setTimeout(() => {
      setIsSubmittingEnterprise(false);
      setShowEnterpriseModal(false);
      setEnterpriseDatabase('');
      setEnterpriseMessage('');
      alert('Enterprise pipeline request cataloged! Our database team will verify connectivity rules.');
    }, 1800);
  };

  const renderStatusBadge = (item: Integration) => {
    const isConnected = isConnectedState(item.status);
    const isConnecting = connectingId === item.id;
    const isSyncing = item.status === 'Syncing' || activeSyncingId === item.id;

    if (isConnecting) {
      return (
        <span className="flex items-center gap-1 text-[10px] font-mono font-bold tracking-wider uppercase border px-2.5 py-1 rounded-full bg-primary/10 border-primary/30 text-primary">
          <Loader2 className="w-2.5 h-2.5 animate-spin text-primary" />
          <span>Verifying...</span>
        </span>
      );
    }

    if (isSyncing) {
      const isProgressRatio = Boolean(
        item.currentProgress &&
        /\d+\s*(of|\/)\s*\d+/i.test(item.currentProgress)
      );

      return (
        <span className="flex items-center gap-1.5 text-[10px] font-mono font-bold tracking-wider uppercase border px-2.5 py-1 rounded-full bg-primary/10 border-primary/30 text-primary animate-pulse">
          <Loader2 className="w-2.5 h-2.5 animate-spin text-primary" />
          <span>{isProgressRatio ? `Syncing (${item.currentProgress})` : 'Syncing...'}</span>
        </span>
      );
    }

    if (item.status === 'Configuration Required') {
      return (
        <button
          onClick={() => setActiveConfigConnector(item)}
          className="text-[10px] font-mono font-bold tracking-wider uppercase border px-2.5 py-1 rounded-full bg-amber-500/10 border-amber-500/30 text-amber-600 dark:text-amber-400 hover:bg-amber-500/20 cursor-pointer transition-all"
        >
          Setup Required
        </button>
      );
    }

    if (isConnected) {
      return (
        <button
          onClick={() => setDisconnectingId(item.id)}
          title="Click to disconnect"
          className="text-[10px] font-mono font-bold tracking-wider uppercase border px-3 py-1 rounded-full bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400 hover:bg-destructive/10 hover:border-destructive/30 hover:text-destructive cursor-pointer transition-all flex items-center gap-1.5 shadow-2xs"
        >
          <CheckCircle2 className="w-3 h-3 text-emerald-500" />
          <span>Connected</span>
        </button>
      );
    }

    return (
      <button
        onClick={() => handleToggleConnection(item)}
        className="text-[10px] font-mono font-bold tracking-wider uppercase border px-2.5 py-1 rounded-full bg-muted border-border hover:border-primary text-muted-foreground hover:text-foreground hover:bg-background cursor-pointer transition-all"
      >
        Available
      </button>
    );
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500 pb-16 relative">
      {/* Lock Notice Banner */}
      {lockNotice && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 flex items-center justify-between gap-3 text-xs font-semibold text-amber-600 dark:text-amber-400 animate-in slide-in-from-top-2">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 shrink-0" />
            <span>{lockNotice}</span>
          </div>
          <button onClick={() => setLockNotice(null)} className="p-1 rounded hover:bg-amber-500/20 cursor-pointer">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Header section */}
      <section className="flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
        <div className="space-y-2">
          <h2 className="font-serif text-3xl font-bold text-primary">Data Connectors</h2>
          <p className="text-sm text-muted-foreground max-w-xl leading-relaxed">
            Synchronize external databases, CRM profiles, and corporate communication transcripts directly into Legacydb context embeddings.
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => setShowEnterpriseModal(true)}
          icon={<Plus className="w-4 h-4 text-primary" />}
          className="w-full md:w-auto text-xs py-2.5 px-4 font-semibold"
        >
          Request Custom Connector
        </Button>
      </section>

      {/* Stats bar */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-card border border-border p-4 rounded-xl shadow-2xs flex justify-between items-center">
          <div>
            <p className="text-[10px] font-mono text-muted-foreground uppercase font-bold tracking-wider">active pipelines</p>
            <h4 className="text-lg font-bold text-foreground mt-1">
              {connectedCount > 0 ? `${connectedCount} Live Connector${connectedCount === 1 ? '' : 's'}` : 'No Active Connectors'}
            </h4>
          </div>
          <span className={`w-2.5 h-2.5 rounded-full ${connectedCount > 0 ? 'bg-emerald-500 animate-pulse' : 'bg-muted-foreground/40'}`}></span>
        </div>
        <div className="bg-card border border-border p-4 rounded-xl shadow-2xs flex justify-between items-center">
          <div>
            <p className="text-[10px] font-mono text-muted-foreground uppercase font-bold tracking-wider">synchronization scope</p>
            <h4 className="text-lg font-bold text-foreground mt-1">
              {totalIndexedFiles.toLocaleString()} Total Items Synced
            </h4>
          </div>
          <FolderOpen className="w-5 h-5 text-primary" />
        </div>
        <div className="bg-card border border-border p-4 rounded-xl shadow-2xs flex justify-between items-center">
          <div>
            <p className="text-[10px] font-mono text-muted-foreground uppercase font-bold tracking-wider">secure channels</p>
            <h4 className="text-lg font-bold text-foreground mt-1">
              {connectedCount > 0 ? 'OAuth2 & LlamaParse Active' : 'OAuth2 Channels Standby'}
            </h4>
          </div>
          <ShieldCheck className={`w-5 h-5 ${connectedCount > 0 ? 'text-primary' : 'text-muted-foreground/60'}`} />
        </div>
      </div>

      {/* Filter and search bar */}
      <div className="flex flex-col md:flex-row gap-4 justify-between items-center border-b border-border/40 pb-6">
        {/* Category Tabs */}
        <div className="flex flex-wrap items-center gap-1.5 bg-muted p-1 rounded-xl border border-border/60 w-full md:w-auto">
          {['All', 'CRM', 'Storage', 'Productivity', 'Databases', 'Communication'].map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
                activeTab === tab
                  ? 'bg-card text-foreground shadow-2xs border border-border/40'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Live Search */}
        <div className="relative w-full md:max-w-xs flex items-center">
          <Search className="absolute left-3.5 text-muted-foreground/60 w-4 h-4 pointer-events-none" />
          <input
            type="text"
            placeholder="Search active connectors..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-background border border-border rounded-xl pl-10 pr-4 py-2.5 text-xs font-medium focus:outline-none focus:ring-1 focus:ring-primary shadow-2xs"
          />
        </div>
      </div>

      {/* Grid of integrations cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredIntegrations.map((item) => {
          const Icon = item.icon;
          const isConnected = isConnectedState(item.status);
          const isConnecting = connectingId === item.id;
          const isSyncing = item.status === 'Syncing' || activeSyncingId === item.id;

          return (
            <div
              key={item.id}
              className={`group bg-card border rounded-2xl p-5 text-left flex flex-col justify-between transition-all duration-300 hover:-translate-y-1 hover:shadow-md ${
                isConnected
                  ? 'border-primary/30 shadow-2xs'
                  : 'border-border hover:border-primary/20'
              }`}
            >
              <div>
                {/* Logo and Status Badge */}
                <div className="flex justify-between items-start mb-5">
                  <div className={`w-11 h-11 rounded-xl flex items-center justify-center border shadow-3xs overflow-hidden ${item.bgColor}`}>
                    {item.logoUrl ? (
                      <img src={item.logoUrl} alt={item.name} className="w-6 h-6 object-contain" />
                    ) : (
                      <Icon className={`w-5 h-5 ${item.iconColor}`} />
                    )}
                  </div>

                  {renderStatusBadge(item)}
                </div>

                {/* Typography */}
                <h3 className="font-serif text-base font-bold text-foreground mb-1 group-hover:text-primary transition-colors flex items-center justify-between">
                  <span>{item.name}</span>
                  {item.id === 'gmail' && gmailDetails?.backfill_state?.is_backfill_complete && (
                    <span className="text-[9px] font-mono font-semibold px-2 py-0.5 bg-emerald-500/10 text-emerald-600 rounded-full border border-emerald-500/20">
                      Webhook Live
                    </span>
                  )}
                </h3>
                <p className="text-[10px] font-mono text-muted-foreground/80 uppercase font-bold tracking-wider mb-3">
                  {item.category}
                </p>
                <p className="text-xs leading-relaxed text-muted-foreground mb-6">
                  {item.description}
                </p>
              </div>

              {/* Bottom Triggers: FREQUENCY, CAPTURED & Action Buttons */}
              <div className="pt-4 border-t border-border/40 flex items-center justify-between gap-2 mt-auto">
                {isConnected ? (
                  <>
                    <div className="flex items-center gap-4">
                      {/* Metric 1: FREQUENCY (Clickable to open dedicated Auto-Sync modal) */}
                      <button
                        type="button"
                        disabled={isSyncing}
                        onClick={() => !isSyncing && setActiveAutoSyncConnector(item)}
                        className={`flex flex-col text-left group/freq ${
                          isSyncing ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'
                        }`}
                        title={
                          isSyncing
                            ? 'Auto-sync schedule can be adjusted after synchronization completes'
                            : 'Click to configure Auto-Sync Schedule (2m, 30m, 1h, 6h, 24h at 2am)'
                        }
                      >
                        <span className="text-[8px] font-mono font-bold text-muted-foreground uppercase tracking-widest flex items-center gap-1 group-hover/freq:text-primary transition-colors">
                          <span>FREQUENCY</span>
                          <Clock className="w-2.5 h-2.5 opacity-60 group-hover/freq:opacity-100" />
                          {item.webhookEnabled && (
                            <span className="text-[8px] px-1 py-0.2 rounded bg-amber-500/20 text-amber-500 font-bold" title="Real-Time Webhook Active">
                              HOOK
                            </span>
                          )}
                        </span>
                        <span className={`text-[11px] font-mono font-bold uppercase mt-0.5 group-hover/freq:underline ${
                          item.syncFrequency === 'OFF' ? 'text-muted-foreground' : 'text-amber-500 dark:text-amber-400'
                        }`}>
                          {item.syncFrequency}
                        </span>
                      </button>

                      {/* Metric 2: CAPTURED (Total Real Synced Data) */}
                      <div className="flex flex-col pl-3 border-l border-border/60">
                        <span className="text-[8px] font-mono font-bold text-muted-foreground uppercase tracking-widest">
                          CAPTURED
                        </span>
                        <span
                          className="text-[11px] font-mono font-bold text-emerald-600 dark:text-emerald-400 mt-0.5 cursor-pointer hover:underline"
                          title={`${item.syncSuccess} Success · ${item.syncSkipped} Skipped · ${item.syncFailed} Failed`}
                          onClick={() => {
                            setSelectedActivityConnector(item);
                            setShowActivityModal(true);
                          }}
                        >
                          {item.syncCaptured} Items
                        </span>
                      </div>
                    </div>

                    {/* Action Buttons: 1. Sync Now, 2. Auto-Sync Schedule, 3. Sync Activity Logs, 4. Configure, 5. Disconnect */}
                    <div className="flex items-center gap-1.5">
                      {/* 1. Sync Now Button */}
                      <button
                        onClick={() => triggerManualSync(item.id)}
                        disabled={isSyncing}
                        aria-label={`Sync Now for ${item.name}`}
                        className={`w-8 h-8 rounded-full border border-border bg-background/80 flex items-center justify-center transition-all shadow-3xs ${
                          isSyncing
                            ? 'text-primary border-primary/40 bg-primary/5 cursor-not-allowed'
                            : 'text-muted-foreground hover:text-foreground hover:bg-muted cursor-pointer'
                        }`}
                        title={isSyncing ? `Syncing in progress for ${item.name}...` : "Sync Now (Process Next Batch)"}
                      >
                        <RefreshCw className={`w-3.5 h-3.5 ${isSyncing ? 'animate-spin text-primary' : ''}`} />
                      </button>

                      {/* 3. Sync Activity / Captured Audit Logs */}
                      <button
                        onClick={() => {
                          setSelectedActivityConnector(item);
                          setShowActivityModal(true);
                        }}
                        aria-label={`View Sync Activity and Audit Logs for ${item.name}`}
                        className="w-8 h-8 rounded-full border border-border bg-background/80 hover:bg-muted flex items-center justify-center text-muted-foreground hover:text-foreground transition-all cursor-pointer shadow-3xs"
                        title="View Sync Activity & Audit Logs"
                      >
                        <Activity className="w-3.5 h-3.5 text-primary" />
                      </button>

                      {/* 4. Configure & Settings Button */}
                      <button
                        onClick={() => !isSyncing && setActiveConfigConnector(item)}
                        disabled={isSyncing}
                        aria-label={`Configure ${item.name} Settings and Limits`}
                        className={`w-8 h-8 rounded-full border border-border bg-background/80 flex items-center justify-center text-muted-foreground transition-all shadow-3xs ${
                          isSyncing
                            ? 'opacity-40 cursor-not-allowed pointer-events-none'
                            : 'hover:bg-muted hover:text-foreground cursor-pointer'
                        }`}
                        title={isSyncing ? 'Settings disabled while syncing' : `Configure ${item.name} Limits & Scopes`}
                      >
                        <Settings className="w-3.5 h-3.5" />
                      </button>

                      {/* 5. Disconnect Button */}
                      <button
                        onClick={() => !isSyncing && setDisconnectingId(item.id)}
                        disabled={isSyncing}
                        aria-label={`Disconnect ${item.name}`}
                        className={`w-8 h-8 rounded-full border border-border bg-background/80 flex items-center justify-center text-muted-foreground transition-all shadow-3xs ${
                          isSyncing
                            ? 'opacity-40 cursor-not-allowed pointer-events-none'
                            : 'hover:bg-destructive/10 hover:border-destructive/30 hover:text-destructive cursor-pointer'
                        }`}
                        title={isSyncing ? 'Disconnect disabled while syncing' : `Disconnect ${item.name}`}
                      >
                        <Power className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </>
                ) : isConnecting ? (
                  <>
                    <span className="text-[10px] text-muted-foreground/80 font-mono flex items-center gap-1.5">
                      <Loader2 className="w-2.5 h-2.5 animate-spin text-primary" /> Authorizing in popup...
                    </span>
                    <button
                      disabled
                      className="text-xs font-semibold text-muted-foreground/60 cursor-not-allowed flex items-center gap-0.5"
                    >
                      <span>Waiting for Auth</span>
                    </button>
                  </>
                ) : item.status === 'Configuration Required' ? (
                  <>
                    <span className="text-[10px] text-amber-600 dark:text-amber-400 font-mono font-semibold">Config Required</span>
                    <button
                      onClick={() => setActiveConfigConnector(item)}
                      className="text-xs font-bold text-primary hover:underline flex items-center gap-0.5 cursor-pointer"
                    >
                      <span>Complete Setup</span>
                      <ChevronRight className="w-3 h-3" />
                    </button>
                  </>
                ) : (
                  <>
                    <span className="text-[10px] text-muted-foreground/60 font-mono">Authentication Required</span>
                    <button
                      onClick={() => handleToggleConnection(item)}
                      disabled={isConnecting}
                      className="text-xs font-bold text-primary hover:underline flex items-center gap-0.5 cursor-pointer"
                    >
                      <span>Setup Connection</span>
                      <ChevronRight className="w-3 h-3" />
                    </button>
                  </>
                )}
              </div>
            </div>
          );
        })}

        {filteredIntegrations.length === 0 && (
          <div className="col-span-full bg-muted/20 border border-border border-dashed p-12 text-center rounded-2xl space-y-3">
            <AlertCircle className="w-8 h-8 text-muted-foreground/60 mx-auto" />
            <h4 className="font-serif text-base font-bold text-foreground">No matching connectors found</h4>
            <p className="text-xs text-muted-foreground max-w-sm mx-auto">
              Refine your active search filters or check another category. Alternatively, request a custom integration.
            </p>
          </div>
        )}
      </div>

      {/* DEDICATED AUTO-SYNC SCHEDULE MODAL */}
      {activeAutoSyncConnector && (
        <AutoSyncModal
          isOpen={Boolean(activeAutoSyncConnector)}
          onClose={() => setActiveAutoSyncConnector(null)}
          connectorId={activeAutoSyncConnector.id}
          connectorName={activeAutoSyncConnector.name}
          logoUrl={activeAutoSyncConnector.logoUrl}
          currentFrequency={activeAutoSyncConnector.syncFrequency}
          initialAutoSyncEnabled={
            activeAutoSyncConnector.autoSyncEnabled ??
            allConnections[activeAutoSyncConnector.id]?.config?.auto_sync_enabled ??
            (activeAutoSyncConnector.id === 'gmail' ? gmailDetails?.config?.auto_sync_enabled : false) ??
            false
          }
          initialWebhookEnabled={
            activeAutoSyncConnector.webhookEnabled ??
            allConnections[activeAutoSyncConnector.id]?.config?.webhook_enabled ??
            (activeAutoSyncConnector.id === 'gmail' ? gmailDetails?.config?.webhook_enabled : false) ??
            false
          }
          isLocked={
            Boolean(allConnections[activeAutoSyncConnector.id]?.lock?.is_locked) ||
            (activeAutoSyncConnector.id === 'gmail' ? gmailDetails?.lock?.is_locked || false : false)
          }
          isConnected={isConnectedState(activeAutoSyncConnector.status)}
          onSaveSchedule={handleSaveAutoSyncSchedule}
        />
      )}

      {/* DYNAMIC UNIVERSAL CONNECTOR CONFIGURATION MODAL (FOR ALL 5 SOURCES) */}
      {activeConfigConnector && (
        <ConnectorConfigModal
          isOpen={Boolean(activeConfigConnector)}
          onClose={() => setActiveConfigConnector(null)}
          onOpenAutoSyncModal={() => {
            const target = activeConfigConnector;
            setActiveConfigConnector(null);
            setActiveAutoSyncConnector(target);
          }}
          onSave={handleSaveConnectorConfig}
          connectorId={activeConfigConnector.id}
          connectorName={activeConfigConnector.name}
          logoUrl={activeConfigConnector.logoUrl}
          initialMaxItems={
            allConnections[activeConfigConnector.id]?.config?.max_emails_per_sync ||
            allConnections[activeConfigConnector.id]?.config?.max_files_per_sync ||
            (activeConfigConnector.id === 'gmail' ? gmailDetails?.config?.max_emails_per_sync : undefined) ||
            10
          }
          initialCategories={
            allConnections[activeConfigConnector.id]?.config?.categories ||
            (activeConfigConnector.id === 'gmail'
              ? gmailDetails?.config?.categories || ['INBOX']
              : activeConfigConnector.id === 'gdrive'
              ? ['MY_DRIVE']
              : [])
          }
          initialSyncFreq={activeConfigConnector.syncFrequency}
          isLocked={
            Boolean(allConnections[activeConfigConnector.id]?.lock?.is_locked) ||
            (activeConfigConnector.id === 'gmail' ? gmailDetails?.lock?.is_locked || false : false)
          }

          isInitialSync={
            !activeConfigConnector.syncCaptured ||
            activeConfigConnector.syncCaptured === 0 ||
            activeConfigConnector.status === 'Configuration Required'
          }
        />
      )}

      {/* UNIVERSAL SYNC ACTIVITY & AUDIT LOG MODAL */}
      {showActivityModal && selectedActivityConnector && (
        <GmailSyncActivityModal
          key={`${selectedActivityConnector.id}-${activeUserId}`}
          isOpen={showActivityModal}
          onClose={() => {
            setShowActivityModal(false);
            setSelectedActivityConnector(null);
          }}
          userId={activeUserId}
          source={selectedActivityConnector.id}
          sourceName={selectedActivityConnector.name}
          logoUrl={selectedActivityConnector.logoUrl}
          onDataPurged={fetchAllConnectorsStatus}
        />
      )}

      {/* CONFIRM DISCONNECT DIALOG MODAL */}
      {disconnectingId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          {/* Backdrop */}
          <div
            className={`absolute inset-0 bg-black/60 backdrop-blur-xs transition-opacity duration-300 animate-in fade-in ${
              isDisconnecting ? 'cursor-not-allowed' : 'cursor-pointer'
            }`}
            onClick={() => !isDisconnecting && setDisconnectingId(null)}
          />

          {/* Modal Content */}
          <div className="relative w-full max-w-sm bg-card border border-red-500/30 dark:border-red-500/20 rounded-2xl p-6 shadow-2xl z-10 animate-in zoom-in-95 duration-200 text-left space-y-4 overflow-hidden">
            {/* Close Button */}
            <button
              type="button"
              disabled={isDisconnecting}
              onClick={() => setDisconnectingId(null)}
              className="absolute top-4 right-4 p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              title="Close"
            >
              <X className="w-4 h-4" />
            </button>

            <div className="flex gap-3">
              <div className="w-10 h-10 bg-red-500/10 text-red-500 dark:text-red-400 rounded-xl flex items-center justify-center shrink-0 border border-red-500/20 shadow-3xs">
                {isDisconnecting ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <Power className="w-5 h-5" />
                )}
              </div>
              <div className="space-y-1 pr-4">
                <h4 className="font-serif text-base font-bold text-foreground">
                  Disconnect {integrations.find((i) => i.id === disconnectingId)?.name || 'Connector'}?
                </h4>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  Disconnecting will revoke active OAuth tokens and pause future auto-sync. All previously synced memories and transcripts in your vector workspace will remain safely preserved.
                </p>
              </div>
            </div>

            <div className="flex justify-end gap-2.5 pt-2">
              <Button
                variant="outline"
                className="text-xs py-2 px-4 border-border hover:bg-muted/50 transition-all"
                disabled={isDisconnecting}
                onClick={() => setDisconnectingId(null)}
              >
                Keep Active
              </Button>
              <button
                type="button"
                disabled={isDisconnecting}
                onClick={confirmDisconnection}
                className="px-4 py-2 rounded-xl text-xs font-bold bg-red-600 hover:bg-red-700 active:bg-red-800 text-white shadow-md transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed border border-red-600"
              >
                {isDisconnecting ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-white" />
                    <span>Disconnecting...</span>
                  </>
                ) : (
                  <>
                    <Power className="w-3.5 h-3.5 text-white" />
                    <span>Confirm Disconnect</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* CUSTOM CONNECTOR REQUEST DIALOG MODAL */}
      {showEnterpriseModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-xs transition-opacity duration-300 animate-in fade-in"
            onClick={() => setShowEnterpriseModal(false)}
          />

          {/* Modal Panel */}
          <form onSubmit={dispatchEnterpriseRequest} className="relative w-full max-w-md bg-card border border-border rounded-2xl p-6 shadow-2xl z-10 animate-in zoom-in-95 duration-200 text-left space-y-4">
            <div className="flex items-center gap-2 border-b border-border/60 pb-3">
              <HelpCircle className="w-5 h-5 text-primary" />
              <h3 className="font-serif text-lg font-bold text-foreground">Request Enterprise Sync</h3>
            </div>

            <div className="space-y-4">
              {/* Target System */}
              <Input
                label="Target Database / System Name"
                id="target-system"
                type="text"
                placeholder="e.g. AWS Redshift, Oracle CRM, MongoDB Atlas"
                value={enterpriseDatabase}
                onChange={(e) => setEnterpriseDatabase(e.target.value)}
                required
              />

              {/* Requirements Message */}
              <div className="space-y-1.5">
                <label htmlFor="trace-details" className="text-xs font-semibold text-muted-foreground">
                  Requirements & Legacy Data Schema Details
                </label>
                <textarea
                  id="trace-details"
                  rows={4}
                  value={enterpriseMessage}
                  onChange={(e) => setEnterpriseMessage(e.target.value)}
                  className="w-full bg-background border border-border rounded-xl px-4 py-2.5 text-xs font-medium focus:outline-none focus:ring-1 focus:ring-primary shadow-2xs resize-none"
                  placeholder="Describe your backend database system (Oracle, DynamoDB, PostgreSQL, etc.), vector expectations, sync triggers needed, and LDAP security scopes."
                  required
                />
              </div>
            </div>

            {/* Actions */}
            <div className="flex justify-end gap-2 pt-2">
              <Button
                variant="outline"
                className="text-xs py-2 px-4"
                onClick={() => setShowEnterpriseModal(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                isLoading={isSubmittingEnterprise}
                loadingText="Sending Request..."
                className="text-xs py-2 px-4"
              >
                Dispatch Request
              </Button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};

export default ExternalConnector;
