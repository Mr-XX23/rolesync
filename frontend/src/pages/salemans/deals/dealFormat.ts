import type { Deal, DealInput, DealQuote, DealStage } from '../../../api/dealsApi';

export const STAGE_META: Record<DealStage, { label: string; dot: string }> = {
  PROSPECTING: { label: 'Prospecting', dot: 'bg-slate-400' },
  QUALIFIED: { label: 'Qualified', dot: 'bg-sky-500' },
  PROPOSAL: { label: 'Proposal', dot: 'bg-violet-500' },
  NEGOTIATION: { label: 'Negotiation', dot: 'bg-amber-500' },
  WON: { label: 'Won', dot: 'bg-emerald-500' },
  LOST: { label: 'Lost', dot: 'bg-red-400' },
};

export const CLOSED_STAGES: ReadonlySet<string> = new Set(['WON', 'LOST']);

export const CURRENCIES = ['USD', 'EUR', 'GBP', 'INR', 'AUD', 'CAD', 'SGD', 'AED', 'JPY'];

export function stageLabel(stage: string): string {
  return stage in STAGE_META ? STAGE_META[stage as DealStage].label : stage;
}

export function formatMoney(amount: unknown, currency: unknown, compact = false): string {
  if (amount === null || amount === undefined || amount === '') return '';
  const value = Number(amount);
  if (!Number.isFinite(value)) return '';
  const code = typeof currency === 'string' && /^[A-Z]{3}$/.test(currency) ? currency : 'USD';
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: code,
      notation: compact ? 'compact' : 'standard',
      minimumFractionDigits: 0,
      maximumFractionDigits: compact ? 1 : 2,
    }).format(value);
  } catch {
    return `${code} ${value.toLocaleString()}`;
  }
}

/** "$12K + €3K": amounts added up per currency, largest first. */
export function totalByCurrency(deals: Deal[]): string {
  const sums = new Map<string, number>();
  for (const deal of deals) {
    if (deal.amount !== null && deal.amount !== undefined) {
      const code = deal.currency || 'USD';
      sums.set(code, (sums.get(code) ?? 0) + Number(deal.amount));
    }
  }
  return [...sums.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([code, sum]) => formatMoney(sum, code, true))
    .join(' + ');
}

/** "1 Oct", or "1 Oct 2027" outside this year, for a YYYY-MM-DD day (no time zone shift). */
export function formatDay(day: string | null | undefined): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(day ?? '');
  if (!match) return day ?? '';
  const year = Number(match[1]);
  const date = new Date(Date.UTC(year, Number(match[2]) - 1, Number(match[3])));
  return date.toLocaleDateString([], {
    day: 'numeric',
    month: 'short',
    year: year === new Date().getFullYear() ? undefined : 'numeric',
    timeZone: 'UTC',
  });
}

export function matchesDeal(deal: Deal, query: string): boolean {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const text = [deal.title, deal.company, deal.next_step, deal.owner_name, ...(deal.contacts ?? []).flatMap((c) => [c.name, c.email])]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return words.every((word) => text.includes(word));
}

// ---------------------------------------------------------------------------- editing

export interface ContactForm {
  uid: number; // identifies the row while editing
  name: string;
  email: string;
  role: string;
  phone: string;
}

export interface DealForm {
  title: string;
  company: string;
  stage: DealStage;
  amount: string;
  currency: string;
  expectedCloseDate: string;
  nextStep: string;
  notes: string;
  contacts: ContactForm[];
}

/** A deal's editable values, as the server returns them (a Deal) or as they are saved (a DealInput). */
type DealValues = Omit<DealInput, 'currency'> & { currency: string | null };

let contactRows = 0;

export function emptyContact(): ContactForm {
  contactRows += 1;
  return { uid: contactRows, name: '', email: '', role: '', phone: '' };
}

export function emptyForm(): DealForm {
  return {
    title: '',
    company: '',
    stage: 'PROSPECTING',
    amount: '',
    currency: 'USD',
    expectedCloseDate: '',
    nextStep: '',
    notes: '',
    contacts: [],
  };
}

export function formFromValues(values: DealValues): DealForm {
  return {
    title: values.title ?? '',
    company: values.company ?? '',
    stage: values.stage,
    amount: values.amount === null || values.amount === undefined ? '' : String(values.amount),
    currency: values.currency || 'USD',
    expectedCloseDate: values.expected_close_date ?? '',
    nextStep: values.next_step ?? '',
    notes: values.notes ?? '',
    contacts: (values.contacts ?? []).map((contact) => ({
      ...emptyContact(),
      name: contact.name ?? '',
      email: contact.email ?? '',
      role: contact.role ?? '',
      phone: contact.phone ?? '',
    })),
  };
}

export function inputFromForm(form: DealForm, quotes: DealQuote[]): DealInput {
  const clean = (value: string): string | null => value.trim() || null;
  return {
    title: form.title.trim(),
    company: form.company.trim(),
    stage: form.stage,
    amount: form.amount.trim() === '' ? null : Number(form.amount),
    currency: form.currency,
    expected_close_date: form.expectedCloseDate || null,
    next_step: clean(form.nextStep),
    notes: clean(form.notes),
    contacts: form.contacts
      .filter((contact) => [contact.name, contact.email, contact.role, contact.phone].some((value) => value.trim()))
      .map((contact) => ({
        name: contact.name.trim(),
        email: clean(contact.email),
        role: clean(contact.role),
        phone: clean(contact.phone),
      })),
    quotes,
  };
}

/** A saved deal in the same normalized form as an edit, so the two compare field by field. */
export function inputFromDeal(deal: Deal): DealInput {
  return inputFromForm(formFromValues(deal), deal.quotes ?? []);
}

export function validateForm(form: DealForm): string | null {
  if (!form.title.trim()) return 'Give the deal a title.';
  if (!form.company.trim()) return 'Enter the customer’s company.';
  if (form.amount.trim() && !/^\d{1,13}(\.\d{1,2})?$/.test(form.amount.trim())) {
    return 'Enter the value as a number, such as 12000 or 12000.50.';
  }
  for (const contact of form.contacts) {
    const email = contact.email.trim();
    if (!contact.name.trim() && (email || contact.role.trim() || contact.phone.trim())) return 'Each contact needs a name.';
    if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return `“${email}” isn’t a valid email address.`;
  }
  return null;
}

export const DEAL_FIELDS = [
  'title',
  'company',
  'stage',
  'amount',
  'currency',
  'expected_close_date',
  'next_step',
  'notes',
  'contacts',
  'quotes',
] as const;
export type DealField = (typeof DEAL_FIELDS)[number];

export const FIELD_LABEL: Record<DealField, string> = {
  title: 'title',
  company: 'company',
  stage: 'stage',
  amount: 'value',
  currency: 'currency',
  expected_close_date: 'close date',
  next_step: 'next step',
  notes: 'notes',
  contacts: 'contacts',
  quotes: 'quotes',
};

export function changedFields(from: DealInput, to: DealInput): DealField[] {
  return DEAL_FIELDS.filter((field) => JSON.stringify(from[field]) !== JSON.stringify(to[field]));
}

/** ``target`` with ``fields`` taken from ``source``. */
export function withFields(target: DealInput, source: DealInput, fields: readonly DealField[]): DealInput {
  const merged: DealInput = { ...target };
  const copy = <K extends DealField>(field: K) => {
    merged[field] = source[field];
  };
  fields.forEach((field) => copy(field));
  return merged;
}

export function showField(field: DealField, input: DealInput): string {
  switch (field) {
    case 'stage':
      return stageLabel(input.stage);
    case 'amount':
      return formatMoney(input.amount, input.currency) || '(none)';
    case 'contacts':
      return input.contacts.map((contact) => contact.name).join(', ') || '(none)';
    case 'quotes':
      return input.quotes.map((quote) => quote.number).join(', ') || '(none)';
    default: {
      const value = input[field];
      const text = value === null || value === undefined || value === '' ? '(none)' : String(value);
      return text.length > 80 ? `${text.slice(0, 79)}…` : text;
    }
  }
}
