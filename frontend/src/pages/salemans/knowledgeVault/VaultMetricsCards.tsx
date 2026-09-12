import React from 'react';
import { FileText, Layers, Database, HardDrive, ArrowUpRight } from 'lucide-react';
import type { VaultStats } from '../../../api/knowledgeVaultApi';
import { formatSize } from './vaultUtils';

interface VaultMetricsCardsProps {
  stats: VaultStats | null;
  documentsCount: number;
  indexedCount: number;
  fallbackChunks: number;
  fallbackBytes: number;
  // Number of external connectors actually connected (Gmail/GDrive/Notion/…),
  // not the number of document sources in the vault.
  connectedSourcesCount: number;
  onConnectorsClick: () => void;
}

export const VaultMetricsCards: React.FC<VaultMetricsCardsProps> = React.memo(
  ({
    stats,
    documentsCount,
    indexedCount,
    fallbackChunks,
    fallbackBytes,
    connectedSourcesCount,
    onConnectorsClick,
  }) => {
    const totalDocs = stats?.total_documents ?? documentsCount;
    const activeIndexed = stats?.indexed_count ?? indexedCount;
    const totalChunks = stats?.total_chunks ?? fallbackChunks;
    const totalBytes = stats?.total_size_bytes ?? fallbackBytes;
    const sourcesCount = connectedSourcesCount;
    const backendLabel = stats?.vector_backend || 'MongoDB Vector Mesh';

    const battlecards = stats?.category_counts?.BATTLECARD || 0;
    const pricing = stats?.category_counts?.PRICING_PACKAGING || 0;
    const caseStudies = stats?.category_counts?.CASE_STUDY_ROI || 0;

    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Documents */}
        <div className="bg-card border border-border rounded-2xl p-4 shadow-2xs flex items-center justify-between transition-all hover:border-border/80">
          <div className="space-y-1">
            <span className="font-mono text-[10px] text-muted-foreground uppercase font-bold tracking-wider">
              Sales Collateral
            </span>
            <h4 className="font-serif text-2xl font-bold text-foreground">
              {totalDocs} Assets
            </h4>
            <div className="flex items-center gap-1.5 text-[10px] font-mono pt-0.5">
              <span className="text-purple-600 dark:text-purple-400 font-semibold">{battlecards} Battlecards</span>
              <span className="text-muted-foreground">·</span>
              <span className="text-amber-600 dark:text-amber-400 font-semibold">{pricing} Pricing</span>
              {caseStudies > 0 && (
                <>
                  <span className="text-muted-foreground">·</span>
                  <span className="text-emerald-600 dark:text-emerald-400 font-semibold">{caseStudies} ROI</span>
                </>
              )}
            </div>
          </div>
          <div className="w-11 h-11 rounded-xl bg-primary/10 text-primary flex items-center justify-center shadow-2xs">
            <FileText className="w-5 h-5" />
          </div>
        </div>

        {/* Vector Chunks */}
        <div className="bg-card border border-border rounded-2xl p-4 shadow-2xs flex items-center justify-between transition-all hover:border-border/80">
          <div className="space-y-1">
            <span className="font-mono text-[10px] text-muted-foreground uppercase font-bold tracking-wider">
              Vector Chunks
            </span>
            <h4 className="font-serif text-2xl font-bold text-foreground">
              {totalChunks.toLocaleString()}
            </h4>
            <p className="text-[11px] text-muted-foreground">
              {activeIndexed} active in semantic index
            </p>
          </div>
          <div className="w-11 h-11 rounded-xl bg-primary/10 text-primary flex items-center justify-center shadow-2xs">
            <Layers className="w-5 h-5" />
          </div>
        </div>

        {/* Intelligence Volume */}
        <div className="bg-card border border-border rounded-2xl p-4 shadow-2xs flex items-center justify-between transition-all hover:border-border/80">
          <div className="space-y-1">
            <span className="font-mono text-[10px] text-muted-foreground uppercase font-bold tracking-wider">
              Intelligence Volume
            </span>
            <h4 className="font-serif text-2xl font-bold text-foreground">
              {formatSize(totalBytes)}
            </h4>
            <p className="text-[11px] text-muted-foreground font-mono truncate max-w-[150px]">
              {backendLabel}
            </p>
          </div>
          <div className="w-11 h-11 rounded-xl bg-primary/10 text-primary flex items-center justify-center shadow-2xs">
            <Database className="w-5 h-5" />
          </div>
        </div>

        {/* External Connectors */}
        <div
          onClick={onConnectorsClick}
          className="group bg-card border border-border rounded-2xl p-4 shadow-2xs flex items-center justify-between hover:border-primary/40 hover:-translate-y-0.5 transition-all cursor-pointer"
        >
          <div className="space-y-1">
            <span className="font-mono text-[10px] text-primary uppercase font-bold tracking-wider flex items-center gap-1">
              External Connectors{' '}
              <ArrowUpRight className="w-3 h-3 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" />
            </span>
            <h4 className="font-serif text-2xl font-bold text-foreground">
              {sourcesCount} Sources
            </h4>
            <p className="text-[11px] text-muted-foreground">
              Gmail, GDrive, Notion, Slack & Calendar
            </p>
          </div>
          <div className="w-11 h-11 rounded-xl bg-primary/10 text-primary flex items-center justify-center group-hover:scale-105 transition-transform shadow-2xs">
            <HardDrive className="w-5 h-5" />
          </div>
        </div>
      </div>
    );
  }
);

VaultMetricsCards.displayName = 'VaultMetricsCards';
