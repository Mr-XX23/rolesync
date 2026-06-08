import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CloudUpload,
  Sliders,
  Save,
  FolderOpen,
  FileText,
  FileSpreadsheet,
  Share2,
  RefreshCw,
  MoreVertical,
  CheckCircle2,
  Plus,
  Loader2,
  AlertCircle
} from 'lucide-react';
import { Button } from '../../../components/common/Button';

interface IngestionResource {
  id: string;
  name: string;
  type: string;
  chunks: string;
  status: 'Indexed' | 'Parsing' | 'Error';
  lastUpdated: string;
}

export const KnowledgeVault: React.FC = () => {
  const navigate = useNavigate();
  // RAG States
  const [chunkSize, setChunkSize] = useState(512);
  const [overlap, setOverlap] = useState(12);
  const [embeddingEngine, setEmbeddingEngine] = useState('BGE-M3 (Enterprise-Grade)');
  const [isSavingConfig, setIsSavingConfig] = useState(false);

  // Ingestion List States
  const [filter, setFilter] = useState<'all' | 'unprocessed'>('all');
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [resources, setResources] = useState<IngestionResource[]>([
    {
      id: '1',
      name: 'Q4_Pricing_Guide_Final.pdf',
      type: 'PDF',
      chunks: '1,248',
      status: 'Indexed',
      lastUpdated: '2 mins ago',
    },
    {
      id: '2',
      name: 'CRM_Export_NorthAmerica.csv',
      type: 'DATA',
      chunks: '--',
      status: 'Parsing',
      lastUpdated: 'Just now',
    },
  ]);

  // Simulate complete parsing for Row 2 after 5 seconds
  useEffect(() => {
    const timer = setTimeout(() => {
      setResources((prev) =>
        prev.map((r) =>
          r.id === '2'
            ? { ...r, status: 'Indexed', chunks: '852', lastUpdated: '1 min ago' }
            : r
        )
      );
    }, 5000);
    return () => clearTimeout(timer);
  }, []);

  // Handle Drag Events
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  // Process Simulated Upload
  const processSimulatedFiles = (files: FileList) => {
    Array.from(files).forEach((file) => {
      const newId = Math.random().toString(36).substring(2, 9);
      const fileExt = file.name.split('.').pop()?.toUpperCase() || 'FILE';

      // Insert new row in "Parsing" state
      const newResource: IngestionResource = {
        id: newId,
        name: file.name,
        type: fileExt,
        chunks: '--',
        status: 'Parsing',
        lastUpdated: 'Just now',
      };

      setResources((prev) => [newResource, ...prev]);

      // Simulate completion after 3.5 seconds
      setTimeout(() => {
        setResources((prev) =>
          prev.map((r) =>
            r.id === newId
              ? {
                  ...r,
                  status: 'Indexed',
                  chunks: Math.floor(Math.random() * 800 + 200).toLocaleString(),
                  lastUpdated: '1 sec ago',
                }
              : r
          )
        );
      }, 3500);
    });
  };

  // Drag & Drop
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      processSimulatedFiles(e.dataTransfer.files);
    }
  };

  // Click file select
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      processSimulatedFiles(e.target.files);
    }
  };

  // Ingest URL FAB
  const handleIngestUrl = () => {
    const url = prompt('Enter business URL to ingest (e.g., https://enterprise.com/pricing):');
    if (!url) return;

    const newId = Math.random().toString(36).substring(2, 9);

    const newResource: IngestionResource = {
      id: newId,
      name: url,
      type: 'URL',
      chunks: '--',
      status: 'Parsing',
      lastUpdated: 'Just now',
    };

    setResources((prev) => [newResource, ...prev]);

    setTimeout(() => {
      setResources((prev) =>
        prev.map((r) =>
          r.id === newId
            ? {
                ...r,
                status: 'Indexed',
                chunks: Math.floor(Math.random() * 400 + 50).toLocaleString(),
                lastUpdated: '1 sec ago',
              }
            : r
        )
      );
    }, 4000);
  };

  // Apply Config Handler
  const handleSaveConfig = () => {
    setIsSavingConfig(true);
    setTimeout(() => {
      setIsSavingConfig(false);
      alert('RAG Parameters successfully committed to the vector mesh context!');
    }, 1200);
  };

  // Connector Actions
  const handleConnect = (_service: string) => {
    navigate('/salesman/external-connector');
  };

  // Refresh
  const handleRefresh = () => {
    alert('Re-indexing pending workspace vector shards...');
  };

  // Filtered resources
  const filteredResources = resources.filter((r) => {
    if (filter === 'unprocessed') return r.status === 'Parsing';
    return true;
  });

  return (
    <div className="space-y-8 animate-in fade-in duration-500 pb-16">
      {/* Page Header */}
      <section className="flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
        <div className="space-y-2">
          <h2 className="font-serif text-3xl font-bold text-primary">
            Knowledge Vault
          </h2>
          <p className="text-sm text-muted-foreground max-w-xl leading-relaxed">
            Centralized repository for the Salesman Engine. Ingest legacy data, manage vector embeddings, and calibrate retrieval augmented generation parameters.
          </p>
        </div>
        <div className="flex items-center gap-1.5 bg-muted p-1 rounded-xl border border-border/60">
          <button
            onClick={() => setFilter('all')}
            className={`px-4 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              filter === 'all'
                ? 'bg-card text-foreground shadow-2xs border border-border/40'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            All Files
          </button>
          <button
            onClick={() => setFilter('unprocessed')}
            className={`px-4 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              filter === 'unprocessed'
                ? 'bg-card text-foreground shadow-2xs border border-border/40'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            Unprocessed
          </button>
        </div>
      </section>

      {/* Grid: Dropzone & RAG control panel */}
      <div className="grid grid-cols-12 gap-6 items-stretch">
        {/* DROPZONE (2/3 width) */}
        <div className="col-span-12 lg:col-span-8 group relative">
          <input
            type="file"
            id="file-upload"
            multiple
            className="hidden"
            ref={fileInputRef}
            onChange={handleFileChange}
          />
          <div
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`h-full border-2 border-dashed rounded-xl flex flex-col items-center justify-center p-8 transition-all duration-300 cursor-pointer relative overflow-hidden bg-card shadow-2xs ${
              dragActive
                ? 'border-primary bg-primary/5 scale-99 shadow-inner'
                : 'border-border hover:border-primary/50 hover:bg-muted/40'
            }`}
          >
            <div className="absolute inset-0 bg-linear-to-tr from-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"></div>
            
            <div className="relative z-10 flex flex-col items-center text-center max-w-md">
              <div className={`w-16 h-16 rounded-full flex items-center justify-center mb-6 transition-all duration-300 shadow-2xs ${
                dragActive ? 'bg-primary text-primary-foreground scale-110' : 'bg-primary/10 text-primary group-hover:scale-105'
              }`}>
                <CloudUpload className="w-8 h-8" />
              </div>
              <h3 className="font-serif text-lg font-bold text-foreground mb-2">
                Ingest Business Intelligence
              </h3>
              <p className="text-xs text-muted-foreground leading-relaxed mb-6">
                Drag and drop legacy PDFs, CRM exports (.csv), or pricing sheets here. Our engine handles normalization, splitting, and vectorization automatically.
              </p>
              <div className="flex gap-3">
                <Button
                  variant="primary"
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    fileInputRef.current?.click();
                  }}
                >
                  Select Files
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleConnect('Salesforce CRM');
                  }}
                >
                  Connect CRM Tools
                </Button>
              </div>
            </div>
          </div>
        </div>

        {/* RAG CONTROL PANEL (1/3 width) */}
        <div className="col-span-12 lg:col-span-4">
          <div className="bg-card border border-border p-6 rounded-xl shadow-2xs h-full flex flex-col justify-between">
            <div>
              <div className="flex items-center gap-2 mb-6">
                <Sliders className="w-5 h-5 text-primary" />
                <h4 className="font-serif text-lg font-bold text-foreground">RAG Parameters</h4>
              </div>

              <div className="space-y-6">
                {/* Chunk Size */}
                <div className="space-y-2">
                  <div className="flex justify-between items-center text-xs">
                    <label className="text-muted-foreground font-medium">Chunk Size</label>
                    <span className="font-mono bg-primary/10 text-primary px-2.5 py-0.5 rounded-md font-bold">
                      {chunkSize} tokens
                    </span>
                  </div>
                  <input
                    className="w-full h-1 bg-border rounded-lg appearance-none cursor-pointer accent-primary focus:outline-none"
                    max="2048"
                    min="128"
                    step="64"
                    type="range"
                    value={chunkSize}
                    onChange={(e) => setChunkSize(Number(e.target.value))}
                  />
                </div>

                {/* Overlap */}
                <div className="space-y-2">
                  <div className="flex justify-between items-center text-xs">
                    <label className="text-muted-foreground font-medium">Overlap Window</label>
                    <span className="font-mono bg-secondary/80 text-secondary-foreground px-2.5 py-0.5 rounded-md font-bold">
                      {overlap}%
                    </span>
                  </div>
                  <input
                    className="w-full h-1 bg-border rounded-lg appearance-none cursor-pointer accent-primary focus:outline-none"
                    max="30"
                    min="0"
                    step="1"
                    type="range"
                    value={overlap}
                    onChange={(e) => setOverlap(Number(e.target.value))}
                  />
                </div>

                {/* Model Selector */}
                <div className="space-y-2">
                  <label className="text-xs text-muted-foreground font-medium block">
                    Embedding Engine
                  </label>
                  <select
                    value={embeddingEngine}
                    onChange={(e) => setEmbeddingEngine(e.target.value)}
                    className="w-full bg-background border border-border/80 rounded-xl p-2.5 text-xs font-semibold focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary"
                  >
                    <option value="Text-Embedding-3-Small">Text-Embedding-3-Small</option>
                    <option value="BGE-M3 (Enterprise-Grade)">BGE-M3 (Enterprise-Grade)</option>
                    <option value="Titan Multimodal v2">Titan Multimodal v2</option>
                  </select>
                </div>
              </div>
            </div>

            <div className="mt-8 pt-6 border-t border-border/60">
              <Button
                onClick={handleSaveConfig}
                isLoading={isSavingConfig}
                loadingText="Apply Global Config..."
                icon={<Save className="w-4 h-4" />}
              >
                Apply Global Config
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Sync Connectors */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-mono text-[10px] font-bold text-muted-foreground uppercase tracking-widest">
            Live Data Sync Connectors
          </h3>
          <span className="px-2.5 py-0.5 bg-primary/10 text-primary font-mono text-[9px] rounded-full border border-primary/20 font-bold uppercase">
            OAuth2 Secured
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Google Drive */}
          <div
            onClick={() => handleConnect('Google Drive')}
            className="group relative bg-card border border-border rounded-2xl p-4 transition-all duration-300 hover:border-primary/40 hover:-translate-y-1 hover:shadow-sm cursor-pointer"
          >
            <div className="absolute top-4 right-4 flex items-center gap-1">
              <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse"></span>
              <span className="font-mono text-[8px] text-muted-foreground font-bold tracking-tighter">SYNCING</span>
            </div>
            <div className="w-10 h-10 bg-primary/10 text-primary rounded-xl flex items-center justify-center mb-4 group-hover:scale-110 transition-transform shadow-2xs">
              <FolderOpen className="w-5 h-5" />
            </div>
            <div>
              <h4 className="font-serif text-sm font-bold text-foreground">Google Drive</h4>
              <p className="text-[11px] text-muted-foreground leading-tight mt-1">
                Auto-sync shared project folders & PDFs.
              </p>
            </div>
          </div>

          {/* Notion */}
          <div
            onClick={() => handleConnect('Notion Workspace')}
            className="group relative bg-card border border-border rounded-2xl p-4 transition-all duration-300 hover:border-primary/40 hover:-translate-y-1 hover:shadow-sm cursor-pointer"
          >
            <div className="absolute top-4 right-4 text-muted-foreground/45 group-hover:text-primary transition-colors">
              <Plus className="w-4 h-4" />
            </div>
            <div className="w-10 h-10 bg-primary/10 text-primary rounded-xl flex items-center justify-center mb-4 group-hover:scale-110 transition-transform shadow-2xs">
              <FileText className="w-5 h-5" />
            </div>
            <div>
              <h4 className="font-serif text-sm font-bold text-foreground">Notion Workspace</h4>
              <p className="text-[11px] text-muted-foreground leading-tight mt-1">
                Import documentation & wikis.
              </p>
            </div>
          </div>

          {/* Excel */}
          <div
            onClick={() => handleConnect('Microsoft Excel')}
            className="group relative bg-card border border-border rounded-2xl p-4 transition-all duration-300 hover:border-primary/40 hover:-translate-y-1 hover:shadow-sm cursor-pointer"
          >
            <div className="absolute top-4 right-4 text-muted-foreground/45 group-hover:text-primary transition-colors">
              <Plus className="w-4 h-4" />
            </div>
            <div className="w-10 h-10 bg-primary/10 text-primary rounded-xl flex items-center justify-center mb-4 group-hover:scale-110 transition-transform shadow-2xs">
              <FileSpreadsheet className="w-5 h-5" />
            </div>
            <div>
              <h4 className="font-serif text-sm font-bold text-foreground">Microsoft Excel</h4>
              <p className="text-[11px] text-muted-foreground leading-tight mt-1">
                Sync pricing sheets & spreadsheets.
              </p>
            </div>
          </div>

          {/* Salesforce */}
          <div
            onClick={() => handleConnect('Salesforce CRM')}
            className="group relative bg-card border border-border rounded-2xl p-4 transition-all duration-300 hover:border-primary/40 hover:-translate-y-1 hover:shadow-sm cursor-pointer"
          >
            <div className="absolute top-4 right-4 text-muted-foreground/45 group-hover:text-primary transition-colors">
              <Plus className="w-4 h-4" />
            </div>
            <div className="w-10 h-10 bg-primary/10 text-primary rounded-xl flex items-center justify-center mb-4 group-hover:scale-110 transition-transform shadow-2xs">
              <Share2 className="w-5 h-5" />
            </div>
            <div>
              <h4 className="font-serif text-sm font-bold text-foreground">Salesforce CRM</h4>
              <p className="text-[11px] text-muted-foreground leading-tight mt-1">
                Pull client interactions & history.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Ingestion Table Panel */}
      <div className="bg-card border border-border rounded-2xl p-6 shadow-2xs overflow-hidden">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-2.5 h-2.5 bg-emerald-500 rounded-full animate-pulse"></div>
            <h4 className="font-serif text-lg font-bold text-foreground">Ingestion Pipeline</h4>
            <span className="hidden sm:inline font-mono text-[9px] text-muted-foreground bg-muted border border-border/80 px-2 py-0.5 rounded-md font-medium">
              pgvector-instance-04
            </span>
          </div>
          <div className="flex gap-1.5">
            <Button
              variant="outline"
              onClick={handleRefresh}
              className="p-2 aspect-square rounded-xl shadow-3xs"
              title="Refresh Pipeline"
              icon={<RefreshCw className="w-4 h-4 text-muted-foreground hover:text-foreground" />}
            />
            <Button
              variant="outline"
              onClick={() => alert('Options panel coming soon')}
              className="p-2 aspect-square rounded-xl shadow-3xs"
              title="Actions"
              icon={<MoreVertical className="w-4 h-4 text-muted-foreground hover:text-foreground" />}
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-separate border-spacing-y-2">
            <thead className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider">
              <tr>
                <th className="px-4 pb-2">Resource Name</th>
                <th className="px-4 pb-2">Type</th>
                <th className="px-4 pb-2">Chunks</th>
                <th className="px-4 pb-2">Status</th>
                <th className="px-4 pb-2">Last Updated</th>
                <th className="px-4 pb-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredResources.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center py-8 text-xs text-muted-foreground font-mono">
                    No resources currently in the synchronization queue.
                  </td>
                </tr>
              ) : (
                filteredResources.map((resource) => (
                  <tr key={resource.id} className="bg-muted/40 hover:bg-muted/70 transition-colors border border-border/40">
                    <td className="px-4 py-4 rounded-l-xl">
                      <div className="flex items-center gap-3">
                        <FileText className="w-4 h-4 text-primary shrink-0" />
                        <span className="text-xs font-semibold text-foreground leading-tight truncate max-w-[200px] sm:max-w-xs">
                          {resource.name}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-4">
                      <span className="font-mono text-[9px] font-bold bg-background text-muted-foreground px-2 py-0.5 rounded-md border border-border/40">
                        {resource.type}
                      </span>
                    </td>
                    <td className="px-4 py-4 font-mono text-xs font-semibold text-foreground">
                      {resource.chunks}
                    </td>
                    <td className="px-4 py-4">
                      {resource.status === 'Indexed' ? (
                        <div className="flex items-center gap-1.5 text-emerald-700 dark:text-emerald-400 font-bold">
                          <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                          <span className="text-[11px] uppercase tracking-wide">Indexed</span>
                        </div>
                      ) : resource.status === 'Parsing' ? (
                        <div className="flex items-center gap-1.5 text-primary font-bold">
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          <span className="text-[11px] uppercase tracking-wide animate-pulse">Parsing...</span>
                        </div>
                      ) : (
                        <div className="flex items-center gap-1.5 text-destructive font-bold">
                          <AlertCircle className="w-4 h-4" />
                          <span className="text-[11px] uppercase tracking-wide">Error</span>
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-4 text-xs font-medium text-muted-foreground">
                      {resource.lastUpdated}
                    </td>
                    <td className="px-4 py-4 rounded-r-xl text-right">
                      {resource.status === 'Indexed' ? (
                        <button
                          onClick={() => alert(`Vector embeddings details: ${resource.chunks} segments, Cosine similarity indexed.`)}
                          className="text-xs font-bold text-primary hover:underline transition-all"
                        >
                          View Vectors
                        </button>
                      ) : (
                        <button
                          onClick={() => {
                            setResources((prev) => prev.filter((r) => r.id !== resource.id));
                          }}
                          className="text-xs font-bold text-muted-foreground/80 hover:text-destructive transition-all"
                        >
                          Abort
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* FAB Floating action button */}
      <button
        onClick={handleIngestUrl}
        className="fixed bottom-8 right-8 w-14 h-14 bg-primary text-primary-foreground rounded-full shadow-lg flex items-center justify-center hover:scale-105 active:scale-95 transition-all z-50 group border border-primary/20"
        title="Ingest Single URL"
      >
        <Plus className="w-6 h-6 transition-transform group-hover:rotate-90 duration-300" />
        <span className="absolute right-full mr-4 bg-primary text-primary-foreground font-semibold px-3 py-1.5 rounded-xl text-xs whitespace-nowrap opacity-0 group-hover:opacity-100 transition-all duration-300 scale-90 group-hover:scale-100 translate-x-2 group-hover:translate-x-0 shadow-sm pointer-events-none">
          Ingest Single URL
        </span>
      </button>

      <footer className="pt-8 text-center text-muted-foreground/50 font-mono text-[9px] uppercase tracking-widest">
        RoleSync Enterprise Knowledge Management Engine v4.2 // Distributed Vector Mesh Enabled
      </footer>
    </div>
  );
};
export default KnowledgeVault;
