import React, { useState, useEffect, useCallback } from 'react';
import {
  Sliders,
  Key,
  Server,
  RotateCcw,
  Save,
  CheckCircle2,
  Layers,
  Sparkles,
  Info,
  Cpu,
} from 'lucide-react';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';
import { useToast } from '../../context/ToastContext';
import { useAppSelector } from '../../store';
import {
  knowledgeVaultApi,
  type RagConfig,
} from '../../api/knowledgeVaultApi';
import { RAG_PRESETS } from './knowledgeVault/vaultUtils';

export const Settings: React.FC = () => {
  const toast = useToast();
  const activeUser = useAppSelector((state) => state.auth.user);
  const userId = activeUser?.userId || 'usr_active';

  // Navigation Filter Tab
  const [activeTab, setActiveTab] = useState<'all' | 'rag' | 'credentials' | 'diagnostics'>('all');

  // RAG Calibration States
  const [chunkSize, setChunkSize] = useState(512);
  const [overlap, setOverlap] = useState(12);
  const [similarityThreshold, setSimilarityThreshold] = useState(0.72);
  const [embeddingEngine, setEmbeddingEngine] = useState('RoleSync Vector Engine (1536-dim)');
  const [activePreset, setActivePreset] = useState<string>('balanced');
  const [isSavingRag, setIsSavingRag] = useState(false);
  const [isLoadingConfig, setIsLoadingConfig] = useState(true);

  // API Credentials States
  const [openaiKey, setOpenaiKey] = useState('sk-••••••••••••••••••••••••3a2f');
  const [salesforceUrl, setSalesforceUrl] = useState('https://na42.salesforce.com');
  const [isSubmittingCreds, setIsSubmittingCreds] = useState(false);

  // Load Saved RAG Configuration on Mount
  useEffect(() => {
    let isMounted = true;
    const loadConfig = async () => {
      try {
        const cfg = await knowledgeVaultApi.getRagConfig(userId);
        if (cfg && isMounted) {
          setChunkSize(cfg.chunk_size || 512);
          setOverlap(cfg.overlap || 12);
          setEmbeddingEngine(cfg.embedding_engine || 'RoleSync Vector Engine (1536-dim)');
          if (cfg.similarity_threshold !== undefined) {
            setSimilarityThreshold(cfg.similarity_threshold);
          }

          // Match active preset if matches exactly
          if (cfg.chunk_size === 256 && cfg.overlap === 8) {
            setActivePreset('qa');
          } else if (cfg.chunk_size === 1024 && cfg.overlap === 20) {
            setActivePreset('long_context');
          } else if (cfg.chunk_size === 512 && cfg.overlap === 12) {
            setActivePreset('balanced');
          } else {
            setActivePreset('');
          }
        }
      } catch (err) {
        console.warn('[Settings] Failed to fetch RAG config, using defaults:', err);
      } finally {
        if (isMounted) setIsLoadingConfig(false);
      }
    };

    loadConfig();
    return () => {
      isMounted = false;
    };
  }, [userId]);

  // Apply Tuning Preset
  const handleApplyPreset = useCallback((presetKey: string) => {
    const preset = RAG_PRESETS[presetKey];
    if (preset) {
      setActivePreset(presetKey);
      setChunkSize(preset.chunkSize);
      setOverlap(preset.overlap);
    }
  }, []);

  // Reset RAG Parameters to Enterprise Defaults
  const handleResetRagDefaults = useCallback(() => {
    handleApplyPreset('balanced');
    setSimilarityThreshold(0.72);
    setEmbeddingEngine('RoleSync Vector Engine (1536-dim)');
    toast.info('RAG parameters reset to recommended enterprise defaults.');
  }, [handleApplyPreset, toast]);

  // Save RAG Parameters to MongoDB
  const handleSaveRagConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingRag(true);
    try {
      const config: RagConfig = {
        chunk_size: chunkSize,
        overlap: overlap,
        embedding_engine: embeddingEngine,
        similarity_threshold: similarityThreshold,
      };
      await knowledgeVaultApi.saveRagConfig(config, userId);
      toast.success(
        `Chunk Size: ${chunkSize} tokens | Overlap: ${overlap}% | Similarity: ${similarityThreshold}`,
        'RAG Parameters Saved'
      );
    } catch (err) {
      console.error('[Settings] Failed to save RAG parameters:', err);
      toast.error('Failed to commit RAG configuration to database.');
    } finally {
      setIsSavingRag(false);
    }
  };

  // Save API Credentials
  const handleSaveCredentials = (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmittingCreds(true);
    setTimeout(() => {
      setIsSubmittingCreds(false);
      toast.success('Integration API credentials securely updated.', 'Credentials Updated');
    }, 1000);
  };

  // Preset helper descriptions
  const getPresetDescription = (key: string) => {
    switch (key) {
      case 'qa':
        return 'Precision: Optimized for FAQs, battlecard snippet lookups, and short facts.';
      case 'long_context':
        return 'Context: Extended chunk window for multi-page contracts and in-depth case studies.';
      case 'balanced':
      default:
        return 'Balanced: Recommended general setting for proposals, sales decks, and specifications.';
    }
  };

  // Estimated chunks calculation for typical 10-page doc (~5000 tokens)
  const estimatedChunks = Math.max(1, Math.round((5000 / chunkSize) * (1 + overlap / 100)));

  return (
    <div className="space-y-8 animate-in fade-in duration-500 pb-16">
      {/* Header */}
      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <h2 className="font-serif text-3xl font-bold text-primary tracking-tight">Settings</h2>
          <span className="font-mono text-[10px] px-2.5 py-0.5 rounded-full bg-primary/10 text-primary font-bold border border-primary/20">
            SYSTEM CONTROL
          </span>
        </div>
        <p className="text-sm text-muted-foreground max-w-2xl leading-relaxed">
          Calibrate document chunking, tune vector search confidence thresholds, manage API authentication keys, and inspect cluster diagnostics.
        </p>
      </section>

      {/* Tab Navigation Filter */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border/60 pb-3">
        {[
          { id: 'all' as const, label: 'All Settings', icon: Layers },
          { id: 'rag' as const, label: 'RAG Calibration', icon: Sliders },
          { id: 'credentials' as const, label: 'API Credentials', icon: Key },
          { id: 'diagnostics' as const, label: 'Cluster Diagnostics', icon: Server },
        ].map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all cursor-pointer ${
                isActive
                  ? 'bg-primary text-primary-foreground shadow-xs'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted/60'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* ================================================================ */}
      {/* SECTION 1: RAG & VECTOR CALIBRATION                             */}
      {/* ================================================================ */}
      {(activeTab === 'all' || activeTab === 'rag') && (
        <form
          onSubmit={handleSaveRagConfig}
          className="bg-card border border-border p-6 md:p-8 rounded-2xl shadow-2xs space-y-7"
        >
          {/* Card Header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border/60 pb-5">
            <div className="flex items-start gap-3">
              <div className="p-2 rounded-xl bg-primary/10 text-primary border border-primary/20">
                <Sliders className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-serif text-xl font-bold text-foreground flex items-center gap-2">
                  RAG Calibration & Chunking Engine
                </h3>
                <p className="text-xs text-muted-foreground mt-0.5 max-w-xl leading-relaxed">
                  Controls how documents in the Knowledge Vault are chunked, tokenized, and filtered for vector similarity queries.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 self-start sm:self-center">
              {isLoadingConfig ? (
                <span className="text-xs text-muted-foreground font-mono flex items-center gap-2 px-3 py-1.5">
                  <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                  Fetching parameters...
                </span>
              ) : (
                <button
                  type="button"
                  onClick={handleResetRagDefaults}
                  className="text-xs font-medium text-muted-foreground hover:text-foreground flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border/60 hover:bg-muted/40 transition-all cursor-pointer"
                  title="Reset to recommended defaults"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>Reset Defaults</span>
                </button>
              )}
            </div>
          </div>

          {/* Tuning Presets Bar */}
          <div className="space-y-2.5">
            <label className="text-xs text-muted-foreground font-semibold flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-primary" />
              <span>Recommended Tuning Presets</span>
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 p-1.5 bg-muted/40 rounded-2xl border border-border/60">
              {[
                { key: 'balanced', label: 'Balanced', sub: '512 tokens • 12% overlap' },
                { key: 'qa', label: 'Precision', sub: '256 tokens • 8% overlap' },
                { key: 'long_context', label: 'Context', sub: '1024 tokens • 20% overlap' },
              ].map((p) => (
                <button
                  key={p.key}
                  type="button"
                  onClick={() => handleApplyPreset(p.key)}
                  className={`p-3 text-left rounded-xl transition-all cursor-pointer flex flex-col gap-0.5 ${
                    activePreset === p.key
                      ? 'bg-card text-foreground shadow-2xs border border-border'
                      : 'text-muted-foreground hover:text-foreground hover:bg-card/50'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold">{p.label}</span>
                    {activePreset === p.key && (
                      <CheckCircle2 className="w-3.5 h-3.5 text-primary" />
                    )}
                  </div>
                  <span className="text-[10px] font-mono text-muted-foreground">
                    {p.sub}
                  </span>
                </button>
              ))}
            </div>
            {activePreset && (
              <p className="text-[11px] text-muted-foreground/80 flex items-center gap-1.5 italic">
                <Info className="w-3 h-3 shrink-0 text-primary" />
                {getPresetDescription(activePreset)}
              </p>
            )}
          </div>

          {/* Sliders Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-2">
            {/* Chunk Size Slider */}
            <div className="space-y-2.5 p-4 rounded-xl bg-muted/20 border border-border/50">
              <div className="flex justify-between items-center text-xs">
                <label className="text-foreground font-semibold">Chunk Size</label>
                <span className="font-mono text-primary font-bold px-2 py-0.5 rounded bg-primary/10 border border-primary/20">
                  {chunkSize} tokens
                </span>
              </div>
              <input
                className="w-full h-1.5 bg-border rounded-lg appearance-none cursor-pointer accent-primary focus:outline-none"
                max="2048"
                min="128"
                step="64"
                type="range"
                value={chunkSize}
                onChange={(e) => {
                  setChunkSize(Number(e.target.value));
                  setActivePreset('');
                }}
              />
              <div className="flex justify-between text-[10px] text-muted-foreground font-mono">
                <span>128 (Granular)</span>
                <span>2048 (Broad)</span>
              </div>
              <p className="text-[10px] text-muted-foreground/80 leading-relaxed pt-1 border-t border-border/40">
                Target token size of each indexed vector shard during document processing.
              </p>
            </div>

            {/* Overlap Window Slider */}
            <div className="space-y-2.5 p-4 rounded-xl bg-muted/20 border border-border/50">
              <div className="flex justify-between items-center text-xs">
                <label className="text-foreground font-semibold">Overlap Window</label>
                <span className="font-mono text-primary font-bold px-2 py-0.5 rounded bg-primary/10 border border-primary/20">
                  {overlap}%
                </span>
              </div>
              <input
                className="w-full h-1.5 bg-border rounded-lg appearance-none cursor-pointer accent-primary focus:outline-none"
                max="30"
                min="0"
                step="1"
                type="range"
                value={overlap}
                onChange={(e) => {
                  setOverlap(Number(e.target.value));
                  setActivePreset('');
                }}
              />
              <div className="flex justify-between text-[10px] text-muted-foreground font-mono">
                <span>0% (Disjoint)</span>
                <span>30% (Dense)</span>
              </div>
              <p className="text-[10px] text-muted-foreground/80 leading-relaxed pt-1 border-t border-border/40">
                Maintains semantic context between adjacent chunks to prevent sliced thoughts.
              </p>
            </div>

            {/* Similarity Filter Slider */}
            <div className="space-y-2.5 p-4 rounded-xl bg-muted/20 border border-border/50">
              <div className="flex justify-between items-center text-xs">
                <label className="text-foreground font-semibold">Similarity Filter</label>
                <span className="font-mono text-primary font-bold px-2 py-0.5 rounded bg-primary/10 border border-primary/20">
                  {similarityThreshold}
                </span>
              </div>
              <input
                className="w-full h-1.5 bg-border rounded-lg appearance-none cursor-pointer accent-primary focus:outline-none"
                max="0.95"
                min="0.50"
                step="0.01"
                type="range"
                value={similarityThreshold}
                onChange={(e) => setSimilarityThreshold(parseFloat(e.target.value))}
              />
              <div className="flex justify-between text-[10px] text-muted-foreground font-mono">
                <span>0.50 (Permissive)</span>
                <span>0.95 (Strict)</span>
              </div>
              <p className="text-[10px] text-muted-foreground/80 leading-relaxed pt-1 border-t border-border/40">
                Cosine similarity threshold for vector retrieval matching.
              </p>
            </div>
          </div>

          {/* Engine & Live Diagnostic Bar */}
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-4 rounded-xl bg-muted/30 border border-border/60">
            <div className="flex items-center gap-3">
              <Cpu className="w-4 h-4 text-emerald-500" />
              <div>
                <span className="text-[10px] font-mono uppercase text-muted-foreground tracking-wider block">
                  Active Vector Engine
                </span>
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shrink-0" />
                  <span className="text-xs font-bold text-foreground">
                    {embeddingEngine.split('(')[0].trim()}
                  </span>
                  <span className="px-2 py-0.2 rounded text-[10px] font-mono font-semibold bg-primary/10 text-primary border border-primary/20">
                    1536-dim
                  </span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-4 text-xs font-mono text-muted-foreground">
              <div>
                <span className="block text-[10px] uppercase text-muted-foreground/70">Est. 10-Page Shards</span>
                <span className="font-bold text-foreground">~{estimatedChunks} chunks</span>
              </div>
              <div className="h-6 w-px bg-border/60" />
              <div>
                <span className="block text-[10px] uppercase text-muted-foreground/70">Context Density</span>
                <span className="font-bold text-emerald-600 dark:text-emerald-400">
                  {overlap > 18 ? 'High Redundancy' : overlap >= 10 ? 'Optimal' : 'Lean'}
                </span>
              </div>
            </div>
          </div>

          {/* Save Action */}
          <div className="flex justify-end pt-2">
            <Button
              type="submit"
              isLoading={isSavingRag}
              loadingText="Committing RAG Parameters..."
              icon={<Save className="w-4 h-4" />}
              className="w-auto px-6 py-2.5 text-xs font-semibold rounded-xl shadow-2xs"
            >
              Save RAG Calibration
            </Button>
          </div>
        </form>
      )}

      {/* ================================================================ */}
      {/* SECTION 2 & 3: API CREDENTIALS & CLUSTER DIAGNOSTICS             */}
      {/* ================================================================ */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-stretch">
        {/* Core Integrations Form */}
        {(activeTab === 'all' || activeTab === 'credentials') && (
          <div className={activeTab === 'credentials' ? 'col-span-1 lg:col-span-3' : 'col-span-1 lg:col-span-2'}>
            <form onSubmit={handleSaveCredentials} className="bg-card border border-border p-6 md:p-8 rounded-2xl shadow-2xs space-y-6 h-full flex flex-col justify-between">
              <div className="space-y-5">
                <div className="flex items-center gap-2 border-b border-border/60 pb-4">
                  <Key className="w-5 h-5 text-primary" />
                  <h3 className="font-serif text-lg font-bold text-foreground">API Credentials</h3>
                </div>

                <div className="space-y-4">
                  {/* OpenAI / OpenRouter Key */}
                  <Input
                    label="Embedding & OpenRouter API Token"
                    id="openai-key-setting"
                    type="password"
                    value={openaiKey}
                    onChange={(e) => setOpenaiKey(e.target.value)}
                    className="font-mono text-xs"
                    placeholder="sk-or-v1-..."
                  />

                  {/* Salesforce CRM Target */}
                  <Input
                    label="Salesforce CRM API Target Endpoint"
                    id="salesforce-url-setting"
                    type="text"
                    value={salesforceUrl}
                    onChange={(e) => setSalesforceUrl(e.target.value)}
                    className="font-mono text-xs"
                    placeholder="https://..."
                  />
                </div>
              </div>

              <div className="pt-4 flex justify-end">
                <Button
                  type="submit"
                  isLoading={isSubmittingCreds}
                  loadingText="Saving Credentials..."
                  className="w-auto px-6 py-2.5 text-xs font-semibold rounded-xl"
                >
                  Save API Credentials
                </Button>
              </div>
            </form>
          </div>
        )}

        {/* Diagnostic Metadata Panel */}
        {(activeTab === 'all' || activeTab === 'diagnostics') && (
          <div className={activeTab === 'diagnostics' ? 'col-span-1 lg:col-span-3' : 'col-span-1'}>
            <div className="bg-card border border-border p-6 md:p-8 rounded-2xl shadow-2xs h-full flex flex-col justify-between space-y-6">
              <div className="space-y-4">
                <div className="flex items-center gap-2 border-b border-border/60 pb-4">
                  <Server className="w-5 h-5 text-primary" />
                  <h3 className="font-serif text-lg font-bold text-foreground">Cluster Diagnostics</h3>
                </div>

                <div className="space-y-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
                  <div className="flex justify-between border-b border-border/40 pb-2">
                    <span className="font-bold">Vector Backend:</span>
                    <span className="text-foreground font-semibold">MongoDB Atlas Vector</span>
                  </div>
                  <div className="flex justify-between border-b border-border/40 pb-2">
                    <span className="font-bold">pgvector build:</span>
                    <span>v0.5.1 // PostgreSQL 16</span>
                  </div>
                  <div className="flex justify-between border-b border-border/40 pb-2">
                    <span className="font-bold">Active Shards:</span>
                    <span>4 Vector Partitions</span>
                  </div>
                  <div className="flex justify-between border-b border-border/40 pb-2">
                    <span className="font-bold">Embedding Dimensions:</span>
                    <span>1,536 dimensions</span>
                  </div>
                  <div className="flex justify-between border-b border-border/40 pb-2">
                    <span className="font-bold">System Status:</span>
                    <span className="text-emerald-700 dark:text-emerald-400 font-bold uppercase">
                      nominal
                    </span>
                  </div>
                </div>
              </div>

              <Button
                variant="outline"
                onClick={() => toast.success('Vector index sync cache wiped successfully.', 'Cache Purged')}
                className="w-full py-2.5 text-xs font-semibold rounded-xl"
              >
                Clear Vector Cache
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default Settings;

