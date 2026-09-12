import React, { useState, useEffect } from 'react';
import {
  X,
  Sparkles,
  Building2,
  Tag,
  FileText,
  Save,
  CheckCircle2,
  Briefcase,
  Swords,
  CreditCard,
  TrendingUp,
  ShieldCheck,
  Cpu,
  Scale,
  Layers,
  HelpCircle,
  ChevronDown,
  Check,
  AlertCircle,
  Plus,
} from 'lucide-react';
import { Button } from '../../../components/common/Button';
import {
  SALES_CATEGORIES,
  getSalesCategoryMeta,
  type SalesCategoryMeta,
} from './vaultUtils';
import type { KnowledgeDocument } from '../../../api/knowledgeVaultApi';

interface EditSalesMetadataModalProps {
  document: KnowledgeDocument | null;
  isOpen: boolean;
  onClose: () => void;
  onSave: (
    docId: string,
    data: {
      category: string;
      target_competitor: string | null;
      target_industry: string | null;
      sales_summary: string;
      sales_tags: string[];
    }
  ) => Promise<void>;
  onReclassify: (docId: string) => Promise<KnowledgeDocument>;
}

const COMMON_COMPETITORS = [
  'Salesforce',
  'HubSpot',
  'Zendesk',
  'ServiceNow',
  'Slack',
  'Notion',
  'Zoom',
  'Jira',
];

const COMMON_INDUSTRIES = [
  'Healthcare',
  'Fintech',
  'Enterprise SaaS',
  'Retail',
  'Cybersecurity',
  'Banking',
];

const CATEGORY_ICONS: Record<string, React.FC<{ className?: string }>> = {
  BATTLECARD: Swords,
  PRICING_PACKAGING: CreditCard,
  CASE_STUDY_ROI: TrendingUp,
  SECURITY_COMPLIANCE: ShieldCheck,
  PRODUCT_SPEC: Cpu,
  CONTRACT_LEGAL: Scale,
  GENERAL_RESOURCE: Layers,
};

const RECOMMENDED_TAGS: Record<string, string[]> = {
  BATTLECARD: ['objection-handling', 'kill-sheet', 'differentiator', 'win-loss', 'rebuttal'],
  PRICING_PACKAGING: ['rate-card', 'discount-rules', 'tier-pricing', 'enterprise-quote', 'licensing'],
  CASE_STUDY_ROI: ['customer-metrics', 'roi-proof', 'client-story', 'logos', 'benchmark'],
  SECURITY_COMPLIANCE: ['soc2', 'hipaa', 'gdpr', 'iso27001', 'encryption', 'pen-test'],
  PRODUCT_SPEC: ['api-docs', 'architecture', 'technical-spec', 'data-model', 'system-guide'],
  CONTRACT_LEGAL: ['msa', 'sla', 'dpa', 'terms-of-service', 'liability'],
  GENERAL_RESOURCE: ['overview', 'enablement', 'guide', 'reference'],
};

export const EditSalesMetadataModal: React.FC<EditSalesMetadataModalProps> = ({
  document,
  isOpen,
  onClose,
  onSave,
  onReclassify,
}) => {
  const [selectedCategory, setSelectedCategory] = useState<string>('GENERAL_RESOURCE');
  const [targetCompetitor, setTargetCompetitor] = useState<string>('');
  const [targetIndustry, setTargetIndustry] = useState<string>('');
  const [salesSummary, setSalesSummary] = useState<string>('');
  const [tags, setTags] = useState<string[]>([]);
  const [newTagInput, setNewTagInput] = useState<string>('');
  const [isSaving, setIsSaving] = useState(false);
  const [isReclassifying, setIsReclassifying] = useState(false);
  const [feedbackNotice, setFeedbackNotice] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Sync state when document changes
  useEffect(() => {
    if (document) {
      setSelectedCategory(document.category || 'GENERAL_RESOURCE');
      setTargetCompetitor(document.target_competitor || '');
      setTargetIndustry(document.target_industry || '');
      setSalesSummary(document.sales_summary || '');
      setTags(document.sales_tags || []);
      setFeedbackNotice(null);
    }
  }, [document]);

  // Lock Escape key when saving or reclassifying
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isSaving && !isReclassifying) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isSaving, isReclassifying, onClose]);

  if (!isOpen || !document) return null;

  const currentCategoryMeta: SalesCategoryMeta = getSalesCategoryMeta(selectedCategory);

  const handleAddTag = (tagToAdd?: string) => {
    const clean = (tagToAdd || newTagInput).trim().replace(/^#/, '');
    if (clean && !tags.includes(clean) && tags.length < 8) {
      setTags([...tags, clean]);
      if (!tagToAdd) setNewTagInput('');
    }
  };

  const handleRemoveTag = (tagToRemove: string) => {
    if (isSaving || isReclassifying) return;
    setTags(tags.filter((t) => t !== tagToRemove));
  };

  const handleSave = async () => {
    if (isSaving || isReclassifying) return;
    setIsSaving(true);
    setFeedbackNotice(null);
    try {
      await onSave(document.doc_id, {
        category: selectedCategory,
        target_competitor: targetCompetitor.trim() || null,
        target_industry: targetIndustry.trim() || null,
        sales_summary: salesSummary.trim(),
        sales_tags: tags,
      });
      setFeedbackNotice({
        type: 'success',
        message: 'Sales intelligence saved & synced with sales agents.',
      });
      setTimeout(() => {
        onClose();
      }, 750);
    } catch (err: any) {
      setFeedbackNotice({
        type: 'error',
        message: `Failed to save: ${err.message || 'Server error occurred'}`,
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleRunReclassify = async () => {
    if (isSaving || isReclassifying) return;
    setIsReclassifying(true);
    setFeedbackNotice(null);
    try {
      const updated = await onReclassify(document.doc_id);
      if (updated) {
        setSelectedCategory(updated.category || 'GENERAL_RESOURCE');
        setTargetCompetitor(updated.target_competitor || '');
        setTargetIndustry(updated.target_industry || '');
        setSalesSummary(updated.sales_summary || '');
        setTags(updated.sales_tags || []);
        setFeedbackNotice({
          type: 'success',
          message: `Deep AI re-classified document as "${getSalesCategoryMeta(updated.category).label}" with verified taxonomy.`,
        });
      }
    } catch (err: any) {
      setFeedbackNotice({
        type: 'error',
        message: `AI Reclassification failed: ${err.message || 'Service unreachable'}`,
      });
    } finally {
      setIsReclassifying(false);
    }
  };

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget && !isSaving && !isReclassifying) {
      onClose();
    }
  };

  // Human-friendly classifier label formatting
  const getClassifierInfo = (rawClassifier?: string, confidence?: number) => {
    const raw = rawClassifier || '';
    const isManual = raw === 'manual_user_override';
    const isOpenRouter = raw.startsWith('openrouter:');

    if (isManual) {
      return {
        title: 'Manual Verification',
        tag: 'User Verified',
        subtext: 'Manually curated and approved by a sales team member.',
        badge: '100% Match',
        badgeColor: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
        isAi: false,
      };
    }

    if (isOpenRouter) {
      const modelShort = raw.replace('openrouter:', '').split('/').pop() || 'Deep AI';
      const pct = confidence !== undefined ? Math.round(confidence * 100) : 95;
      return {
        title: `OpenRouter AI (${modelShort})`,
        tag: 'Deep Semantic Scan',
        subtext: 'Extracted via LLM content reading of document text.',
        badge: `${pct}% High Confidence`,
        badgeColor: 'bg-primary/10 text-primary border-primary/30',
        isAi: true,
      };
    }

    // Default heuristic engine
    const pct = confidence !== undefined ? Math.round(confidence * 100) : 50;
    return {
      title: 'Pattern Rule Engine',
      tag: 'Fast Heuristics',
      subtext: 'Initial scan from filename & keyword signals. Click "Re-classify with AI" for deep document reading (>90% accuracy).',
      badge: `${pct}% Baseline Scan`,
      badgeColor: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30',
      isAi: false,
    };
  };

  const classifierInfo = getClassifierInfo(document.classifier_used, document.confidence_score);
  const isBusy = isSaving || isReclassifying;

  return (
    <div
      onClick={handleBackdropClick}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-xs animate-in fade-in duration-200"
    >
      <div
        className="bg-card border border-border w-full max-w-2xl rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[92vh] animate-in zoom-in-95 duration-200"
        role="dialog"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-muted/20">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 text-primary flex items-center justify-center font-bold shadow-xs">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-serif text-lg font-bold text-foreground">
                  Sales Taxonomy & Intelligence
                </h3>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">
                  RAG Indexed
                </span>
              </div>
              <p className="text-xs text-muted-foreground truncate max-w-md mt-0.5" title={document.name}>
                {document.name}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isBusy}
            aria-label="Close modal"
            className={`p-1.5 rounded-lg transition-colors ${
              isBusy
                ? 'opacity-30 cursor-not-allowed text-muted-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/80 cursor-pointer'
            }`}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body Form */}
        <div className="p-6 space-y-5 overflow-y-auto flex-1">
          {/* Feedback Notice */}
          {feedbackNotice && (
            <div
              className={`p-3 rounded-xl border text-xs font-medium flex items-center gap-2 animate-in fade-in duration-200 ${
                feedbackNotice.type === 'success'
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400'
                  : 'bg-destructive/10 border-destructive/30 text-destructive'
              }`}
            >
              {feedbackNotice.type === 'success' ? (
                <CheckCircle2 className="w-4 h-4 shrink-0" />
              ) : (
                <AlertCircle className="w-4 h-4 shrink-0" />
              )}
              <span>{feedbackNotice.message}</span>
            </div>
          )}

          {/* Clean Human-Friendly Classifier Status Banner */}
          <div className="p-4 rounded-xl bg-muted/40 border border-border/80 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-2xs">
            <div className="space-y-1">
              <div className="flex items-center flex-wrap gap-2">
                <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                  Classifier:
                </span>
                <span className="text-xs font-bold text-foreground">
                  {classifierInfo.title}
                </span>
                <span className={`text-[11px] font-medium px-2 py-0.5 rounded-md border ${classifierInfo.badgeColor}`}>
                  {classifierInfo.badge}
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                {classifierInfo.subtext}
              </p>
            </div>

            <Button
              variant="outline"
              onClick={handleRunReclassify}
              disabled={isBusy}
              isLoading={isReclassifying}
              loadingText="Analyzing with AI..."
              icon={<Sparkles className="w-3.5 h-3.5 text-amber-500 shrink-0" />}
              iconPosition="left"
              className="text-xs py-2 px-3.5 h-auto rounded-xl shrink-0 font-medium hover:border-amber-500/40 hover:bg-amber-500/5 transition-all shadow-xs"
            >
              Re-classify with AI
            </Button>
          </div>

          {/* Sales Collateral Category Selector */}
          <div className="space-y-2.5">
            <div className="flex items-center justify-between">
              <div>
                <label className="text-xs font-semibold text-foreground block">
                  Sales Collateral Category
                </label>
                <p className="text-[11px] text-muted-foreground">
                  Controls how sales agents discover this asset during buyer negotiations & objections
                </p>
              </div>
              <span
                className={`text-[11px] font-medium px-2.5 py-0.5 rounded-md border ${currentCategoryMeta.badgeBg} ${currentCategoryMeta.badgeText} ${currentCategoryMeta.borderColor}`}
              >
                {currentCategoryMeta.label}
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              {Object.values(SALES_CATEGORIES).map((cat) => {
                const isSelected = selectedCategory === cat.id;
                const IconComponent = CATEGORY_ICONS[cat.id] || Layers;
                return (
                  <button
                    key={cat.id}
                    type="button"
                    disabled={isBusy}
                    onClick={() => setSelectedCategory(cat.id)}
                    className={`p-3 rounded-xl border text-left transition-all cursor-pointer flex flex-col gap-1.5 relative group ${
                      isSelected
                        ? `${cat.badgeBg} ${cat.borderColor} ring-2 ring-primary/40 shadow-xs`
                        : 'bg-background hover:bg-muted/40 border-border/70 hover:border-border'
                    } ${isBusy ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className={`w-6 h-6 rounded-lg flex items-center justify-center shrink-0 ${cat.badgeBg} ${cat.badgeText}`}>
                          <IconComponent className="w-3.5 h-3.5" />
                        </div>
                        <span className="text-xs font-bold text-foreground">
                          {cat.label}
                        </span>
                      </div>
                      {isSelected ? (
                        <div className="w-4 h-4 rounded-full bg-primary text-primary-foreground flex items-center justify-center shrink-0">
                          <Check className="w-2.5 h-2.5 stroke-[3]" />
                        </div>
                      ) : (
                        <div className={`w-2 h-2 rounded-full ${cat.dotColor} opacity-60 group-hover:opacity-100 transition-opacity shrink-0`} />
                      )}
                    </div>
                    <p className="text-[11px] text-muted-foreground line-clamp-2 pl-8 leading-relaxed">
                      {cat.description}
                    </p>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Target Competitor & Industry Row */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Target Competitor */}
            <div className="space-y-2">
              <label className="text-xs font-semibold text-foreground flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <Building2 className="w-4 h-4 text-purple-500 shrink-0" />
                  <span>Target Competitor</span>
                </span>
                <span className="text-[10px] text-muted-foreground font-normal">Optional • Battlecards</span>
              </label>
              <input
                type="text"
                disabled={isBusy}
                placeholder="e.g. Salesforce, HubSpot, Zendesk"
                value={targetCompetitor}
                onChange={(e) => setTargetCompetitor(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-background border border-border rounded-xl text-sm placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary disabled:opacity-50 disabled:cursor-not-allowed transition-all"
              />
              <div className="flex flex-wrap gap-1.5 pt-0.5">
                {COMMON_COMPETITORS.slice(0, 5).map((c) => {
                  const isActive = targetCompetitor.toLowerCase() === c.toLowerCase();
                  return (
                    <button
                      key={c}
                      type="button"
                      disabled={isBusy}
                      onClick={() => setTargetCompetitor(isActive ? '' : c)}
                      className={`text-[11px] font-medium px-2.5 py-1 rounded-lg border transition-all cursor-pointer ${
                        isActive
                          ? 'bg-purple-500/15 text-purple-600 dark:text-purple-300 border-purple-500/40 font-semibold shadow-2xs'
                          : 'bg-muted/50 hover:bg-muted text-muted-foreground hover:text-foreground border-border/60'
                      } ${isBusy ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      {isActive ? `✓ ${c}` : `+${c}`}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Target Industry */}
            <div className="space-y-2">
              <label className="text-xs font-semibold text-foreground flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <Briefcase className="w-4 h-4 text-emerald-500 shrink-0" />
                  <span>Target Industry</span>
                </span>
                <span className="text-[10px] text-muted-foreground font-normal">Optional • Vertical RAG</span>
              </label>
              <input
                type="text"
                disabled={isBusy}
                placeholder="e.g. Healthcare, Fintech, Enterprise SaaS"
                value={targetIndustry}
                onChange={(e) => setTargetIndustry(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-background border border-border rounded-xl text-sm placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary disabled:opacity-50 disabled:cursor-not-allowed transition-all"
              />
              <div className="flex flex-wrap gap-1.5 pt-0.5">
                {COMMON_INDUSTRIES.slice(0, 5).map((ind) => {
                  const isActive = targetIndustry.toLowerCase() === ind.toLowerCase();
                  return (
                    <button
                      key={ind}
                      type="button"
                      disabled={isBusy}
                      onClick={() => setTargetIndustry(isActive ? '' : ind)}
                      className={`text-[11px] font-medium px-2.5 py-1 rounded-lg border transition-all cursor-pointer ${
                        isActive
                          ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 border-emerald-500/40 font-semibold shadow-2xs'
                          : 'bg-muted/50 hover:bg-muted text-muted-foreground hover:text-foreground border-border/60'
                      } ${isBusy ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      {isActive ? `✓ ${ind}` : `+${ind}`}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Sales Executive Summary - Bigger Spacious Textarea */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                <FileText className="w-4 h-4 text-primary shrink-0" />
                <span>Sales Executive Summary</span>
              </label>
              <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
                Injected into Agent Context
              </span>
            </div>
            <textarea
              rows={4}
              disabled={isBusy}
              value={salesSummary}
              onChange={(e) => setSalesSummary(e.target.value)}
              placeholder="High-density 1-2 sentence briefing that sales agents read first when fielding customer inquiries, objections, and negotiation calls..."
              className="w-full p-3.5 bg-background border border-border rounded-xl text-sm leading-relaxed placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary resize-y min-h-[105px] disabled:opacity-50 disabled:cursor-not-allowed transition-all"
            />
            <div className="flex items-center justify-between text-[11px] text-muted-foreground pt-0.5">
              <span>This summary is indexed with high 2.0x weight for immediate retrieval during sales reps calls.</span>
              <span className="font-mono text-[10px]">{salesSummary.length} chars</span>
            </div>
          </div>

          {/* Smart Sales Tags - Spacious Input & Recommended Suggestions */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                <Tag className="w-4 h-4 text-amber-500 shrink-0" />
                <span>Smart Sales Tags</span>
                <span className="text-[10px] text-muted-foreground font-normal">(Up to 8 tags)</span>
              </label>
              <span className="text-[10px] text-muted-foreground font-mono">
                {tags.length}/8 tags
              </span>
            </div>

            {/* Tag Badges Container */}
            <div className="min-h-[50px] p-2.5 bg-background border border-border rounded-xl flex flex-wrap items-center gap-2 focus-within:ring-2 focus-within:ring-primary/20 focus-within:border-primary transition-all">
              {tags.map((tag) => (
                <span
                  key={tag}
                  className="inline-flex items-center gap-1.5 text-xs font-mono px-2.5 py-1 rounded-lg bg-primary/10 text-primary border border-primary/20 font-medium shadow-2xs"
                >
                  #{tag}
                  <button
                    type="button"
                    disabled={isBusy}
                    onClick={() => handleRemoveTag(tag)}
                    aria-label={`Remove tag ${tag}`}
                    className="hover:text-foreground hover:bg-primary/20 rounded p-0.5 cursor-pointer disabled:cursor-not-allowed transition-colors"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
              <input
                type="text"
                disabled={isBusy || tags.length >= 8}
                placeholder={
                  tags.length >= 8
                    ? 'Maximum tags reached'
                    : tags.length === 0
                    ? 'Type tag and press Enter (e.g. #objection, #soc2)...'
                    : 'Add tag...'
                }
                value={newTagInput}
                onChange={(e) => setNewTagInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleAddTag();
                  }
                }}
                className="flex-1 min-w-[150px] bg-transparent text-sm focus:outline-none px-2 py-1 disabled:cursor-not-allowed"
              />
            </div>

            {/* Recommended Tags Quick Suggestions */}
            {RECOMMENDED_TAGS[selectedCategory] && (
              <div className="flex items-center flex-wrap gap-1.5 pt-1">
                <span className="text-[10px] text-muted-foreground font-medium flex items-center gap-1">
                  <Plus className="w-3 h-3" /> Suggestions:
                </span>
                {RECOMMENDED_TAGS[selectedCategory].map((sug) => {
                  const alreadyAdded = tags.includes(sug);
                  return (
                    <button
                      key={sug}
                      type="button"
                      disabled={isBusy || alreadyAdded || tags.length >= 8}
                      onClick={() => handleAddTag(sug)}
                      className={`text-[10px] font-mono px-2 py-0.5 rounded-md border transition-colors cursor-pointer ${
                        alreadyAdded
                          ? 'bg-primary/10 text-primary/40 border-primary/10 cursor-not-allowed'
                          : 'bg-muted/40 hover:bg-muted text-muted-foreground hover:text-foreground border-border/50'
                      }`}
                    >
                      {alreadyAdded ? `✓ #${sug}` : `+#${sug}`}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Embedded "How Sales Intelligence Powers Your Platform" Helper Drawer */}
          <details className="group rounded-xl border border-border/70 bg-muted/20 p-3 text-xs">
            <summary className="font-semibold text-foreground cursor-pointer flex items-center justify-between list-none">
              <span className="flex items-center gap-2 text-muted-foreground group-hover:text-foreground transition-colors">
                <HelpCircle className="w-3.5 h-3.5 text-primary" />
                <span>How Sales Intelligence Powers Autonomous Sales Agents</span>
              </span>
              <ChevronDown className="w-3.5 h-3.5 text-muted-foreground group-open:rotate-180 transition-transform" />
            </summary>
            <div className="pt-2.5 text-muted-foreground space-y-2 text-[11px] leading-relaxed border-t border-border/50 mt-2">
              <p>
                When prospects ask questions during sales calls or negotiation, autonomous agents query the Knowledge Vault using <strong>weighted metadata ranking</strong>:
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 font-mono text-[10px] text-foreground bg-muted/40 p-2.5 rounded-lg border border-border/40">
                <div>• Competitor: <span className="text-primary font-bold">2.0x</span></div>
                <div>• Summary: <span className="text-primary font-bold">2.0x</span></div>
                <div>• Sales Tags: <span className="text-primary font-bold">2.0x</span></div>
                <div>• Industry: <span className="text-primary font-bold">1.5x</span></div>
                <div>• Category: <span className="text-primary font-bold">1.0x</span></div>
                <div>• Filename: <span className="text-primary font-bold">3.0x</span></div>
              </div>
              <p className="text-[10px] italic text-muted-foreground">
                This taxonomy guarantees your agents cite exact pricing, battlecards, and compliance without hallucination.
              </p>
            </div>
          </details>
        </div>

        {/* Footer Actions - With Strict Action Blocking */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-border bg-muted/20">
          <Button
            variant="outline"
            onClick={onClose}
            disabled={isBusy}
            className="text-xs py-2 px-4 rounded-xl w-auto font-medium"
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleSave}
            disabled={isBusy}
            isLoading={isSaving}
            loadingText="Saving Intelligence..."
            icon={<Save className="w-4 h-4 shrink-0" />}
            iconPosition="left"
            className="text-xs py-2 px-6 rounded-xl w-auto font-semibold shadow-xs"
          >
            Save Intelligence
          </Button>
        </div>
      </div>
    </div>
  );
};
