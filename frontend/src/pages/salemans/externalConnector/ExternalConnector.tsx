import React, { useState, useMemo } from 'react';
import {
  Cloud,
  Layers,
  FolderOpen,
  FileText,
  MessageSquare as SlackIcon,
  Database,
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
  AlertCircle
} from 'lucide-react';
import { Button } from '../../../components/common/Button';
import { Input } from '../../../components/common/Input';

interface Integration {
  id: string;
  name: string;
  category: 'CRM' | 'Storage' | 'Productivity' | 'Databases' | 'Communication';
  status: 'Connected' | 'Available';
  description: string;
  icon: React.ComponentType<any>;
  iconColor: string;
  bgColor: string;
  details: string;
  syncFrequency: string;
}

export const ExternalConnector: React.FC = () => {
  // State: Integrations List
  const [integrations, setIntegrations] = useState<Integration[]>([
    {
      id: 'salesforce',
      name: 'Salesforce',
      category: 'CRM',
      status: 'Connected',
      description: 'Sync leads, opportunities, and contact records with bi-directional field mapping for real-time pipeline visibility.',
      icon: Cloud,
      iconColor: 'text-blue-600 dark:text-blue-400',
      bgColor: 'bg-blue-50 dark:bg-blue-950/30 border-blue-200/50 dark:border-blue-800/30',
      details: 'Sync leads, contacts, and opportunities. Fields mapped: 14 default, 4 custom. Sync frequency: Hourly.',
      syncFrequency: 'hourly',
    },
    {
      id: 'hubspot',
      name: 'HubSpot',
      category: 'CRM',
      status: 'Available',
      description: 'Integrate marketing automation workflows and contact lifecycle stages directly into your RoleSync dashboard.',
      icon: Layers,
      iconColor: 'text-orange-500',
      bgColor: 'bg-orange-50 dark:bg-orange-950/30 border-orange-200/50 dark:border-orange-800/30',
      details: 'Import pipeline stages, marketing lists, and lifecycle events.',
      syncFrequency: 'daily',
    },
    {
      id: 'gdrive',
      name: 'Google Drive',
      category: 'Storage',
      status: 'Connected',
      description: 'Automated document synchronization to index spreadsheets, contract PDFs, and slides into your vector workspace.',
      icon: FolderOpen,
      iconColor: 'text-emerald-600 dark:text-emerald-400',
      bgColor: 'bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200/50 dark:border-emerald-800/30',
      details: 'Auto-sync from specified folders. Active indexing enabled: 124 files verified.',
      syncFrequency: 'realtime',
    },
    {
      id: 'notion',
      name: 'Notion Workspace',
      category: 'Productivity',
      status: 'Available',
      description: 'Map internal wikis, database boards, and procedural guidepages directly into Legacydb context embeddings.',
      icon: FileText,
      iconColor: 'text-neutral-700 dark:text-neutral-300',
      bgColor: 'bg-neutral-50 dark:bg-neutral-900/30 border-neutral-200/50 dark:border-neutral-800/30',
      details: 'Sync workspace directories, page trees, and markdown blocks.',
      syncFrequency: 'daily',
    },
    {
      id: 'slack',
      name: 'Slack channels',
      category: 'Communication',
      status: 'Available',
      description: 'Calibrate companion agents on chat transcripts, support logs, and historical feedback loops.',
      icon: SlackIcon,
      iconColor: 'text-purple-600 dark:text-purple-400',
      bgColor: 'bg-purple-50 dark:bg-purple-950/30 border-purple-200/50 dark:border-purple-800/30',
      details: 'Ingest public channels and support logs.',
      syncFrequency: 'daily',
    },
    {
      id: 'snowflake',
      name: 'Snowflake Shards',
      category: 'Databases',
      status: 'Available',
      description: 'Query warehousing schemas directly to vectorize transaction metrics and pricing data shards on the fly.',
      icon: Database,
      iconColor: 'text-sky-500',
      bgColor: 'bg-sky-50 dark:bg-sky-950/30 border-sky-200/50 dark:border-sky-800/30',
      details: 'Sync warehousing shards. DB queries vectorized on schedule.',
      syncFrequency: 'weekly',
    },
  ]);

  // UI Control States
  const [activeTab, setActiveTab] = useState<string>('All');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedIntegration, setSelectedIntegration] = useState<Integration | null>(null);
  const [showConfigDrawer, setShowConfigDrawer] = useState<boolean>(false);
  const [showEnterpriseModal, setShowEnterpriseModal] = useState<boolean>(false);

  // Connection Simulation States
  const [connectingId, setConnectingId] = useState<string | null>(null);
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);
  const [activeSyncingId, setActiveSyncingId] = useState<string | null>(null);

  // Form State inside modals
  const [enterpriseDatabase, setEnterpriseDatabase] = useState<string>('');
  const [enterpriseMessage, setEnterpriseMessage] = useState<string>('');
  const [isSubmittingEnterprise, setIsSubmittingEnterprise] = useState<boolean>(false);

  // Drawer fields mapping configuration state
  const [syncFreq, setSyncFreq] = useState<string>('hourly');
  const [fieldMapping, setFieldMapping] = useState({
    firstName: true,
    lastName: true,
    email: true,
    company: true,
    annualRevenue: false,
    opportunityStage: false,
  });

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

  // Connect Simulation
  const handleToggleConnection = (id: string, currentStatus: 'Connected' | 'Available') => {
    if (currentStatus === 'Available') {
      setConnectingId(id);
      setTimeout(() => {
        setIntegrations((prev) =>
          prev.map((item) =>
            item.id === id ? { ...item, status: 'Connected', syncFrequency: 'hourly' } : item
          )
        );
        setConnectingId(null);
      }, 1500);
    } else {
      setDisconnectingId(id);
    }
  };

  // Confirm Disconnection Action
  const confirmDisconnection = () => {
    if (!disconnectingId) return;
    const targetId = disconnectingId;
    setIntegrations((prev) =>
      prev.map((item) =>
        item.id === targetId ? { ...item, status: 'Available' } : item
      )
    );
    setDisconnectingId(null);
    if (selectedIntegration?.id === targetId) {
      setShowConfigDrawer(false);
    }
  };

  // Sync Shards Simulation
  const triggerManualSync = (id: string) => {
    setActiveSyncingId(id);
    setTimeout(() => {
      setActiveSyncingId(null);
      alert('Manual context sync pipeline completed! Shard metrics successfully updated.');
    }, 1500);
  };

  // Save mapping RAG config
  const saveMappingConfig = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedIntegration) return;

    setIntegrations((prev) =>
      prev.map((item) =>
        item.id === selectedIntegration.id ? { ...item, syncFrequency: syncFreq } : item
      )
    );
    setShowConfigDrawer(false);
    alert(`Configuration successfully committed for ${selectedIntegration.name}!`);
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

  return (
    <div className="space-y-8 animate-in fade-in duration-500 pb-16 relative">
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
            <h4 className="text-lg font-bold text-foreground mt-1">2 Live Connectors</h4>
          </div>
          <span className="w-2.5 h-2.5 bg-emerald-500 rounded-full animate-pulse"></span>
        </div>
        <div className="bg-card border border-border p-4 rounded-xl shadow-2xs flex justify-between items-center">
          <div>
            <p className="text-[10px] font-mono text-muted-foreground uppercase font-bold tracking-wider">synchronization scope</p>
            <h4 className="text-lg font-bold text-foreground mt-1">1,372 Indexed Files</h4>
          </div>
          <FolderOpen className="w-5 h-5 text-primary" />
        </div>
        <div className="bg-card border border-border p-4 rounded-xl shadow-2xs flex justify-between items-center">
          <div>
            <p className="text-[10px] font-mono text-muted-foreground uppercase font-bold tracking-wider">secure channels</p>
            <h4 className="text-lg font-bold text-foreground mt-1">OAuth2 Protocol Active</h4>
          </div>
          <ShieldCheck className="w-5 h-5 text-primary" />
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
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
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
          const isConnected = item.status === 'Connected';
          const isConnecting = connectingId === item.id;
          const isSyncing = activeSyncingId === item.id;

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
                  <div className={`w-11 h-11 rounded-xl flex items-center justify-center border shadow-3xs ${item.bgColor}`}>
                    <Icon className={`w-5 h-5 ${item.iconColor}`} />
                  </div>

                  <button
                    onClick={() => handleToggleConnection(item.id, item.status)}
                    disabled={isConnecting}
                    className={`text-[10px] font-mono font-bold tracking-wider uppercase border px-2.5 py-1 rounded-full cursor-pointer transition-all ${
                      isConnected
                        ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-800 dark:text-emerald-300 hover:bg-destructive/10 hover:border-destructive/30 hover:text-destructive hover:after:content-["Disconnect"] transition-all'
                        : 'bg-muted border-border hover:border-primary text-muted-foreground hover:text-foreground hover:bg-background'
                    }`}
                  >
                    {isConnecting ? (
                      <span className="flex items-center gap-1">
                        <Loader2 className="w-2.5 h-2.5 animate-spin text-primary" />
                        <span>Verifying...</span>
                      </span>
                    ) : (
                      <span>{item.status}</span>
                    )}
                  </button>
                </div>

                {/* Typography */}
                <h3 className="font-serif text-base font-bold text-foreground mb-1 group-hover:text-primary transition-colors">
                  {item.name}
                </h3>
                <p className="text-[10px] font-mono text-muted-foreground/80 uppercase font-bold tracking-wider mb-3">
                  {item.category}
                </p>
                <p className="text-xs leading-relaxed text-muted-foreground mb-6">
                  {item.description}
                </p>
              </div>

              {/* Bottom Triggers (Connected details vs standard actions) */}
              <div className="pt-4 border-t border-border/40 flex items-center justify-between gap-2 mt-auto">
                {isConnected ? (
                  <>
                    <div className="flex flex-col">
                      <span className="text-[8px] font-mono font-bold text-muted-foreground uppercase tracking-widest">sync frequency</span>
                      <span className="text-[10px] font-mono font-bold text-primary uppercase mt-0.5">{item.syncFrequency}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Button
                        variant="outline"
                        onClick={() => triggerManualSync(item.id)}
                        disabled={isSyncing}
                        className="p-2 aspect-square rounded-xl shadow-3xs"
                        title="Sync Now"
                      >
                        <RefreshCw className={`w-3.5 h-3.5 text-primary ${isSyncing ? 'animate-spin' : ''}`} />
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => {
                          setSelectedIntegration(item);
                          setSyncFreq(item.syncFrequency);
                          setShowConfigDrawer(true);
                        }}
                        className="p-2 aspect-square rounded-xl shadow-3xs"
                        title="Configure Field Mappings"
                      >
                        <Settings className="w-3.5 h-3.5 text-primary" />
                      </Button>
                    </div>
                  </>
                ) : (
                  <>
                    <span className="text-[10px] text-muted-foreground/60 font-mono">Authentication Required</span>
                    <button
                      onClick={() => handleToggleConnection(item.id, 'Available')}
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

      {/* SLIDE OVER DRAWER: Field Mappings Configuration */}
      {showConfigDrawer && selectedIntegration && (
        <div className="fixed inset-0 z-50 overflow-hidden flex justify-end">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-xs transition-opacity duration-300 animate-in fade-in"
            onClick={() => setShowConfigDrawer(false)}
          />

          {/* Drawer content */}
          <div className="relative w-full max-w-md bg-card border-l border-border h-screen flex flex-col justify-between shadow-2xl z-10 animate-in slide-in-from-right duration-300">
            <div>
              {/* Header */}
              <div className="p-6 border-b border-border flex justify-between items-center">
                <div className="flex items-center gap-2">
                  <Settings className="w-5 h-5 text-primary animate-spin-slow" />
                  <h3 className="font-serif text-lg font-bold text-foreground">
                    Configure {selectedIntegration.name}
                  </h3>
                </div>
                <button
                  onClick={() => setShowConfigDrawer(false)}
                  className="p-1.5 rounded-lg border border-border/80 hover:bg-muted text-muted-foreground hover:text-foreground active:scale-95 transition-all"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Form body */}
              <form onSubmit={saveMappingConfig} className="p-6 space-y-6 overflow-y-auto max-h-[calc(100vh-170px)] text-left">
                {/* Sync Frequency dropdown */}
                <div className="space-y-1.5">
                  <label htmlFor="sync-frequency" className="text-xs font-semibold text-muted-foreground">
                    Synchronization Sync Cron Interval
                  </label>
                  <select
                    id="sync-frequency"
                    value={syncFreq}
                    onChange={(e) => setSyncFreq(e.target.value)}
                    className="w-full bg-background border border-border rounded-xl p-2.5 text-xs font-semibold focus:outline-none focus:ring-1 focus:ring-primary cursor-pointer"
                  >
                    <option value="realtime">Real-time Continuous Sync</option>
                    <option value="hourly">Hourly Interval Scrape</option>
                    <option value="daily">Daily Cron Sequence (02:00 AM)</option>
                    <option value="weekly">Weekly Shard Calibration</option>
                  </select>
                </div>

                {/* Field mappings checklist */}
                <div className="space-y-3">
                  <div className="flex justify-between items-center">
                    <label className="text-xs font-semibold text-muted-foreground">Select Fields to Vectorize</label>
                    <span className="text-[9px] font-mono bg-primary/10 text-primary px-2 py-0.5 rounded font-bold">RAG CONTEXT</span>
                  </div>

                  <div className="bg-muted/40 border border-border/40 rounded-xl p-4 space-y-3">
                    {Object.keys(fieldMapping).map((fieldName) => (
                      <label key={fieldName} className="flex items-center gap-3 cursor-pointer text-xs font-semibold text-foreground select-none">
                        <input
                          type="checkbox"
                          checked={(fieldMapping as any)[fieldName]}
                          onChange={(e) =>
                            setFieldMapping((prev) => ({
                              ...prev,
                              [fieldName]: e.target.checked,
                            }))
                          }
                          className="w-4 h-4 rounded border-border text-primary accent-primary focus:ring-primary/20 cursor-pointer bg-background"
                        />
                        <span className="capitalize">{fieldName.replace(/([A-Z])/g, ' $1')}</span>
                      </label>
                    ))}
                  </div>
                  <p className="text-[10px] text-muted-foreground/80 leading-relaxed">
                    Checked attributes will be segmented, parsed into RAG shards, and token-inserted into Legacydb for vector-cosine match routines.
                  </p>
                </div>
              </form>
            </div>

            {/* Bottom Actions */}
            <div className="p-6 border-t border-border flex gap-2">
              <Button
                variant="outline"
                className="w-full text-xs font-bold py-2.5"
                onClick={() => setShowConfigDrawer(false)}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                className="w-full text-xs font-bold py-2.5"
                onClick={saveMappingConfig}
              >
                Commit Changes
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* CONFIRM DISCONNECT DIALOG MODAL */}
      {disconnectingId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-xs transition-opacity duration-300 animate-in fade-in"
            onClick={() => setDisconnectingId(null)}
          />

          {/* Modal Content */}
          <div className="relative w-full max-w-sm bg-card border border-border rounded-2xl p-6 shadow-2xl z-10 animate-in zoom-in-95 duration-200 text-left space-y-4">
            <div className="flex gap-3">
              <div className="w-10 h-10 bg-destructive/10 text-destructive rounded-xl flex items-center justify-center shrink-0 border border-destructive/20 shadow-3xs">
                <Power className="w-5 h-5" />
              </div>
              <div className="space-y-1">
                <h4 className="font-serif text-base font-bold text-foreground">Terminate Connection?</h4>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  Disconnecting this database will purge all indexed context shards from the vector vault. Semantic similarity queries for these files will fail immediately.
                </p>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button
                variant="outline"
                className="text-xs py-2 px-4"
                onClick={() => setDisconnectingId(null)}
              >
                Keep Active
              </Button>
              <Button
                variant="primary"
                className="bg-destructive hover:bg-destructive/90 text-white text-xs py-2 px-4 border-transparent"
                onClick={confirmDisconnection}
              >
                Confirm Purge
              </Button>
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
