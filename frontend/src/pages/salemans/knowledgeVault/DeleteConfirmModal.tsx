import React, { useState } from 'react';
import { AlertTriangle, Trash2, X } from 'lucide-react';
import { Button } from '../../../components/common/Button';

interface DeleteConfirmModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void> | void;
  docName: string;
  isAbort?: boolean;
}

export const DeleteConfirmModal: React.FC<DeleteConfirmModalProps> = ({
  isOpen,
  onClose,
  onConfirm,
  docName,
  isAbort = false,
}) => {
  const [isProcessing, setIsProcessing] = useState(false);

  if (!isOpen) return null;

  const handleConfirm = async () => {
    setIsProcessing(true);
    try {
      await onConfirm();
    } finally {
      setIsProcessing(false);
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-sm animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="bg-card border border-border rounded-2xl max-w-md w-full p-6 shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200 space-y-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div className="w-11 h-11 rounded-xl bg-rose-500/10 text-rose-500 flex items-center justify-center shrink-0">
            <AlertTriangle className="w-6 h-6" />
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors cursor-pointer"
            aria-label="Close dialog"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div>
          <h3 className="font-serif text-lg font-bold text-foreground">
            {isAbort ? 'Abort Ingestion Pipeline?' : 'Purge Document from Vault?'}
          </h3>
          <p className="text-xs text-muted-foreground mt-2 leading-relaxed">
            {isAbort
              ? `Are you sure you want to stop indexing "${docName}"? In-progress parsing workers and temporary chunk buffers will be terminated.`
              : `Are you sure you want to delete "${docName}"? This action will permanently remove all associated vector embeddings from the vector store.`}
          </p>
        </div>

        <div className="p-3 bg-muted/40 rounded-xl border border-border/60">
          <p className="text-xs font-mono text-foreground/80 truncate">
            Target: <span className="font-bold">{docName}</span>
          </p>
        </div>

        <div className="flex justify-end gap-2.5 pt-2">
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={isProcessing}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleConfirm}
            isLoading={isProcessing}
            loadingText={isAbort ? 'Aborting...' : 'Deleting...'}
            className="bg-rose-600 hover:bg-rose-700 text-white border-transparent"
            icon={<Trash2 className="w-4 h-4" />}
          >
            {isAbort ? 'Abort Ingestion' : 'Confirm Delete'}
          </Button>
        </div>
      </div>
    </div>
  );
};
