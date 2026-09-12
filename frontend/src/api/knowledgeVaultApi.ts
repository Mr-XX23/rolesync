import api from './axiosInstance';
import { getActiveTenantId } from './catalogApi';

export interface KnowledgeDocument {
  doc_id: string;
  name: string;
  type: string;
  size_bytes?: number;
  chunks: number;
  status: 'Indexed' | 'Parsing' | 'Error';
  created_at?: string;
  last_updated: string;
  source?: string;
  category?: string;
  target_competitor?: string | null;
  target_industry?: string | null;
  sales_summary?: string;
  sales_tags?: string[];
  classifier_used?: string;
  confidence_score?: number;
  error_message?: string;
  metadata?: {
    preview_snippet?: string;
    embedding_model?: string;
    total_tokens?: number;
    target_url?: string;
    parser_used?: string;
    sales_classification?: Record<string, any>;
    [key: string]: any;
  };
}

export interface VectorChunk {
  chunk_id: string;
  chunk_index: number;
  doc_ref_id?: string;
  prev_chunk_id?: string | null;
  next_chunk_id?: string | null;
  total_chunks?: number;
  text: string;
  token_count: number;
  dimension?: number;
  created_at?: string;
  metadata?: {
    category?: string;
    document_type?: string;
    target_competitor?: string | null;
    target_industry?: string | null;
    sales_tags?: string[];
    parser_used?: string;
    [key: string]: any;
  };
}

export interface DocumentVectorsResponse {
  status: string;
  doc_id: string;
  doc_ref_id?: string;
  name: string;
  type: string;
  category?: string;
  total_chunks: number;
  embedding_model: string;
  chunks: VectorChunk[];
}

export interface DocumentContentResponse {
  status: string;
  doc_id: string;
  doc_ref_id: string;
  filename: string;
  category: string;
  full_text: string;
  word_count: number;
  character_count: number;
}

export interface RagConfig {
  chunk_size: number;
  overlap: number;
  embedding_engine: string;
  similarity_threshold?: number;
}

export interface VaultStats {
  total_documents: number;
  total_chunks: number;
  total_size_bytes: number;
  active_sources_count: number;
  vector_backend: string;
  indexed_count: number;
  parsing_count: number;
  error_count: number;
  category_counts?: Record<string, number>;
}

// Local cache storage key
const STORAGE_KEY = 'rolesync_knowledge_vault_docs';
const CONFIG_KEY = 'rolesync_knowledge_vault_config';

const getLocalDocs = (): KnowledgeDocument[] => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        // Clean out any legacy mock docs
        const clean = parsed.filter((d) => !d.doc_id?.startsWith('doc_init_'));
        if (clean.length !== parsed.length) {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(clean));
        }
        return clean;
      }
    }
  } catch (e) {
    console.warn('[KnowledgeVaultApi] Local storage read error:', e);
  }
  // Pure empty by default — NO hardcoded files
  return [];
};

const saveLocalDocs = (docs: KnowledgeDocument[]) => {
  try {
    // Dedupe by doc_id (keeping the first/newest occurrence) so a re-uploaded or
    // re-fetched document can never leave a phantom duplicate row in the cache.
    const seen = new Set<string>();
    const unique = docs.filter((d) => {
      if (!d.doc_id || seen.has(d.doc_id)) return false;
      seen.add(d.doc_id);
      return true;
    });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(unique));
  } catch (e) {
    console.warn('[KnowledgeVaultApi] Local storage save error:', e);
  }
};

const getLocalConfig = (): RagConfig => {
  try {
    const raw = localStorage.getItem(CONFIG_KEY);
    if (raw) return JSON.parse(raw);
  } catch (e) {
    console.warn('[KnowledgeVaultApi] Local storage config read error:', e);
  }
  return {
    chunk_size: 512,
    overlap: 12,
    embedding_engine: 'RoleSync Vector Engine (1536-dim)',
  };
};

const saveLocalConfig = (config: RagConfig) => {
  try {
    localStorage.setItem(CONFIG_KEY, JSON.stringify(config));
  } catch (e) {
    console.warn('[KnowledgeVaultApi] Local storage config save error:', e);
  }
};

/**
 * The vault is shared by the active workspace (like the catalog): every call names it, and
 * data-pipeline checks the signed-in user is a member. The uploader comes from the session.
 */
const inWorkspace = (headers: Record<string, string> = {}) => ({
  headers: { ...headers, 'X-Tenant-Id': getActiveTenantId() },
});

export const knowledgeVaultApi = {
  // Fetch Vault Aggregated Stats
  getStats: async (): Promise<VaultStats> => {
    try {
      const response = await api.get<{ status: string; stats: VaultStats }>(
        '/data-pipeline/knowledge-vault/stats',
        inWorkspace()
      );
      if (response.data?.stats) {
        return response.data.stats;
      }
    } catch (err) {
      console.warn('[KnowledgeVaultApi] Live stats endpoint unreachable, calculating from local state:', err);
    }
    const docs = getLocalDocs();
    const categoryCounts: Record<string, number> = {
      BATTLECARD: 0,
      PRICING_PACKAGING: 0,
      CASE_STUDY_ROI: 0,
      SECURITY_COMPLIANCE: 0,
      PRODUCT_SPEC: 0,
      CONTRACT_LEGAL: 0,
      GENERAL_RESOURCE: 0,
    };
    docs.forEach((d) => {
      const c = d.category || 'GENERAL_RESOURCE';
      categoryCounts[c] = (categoryCounts[c] || 0) + 1;
    });

    return {
      total_documents: docs.length,
      total_chunks: docs.reduce((acc, d) => acc + (d.chunks || 0), 0),
      total_size_bytes: docs.reduce((acc, d) => acc + (d.size_bytes || 0), 0),
      active_sources_count: docs.length > 0 ? new Set(docs.map((d) => d.source || 'USER_UPLOAD')).size : 0,
      vector_backend: 'MongoDB Vector Mesh',
      indexed_count: docs.filter((d) => d.status === 'Indexed').length,
      parsing_count: docs.filter((d) => d.status === 'Parsing').length,
      error_count: docs.filter((d) => d.status === 'Error').length,
      category_counts: categoryCounts,
    };
  },

  // Fetch Documents
  getDocuments: async (status?: string, search?: string, category?: string): Promise<KnowledgeDocument[]> => {
    try {
      const params = new URLSearchParams();
      if (status && status !== 'all') params.append('status', status);
      if (category && category !== 'all') params.append('category', category);
      if (search) params.append('search', search);

      const response = await api.get<{ status: string; documents: KnowledgeDocument[] }>(
        `/data-pipeline/knowledge-vault/documents?${params.toString()}`,
        inWorkspace()
      );
      if (response.data?.documents) {
        saveLocalDocs(response.data.documents);
        return response.data.documents;
      }
    } catch (err) {
      console.warn('[KnowledgeVaultApi] Live documents endpoint unreachable, returning local docs:', err);
    }

    let docs = getLocalDocs();
    if (status && status !== 'all') {
      docs = docs.filter((d) => d.status.toLowerCase() === status.toLowerCase());
    }
    if (category && category !== 'all') {
      docs = docs.filter((d) => (d.category || 'GENERAL_RESOURCE').toUpperCase() === category.toUpperCase());
    }
    if (search) {
      const s = search.toLowerCase();
      docs = docs.filter(
        (d) =>
          d.name.toLowerCase().includes(s) ||
          d.type.toLowerCase().includes(s) ||
          (d.category && d.category.toLowerCase().includes(s)) ||
          (d.target_competitor && d.target_competitor.toLowerCase().includes(s)) ||
          (d.sales_tags && d.sales_tags.some((t) => t.toLowerCase().includes(s)))
      );
    }
    return docs;
  },

  // Upload Single File to real backend pipeline
  uploadFile: async (file: File, category?: string, targetCompetitor?: string): Promise<KnowledgeDocument> => {
    const formData = new FormData();
    formData.append('file', file);
    if (category) formData.append('category', category);
    if (targetCompetitor) formData.append('target_competitor', targetCompetitor);

    try {
      const response = await api.post<{ status: string; document: KnowledgeDocument }>(
        '/data-pipeline/knowledge-vault/upload',
        formData,
        inWorkspace({ 'Content-Type': 'multipart/form-data' })
      );
      if (response.data?.document) {
        const local = getLocalDocs();
        saveLocalDocs([response.data.document, ...local]);
        return response.data.document;
      }
    } catch (err: any) {
      console.warn('[KnowledgeVaultApi] Upload API response error:', err);
      if (err.response?.data?.detail) {
        throw new Error(err.response.data.detail);
      }
      throw err;
    }

    throw new Error('Upload endpoint did not return document.');
  },

  // Ingest URL to real backend pipeline
  ingestUrl: async (
    url: string,
    title?: string,
    category?: string,
    targetCompetitor?: string
  ): Promise<KnowledgeDocument> => {
    try {
      const response = await api.post<{ status: string; document: KnowledgeDocument }>(
        '/data-pipeline/knowledge-vault/ingest-url',
        { url, title, category, target_competitor: targetCompetitor },
        inWorkspace()
      );
      if (response.data?.document) {
        const local = getLocalDocs();
        saveLocalDocs([response.data.document, ...local]);
        return response.data.document;
      }
    } catch (err: any) {
      console.warn('[KnowledgeVaultApi] Ingest URL API error:', err);
      if (err.response?.data?.detail) {
        throw new Error(err.response.data.detail);
      }
      throw err;
    }

    throw new Error('Ingest URL endpoint did not return document.');
  },

  // Update Sales Classification
  updateSalesClassification: async (
    docId: string,
    data: {
      category?: string;
      target_competitor?: string | null;
      target_industry?: string | null;
      sales_summary?: string;
      sales_tags?: string[];
    }
  ): Promise<KnowledgeDocument> => {
    try {
      const response = await api.patch<{ status: string; document: KnowledgeDocument }>(
        `/data-pipeline/knowledge-vault/documents/${encodeURIComponent(docId)}/sales-classification`,
        data,
        inWorkspace()
      );
      if (response.data?.document) {
        const local = getLocalDocs();
        const updated = local.map((d) => (d.doc_id === docId ? response.data.document : d));
        saveLocalDocs(updated);
        return response.data.document;
      }
    } catch (err: any) {
      console.warn('[KnowledgeVaultApi] Update sales classification error:', err);
      if (err.response?.data?.detail) {
        throw new Error(err.response.data.detail);
      }
    }

    // Local fallback update
    const local = getLocalDocs();
    const updated = local.map((d) =>
      d.doc_id === docId
        ? {
            ...d,
            ...data,
            classifier_used: 'manual_user_override',
            confidence_score: 1.0,
            last_updated: 'Just now',
          }
        : d
    );
    saveLocalDocs(updated);
    return updated.find((d) => d.doc_id === docId)!;
  },

  // Reclassify Document with AI
  reclassifyDocument: async (docId: string): Promise<KnowledgeDocument> => {
    try {
      const response = await api.post<{ status: string; document: KnowledgeDocument }>(
        `/data-pipeline/knowledge-vault/documents/${encodeURIComponent(docId)}/reclassify`,
        undefined,
        inWorkspace()
      );
      if (response.data?.document) {
        const local = getLocalDocs();
        const updated = local.map((d) => (d.doc_id === docId ? response.data.document : d));
        saveLocalDocs(updated);
        return response.data.document;
      }
    } catch (err: any) {
      console.warn('[KnowledgeVaultApi] Reclassify API error:', err);
      if (err.response?.data?.detail) {
        throw new Error(err.response.data.detail);
      }
    }

    const local = getLocalDocs();
    return local.find((d) => d.doc_id === docId)!;
  },

  // Get Vectors for Document
  getDocumentVectors: async (docId: string): Promise<DocumentVectorsResponse> => {
    try {
      const response = await api.get<DocumentVectorsResponse>(
        `/data-pipeline/knowledge-vault/documents/${encodeURIComponent(docId)}/vectors`,
        inWorkspace()
      );
      if (response.data?.chunks) {
        return response.data;
      }
    } catch (err) {
      console.warn('[KnowledgeVaultApi] Vectors endpoint error:', err);
    }

    const docs = getLocalDocs();
    const doc = docs.find((d) => d.doc_id === docId);
    return {
      status: 'success',
      doc_id: docId,
      name: doc?.name || 'Document Preview',
      type: doc?.type || 'DOC',
      total_chunks: doc?.chunks || 0,
      embedding_model: doc?.metadata?.embedding_model || 'RoleSync Vector Engine (1536-dim)',
      chunks: [],
    };
  },

  // Delete Document
  deleteDocument: async (docId: string): Promise<void> => {
    try {
      await api.delete(`/data-pipeline/knowledge-vault/documents/${encodeURIComponent(docId)}`, inWorkspace());
    } catch (err) {
      console.warn('[KnowledgeVaultApi] Delete API error:', err);
    }
    const current = getLocalDocs().filter((d) => d.doc_id !== docId);
    saveLocalDocs(current);
  },

  // Reindex Document
  reindexDocument: async (docId: string): Promise<KnowledgeDocument> => {
    try {
      const response = await api.post<{ status: string; document: KnowledgeDocument }>(
        `/data-pipeline/knowledge-vault/documents/${encodeURIComponent(docId)}/reindex`,
        undefined,
        inWorkspace()
      );
      if (response.data?.document) {
        return response.data.document;
      }
    } catch (err) {
      console.warn('[KnowledgeVaultApi] Reindex API error:', err);
    }

    const current = getLocalDocs();
    const updated = current.map((d) =>
      d.doc_id === docId
        ? {
            ...d,
            status: 'Parsing' as const,
            last_updated: 'Just now',
            chunks: 0,
          }
        : d
    );
    saveLocalDocs(updated);
    return updated.find((d) => d.doc_id === docId)!;
  },

  // Fetch RAG Config
  getRagConfig: async (): Promise<RagConfig> => {
    try {
      const response = await api.get<{ status: string; config: RagConfig }>(
        '/data-pipeline/knowledge-vault/config',
        inWorkspace()
      );
      if (response.data?.config) {
        saveLocalConfig(response.data.config);
        return response.data.config;
      }
    } catch (err) {
      console.warn('[KnowledgeVaultApi] RAG config endpoint error:', err);
    }
    return getLocalConfig();
  },

  // Save RAG Config
  saveRagConfig: async (config: RagConfig): Promise<RagConfig> => {
    try {
      const response = await api.post<{ status: string; config: RagConfig }>(
        '/data-pipeline/knowledge-vault/config',
        config,
        inWorkspace()
      );
      if (response.data?.config) {
        saveLocalConfig(response.data.config);
        return response.data.config;
      }
    } catch (err) {
      console.warn('[KnowledgeVaultApi] Save RAG config error:', err);
    }
    saveLocalConfig(config);
    return config;
  },

  // Get full document unfragmented content
  getDocumentFullContent: async (docId: string): Promise<DocumentContentResponse> => {
    const response = await api.get<DocumentContentResponse>(
      `/data-pipeline/knowledge-vault/documents/${encodeURIComponent(docId)}/content`,
      inWorkspace()
    );
    return response.data;
  },

  // Download raw document
  downloadRawDocument: async (docId: string, filename: string = 'document'): Promise<void> => {
    const response = await api.get(`/data-pipeline/knowledge-vault/documents/${encodeURIComponent(docId)}/download`, {
      ...inWorkspace(),
      responseType: 'blob',
    });
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    link.parentNode?.removeChild(link);
    window.URL.revokeObjectURL(url);
  },

  // Backfill existing chunks
  backfillExistingChunks: async (): Promise<{ status: string; updated_chunks: number }> => {
    const response = await api.post<{ status: string; updated_chunks: number }>(
      '/data-pipeline/knowledge-vault/backfill-chunks',
      undefined,
      inWorkspace()
    );
    return response.data;
  },
};
