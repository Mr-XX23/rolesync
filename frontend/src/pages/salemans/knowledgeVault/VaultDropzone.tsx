import React from 'react';
import { CloudUpload, Globe, Loader2, Sliders } from 'lucide-react';
import { Button } from '../../../components/common/Button';
import { ALLOWED_EXTENSIONS } from './vaultUtils';

interface VaultDropzoneProps {
  dragActive: boolean;
  uploadQueue: string[];
  isUploading?: boolean;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onDrag: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  onFileChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onOpenUrlModal: () => void;
  ragConfigSummary?: {
    chunkSize: number;
    overlap: number;
    engine: string;
  };
  onConfigureSettings?: () => void;
}

export const VaultDropzone: React.FC<VaultDropzoneProps> = React.memo(
  ({
    dragActive,
    uploadQueue,
    isUploading = false,
    fileInputRef,
    onDrag,
    onDrop,
    onFileChange,
    onOpenUrlModal,
    ragConfigSummary,
    onConfigureSettings,
  }) => {
    return (
      <div className="w-full group relative">
        <input
          type="file"
          id="file-upload"
          multiple
          accept=".pdf,.csv,.txt,.docx,.md,.json,.tsv,.yaml,.yml"
          className="hidden"
          ref={fileInputRef}
          onChange={onFileChange}
          disabled={isUploading}
        />

        <div
          onDragEnter={isUploading ? undefined : onDrag}
          onDragLeave={isUploading ? undefined : onDrag}
          onDragOver={isUploading ? undefined : onDrag}
          onDrop={isUploading ? undefined : onDrop}
          onClick={() => {
            if (!isUploading) fileInputRef.current?.click();
          }}
          className={`w-full border-2 border-dashed rounded-2xl p-8 md:p-10 flex flex-col items-center justify-center text-center transition-all relative overflow-hidden bg-card/60 ${
            isUploading
              ? 'border-border/80 opacity-90 cursor-not-allowed'
              : dragActive
              ? 'border-primary bg-primary/5 scale-[0.99] shadow-inner ring-4 ring-primary/10 cursor-pointer'
              : 'border-border/80 hover:border-primary/50 hover:bg-muted/30 shadow-2xs cursor-pointer'
          }`}
        >
          {/* Active Upload Queue Banner */}
          {uploadQueue.length > 0 && (
            <div className="absolute top-3 inset-x-4 bg-primary/10 border border-primary/20 rounded-xl py-2 px-3 flex items-center justify-between text-xs text-primary animate-pulse z-10">
              <div className="flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span className="font-semibold">
                  Uploading {uploadQueue.length} file{uploadQueue.length > 1 ? 's' : ''}...
                </span>
              </div>
              <span className="text-[10px] font-mono truncate max-w-[200px]">
                {uploadQueue[uploadQueue.length - 1]}
              </span>
            </div>
          )}

          {/* Animated Upload Icon */}
          <div className="w-16 h-16 rounded-2xl bg-muted/80 flex items-center justify-center mb-4 group-hover:scale-110 group-hover:bg-primary/15 group-hover:text-primary transition-all duration-300 shadow-2xs">
            <CloudUpload className="w-8 h-8 text-muted-foreground group-hover:text-primary transition-colors" />
          </div>

          <h3 className="font-serif text-xl font-bold text-foreground mb-1">
            Drop your sales & enterprise documents here
          </h3>
          <p className="text-xs text-muted-foreground max-w-md mb-4">
            Upload PDFs, Office files, Battlecards, or raw text. Documents automatically classify.
          </p>

          {/* Supported Format Badges */}
          <div className="flex flex-wrap items-center justify-center gap-1.5 mb-5 max-w-md">
            {ALLOWED_EXTENSIONS.map((ext) => (
              <span
                key={ext}
                className="px-2 py-0.5 rounded-md text-[9px] font-mono font-bold bg-muted text-muted-foreground border border-border/60"
              >
                .{ext.toLowerCase()}
              </span>
            ))}
          </div>

          <div className="flex flex-wrap items-center justify-center gap-3">
            <Button
              variant="primary"
              disabled={isUploading}
              isLoading={isUploading}
              loadingText="Uploading..."
              onClick={(e) => {
                e.stopPropagation();
                fileInputRef.current?.click();
              }}
              className="w-auto px-5 py-2 text-xs rounded-xl shadow-3xs"
            >
              Select Files from Device
            </Button>
            <Button
              variant="outline"
              disabled={isUploading}
              onClick={(e) => {
                e.stopPropagation();
                onOpenUrlModal();
              }}
              icon={<Globe className="w-3.5 h-3.5 text-muted-foreground" />}
              className="w-auto px-4 py-2 text-xs rounded-xl shadow-3xs"
            >
              Crawl URL
            </Button>
          </div>

          <span className="mt-4 font-mono text-[10px] text-muted-foreground">
            Maximum single file size: 25 MB
          </span>

          {/* Active RAG Pipeline Strip */}
          <div
            onClick={(e) => {
              e.stopPropagation();
              onConfigureSettings?.();
            }}
            className="mt-6 pt-4 border-t border-border/60 w-full max-w-xl flex flex-wrap items-center justify-between gap-3 text-left hover:opacity-90 transition-opacity"
          >
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shrink-0" />
              <span className="text-[11px] font-medium text-muted-foreground">
                Active RAG Pipeline:{' '}
                <strong className="text-foreground font-semibold">
                  {ragConfigSummary?.chunkSize || 512} tokens
                </strong>{' '}
                chunk •{' '}
                <strong className="text-foreground font-semibold">
                  {ragConfigSummary?.overlap || 12}%
                </strong>{' '}
                overlap
              </span>
            </div>
            {onConfigureSettings && (
              <button
                type="button"
                className="text-[11px] font-semibold text-primary hover:underline flex items-center gap-1.5 cursor-pointer bg-primary/10 px-2.5 py-1 rounded-lg border border-primary/20"
              >
                <Sliders className="w-3 h-3" />
                <span>Configure in Settings &rarr;</span>
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }
);

VaultDropzone.displayName = 'VaultDropzone';
