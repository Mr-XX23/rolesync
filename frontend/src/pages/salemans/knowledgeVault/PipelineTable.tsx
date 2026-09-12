import React from 'react';
import {
  FileText,
  Search,
  RefreshCw,
  Loader2,
  CheckCircle2,
  AlertCircle,
  RotateCw,
  Trash2,
  Plus,
  X,
  Sparkles,
  Building2,
  Briefcase,
  ChevronDown,
} from 'lucide-react';
import { Button } from '../../../components/common/Button';
import type { KnowledgeDocument } from '../../../api/knowledgeVaultApi';
import {
  formatSize,
  formatTimestamp,
  getSalesCategoryMeta,
} from './vaultUtils';

interface PipelineTableProps {
  documents: KnowledgeDocument[];
  filteredDocuments: KnowledgeDocument[];
  isLoading: boolean;
  isRefreshing: boolean;
  filter: 'all' | 'Indexed' | 'Parsing' | 'Error' | 'Rejected';
  categoryFilter: string;
  searchQuery: string;
  hasIncompleteDocuments: boolean;
  onFilterChange: (filter: 'all' | 'Indexed' | 'Parsing' | 'Error' | 'Rejected') => void;
  onCategoryFilterChange: (category: string) => void;
  onSearchChange: (query: string) => void;
  onRefresh: () => void;
  onUploadClick: () => void;
  onInspectDoc: (doc: { id: string; name: string }) => void;
  onEditSalesIntelligence: (doc: KnowledgeDocument) => void;
  onReindex: (docId: string, docName: string) => void;
  onDeleteRequest: (target: { id: string; name: string; isAbort: boolean }) => void;
}

export const PipelineTable: React.FC<PipelineTableProps> = React.memo(
  ({
    documents,
    filteredDocuments,
    isLoading,
    isRefreshing,
    filter,
    categoryFilter,
    searchQuery,
    hasIncompleteDocuments,
    onFilterChange,
    onCategoryFilterChange,
    onSearchChange,
    onRefresh,
    onUploadClick,
    onInspectDoc,
    onEditSalesIntelligence,
    onReindex,
    onDeleteRequest,
  }) => {


    // Sales Category Pills
    const salesCategoryTabs = [
      { id: 'all', label: 'All Documents', count: documents.length },
      {
        id: 'BATTLECARD',
        label: 'Battlecards',
        count: documents.filter((d) => (d.category || 'GENERAL_RESOURCE') === 'BATTLECARD').length,
      },
      {
        id: 'PRICING_PACKAGING',
        label: 'Pricing',
        count: documents.filter((d) => (d.category || 'GENERAL_RESOURCE') === 'PRICING_PACKAGING').length,
      },
      {
        id: 'CASE_STUDY_ROI',
        label: 'Case Studies',
        count: documents.filter((d) => (d.category || 'GENERAL_RESOURCE') === 'CASE_STUDY_ROI').length,
      },
      {
        id: 'PRODUCT_SPEC',
        label: 'Product Specs',
        count: documents.filter((d) => (d.category || 'GENERAL_RESOURCE') === 'PRODUCT_SPEC').length,
      },
      {
        id: 'SECURITY_COMPLIANCE',
        label: 'Security & Compliance',
        count: documents.filter((d) => (d.category || 'GENERAL_RESOURCE') === 'SECURITY_COMPLIANCE').length,
      },
      {
        id: 'CONTRACT_LEGAL',
        label: 'Contracts & Legal',
        count: documents.filter((d) => (d.category || 'GENERAL_RESOURCE') === 'CONTRACT_LEGAL').length,
      },
      {
        id: 'GENERAL_RESOURCE',
        label: 'General',
        count: documents.filter((d) => (d.category || 'GENERAL_RESOURCE') === 'GENERAL_RESOURCE').length,
      },
    ];

    return (
      <div className="bg-card border border-border rounded-2xl p-6 shadow-2xs overflow-hidden space-y-5">
        {/* Header Toolbar */}
        <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4">
          {/* Simple, Friendly Heading */}
          <div className="flex items-center gap-3">
            <div
              className={`w-2.5 h-2.5 rounded-full ${
                hasIncompleteDocuments ? 'bg-amber-500 animate-ping' : 'bg-emerald-500'
              }`}
            />
            <div>
              <div className="flex items-center gap-2">
                <h4 className="font-serif text-lg font-bold text-foreground">
                  Sales Documents
                </h4>
                <span className="text-[11px] font-semibold text-muted-foreground bg-muted border border-border/80 px-2 py-0.5 rounded-md font-sans">
                  {filteredDocuments.length} {filteredDocuments.length === 1 ? 'file' : 'files'}
                </span>
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                All your sales collateral, organized automatically by category and competitor.
              </p>
            </div>
          </div>

          {/* Clean Controls: Search + Status Dropdown + Refresh */}
          <div className="flex items-center gap-2.5 w-full sm:w-auto">
            {/* Search Input */}
            <div className="relative flex-1 sm:w-64 md:w-72">
              <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search documents, competitors, tags..."
                value={searchQuery}
                onChange={(e) => onSearchChange(e.target.value)}
                className="w-full pl-9 pr-8 py-2 bg-background border border-border rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary shadow-3xs"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => onSearchChange('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground cursor-pointer"
                  title="Clear search"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            {/* Compact Status Filter Dropdown */}
            <div className="relative shrink-0">
              <select
                value={filter}
                onChange={(e) => onFilterChange(e.target.value as any)}
                className="h-9 pl-3 pr-8 text-xs font-medium rounded-xl bg-muted/70 hover:bg-muted border border-border text-foreground appearance-none cursor-pointer focus:outline-none focus:ring-1 focus:ring-primary transition-colors shadow-3xs"
                title="Filter by document status"
              >
                <option value="all">All Status ({documents.length})</option>
                <option value="Indexed">Ready ({documents.filter((d) => d.status === 'Indexed').length})</option>
                <option value="Parsing">Processing ({documents.filter((d) => d.status === 'Parsing').length})</option>
                <option value="Error">Errors ({documents.filter((d) => d.status === 'Error').length})</option>
                <option value="Rejected">Not indexed ({documents.filter((d) => d.status === 'Rejected').length})</option>
              </select>
              <ChevronDown className="w-3.5 h-3.5 absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            </div>

            {/* Refresh Button */}
            <Button
              variant="outline"
              onClick={onRefresh}
              isLoading={isRefreshing}
              className="p-2 aspect-square rounded-xl shadow-3xs shrink-0"
              title="Refresh list"
              icon={
                <RefreshCw
                  className={`w-3.5 h-3.5 text-muted-foreground hover:text-foreground ${
                    isRefreshing ? 'animate-spin' : ''
                  }`}
                />
              }
            />
          </div>
        </div>

        {/* Primary Category Tabs */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-3 border-b border-border/60 text-xs scrollbar-none">
          {salesCategoryTabs.map((catTab) => {
            const isSelected = categoryFilter === catTab.id;
            return (
              <button
                key={catTab.id}
                type="button"
                onClick={() => onCategoryFilterChange(catTab.id)}
                className={`px-3.5 py-1.5 rounded-xl font-medium transition-all shrink-0 flex items-center gap-1.5 cursor-pointer border ${
                  isSelected
                    ? 'bg-primary text-primary-foreground border-primary font-semibold shadow-xs'
                    : 'bg-muted/40 hover:bg-muted border-border/60 text-muted-foreground hover:text-foreground'
                }`}
              >
                <span>{catTab.label}</span>
                {catTab.count > 0 && (
                  <span
                    className={`text-[10px] font-mono px-1.5 py-0.2 rounded-full leading-none font-bold ${
                      isSelected
                        ? 'bg-primary-foreground/20 text-primary-foreground'
                        : 'bg-muted-foreground/15 text-muted-foreground'
                    }`}
                  >
                    {catTab.count}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Table Container */}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-separate border-spacing-y-2">
            <thead className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider">
              <tr>
                <th className="px-4 pb-2">Document</th>
                <th className="px-4 pb-2">Category & Competitor</th>
                <th className="px-4 pb-2">Format</th>
                <th className="px-4 pb-2">Size</th>
                <th className="px-4 pb-2">Vectors</th>
                <th className="px-4 pb-2">Status</th>
                <th className="px-4 pb-2">Updated</th>
                <th className="px-4 pb-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={8} className="text-center py-12">
                    <Loader2 className="w-7 h-7 text-primary animate-spin mx-auto mb-2" />
                    <p className="text-xs text-muted-foreground font-mono">
                      Loading synchronized knowledge records...
                    </p>
                  </td>
                </tr>
              ) : filteredDocuments.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center py-12 text-xs text-muted-foreground">
                    <div className="flex flex-col items-center justify-center max-w-md mx-auto space-y-3">
                      <div className="w-10 h-10 rounded-full bg-muted/60 flex items-center justify-center text-muted-foreground/50 mb-1">
                        <FileText className="w-5 h-5" />
                      </div>
                      <p className="font-semibold text-foreground text-sm">
                        {searchQuery
                          ? `No documents matched "${searchQuery}".`
                          : categoryFilter !== 'all'
                          ? `No documents found in "${salesCategoryTabs.find((t) => t.id === categoryFilter)?.label || categoryFilter}".`
                          : filter !== 'all'
                          ? `No documents with status "${filter}".`
                          : 'No documents in your sales library yet.'}
                      </p>
                      <p className="text-xs text-muted-foreground max-w-sm text-center leading-relaxed">
                        {searchQuery || categoryFilter !== 'all' || filter !== 'all'
                          ? 'Try resetting your search or category filter to view all sales documents.'
                          : 'Drag and drop files into the upload area above to build your sales library.'}
                      </p>
                      <div className="pt-2 flex items-center justify-center gap-2">
                        {(categoryFilter !== 'all' || filter !== 'all') && (
                          <button
                            type="button"
                            onClick={() => {
                              onCategoryFilterChange('all');
                              onFilterChange('all');
                            }}
                            className="px-3 py-1.5 rounded-lg border border-border/80 bg-background hover:bg-muted text-xs font-semibold text-foreground transition-colors cursor-pointer shadow-3xs"
                          >
                            Reset Filters ({documents.length})
                          </button>
                        )}
                        {searchQuery && (
                          <button
                            type="button"
                            onClick={() => onSearchChange('')}
                            className="px-3 py-1.5 rounded-lg border border-border/80 bg-background hover:bg-muted text-xs font-semibold text-foreground transition-colors cursor-pointer shadow-3xs"
                          >
                            Clear Search
                          </button>
                        )}
                        <Button
                          variant="primary"
                          onClick={onUploadClick}
                          icon={<Plus className="w-3.5 h-3.5" />}
                          className="w-auto px-4 py-1.5 text-xs rounded-lg shadow-3xs"
                        >
                          {documents.length === 0 ? 'Upload First Document' : 'Upload Document'}
                        </Button>
                      </div>
                    </div>
                  </td>
                </tr>
              ) : (
                filteredDocuments.map((resource) => {
                  const dateInfo = formatTimestamp(resource.last_updated);
                  const catMeta = getSalesCategoryMeta(resource.category);

                  return (
                    <tr
                      key={resource.doc_id}
                      className="bg-muted/40 hover:bg-muted/70 transition-colors border border-border/40"
                    >
                      {/* Name */}
                      <td className="px-4 py-3.5 rounded-l-xl">
                        <div className="flex items-center gap-3">
                          <FileText className="w-4 h-4 text-primary shrink-0" />
                          <div className="truncate max-w-[170px] sm:max-w-xs">
                            <span
                              className="text-xs font-semibold text-foreground leading-tight truncate block hover:text-primary cursor-pointer"
                              onClick={() =>
                                onInspectDoc({ id: resource.doc_id, name: resource.name })
                              }
                              title={resource.name}
                            >
                              {resource.name}
                            </span>
                            {resource.sales_summary ? (
                              <span
                                className="text-[10px] text-muted-foreground line-clamp-1 block"
                                title={resource.sales_summary}
                              >
                                {resource.sales_summary}
                              </span>
                            ) : resource.metadata?.target_url ? (
                              <span className="text-[10px] text-muted-foreground font-mono truncate block">
                                {resource.metadata.target_url}
                              </span>
                            ) : null}
                          </div>
                        </div>
                      </td>

                      {/* Sales Intelligence */}
                      <td className="px-4 py-3.5">
                        <div className="flex flex-wrap items-center gap-1.5 max-w-[240px]">
                          {/* Category Badge */}
                          <button
                            type="button"
                            onClick={() => onEditSalesIntelligence(resource)}
                            title={`Click to edit classification (Source: ${resource.classifier_used || 'rule engine'})`}
                            className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-md border transition-transform hover:scale-105 cursor-pointer ${catMeta.badgeBg} ${catMeta.badgeText} ${catMeta.borderColor}`}
                          >
                            <span className={`w-1.5 h-1.5 rounded-full ${catMeta.dotColor}`} />
                            <span>{catMeta.shortLabel}</span>
                          </button>

                          {/* Competitor Chip */}
                          {resource.target_competitor && (
                            <span className="inline-flex items-center gap-0.5 text-[9px] font-mono px-1.5 py-0.5 rounded-md bg-purple-500/10 text-purple-700 dark:text-purple-300 border border-purple-500/20 font-bold">
                              <Building2 className="w-2.5 h-2.5" />
                              <span>vs {resource.target_competitor}</span>
                            </span>
                          )}

                          {/* Industry Chip */}
                          {resource.target_industry && (
                            <span className="inline-flex items-center gap-0.5 text-[9px] font-mono px-1.5 py-0.5 rounded-md bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/20 font-medium">
                              <Briefcase className="w-2.5 h-2.5" />
                              <span>{resource.target_industry}</span>
                            </span>
                          )}

                          {/* First tag */}
                          {resource.sales_tags && resource.sales_tags.length > 0 && (
                            <span className="text-[9px] font-mono text-muted-foreground bg-background px-1.5 py-0.5 rounded border border-border/40">
                              #{resource.sales_tags[0]}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Type */}
                      <td className="px-4 py-3.5">
                        <span className="font-mono text-[9px] font-bold bg-background text-muted-foreground px-2 py-0.5 rounded-md border border-border/40">
                          {resource.type}
                        </span>
                      </td>

                      {/* Size */}
                      <td className="px-4 py-3.5 text-xs font-mono text-muted-foreground">
                        {formatSize(resource.size_bytes)}
                      </td>

                      {/* Chunks */}
                      <td className="px-4 py-3.5 font-mono text-xs font-semibold text-foreground">
                        {resource.chunks ? resource.chunks.toLocaleString() : '--'}
                      </td>

                      {/* Status */}
                      <td className="px-4 py-3.5">
                        {resource.status === 'Indexed' ? (
                          <div className="flex items-center gap-1.5 text-emerald-700 dark:text-emerald-400 font-bold">
                            <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                            <span className="text-[11px] uppercase tracking-wide">Indexed</span>
                          </div>
                        ) : resource.status === 'Parsing' ? (
                          <div className="flex items-center gap-1.5 text-primary font-bold">
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            <span className="text-[11px] uppercase tracking-wide animate-pulse">
                              Parsing...
                            </span>
                          </div>
                        ) : resource.status === 'Rejected' ? (
                          <div
                            className="flex items-center gap-1.5 text-amber-600 dark:text-amber-400 font-bold"
                            title={
                              resource.error_message ||
                              'This document was not added to the Knowledge Vault.'
                            }
                          >
                            <AlertCircle className="w-4 h-4" />
                            <span className="text-[11px] uppercase tracking-wide">Not indexed</span>
                          </div>
                        ) : (
                          <div
                            className="flex items-center gap-1.5 text-rose-600 dark:text-rose-400 font-bold"
                            title={resource.error_message || 'Indexing failed'}
                          >
                            <AlertCircle className="w-4 h-4" />
                            <span className="text-[11px] uppercase tracking-wide">Error</span>
                          </div>
                        )}
                      </td>

                      {/* Last Updated */}
                      <td className="px-4 py-3.5 text-xs font-medium text-muted-foreground">
                        <span title={dateInfo.full} className="cursor-default">
                          {dateInfo.formatted}
                        </span>
                      </td>

                      {/* Actions */}
                      <td className="px-4 py-3.5 rounded-r-xl text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {/* Edit Sales Intelligence */}
                          <button
                            type="button"
                            onClick={() => onEditSalesIntelligence(resource)}
                            className="p-1.5 rounded-lg text-amber-500 hover:text-amber-600 hover:bg-amber-500/10 transition-colors cursor-pointer"
                            title="Edit Sales Taxonomy & Metadata"
                          >
                            <Sparkles className="w-3.5 h-3.5" />
                          </button>

                          {resource.status === 'Indexed' && (
                            <button
                              type="button"
                              onClick={() =>
                                onInspectDoc({ id: resource.doc_id, name: resource.name })
                              }
                              className="text-xs font-bold text-primary hover:underline transition-all cursor-pointer px-1"
                            >
                              Vectors
                            </button>
                          )}

                          {resource.status === 'Error' && (
                            <button
                              type="button"
                              onClick={() => onReindex(resource.doc_id, resource.name)}
                              className="text-xs font-bold text-amber-600 dark:text-amber-400 hover:underline transition-all flex items-center gap-1 cursor-pointer px-1"
                              title="Retry vectorization"
                            >
                              <RotateCw className="w-3 h-3" />
                              <span>Retry</span>
                            </button>
                          )}

                          {resource.status === 'Parsing' ? (
                            <button
                              type="button"
                              onClick={() =>
                                onDeleteRequest({
                                  id: resource.doc_id,
                                  name: resource.name,
                                  isAbort: true,
                                })
                              }
                              className="text-xs font-bold text-muted-foreground/80 hover:text-rose-600 transition-all cursor-pointer px-1"
                            >
                              Abort
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() =>
                                onDeleteRequest({
                                  id: resource.doc_id,
                                  name: resource.name,
                                  isAbort: false,
                                })
                              }
                              className="p-1.5 rounded-lg text-muted-foreground/60 hover:text-rose-600 hover:bg-rose-500/10 transition-colors cursor-pointer"
                              title="Delete document"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    );
  }
);

PipelineTable.displayName = 'PipelineTable';
