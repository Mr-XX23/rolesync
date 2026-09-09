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
  const [feedbackNotice, setFeedbackNotice] = useState<string | null>(null);

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

  if (!isOpen || !document) return null;

  const currentCategoryMeta: SalesCategoryMeta = getSalesCategoryMeta(selectedCategory);

  const handleAddTag = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const clean = newTagInput.trim().replace(/^#/, '');
    if (clean && !tags.includes(clean) && tags.length < 8) {
      setTags([...tags, clean]);
      setNewTagInput('');
    }
  };

  const handleRemoveTag = (tagToRemove: string) => {
    setTags(tags.filter((t) => t !== tagToRemove));
  };

  const handleSave = async () => {
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
      setFeedbackNotice('Sales intelligence saved successfully.');
      setTimeout(() => {
        onClose();
      }, 700);
    } catch (err: any) {
      setFeedbackNotice(`Error saving: ${err.message || 'Failed to update'}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleRunReclassify = async () => {
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
        setFeedbackNotice(`AI re-classified document as ${updated.category}.`);
      }
    } catch (err: any) {
      setFeedbackNotice(`Reclassification error: ${err.message || 'Could not reclassify'}`);
    } finally {
      setIsReclassifying(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-xs animate-in fade-in duration-200">
      <div
        className="bg-card border border-border w-full max-w-2xl rounded-2xl shadow-xl overflow-hidden flex flex-col max-h-[90vh] animate-in zoom-in-95 duration-200"
        role="dialog"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-muted/20">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-primary/10 text-primary flex items-center justify-center font-bold">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-serif text-lg font-bold text-foreground">
                Sales Taxonomy & Intelligence
              </h3>
              <p className="text-xs text-muted-foreground truncate max-w-md">
                {document.name}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 text-muted-foreground hover:text-foreground rounded-lg hover:bg-muted/80 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body Form */}
        <div className="p-6 space-y-5 overflow-y-auto flex-1">
          {feedbackNotice && (
            <div className="p-3 rounded-xl bg-primary/10 border border-primary/20 text-xs text-primary font-medium flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>{feedbackNotice}</span>
            </div>
          )}

          {/* AI Status Banner */}
          <div className="flex items-center justify-between p-3.5 rounded-xl bg-muted/40 border border-border/80 text-xs">
            <div className="space-y-0.5">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] uppercase font-bold text-muted-foreground">Classifier:</span>
                <span className="font-mono text-[11px] font-semibold text-foreground">
                  {document.classifier_used || 'heuristic_rule_engine'}
                </span>
                {document.confidence_score !== undefined && (
                  <span className="font-mono text-[10px] px-1.5 py-0.5 rounded-md bg-primary/10 text-primary font-bold">
                    {Math.round(document.confidence_score * 100)}% Match
                  </span>
                )}
              </div>
              <p className="text-[11px] text-muted-foreground">
                Automatically categorized via OpenRouter AI & heuristic rules.
              </p>
            </div>
            <Button
              variant="outline"
              onClick={handleRunReclassify}
              isLoading={isReclassifying}
              className="text-xs py-1.5 px-3 h-auto rounded-lg shrink-0"
              icon={<Sparkles className="w-3.5 h-3.5 text-amber-500" />}
            >
              Re-classify AI
            </Button>
          </div>

          {/* Category Selector */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-foreground flex items-center justify-between">
              <span>Sales Collateral Category</span>
              <span className={`text-[10px] font-mono px-2 py-0.5 rounded-md border font-semibold ${currentCategoryMeta.badgeBg} ${currentCategoryMeta.badgeText} ${currentCategoryMeta.borderColor}`}>
                {currentCategoryMeta.label}
              </span>
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {Object.values(SALES_CATEGORIES).map((cat) => {
                const isSelected = selectedCategory === cat.id;
                return (
                  <button
                    key={cat.id}
                    type="button"
                    onClick={() => setSelectedCategory(cat.id)}
                    className={`p-3 rounded-xl border text-left transition-all cursor-pointer flex flex-col gap-1 ${
                      isSelected
                        ? `${cat.badgeBg} ${cat.borderColor} ring-1 ring-primary/40`
                        : 'bg-background hover:bg-muted/40 border-border/70'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-foreground">
                        {cat.label}
                      </span>
                      <div className={`w-2 h-2 rounded-full ${cat.dotColor}`} />
                    </div>
                    <p className="text-[10px] text-muted-foreground line-clamp-1">
                      {cat.description}
                    </p>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Competitor & Industry Row */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Target Competitor */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                <Building2 className="w-3.5 h-3.5 text-purple-500" />
                <span>Target Competitor</span>
                <span className="text-[10px] text-muted-foreground font-normal">(Optional)</span>
              </label>
              <input
                type="text"
                placeholder="e.g. Salesforce, HubSpot"
                value={targetCompetitor}
                onChange={(e) => setTargetCompetitor(e.target.value)}
                className="w-full px-3 py-2 bg-background border border-border rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary"
              />
              <div className="flex flex-wrap gap-1 pt-1">
                {COMMON_COMPETITORS.slice(0, 4).map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setTargetCompetitor(c)}
                    className="text-[10px] font-mono px-2 py-0.5 rounded-md bg-muted hover:bg-muted/80 text-muted-foreground hover:text-foreground border border-border/60 transition-colors"
                  >
                    +{c}
                  </button>
                ))}
              </div>
            </div>

            {/* Target Industry */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                <Briefcase className="w-3.5 h-3.5 text-emerald-500" />
                <span>Target Industry</span>
                <span className="text-[10px] text-muted-foreground font-normal">(Optional)</span>
              </label>
              <input
                type="text"
                placeholder="e.g. Healthcare, Fintech"
                value={targetIndustry}
                onChange={(e) => setTargetIndustry(e.target.value)}
                className="w-full px-3 py-2 bg-background border border-border rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary"
              />
              <div className="flex flex-wrap gap-1 pt-1">
                {COMMON_INDUSTRIES.slice(0, 4).map((ind) => (
                  <button
                    key={ind}
                    type="button"
                    onClick={() => setTargetIndustry(ind)}
                    className="text-[10px] font-mono px-2 py-0.5 rounded-md bg-muted hover:bg-muted/80 text-muted-foreground hover:text-foreground border border-border/60 transition-colors"
                  >
                    +{ind}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Sales Summary */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-foreground flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <FileText className="w-3.5 h-3.5 text-primary" />
                <span>Sales Executive Summary</span>
              </span>
              <span className="text-[10px] text-muted-foreground">
                Visible to Sales Agents in RAG
              </span>
            </label>
            <textarea
              rows={3}
              value={salesSummary}
              onChange={(e) => setSalesSummary(e.target.value)}
              placeholder="Concise 1-2 sentence overview of what this document gives to a sales rep..."
              className="w-full px-3 py-2 bg-background border border-border rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary resize-none"
            />
          </div>

          {/* Sales Tags */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-foreground flex items-center gap-1.5">
              <Tag className="w-3.5 h-3.5 text-amber-500" />
              <span>Smart Sales Tags</span>
              <span className="text-[10px] text-muted-foreground font-normal">(Up to 8 tags)</span>
            </label>
            <div className="flex flex-wrap items-center gap-1.5 p-2 bg-background border border-border rounded-xl">
              {tags.map((tag) => (
                <span
                  key={tag}
                  className="inline-flex items-center gap-1 text-[11px] font-mono px-2 py-0.5 rounded-md bg-primary/10 text-primary border border-primary/20 font-medium"
                >
                  #{tag}
                  <button
                    type="button"
                    onClick={() => handleRemoveTag(tag)}
                    className="hover:text-foreground cursor-pointer"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
              <input
                type="text"
                placeholder={tags.length === 0 ? 'Type tag and press Enter...' : 'Add tag...'}
                value={newTagInput}
                onChange={(e) => setNewTagInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleAddTag();
                  }
                }}
                className="flex-1 min-w-[120px] bg-transparent text-xs focus:outline-none px-1 py-0.5"
              />
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-border bg-muted/20">
          <Button
            variant="outline"
            onClick={onClose}
            className="text-xs py-2 px-4 rounded-xl w-auto"
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleSave}
            isLoading={isSaving}
            className="text-xs py-2 px-6 rounded-xl w-auto font-semibold"
            icon={<Save className="w-4 h-4" />}
          >
            Save Intelligence
          </Button>
        </div>
      </div>
    </div>
  );
};
