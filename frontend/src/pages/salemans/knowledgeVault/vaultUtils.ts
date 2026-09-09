export const MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024; // 25 MB
export const ALLOWED_EXTENSIONS = ['PDF', 'CSV', 'TXT', 'DOCX', 'MD', 'JSON', 'TSV', 'YAML', 'YML'];

export interface RagPreset {
  label: string;
  chunkSize: number;
  overlap: number;
}

export const RAG_PRESETS: Record<string, RagPreset> = {
  balanced: { label: 'Balanced (Default)', chunkSize: 512, overlap: 12 },
  qa: { label: 'High-Precision Q&A', chunkSize: 256, overlap: 15 },
  overview: { label: 'Large Context Overview', chunkSize: 1024, overlap: 10 },
};

export interface SalesCategoryMeta {
  id: string;
  label: string;
  shortLabel: string;
  badgeBg: string;
  badgeText: string;
  borderColor: string;
  dotColor: string;
  description: string;
}

export const SALES_CATEGORIES: Record<string, SalesCategoryMeta> = {
  BATTLECARD: {
    id: 'BATTLECARD',
    label: 'Battlecards',
    shortLabel: 'Battlecard',
    badgeBg: 'bg-purple-500/10 dark:bg-purple-500/20',
    badgeText: 'text-purple-700 dark:text-purple-300',
    borderColor: 'border-purple-500/30',
    dotColor: 'bg-purple-500',
    description: 'Competitor comparison, objection handling & win/loss strategies',
  },
  PRICING_PACKAGING: {
    id: 'PRICING_PACKAGING',
    label: 'Pricing & Packaging',
    shortLabel: 'Pricing',
    badgeBg: 'bg-amber-500/10 dark:bg-amber-500/20',
    badgeText: 'text-amber-700 dark:text-amber-300',
    borderColor: 'border-amber-500/30',
    dotColor: 'bg-amber-500',
    description: 'Rate cards, discounting rules, tier packaging & licensing',
  },
  CASE_STUDY_ROI: {
    id: 'CASE_STUDY_ROI',
    label: 'Case Studies & ROI',
    shortLabel: 'Case Study',
    badgeBg: 'bg-emerald-500/10 dark:bg-emerald-500/20',
    badgeText: 'text-emerald-700 dark:text-emerald-300',
    borderColor: 'border-emerald-500/30',
    dotColor: 'bg-emerald-500',
    description: 'Customer success metrics, logos, proof points & ROI calculations',
  },
  SECURITY_COMPLIANCE: {
    id: 'SECURITY_COMPLIANCE',
    label: 'Security & Compliance',
    shortLabel: 'Security',
    badgeBg: 'bg-blue-500/10 dark:bg-blue-500/20',
    badgeText: 'text-blue-700 dark:text-blue-300',
    borderColor: 'border-blue-500/30',
    dotColor: 'bg-blue-500',
    description: 'SOC2, ISO27001, GDPR, HIPAA, compliance reports & architecture',
  },
  PRODUCT_SPEC: {
    id: 'PRODUCT_SPEC',
    label: 'Product Specs',
    shortLabel: 'Product Spec',
    badgeBg: 'bg-indigo-500/10 dark:bg-indigo-500/20',
    badgeText: 'text-indigo-700 dark:text-indigo-300',
    borderColor: 'border-indigo-500/30',
    dotColor: 'bg-indigo-500',
    description: 'Technical specs, architecture overviews, API guides & schemas',
  },
  CONTRACT_LEGAL: {
    id: 'CONTRACT_LEGAL',
    label: 'Contract & Legal',
    shortLabel: 'Legal & MSA',
    badgeBg: 'bg-rose-500/10 dark:bg-rose-500/20',
    badgeText: 'text-rose-700 dark:text-rose-300',
    borderColor: 'border-rose-500/30',
    dotColor: 'bg-rose-500',
    description: 'MSAs, SLAs, DPAs, terms of service & commercial commitments',
  },
  GENERAL_RESOURCE: {
    id: 'GENERAL_RESOURCE',
    label: 'General Resources',
    shortLabel: 'General',
    badgeBg: 'bg-neutral-500/10 dark:bg-neutral-500/20',
    badgeText: 'text-neutral-700 dark:text-neutral-300',
    borderColor: 'border-neutral-500/30',
    dotColor: 'bg-neutral-400',
    description: 'General business collateral, miscellaneous notes & guides',
  },
};

export const getSalesCategoryMeta = (categoryId?: string): SalesCategoryMeta => {
  if (!categoryId) return SALES_CATEGORIES.GENERAL_RESOURCE;
  const upper = categoryId.toUpperCase();
  return SALES_CATEGORIES[upper] || SALES_CATEGORIES.GENERAL_RESOURCE;
};

/**
 * Formats byte values into clean, human-readable strings.
 */
export const formatSize = (bytes?: number): string => {
  if (!bytes || bytes === 0) return '--';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

/**
 * Formats raw ISO timestamps into polished dates and relative times.
 * e.g. "Sep 8, 2026, 09:54 AM" and "5m ago"
 */
export const formatTimestamp = (
  isoStr?: string
): { formatted: string; relative: string; full: string } => {
  if (!isoStr) {
    return { formatted: '--', relative: '--', full: '--' };
  }

  try {
    const date = new Date(isoStr);
    if (isNaN(date.getTime())) {
      return { formatted: isoStr, relative: isoStr, full: isoStr };
    }

    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHours = Math.floor(diffMin / 60);
    const diffDays = Math.floor(diffHours / 24);

    let relative = 'Just now';
    if (diffDays > 0) {
      relative = diffDays === 1 ? '1 day ago' : `${diffDays}d ago`;
    } else if (diffHours > 0) {
      relative = diffHours === 1 ? '1 hour ago' : `${diffHours}h ago`;
    } else if (diffMin > 0) {
      relative = diffMin === 1 ? '1 minute ago' : `${diffMin}m ago`;
    } else if (diffSec > 10) {
      relative = `${diffSec}s ago`;
    }

    const formatted = date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });

    const full = date.toLocaleString('en-US', {
      dateStyle: 'full',
      timeStyle: 'medium',
    });

    return { formatted, relative, full };
  } catch {
    return { formatted: isoStr, relative: isoStr, full: isoStr };
  }
};
