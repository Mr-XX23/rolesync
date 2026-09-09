import React, { useState, useEffect, useMemo } from 'react';
import {
  X,
  Copy,
  Check,
  Search,
  Layers,
  Cpu,
  Hash,
  FileText,
  Loader2,
  Sparkles,
  Download,
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Tag,
} from 'lucide-react';
import { Button } from '../../../components/common/Button';
import { useToast } from '../../../context/ToastContext';
import {
  knowledgeVaultApi,
  type DocumentVectorsResponse,
  type DocumentContentResponse,
} from '../../../api/knowledgeVaultApi';

interface VectorInspectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  docId: string;
  docName: string;
}

export const VectorInspectorModal: React.FC<VectorInspectorModalProps> = ({
  isOpen,
  onClose,
  docId,
  docName,
}) => {
  const toast = useToast();
  const [activeTab, setActiveTab] = useState<'chunks' | 'fullDoc'>('chunks');
  const [loading, setLoading] = useState(true);
  const [vectorData, setVectorData] = useState<DocumentVectorsResponse | null>(null);
  const [fullDocContent, setFullDocContent] = useState<DocumentContentResponse | null>(null);
  const [fullDocLoading, setFullDocLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [chunkFilter, setChunkFilter] = useState('');

  useEffect(() => {
    if (!isOpen || !docId) return;

    let isMounted = true;
    setLoading(true);
    setChunkFilter('');
    setActiveTab('chunks');

    knowledgeVaultApi
      .getDocumentVectors(docId)
      .then((data) => {
        if (isMounted) {
          setVectorData(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          console.error('[VectorInspectorModal] Error fetching vectors:', err);
          toast.error('Failed to load vector chunks for this document.');
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [isOpen, docId]);

  // Lazy-load full document text when user switches to fullDoc tab
  useEffect(() => {
    if (activeTab === 'fullDoc' && !fullDocContent && docId) {
      setFullDocLoading(true);
      knowledgeVaultApi
        .getDocumentFullContent(docId)
        .then((res) => {
          setFullDocContent(res);
          setFullDocLoading(false);
        })
        .catch((err) => {
          console.error('[VectorInspectorModal] Error loading full document:', err);
          toast.error('Could not retrieve full document text.');
          setFullDocLoading(false);
        });
    }
  }, [activeTab, docId, fullDocContent]);

  const handleCopy = (id: string, text: string, label: string = 'Content') => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    toast.success(`${label} copied to clipboard.`);
    setTimeout(() => {
      setCopiedId(null);
    }, 2000);
  };

  const handleDownload = async () => {
    try {
      setDownloading(true);
      await knowledgeVaultApi.downloadRawDocument(docId, docName || `${docId}.txt`);
      toast.success('Original document downloaded.');
    } catch (err) {
      console.error('[VectorInspectorModal] Download error:', err);
      toast.error('Failed to download original document.');
    } finally {
      setDownloading(false);
    }
  };

  const filteredChunks = useMemo(() => {
    if (!vectorData?.chunks) return [];
    if (!chunkFilter.trim()) return vectorData.chunks;
    const term = chunkFilter.toLowerCase();
    return vectorData.chunks.filter(
      (c) =>
        c.text.toLowerCase().includes(term) ||
        c.chunk_id.toLowerCase().includes(term) ||
        `chunk ${c.chunk_index + 1}`.includes(term) ||
        (c.metadata?.category && c.metadata.category.toLowerCase().includes(term))
    );
  }, [vectorData, chunkFilter]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-sm animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="bg-card border border-border rounded-2xl max-w-4xl w-full max-h-[90vh] flex flex-col shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-muted/30">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 text-primary flex items-center justify-center shadow-2xs">
              <Layers className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-serif text-lg font-bold text-foreground truncate max-w-md">
                  {docName || 'Document & Vector Inspector'}
                </h3>
                <span className="font-mono text-[10px] px-2 py-0.5 rounded-md bg-primary/10 text-primary font-bold border border-primary/20">
                  {vectorData?.type || 'DOCUMENT'}
                </span>
                {vectorData?.category && (
                  <span className="font-mono text-[10px] px-2 py-0.5 rounded-md bg-accent/20 text-accent font-semibold border border-accent/30">
                    {vectorData.category}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <p className="text-xs text-muted-foreground">
                  Parent Doc Ref:{' '}
                  <span className="font-mono text-foreground font-semibold">
                    {vectorData?.doc_ref_id || docId}
                  </span>
                </p>
                <button
                  type="button"
                  onClick={() => handleCopy('doc_ref', vectorData?.doc_ref_id || docId, 'Doc Ref ID')}
                  className="text-muted-foreground hover:text-foreground cursor-pointer"
                  title="Copy Document Reference ID"
                >
                  {copiedId === 'doc_ref' ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
                </button>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleDownload}
              disabled={downloading}
              className="px-3 py-1.5 rounded-lg border border-border/70 text-xs text-foreground bg-background hover:bg-muted transition-colors flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
              title="Download original file"
            >
              {downloading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5 text-primary" />}
              <span>Download Raw</span>
            </button>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors cursor-pointer"
              aria-label="Close modal"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* View Tabs */}
        <div className="flex items-center gap-2 px-6 pt-2 border-b border-border bg-muted/10">
          <button
            type="button"
            onClick={() => setActiveTab('chunks')}
            className={`px-4 py-2 text-xs font-semibold border-b-2 transition-all cursor-pointer flex items-center gap-2 ${
              activeTab === 'chunks'
                ? 'border-primary text-primary bg-primary/5'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>Vector Chunks ({vectorData?.total_chunks || vectorData?.chunks?.length || 0})</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('fullDoc')}
            className={`px-4 py-2 text-xs font-semibold border-b-2 transition-all cursor-pointer flex items-center gap-2 ${
              activeTab === 'fullDoc'
                ? 'border-primary text-primary bg-primary/5'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            <BookOpen className="w-3.5 h-3.5" />
            <span>Full Unfragmented Document</span>
          </button>
        </div>

        {/* Overview Badges */}
        <div className="grid grid-cols-3 gap-3 px-6 py-2.5 border-b border-border/60 bg-muted/10 text-xs">
          <div className="flex items-center gap-2">
            <Hash className="w-4 h-4 text-primary shrink-0" />
            <div>
              <span className="text-muted-foreground block text-[10px] uppercase font-mono">
                Total Chunks
              </span>
              <span className="font-mono font-bold text-foreground">
                {loading ? '...' : vectorData?.total_chunks || vectorData?.chunks.length || 0}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Cpu className="w-4 h-4 text-primary shrink-0" />
            <div>
              <span className="text-muted-foreground block text-[10px] uppercase font-mono">
                Embedding Model
              </span>
              <span className="font-mono font-semibold text-foreground truncate max-w-[180px] block">
                {loading ? '...' : vectorData?.embedding_model || 'RoleSync Vector Engine (1536-dim)'}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-emerald-500 shrink-0" />
            <div>
              <span className="text-muted-foreground block text-[10px] uppercase font-mono">
                RAG Context Linking
              </span>
              <span className="font-mono font-bold text-emerald-600 dark:text-emerald-400">
                BIDIRECTIONAL LINKED
              </span>
            </div>
          </div>
        </div>

        {activeTab === 'chunks' ? (
          <>
            {/* Filter bar */}
            <div className="px-6 py-3 border-b border-border/40 flex items-center gap-3">
              <div className="relative flex-1">
                <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <input
                  type="text"
                  placeholder="Search vector text, chunk #, category, or competitor..."
                  value={chunkFilter}
                  onChange={(e) => setChunkFilter(e.target.value)}
                  className="w-full pl-9 pr-4 py-2 bg-background border border-border rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary"
                />
              </div>
              {chunkFilter && (
                <button
                  onClick={() => setChunkFilter('')}
                  className="text-xs text-muted-foreground hover:text-foreground underline cursor-pointer"
                >
                  Clear Filter
                </button>
              )}
            </div>

            {/* Chunks Content Area */}
            <div className="flex-1 overflow-y-auto p-6 space-y-4 max-h-[50vh]">
              {loading ? (
                <div className="flex flex-col items-center justify-center py-16 text-center space-y-3">
                  <Loader2 className="w-8 h-8 text-primary animate-spin" />
                  <p className="text-xs text-muted-foreground font-mono">
                    Retrieving linked vector shards from MongoDB / pgvector...
                  </p>
                </div>
              ) : filteredChunks.length === 0 ? (
                <div className="py-12 text-center text-muted-foreground space-y-2">
                  <FileText className="w-8 h-8 mx-auto opacity-40 mb-2" />
                  <p className="text-xs font-medium">
                    {chunkFilter ? 'No vector chunks matched your search criteria.' : 'No vector chunks found for this document.'}
                  </p>
                  {chunkFilter && (
                    <p className="text-[11px] opacity-70">
                      Try clearing the search filter or refining terms.
                    </p>
                  )}
                </div>
              ) : (
                filteredChunks.map((chunk) => {
                  const isCopied = copiedId === chunk.chunk_id;
                  const totalChunks = chunk.total_chunks || vectorData?.total_chunks || vectorData?.chunks?.length || 1;
                  const category = chunk.metadata?.category || vectorData?.category;
                  const competitor = chunk.metadata?.target_competitor;

                  return (
                    <div
                      key={chunk.chunk_id}
                      className="bg-muted/30 hover:bg-muted/50 border border-border/60 rounded-xl p-4 transition-all duration-200"
                    >
                      {/* Top Header of Chunk Card */}
                      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[10px] font-bold px-2 py-0.5 rounded-md bg-background text-primary border border-border/50">
                            Chunk #{chunk.chunk_index + 1} of {totalChunks}
                          </span>
                          <span className="font-mono text-[10px] text-muted-foreground">
                            {chunk.chunk_id}
                          </span>
                        </div>

                        {/* Metadata Tags & Copy */}
                        <div className="flex items-center gap-1.5">
                          {category && (
                            <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-primary/10 text-primary border border-primary/20 flex items-center gap-1">
                              <Tag className="w-2.5 h-2.5" />
                              {category}
                            </span>
                          )}
                          {competitor && (
                            <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-500 border border-amber-500/20">
                              vs {competitor}
                            </span>
                          )}
                          <span className="font-mono text-[10px] text-muted-foreground bg-background px-2 py-0.5 rounded-md border border-border/40">
                            {chunk.token_count} tokens
                          </span>
                          <button
                            type="button"
                            onClick={() => handleCopy(chunk.chunk_id, chunk.text, `Chunk #${chunk.chunk_index + 1}`)}
                            className={`p-1.5 rounded-lg border text-xs flex items-center gap-1 transition-all cursor-pointer ${
                              isCopied
                                ? 'bg-emerald-500/10 text-emerald-600 border-emerald-500/30'
                                : 'bg-background hover:bg-card text-muted-foreground hover:text-foreground border-border/60'
                            }`}
                            title="Copy chunk content"
                          >
                            {isCopied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                            <span className="text-[10px] font-medium">{isCopied ? 'Copied' : 'Copy'}</span>
                          </button>
                        </div>
                      </div>

                      {/* Text Segment */}
                      <p className="text-xs font-mono text-foreground/90 bg-background/80 p-3 rounded-lg border border-border/40 whitespace-pre-wrap leading-relaxed max-h-36 overflow-y-auto">
                        {chunk.text}
                      </p>

                      {/* Bidirectional Context Links Footer */}
                      <div className="flex items-center justify-between pt-2.5 mt-2.5 border-t border-border/30 text-[11px] font-mono">
                        <div className="flex items-center gap-1.5">
                          {chunk.prev_chunk_id ? (
                            <button
                              type="button"
                              onClick={() => setChunkFilter(`chunk ${chunk.chunk_index}`)}
                              className="inline-flex items-center gap-1 text-primary hover:underline cursor-pointer bg-primary/5 px-2 py-0.5 rounded border border-primary/20"
                              title={`Jump to previous chunk (${chunk.prev_chunk_id})`}
                            >
                              <ArrowLeft className="w-3 h-3" />
                              <span>Prev: Chunk #{chunk.chunk_index}</span>
                            </button>
                          ) : (
                            <span className="text-muted-foreground/60 italic text-[10px]">
                              ● Start of document (no previous chunk)
                            </span>
                          )}
                        </div>

                        <div className="text-[10px] text-muted-foreground">
                          Doc Ref: <span className="font-mono text-foreground font-semibold">{chunk.doc_ref_id || docId}</span>
                        </div>

                        <div className="flex items-center gap-1.5">
                          {chunk.next_chunk_id ? (
                            <button
                              type="button"
                              onClick={() => setChunkFilter(`chunk ${chunk.chunk_index + 2}`)}
                              className="inline-flex items-center gap-1 text-primary hover:underline cursor-pointer bg-primary/5 px-2 py-0.5 rounded border border-primary/20"
                              title={`Jump to next chunk (${chunk.next_chunk_id})`}
                            >
                              <span>Next: Chunk #{chunk.chunk_index + 2}</span>
                              <ArrowRight className="w-3 h-3" />
                            </button>
                          ) : (
                            <span className="text-muted-foreground/60 italic text-[10px]">
                              ● End of document (last chunk)
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </>
        ) : (
          /* Full Unfragmented Document View */
          <div className="flex-1 overflow-y-auto p-6 max-h-[55vh]">
            {fullDocLoading ? (
              <div className="flex flex-col items-center justify-center py-16 text-center space-y-3">
                <Loader2 className="w-8 h-8 text-primary animate-spin" />
                <p className="text-xs text-muted-foreground font-mono">
                  Loading complete unfragmented document from RawDocumentStore...
                </p>
              </div>
            ) : !fullDocContent?.full_text ? (
              <div className="py-12 text-center text-muted-foreground space-y-2">
                <FileText className="w-8 h-8 mx-auto opacity-40 mb-2" />
                <p className="text-xs font-medium">
                  Full parsed content is currently being parsed or indexed.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex items-center justify-between pb-3 border-b border-border/50">
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-muted-foreground">
                      Total Words: <strong className="text-foreground">{fullDocContent.word_count}</strong>
                    </span>
                    <span className="text-xs text-muted-foreground">
                      Total Characters: <strong className="text-foreground">{fullDocContent.character_count}</strong>
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleCopy('full_doc', fullDocContent.full_text, 'Full Document')}
                    className="px-3 py-1 text-xs rounded-lg border border-border/60 bg-background hover:bg-muted flex items-center gap-1.5 cursor-pointer"
                  >
                    {copiedId === 'full_doc' ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>Copy Full Text</span>
                  </button>
                </div>
                <div className="bg-background/90 p-5 rounded-xl border border-border/60 text-xs font-mono whitespace-pre-wrap leading-relaxed overflow-x-auto text-foreground">
                  {fullDocContent.full_text}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Modal Footer */}
        <div className="px-6 py-4 border-t border-border bg-muted/20 flex justify-between items-center">
          <p className="text-[11px] text-muted-foreground font-mono">
            {activeTab === 'chunks'
              ? `Showing ${filteredChunks.length} of ${vectorData?.total_chunks || 0} chunk segments`
              : `Full document stored as single unfragmented record`}
          </p>
          <Button variant="outline" onClick={onClose}>
            Close Inspector
          </Button>
        </div>
      </div>
    </div>
  );
};
