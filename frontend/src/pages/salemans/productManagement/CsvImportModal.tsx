import React, { useState, useRef, useEffect } from 'react';
import {
  X,
  Upload,
  FileSpreadsheet,
  Download,
  CheckCircle2,
  AlertCircle,
  Loader2,
  FileText,
  Play,
  RotateCcw,
} from 'lucide-react';
import {
  catalogApi,
  type ValidationReport,
  type ImportJobResponse,
} from '../../../api/catalogApi';
import { useToast } from '../../../context/ToastContext';

interface CsvImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onImportCompleted: () => void;
}

export const CsvImportModal: React.FC<CsvImportModalProps> = ({
  isOpen,
  onClose,
  onImportCompleted,
}) => {
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024; // 25 MB

  const [inputMode, setInputMode] = useState<'upload' | 'paste'>('upload');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [pastedCsv, setPastedCsv] = useState<string>('');
  const [skipInvalid, setSkipInvalid] = useState<boolean>(true);
  const [autoCreateCategories, setAutoCreateCategories] = useState<boolean>(true);

  // Validation state
  const [isValidating, setIsValidating] = useState<boolean>(false);
  const [validationReport, setValidationReport] = useState<ValidationReport | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  // Commit & polling state
  const [isCommitting, setIsCommitting] = useState<boolean>(false);
  const [jobStatus, setJobStatus] = useState<ImportJobResponse | null>(null);
  const [isPolling, setIsPolling] = useState<boolean>(false);
  const [hasImportedSuccessfully, setHasImportedSuccessfully] = useState<boolean>(false);

  const isBusy = isValidating || isCommitting || isPolling;
  const canCommit = !isBusy && validationReport !== null && validationReport.valid_count > 0;

  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  const handleSafeClose = () => {
    if (isBusy) return;
    if (hasImportedSuccessfully) {
      onImportCompleted();
    }
    onClose();
  };

  const handleDownloadTemplate = async () => {
    try {
      const csvData = await catalogApi.downloadTemplateCsv();
      const blob = new Blob([csvData], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.setAttribute('href', url);
      link.setAttribute('download', 'catalog_import_template.csv');
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      toast.success('Downloaded canonical catalog template.', 'Template Ready');
    } catch (err) {
      toast.error('Failed to download template CSV.');
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (isBusy) return;
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      if (file.size > MAX_FILE_SIZE_BYTES) {
        const sizeMb = (file.size / (1024 * 1024)).toFixed(1);
        const errorMsg = `File size (${sizeMb} MB) exceeds the 25 MB limit. Please select a CSV file under 25 MB.`;
        setValidationError(errorMsg);
        toast.error(errorMsg, 'File Limit Exceeded');
        if (fileInputRef.current) fileInputRef.current.value = '';
        setSelectedFile(null);
        setValidationReport(null);
        setJobStatus(null);
        return;
      }

      setSelectedFile(file);
      setValidationReport(null);
      setValidationError(null);
      setJobStatus(null);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (isBusy) return;
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (file.size > MAX_FILE_SIZE_BYTES) {
        const sizeMb = (file.size / (1024 * 1024)).toFixed(1);
        const errorMsg = `File size (${sizeMb} MB) exceeds the 25 MB limit. Please select a CSV file under 25 MB.`;
        setValidationError(errorMsg);
        toast.error(errorMsg, 'File Limit Exceeded');
        if (fileInputRef.current) fileInputRef.current.value = '';
        setSelectedFile(null);
        setValidationReport(null);
        setJobStatus(null);
        return;
      }

      setSelectedFile(file);
      setValidationReport(null);
      setValidationError(null);
      setJobStatus(null);
    }
  };

  const handleRunValidation = async () => {
    const payload = inputMode === 'upload' ? selectedFile : pastedCsv.trim();
    if (!payload) {
      setValidationError('Please select a CSV file or paste CSV content.');
      return;
    }

    setIsValidating(true);
    setValidationError(null);
    setValidationReport(null);

    try {
      const report = await catalogApi.validateCsvImport(payload, autoCreateCategories);
      setValidationReport(report);
      if (report.error_count > 0) {
        toast.warning(
          `Validation completed with ${report.error_count} row errors. Review report below.`,
          'Dry-Run Finished'
        );
      } else {
        toast.success(
          `All ${report.valid_count} rows passed validation cleanly! Ready to commit.`,
          'Validation Passed'
        );
      }
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Validation failed.';
      setValidationError(msg);
      toast.error(msg, 'Validation Error');
    } finally {
      setIsValidating(false);
    }
  };

  const pollJobUntilDone = async (jobId: string) => {
    setIsPolling(true);
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
    pollIntervalRef.current = setInterval(async () => {
      try {
        const job = await catalogApi.getImportJobStatus(jobId);
        setJobStatus(job);

        if (job.status === 'COMPLETED') {
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
          setIsPolling(false);
          setHasImportedSuccessfully(true);
          toast.success(
            `Import job completed! Created: ${job.created_count}, Updated: ${job.updated_count}, Skipped: ${job.skipped_count}.`,
            'Import Successful'
          );
          onImportCompleted();
        } else if (job.status === 'FAILED') {
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
          setIsPolling(false);
          toast.error(
            job.errors.length > 0 ? job.errors.join('; ') : 'CSV Import background worker failed.',
            'Import Failed'
          );
        }
      } catch (e) {
        console.warn('Job polling error:', e);
      }
    }, 1500);
  };

  const handleCommit = async () => {
    const payload = inputMode === 'upload' ? selectedFile : pastedCsv.trim();
    if (!payload || !canCommit) return;

    setIsCommitting(true);
    setValidationError(null);

    try {
      const commitRes = await catalogApi.commitCsvImport({
        fileOrContent: payload,
        skipInvalid,
        autoCreateCategories,
      });

      toast.info('Import job queued. Tracking execution...', 'Job Enqueued');
      pollJobUntilDone(commitRes.job_id);
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to commit import job.';
      setValidationError(msg);
      toast.error(msg, 'Commit Error');
      setIsCommitting(false);
    }
  };

  const resetAll = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
    setSelectedFile(null);
    setPastedCsv('');
    setValidationReport(null);
    setValidationError(null);
    setJobStatus(null);
    setIsCommitting(false);
    setIsPolling(false);
    setHasImportedSuccessfully(false);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="relative w-full max-w-3xl bg-card border border-border/80 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border/60 flex items-center justify-between bg-card/80">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
              <FileSpreadsheet className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-semibold text-foreground text-base">Import Products from CSV</h3>
                {isPolling && (
                  <span className="font-mono text-[10px] px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20 flex items-center gap-1">
                    <Loader2 className="w-3 h-3 animate-spin" /> Live Polling
                  </span>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Upload your product catalog CSV to preview, validate, and import items
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleDownloadTemplate}
              disabled={isBusy}
              className="px-3 py-1.5 text-xs font-medium rounded-xl border border-border/70 hover:bg-muted/50 text-foreground transition-colors flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Download className="w-3.5 h-3.5 text-muted-foreground" />
              Template
            </button>
            <button
              onClick={handleSafeClose}
              disabled={isBusy}
              title={isBusy ? 'Operation in progress' : 'Close'}
              className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-5 overflow-y-auto">
          {validationError && (
            <div className="p-3.5 rounded-xl bg-destructive/10 border border-destructive/25 text-destructive text-xs flex items-start gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{validationError}</span>
            </div>
          )}

          {/* If Job is in progress or completed */}
          {jobStatus ? (
            <div className="p-6 rounded-2xl border border-border/80 bg-muted/20 space-y-4 text-center">
              <div className="w-12 h-12 mx-auto rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
                {jobStatus.status === 'COMPLETED' ? (
                  <CheckCircle2 className="w-6 h-6 text-emerald-500" />
                ) : jobStatus.status === 'FAILED' ? (
                  <AlertCircle className="w-6 h-6 text-destructive" />
                ) : (
                  <Loader2 className="w-6 h-6 animate-spin text-primary" />
                )}
              </div>

              <div>
                <h4 className="font-serif text-lg font-bold text-foreground">
                  {jobStatus.status === 'COMPLETED'
                    ? 'Import Completed Successfully'
                    : jobStatus.status === 'FAILED'
                    ? 'Import Failed'
                    : 'Processing CSV Import In Background...'}
                </h4>
                <p className="text-xs text-muted-foreground mt-1">
                  Job ID: <span className="font-mono">{jobStatus.job_id}</span>
                </p>
              </div>

              {/* Progress Bar */}
              <div className="max-w-md mx-auto space-y-1.5">
                <div className="flex justify-between text-xs font-mono text-muted-foreground">
                  <span>{jobStatus.status}</span>
                  <span>{Math.round(jobStatus.progress_pct || 0)}%</span>
                </div>
                <div className="w-full h-2.5 rounded-full bg-muted overflow-hidden">
                  <div
                    className="h-full bg-primary transition-all duration-300"
                    style={{ width: `${jobStatus.progress_pct || 0}%` }}
                  />
                </div>
              </div>

              {/* Counts Grid */}
              <div className="grid grid-cols-4 gap-2 max-w-lg mx-auto text-left pt-2">
                <div className="p-2.5 rounded-xl bg-card border border-border/70 text-center">
                  <span className="text-[10px] uppercase font-mono text-muted-foreground block">
                    Total
                  </span>
                  <span className="text-sm font-bold text-foreground">{jobStatus.total_rows}</span>
                </div>
                <div className="p-2.5 rounded-xl bg-card border border-border/70 text-center">
                  <span className="text-[10px] uppercase font-mono text-emerald-500 block">
                    Created
                  </span>
                  <span className="text-sm font-bold text-emerald-500">{jobStatus.created_count}</span>
                </div>
                <div className="p-2.5 rounded-xl bg-card border border-border/70 text-center">
                  <span className="text-[10px] uppercase font-mono text-primary block">
                    Updated
                  </span>
                  <span className="text-sm font-bold text-primary">{jobStatus.updated_count}</span>
                </div>
                <div className="p-2.5 rounded-xl bg-card border border-border/70 text-center">
                  <span className="text-[10px] uppercase font-mono text-amber-500 block">
                    Skipped
                  </span>
                  <span className="text-sm font-bold text-amber-500">{jobStatus.skipped_count}</span>
                </div>
              </div>

              {/* Errors list if any */}
              {jobStatus.errors && jobStatus.errors.length > 0 && (
                <div className="p-3 rounded-xl bg-destructive/10 border border-destructive/25 text-left max-h-40 overflow-y-auto space-y-1 text-xs text-destructive">
                  <span className="font-semibold block">Row Errors Encountered:</span>
                  {jobStatus.errors.map((err, idx) => (
                    <div key={idx} className="font-mono text-[11px]">
                      • {err}
                    </div>
                  ))}
                </div>
              )}

              <div className="pt-2 flex justify-center gap-2">
                {jobStatus.status === 'COMPLETED' || jobStatus.status === 'FAILED' ? (
                  <>
                    <button
                      onClick={resetAll}
                      className="px-4 py-2 text-xs font-semibold rounded-xl border border-border/80 hover:bg-muted text-foreground transition-colors flex items-center gap-1.5 cursor-pointer"
                    >
                      <RotateCcw className="w-3.5 h-3.5" />
                      Import Another CSV
                    </button>
                    <button
                      onClick={() => {
                        onImportCompleted();
                        onClose();
                      }}
                      className="px-4 py-2 text-xs font-semibold rounded-xl bg-primary text-primary-foreground hover:opacity-95 transition-opacity cursor-pointer"
                    >
                      Close & View Catalog
                    </button>
                  </>
                ) : null}
              </div>
            </div>
          ) : (
            <>
              {/* Input Mode Selector */}
              <div className="flex rounded-xl bg-muted/40 p-1 border border-border/60">
                <button
                  type="button"
                  disabled={isBusy}
                  onClick={() => setInputMode('upload')}
                  className={`flex-1 py-1.5 text-xs font-semibold rounded-lg transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${
                    inputMode === 'upload'
                      ? 'bg-card text-foreground shadow-xs border border-border/60'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  <Upload className="w-3.5 h-3.5" />
                  Upload File (.csv)
                </button>
                <button
                  type="button"
                  disabled={isBusy}
                  onClick={() => setInputMode('paste')}
                  className={`flex-1 py-1.5 text-xs font-semibold rounded-lg transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${
                    inputMode === 'paste'
                      ? 'bg-card text-foreground shadow-xs border border-border/60'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  <FileText className="w-3.5 h-3.5" />
                  Paste CSV Text
                </button>
              </div>

              {/* Mode 1: File Upload */}
              {inputMode === 'upload' && (
                <div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".csv"
                    onChange={handleFileChange}
                    disabled={isBusy}
                    className="hidden"
                  />
                  <div
                    onDragOver={handleDragOver}
                    onDrop={handleDrop}
                    onClick={() => {
                      if (!isBusy) fileInputRef.current?.click();
                    }}
                    className={`p-8 border-2 border-dashed border-border/80 rounded-2xl bg-muted/20 transition-all text-center space-y-3 ${
                      isBusy
                        ? 'opacity-60 cursor-not-allowed'
                        : 'hover:border-primary/50 hover:bg-muted/40 cursor-pointer'
                    }`}
                  >
                    <div className="w-12 h-12 mx-auto rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
                      <Upload className="w-6 h-6" />
                    </div>
                    <div>
                      {selectedFile ? (
                        <div className="space-y-1">
                          <p className="text-xs font-semibold text-foreground">
                            {selectedFile.name}
                          </p>
                          <p className="text-[11px] font-mono text-muted-foreground">
                            {selectedFile.size > 1024 * 1024
                              ? `${(selectedFile.size / (1024 * 1024)).toFixed(2)} MB`
                              : `${(selectedFile.size / 1024).toFixed(1)} KB`}{' '}
                            • {isBusy ? 'Processing file' : 'Click or drop to replace'}
                          </p>
                        </div>
                      ) : (
                        <div className="space-y-1">
                          <p className="text-xs font-medium text-foreground">
                            Drop your CSV file here, or{' '}
                            <span className="text-primary underline">browse files</span>
                          </p>
                          <p className="text-[11px] text-muted-foreground">
                            Standard UTF-8 encoded CSV up to 25 MB matching RoleSync catalog format
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Mode 2: Paste Raw CSV */}
              {inputMode === 'paste' && (
                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">
                    Raw CSV Contents
                  </label>
                  <textarea
                    rows={8}
                    value={pastedCsv}
                    disabled={isBusy}
                    onChange={(e) => {
                      setPastedCsv(e.target.value);
                      setValidationReport(null);
                    }}
                    placeholder={`product_name,category,type,sku,price,currency,option_Size,option_Color,keywords\n"Ergonomic Chair",furniture,PRODUCT,CHAIR-BLK,299.00,USD,L,Black,"ergonomic;back pain"`}
                    className="w-full px-3 py-2 text-xs font-mono rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 resize-none disabled:opacity-60 disabled:cursor-not-allowed"
                  />
                </div>
              )}

              {/* Options & Guardrails */}
              <div className="p-4 rounded-xl bg-muted/30 border border-border/60 space-y-3">
                <span className="text-xs font-semibold text-foreground uppercase tracking-wider block">
                  Import Guardrails & Policies
                </span>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <label className={`flex items-center gap-2 ${isBusy ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}>
                    <input
                      type="checkbox"
                      disabled={isBusy}
                      checked={skipInvalid}
                      onChange={(e) => setSkipInvalid(e.target.checked)}
                      className="w-4 h-4 rounded-md border-border/80 text-primary focus:ring-primary/40 disabled:cursor-not-allowed"
                    />
                    <span>
                      <strong className="text-foreground">Skip Invalid Rows:</strong> Commit valid rows and log failures without aborting the entire batch
                    </span>
                  </label>

                  <label className={`flex items-center gap-2 ${isBusy ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}>
                    <input
                      type="checkbox"
                      disabled={isBusy}
                      checked={autoCreateCategories}
                      onChange={(e) => setAutoCreateCategories(e.target.checked)}
                      className="w-4 h-4 rounded-md border-border/80 text-primary focus:ring-primary/40 disabled:cursor-not-allowed"
                    />
                    <span>
                      <strong className="text-foreground">Auto-Register Categories:</strong> Automatically insert new categories in vocabulary
                    </span>
                  </label>
                </div>
              </div>

              {/* Dry-Run Validation Results */}
              {validationReport && (
                <div className="p-4 rounded-xl border border-border/80 bg-background space-y-4 animate-in fade-in duration-300">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <FileSpreadsheet className="w-4 h-4 text-primary" />
                      <span className="text-xs font-semibold text-foreground">
                        Dry-Run Validation Summary
                      </span>
                    </div>
                    <span
                      className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-full border ${
                        validationReport.error_count === 0
                          ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                          : 'bg-amber-500/10 text-amber-500 border-amber-500/20'
                      }`}
                    >
                      {validationReport.error_count === 0
                        ? 'CLEAN VALIDATION'
                        : `${validationReport.error_count} ERRORS DETECTED`}
                    </span>
                  </div>

                  {/* Metrics preview */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <div className="p-2.5 rounded-lg bg-muted/40 text-center">
                      <span className="text-[10px] text-muted-foreground block">Total Rows</span>
                      <span className="text-sm font-bold text-foreground">
                        {validationReport.total_rows}
                      </span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-emerald-500/10 text-center">
                      <span className="text-[10px] text-emerald-600 dark:text-emerald-400 block">
                        Valid Rows
                      </span>
                      <span className="text-sm font-bold text-emerald-600 dark:text-emerald-400">
                        {validationReport.valid_count}
                      </span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-primary/10 text-center">
                      <span className="text-[10px] text-primary block">Products (+ / ~)</span>
                      <span className="text-sm font-bold text-foreground">
                        +{validationReport.products_to_create} / ~
                        {validationReport.products_to_update}
                      </span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-primary/10 text-center">
                      <span className="text-[10px] text-primary block">Variants (+ / ~)</span>
                      <span className="text-sm font-bold text-foreground">
                        +{validationReport.variants_to_create} / ~
                        {validationReport.variants_to_update}
                      </span>
                    </div>
                  </div>

                  {/* Row-Level Errors Preview if any */}
                  {validationReport.row_results.some((r) => !r.valid) && (
                    <div className="space-y-1.5">
                      <span className="text-[11px] font-medium text-destructive block">
                        Issues Found on Rows:
                      </span>
                      <div className="max-h-36 overflow-y-auto divide-y divide-border/60 rounded-lg border border-border/70 bg-card">
                        {validationReport.row_results
                          .filter((r) => !r.valid)
                          .map((row) => (
                            <div
                              key={row.row_index}
                              className="p-2.5 text-xs flex items-start gap-2"
                            >
                              <span className="px-1.5 py-0.5 rounded bg-destructive/10 text-destructive font-mono text-[10px] font-bold shrink-0">
                                Row {row.row_index}
                              </span>
                              <div className="space-y-0.5 min-w-0">
                                {row.errors.map((err, i) => (
                                  <div key={i} className="text-destructive text-[11px]">
                                    {err}
                                  </div>
                                ))}
                              </div>
                            </div>
                          ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer Actions */}
        {!jobStatus && (
          <div className="px-6 py-4 border-t border-border/60 flex items-center justify-between bg-card/80">
            <button
              type="button"
              onClick={handleSafeClose}
              disabled={isBusy}
              className="px-4 py-2 text-xs font-medium rounded-xl border border-border/70 hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Cancel
            </button>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleRunValidation}
                disabled={isBusy || (!selectedFile && !pastedCsv.trim())}
                className="px-4 py-2 text-xs font-semibold rounded-xl border border-primary/30 hover:bg-primary/10 text-primary transition-all flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              >
                {isValidating ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Validating CSV...
                  </>
                ) : (
                  <>
                    <Play className="w-3.5 h-3.5" />
                    Dry-Run Validate
                  </>
                )}
              </button>

              <button
                type="button"
                onClick={handleCommit}
                disabled={!canCommit}
                title={
                  isBusy
                    ? 'Operation in progress'
                    : !validationReport
                    ? 'Run Dry-Run Validate first to verify rows before committing'
                    : validationReport.valid_count === 0
                    ? 'No valid rows to commit'
                    : 'Commit validated products into catalog'
                }
                className="px-4 py-2 text-xs font-semibold rounded-xl bg-primary text-primary-foreground hover:opacity-95 active:scale-98 transition-all flex items-center gap-1.5 shadow-xs disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              >
                {isCommitting ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Queueing Import...
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    Commit Ingestion
                  </>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
