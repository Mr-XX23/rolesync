import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Globe } from 'lucide-react';
import { useToast } from '../../../context/ToastContext';
import { useAppSelector } from '../../../store';
import {
  knowledgeVaultApi,
  type KnowledgeDocument,
  type VaultStats,
} from '../../../api/knowledgeVaultApi';
import { useAdaptivePolling } from './useAdaptivePolling';
import { VectorInspectorModal } from './VectorInspectorModal';
import { IngestUrlModal } from './IngestUrlModal';
import { DeleteConfirmModal } from './DeleteConfirmModal';
import { EditSalesMetadataModal } from './EditSalesMetadataModal';
import { VaultMetricsCards } from './VaultMetricsCards';
import { VaultDropzone } from './VaultDropzone';
import { PipelineTable } from './PipelineTable';
import {
  MAX_FILE_SIZE_BYTES,
  ALLOWED_EXTENSIONS,
} from './vaultUtils';

export const KnowledgeVault: React.FC = () => {
  const navigate = useNavigate();
  const toast = useToast();
  const activeUser = useAppSelector((state) => state.auth.user);
  const userId = activeUser?.userId || 'usr_active';

  // Active Calibrated RAG Parameters (configured via Settings)
  const [chunkSize, setChunkSize] = useState(512);
  const [overlap, setOverlap] = useState(12);
  const [embeddingEngine, setEmbeddingEngine] = useState('RoleSync Vector Engine (1536-dim)');

  // Documents & Stats States
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [stats, setStats] = useState<VaultStats | null>(null);
  const [isLoadingDocs, setIsLoadingDocs] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Ingestion & Drag States
  const [filter, setFilter] = useState<'all' | 'Indexed' | 'Parsing' | 'Error'>('all');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const [uploadQueue, setUploadQueue] = useState<string[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Modals States
  const [inspectorDoc, setInspectorDoc] = useState<{ id: string; name: string } | null>(null);
  const [isUrlModalOpen, setIsUrlModalOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string; isAbort: boolean } | null>(null);
  const [editingSalesDoc, setEditingSalesDoc] = useState<KnowledgeDocument | null>(null);

  // Load Vault Data
  const loadVaultData = useCallback(
    async (showToastNotice = false) => {
      try {
        const [docsData, statsData, configData] = await Promise.all([
          knowledgeVaultApi.getDocuments(userId),
          knowledgeVaultApi.getStats(userId),
          knowledgeVaultApi.getRagConfig(userId),
        ]);
        setDocuments(docsData);
        setStats(statsData);
        if (configData) {
          setChunkSize(configData.chunk_size || 512);
          setOverlap(configData.overlap || 12);
          setEmbeddingEngine(configData.embedding_engine || 'RoleSync Vector Engine (1536-dim)');
        }
        if (showToastNotice) {
          toast.success('Knowledge Vault pipeline synchronized.', 'Synchronized');
        }
      } catch (err) {
        console.error('[KnowledgeVault] Failed to load data:', err);
        if (showToastNotice) {
          toast.error('Failed to synchronize Knowledge Vault pipeline.');
        }
      } finally {
        setIsLoadingDocs(false);
        setIsRefreshing(false);
      }
    },
    [userId, toast]
  );

  useEffect(() => {
    loadVaultData();
  }, [loadVaultData]);

  // Check if any documents are actively parsing
  const hasIncompleteDocuments = useMemo(() => {
    return documents.some((d) => d.status === 'Parsing');
  }, [documents]);

  // Hybrid Activity-Aware Adaptive Polling
  const pollIncompleteDocuments = useCallback(async () => {
    try {
      const docs = await knowledgeVaultApi.getDocuments(userId);
      const updatedStats = await knowledgeVaultApi.getStats(userId);
      setDocuments(docs);
      setStats(updatedStats);

      const stillParsing = docs.some((d) => d.status === 'Parsing');
      if (!stillParsing && hasIncompleteDocuments) {
        toast.success('All documents have finished vector ingestion.', 'Indexing Complete');
      }
    } catch (e) {
      console.warn('[KnowledgeVault] Adaptive poll silent error:', e);
    }
  }, [userId, hasIncompleteDocuments, toast]);

  useAdaptivePolling({
    callback: pollIncompleteDocuments,
    enabled: hasIncompleteDocuments,
    minIntervalMs: 3000,
    idleTimeoutMs: 45000,
  });

  // Handle Drag Events
  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  }, []);

  // Process File Uploads with validation
  const processFiles = useCallback(
    async (files: FileList | File[]) => {
      const fileList = Array.from(files);
      if (fileList.length === 0) return;

      for (const file of fileList) {
        const ext = file.name.split('.').pop()?.toUpperCase() || '';

        // Size Validation
        if (file.size > MAX_FILE_SIZE_BYTES) {
          toast.error(
            `File "${file.name}" exceeds the 25MB limit (${(file.size / (1024 * 1024)).toFixed(1)}MB).`,
            'File Too Large'
          );
          continue;
        }

        // Format Validation
        if (!ALLOWED_EXTENSIONS.includes(ext)) {
          toast.warning(
            `"${file.name}" format (.${ext.toLowerCase()}) is not supported. Supported: ${ALLOWED_EXTENSIONS.join(', ')}`,
            'Unsupported Format'
          );
          continue;
        }

        // Add to upload queue
        setUploadQueue((prev) => [...prev, file.name]);

        try {
          const newDoc = await knowledgeVaultApi.uploadFile(file, userId);
          setDocuments((prev) => [newDoc, ...prev.filter((d) => d.doc_id !== newDoc.doc_id)]);
          toast.success(`"${file.name}" queued for parsing & vectorization.`, 'Uploaded');
          // Refresh stats in background
          knowledgeVaultApi.getStats(userId).then(setStats);
        } catch (err: any) {
          console.error('[KnowledgeVault] File upload error:', err);
          toast.error(err.message || `Failed to upload "${file.name}".`, 'Upload Error');
        } finally {
          setUploadQueue((prev) => prev.filter((name) => name !== file.name));
        }
      }
    },
    [userId, toast]
  );

  // Drag & Drop Handler
  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragActive(false);
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        processFiles(e.dataTransfer.files);
      }
    },
    [processFiles]
  );

  // File Input Change
  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        processFiles(e.target.files);
        e.target.value = '';
      }
    },
    [processFiles]
  );



  // Manual Refresh
  const handleRefresh = useCallback(() => {
    setIsRefreshing(true);
    loadVaultData(true);
  }, [loadVaultData]);

  // Re-index Document
  const handleReindex = useCallback(
    async (docId: string, docName: string) => {
      // Optimistically set parsing in UI
      setDocuments((prev) =>
        prev.map((d) => (d.doc_id === docId ? { ...d, status: 'Parsing' as const, chunks: 0 } : d))
      );
      try {
        const updated = await knowledgeVaultApi.reindexDocument(docId);
        setDocuments((prev) => prev.map((d) => (d.doc_id === docId ? updated : d)));
        toast.success(`Re-indexing triggered for "${docName}".`, 'Re-indexing Queued');
      } catch (err) {
        console.error('[KnowledgeVault] Reindex error:', err);
        toast.error(`Failed to re-index "${docName}".`);
        loadVaultData();
      }
    },
    [toast, loadVaultData]
  );

  // Optimistic Document Deletion / Abort
  const handleConfirmDelete = useCallback(async () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    const previousDocs = documents;

    // Optimistically remove from list
    setDocuments((prev) => prev.filter((d) => d.doc_id !== target.id));
    setDeleteTarget(null);

    try {
      await knowledgeVaultApi.deleteDocument(target.id);
      knowledgeVaultApi.getStats(userId).then(setStats);
      toast.success(
        target.isAbort
          ? `Ingestion for "${target.name}" was aborted.`
          : `"${target.name}" and its vector shards were purged.`,
        target.isAbort ? 'Aborted' : 'Document Purged'
      );
    } catch (err) {
      console.error('[KnowledgeVault] Delete error:', err);
      toast.error(`Failed to remove "${target.name}".`);
      // Rollback on failure
      setDocuments(previousDocs);
    }
  }, [deleteTarget, documents, userId, toast]);

  // Save Sales Classification
  const handleSaveSalesClassification = useCallback(
    async (
      docId: string,
      data: {
        category: string;
        target_competitor: string | null;
        target_industry: string | null;
        sales_summary: string;
        sales_tags: string[];
      }
    ) => {
      const updated = await knowledgeVaultApi.updateSalesClassification(docId, data);
      setDocuments((prev) => prev.map((d) => (d.doc_id === docId ? updated : d)));
      knowledgeVaultApi.getStats(userId).then(setStats);
      toast.success(`Updated sales intelligence for "${updated.name}".`, 'Saved');
    },
    [userId, toast]
  );

  // Reclassify Document with AI
  const handleReclassify = useCallback(
    async (docId: string) => {
      const updated = await knowledgeVaultApi.reclassifyDocument(docId);
      setDocuments((prev) => prev.map((d) => (d.doc_id === docId ? updated : d)));
      knowledgeVaultApi.getStats(userId).then(setStats);
      toast.success(`Re-classified "${updated.name}" as ${updated.category}.`, 'AI Classified');
      return updated;
    },
    [userId, toast]
  );

  // Filter & Search Documents
  const filteredDocuments = useMemo(() => {
    return documents.filter((doc) => {
      if (filter !== 'all' && doc.status !== filter) {
        return false;
      }
      if (categoryFilter !== 'all') {
        const docCat = (doc.category || 'GENERAL_RESOURCE').toUpperCase();
        if (docCat !== categoryFilter.toUpperCase()) {
          return false;
        }
      }
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase();
        const matchesName = doc.name.toLowerCase().includes(query);
        const matchesType = doc.type.toLowerCase().includes(query);
        const matchesCat = doc.category?.toLowerCase().includes(query);
        const matchesComp = doc.target_competitor?.toLowerCase().includes(query);
        const matchesInd = doc.target_industry?.toLowerCase().includes(query);
        const matchesTags = doc.sales_tags?.some((t) => t.toLowerCase().includes(query));
        const matchesSnippet = doc.metadata?.preview_snippet?.toLowerCase().includes(query);
        return (
          matchesName ||
          matchesType ||
          Boolean(matchesCat) ||
          Boolean(matchesComp) ||
          Boolean(matchesInd) ||
          Boolean(matchesTags) ||
          Boolean(matchesSnippet)
        );
      }
      return true;
    });
  }, [documents, filter, categoryFilter, searchQuery]);

  return (
    <div className="space-y-8 animate-in fade-in duration-500 pb-16">
      {/* Page Header */}
      <section className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <h2 className="font-serif text-3xl font-bold text-primary">Knowledge Vault</h2>
            <span className="font-mono text-[10px] px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-bold border border-emerald-500/20">
              LIVE MESH
            </span>
          </div>
          <p className="text-sm text-muted-foreground max-w-xl leading-relaxed">
            Your central repository for sales materials. Upload battlecards, pricing sheets, and product specs to power your AI assistant with accurate deal intelligence.
          </p>
        </div>
      </section>

      {/* Dynamic KPI Metric Cards */}
      <VaultMetricsCards
        stats={stats}
        documentsCount={documents.length}
        indexedCount={documents.filter((d) => d.status === 'Indexed').length}
        fallbackChunks={documents.reduce((a, b) => a + (b.chunks || 0), 0)}
        fallbackBytes={documents.reduce((a, b) => a + (b.size_bytes || 0), 0)}
        onConnectorsClick={() => navigate('/salesman/external-connector')}
      />

      {/* Document Ingestion Hero Dropzone */}
      <VaultDropzone
        dragActive={dragActive}
        uploadQueue={uploadQueue}
        fileInputRef={fileInputRef}
        onDrag={handleDrag}
        onDrop={handleDrop}
        onFileChange={handleFileChange}
        onOpenUrlModal={() => setIsUrlModalOpen(true)}
        ragConfigSummary={{
          chunkSize,
          overlap,
          engine: embeddingEngine,
        }}
        onConfigureSettings={() => navigate('/salesman/settings')}
      />

      {/* Ingestion Table Panel */}
      <PipelineTable
        documents={documents}
        filteredDocuments={filteredDocuments}
        isLoading={isLoadingDocs}
        isRefreshing={isRefreshing}
        filter={filter}
        categoryFilter={categoryFilter}
        searchQuery={searchQuery}
        hasIncompleteDocuments={hasIncompleteDocuments}
        onFilterChange={setFilter}
        onCategoryFilterChange={setCategoryFilter}
        onSearchChange={setSearchQuery}
        onRefresh={handleRefresh}
        onUploadClick={() => fileInputRef.current?.click()}
        onInspectDoc={setInspectorDoc}
        onEditSalesIntelligence={setEditingSalesDoc}
        onReindex={handleReindex}
        onDeleteRequest={setDeleteTarget}
      />

      {/* Floating Action Button for Quick URL Ingestion */}
      <button
        onClick={() => setIsUrlModalOpen(true)}
        className="fixed bottom-8 right-8 w-14 h-14 bg-primary text-primary-foreground rounded-full shadow-lg flex items-center justify-center hover:scale-105 active:scale-95 transition-all z-40 group border border-primary/20 cursor-pointer"
        title="Ingest Business Webpage"
      >
        <Globe className="w-6 h-6 transition-transform group-hover:rotate-12 duration-300" />
        <span className="absolute right-full mr-4 bg-primary text-primary-foreground font-semibold px-3 py-1.5 rounded-xl text-xs whitespace-nowrap opacity-0 group-hover:opacity-100 transition-all duration-300 scale-90 group-hover:scale-100 translate-x-2 group-hover:translate-x-0 shadow-sm pointer-events-none">
          Ingest Webpage URL
        </span>
      </button>

      {/* Modals */}
      <VectorInspectorModal
        isOpen={!!inspectorDoc}
        onClose={() => setInspectorDoc(null)}
        docId={inspectorDoc?.id || ''}
        docName={inspectorDoc?.name || ''}
      />

      <IngestUrlModal
        isOpen={isUrlModalOpen}
        onClose={() => setIsUrlModalOpen(false)}
        onSuccess={(newDoc) => {
          setDocuments((prev) => [newDoc, ...prev.filter((d) => d.doc_id !== newDoc.doc_id)]);
          knowledgeVaultApi.getStats(userId).then(setStats);
        }}
      />

      <EditSalesMetadataModal
        isOpen={!!editingSalesDoc}
        document={editingSalesDoc}
        onClose={() => setEditingSalesDoc(null)}
        onSave={handleSaveSalesClassification}
        onReclassify={handleReclassify}
      />

      <DeleteConfirmModal
        isOpen={!!deleteTarget}
        docName={deleteTarget?.name || ''}
        isAbort={!!deleteTarget?.isAbort}
        onConfirm={handleConfirmDelete}
        onClose={() => setDeleteTarget(null)}
      />
    </div>
  );
};

export default KnowledgeVault;
