import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, Brain, ExternalLink, FileText, Handshake, Loader2, Plus, Trash2, X } from 'lucide-react';
import { Button } from '../../../components/common/Button';
import { useToast } from '../../../context/ToastContext';
import { DEAL_STAGES, dealsApi, describeDealError, isDealConflict, newDealId } from '../../../api/dealsApi';
import type { Deal, DealInput, DealStage } from '../../../api/dealsApi';
import { describeAgentError, salesAgentApi } from '../../../api/salesAgentApi';
import type { MemoryFact, MemoryView } from '../../../api/salesAgentApi';
import { MemoryFactList } from '../salesAgent/MemoryFacts';
import { isAppLink, isWebLink } from '../salesAgent/links';
import {
  CURRENCIES,
  FIELD_LABEL,
  STAGE_META,
  changedFields,
  emptyContact,
  emptyForm,
  formFromValues,
  formatDay,
  formatMoney,
  inputFromDeal,
  inputFromForm,
  showField,
  validateForm,
  withFields,
} from './dealFormat';
import type { ContactForm, DealField, DealForm } from './dealFormat';

const control =
  'py-2 px-3 rounded-xl border border-border bg-background text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-primary/10 focus:border-primary disabled:opacity-70 disabled:cursor-not-allowed';
const sectionTitle = 'flex items-center gap-1.5 text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground';

const Field: React.FC<{ label: string; htmlFor: string; className?: string; children: React.ReactNode }> = ({
  label,
  htmlFor,
  className = '',
  children,
}) => (
  <div className={`space-y-1 ${className}`}>
    <label htmlFor={htmlFor} className="block text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground">
      {label}
    </label>
    {children}
  </div>
);

const QuoteLink: React.FC<{ url: string }> = ({ url }) => {
  const label = (
    <>
      Open <ExternalLink className="w-3 h-3" />
    </>
  );
  const className = 'inline-flex items-center gap-1 text-foreground/70 hover:text-foreground hover:underline';
  if (isAppLink(url)) {
    return (
      <Link to={url} className={className}>
        {label}
      </Link>
    );
  }
  if (isWebLink(url)) {
    return (
      <a href={url} target="_blank" rel="noopener noreferrer" className={className}>
        {label}
      </a>
    );
  }
  return null;
};

/** Saving found the deal changed by someone else in the same fields this edit changed. */
interface Clash {
  latest: Deal;
  fields: DealField[];
  mine: DealInput;
  ours: DealField[]; // every field this edit changed
}

interface Remembered {
  deal: MemoryView | null;
  account: MemoryView | null;
  failed: boolean;
}

const statusOf = (error: unknown): number | undefined => (error as { response?: { status?: number } })?.response?.status;
const BUSY_CONFLICT = 'This deal is being changed right now. Try saving again in a moment.';

export const DealModal: React.FC<{
  deal: Deal | null; // null: a new deal
  canEdit: boolean;
  onClose: () => void;
  onSaved: (deal: Deal) => void;
  onDeleted: (dealId: string) => void;
}> = ({ deal, canEdit, onClose, onSaved, onDeleted }) => {
  const toast = useToast();
  const [dealId] = useState(() => deal?.deal_id ?? newDealId());
  const [base, setBase] = useState<Deal | null>(deal); // the saved version this edit started from
  const [form, setForm] = useState<DealForm>(() => (deal ? formFromValues(deal) : emptyForm()));
  const [busy, setBusy] = useState<'save' | 'delete' | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [clash, setClash] = useState<Clash | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [remembered, setRemembered] = useState<Remembered | null>(null);

  const memoryDealId = base?.deal_id;
  const memoryCompany = base?.company;
  useEffect(() => {
    if (!memoryDealId || !memoryCompany) return;
    let active = true;
    Promise.all([salesAgentApi.dealMemory(memoryDealId), salesAgentApi.accountMemory(memoryCompany)])
      .then(([dealMemory, accountMemory]) => {
        if (active) setRemembered({ deal: dealMemory, account: accountMemory, failed: false });
      })
      .catch(() => {
        if (active) setRemembered({ deal: null, account: null, failed: true });
      });
    return () => {
      active = false;
    };
  }, [memoryDealId, memoryCompany]);

  const readOnly = !canEdit;
  const quotes = base?.quotes ?? [];
  const dirty = base
    ? changedFields(inputFromDeal(base), inputFromForm(form, quotes)).length > 0
    : JSON.stringify(inputFromForm(form, [])) !== JSON.stringify(inputFromForm(emptyForm(), []));
  const currencies = CURRENCIES.includes(form.currency) ? CURRENCIES : [form.currency, ...CURRENCIES];

  const set = <K extends keyof DealForm>(field: K, value: DealForm[K]) => setForm((current) => ({ ...current, [field]: value }));
  const setContact = (uid: number, patch: Partial<ContactForm>) =>
    setForm((current) => ({
      ...current,
      contacts: current.contacts.map((contact) => (contact.uid === uid ? { ...contact, ...patch } : contact)),
    }));

  const close = () => {
    if (busy) return;
    if (dirty && canEdit && !window.confirm('Discard your unsaved changes to this deal?')) return;
    onClose();
  };

  const save = async () => {
    if (base && !dirty) {
      onClose();
      return;
    }
    const invalid = validateForm(form);
    if (invalid) {
      setProblem(invalid);
      return;
    }
    setProblem(null);
    setBusy('save');
    const mine = inputFromForm(form, quotes);
    try {
      const saved = await dealsApi.save(dealId, mine, base?.version);
      toast.success(base ? 'Deal saved.' : 'Deal created.');
      onSaved(saved);
    } catch (error) {
      if (base && isDealConflict(error)) {
        await merge(base, mine);
      } else {
        setProblem(describeDealError(error));
      }
    } finally {
      setBusy(null);
    }
  };

  /** Someone else saved the deal during this edit: keep both changes where they touch different fields. */
  const merge = async (start: Deal, mine: DealInput) => {
    let latest: Deal;
    try {
      latest = await dealsApi.get(start.deal_id);
    } catch (error) {
      setProblem(statusOf(error) === 404 ? 'Someone else deleted this deal while you were editing it.' : describeDealError(error));
      return;
    }
    const before = inputFromDeal(start);
    const ours = changedFields(before, mine);
    const theirs = changedFields(before, inputFromDeal(latest));
    const both = ours.filter((field) => theirs.includes(field));
    if (both.length > 0) {
      setClash({ latest, fields: both, mine, ours });
      return;
    }
    try {
      const saved = await dealsApi.save(latest.deal_id, withFields(inputFromDeal(latest), mine, ours), latest.version);
      const kept = theirs.map((field) => FIELD_LABEL[field]).join(', ');
      toast.success(kept ? `Deal saved. Changes someone else made meanwhile (${kept}) were kept.` : 'Deal saved.');
      onSaved(saved);
    } catch (error) {
      setProblem(isDealConflict(error) ? BUSY_CONFLICT : describeDealError(error));
    }
  };

  const takeTheirs = () => {
    if (!clash) return;
    const keep = clash.ours.filter((field) => !clash.fields.includes(field));
    setForm(formFromValues(withFields(inputFromDeal(clash.latest), clash.mine, keep)));
    setBase(clash.latest);
    setClash(null);
  };

  const keepMine = async () => {
    if (!clash) return;
    const { latest, mine, ours } = clash;
    const merged = withFields(inputFromDeal(latest), mine, ours);
    setClash(null);
    setBusy('save');
    try {
      const saved = await dealsApi.save(latest.deal_id, merged, latest.version);
      toast.success('Deal saved.');
      onSaved(saved);
    } catch (error) {
      setBase(latest);
      setForm(formFromValues(merged));
      setProblem(isDealConflict(error) ? BUSY_CONFLICT : describeDealError(error));
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    if (!base) return;
    setBusy('delete');
    try {
      await dealsApi.remove(base.deal_id, base.version);
      toast.success('Deal deleted.');
      onDeleted(base.deal_id);
    } catch (error) {
      setConfirmDelete(false);
      if (statusOf(error) === 404) {
        toast.info('This deal was already deleted.');
        onDeleted(base.deal_id);
      } else if (isDealConflict(error)) {
        try {
          const latest = await dealsApi.get(base.deal_id);
          setBase(latest);
          setForm(formFromValues(latest));
        } catch {
          // The message below still applies.
        }
        setProblem('Someone else just changed this deal. Review the latest version before deleting it.');
      } else {
        setProblem(describeDealError(error));
      }
    } finally {
      setBusy(null);
    }
  };

  const forget = async (view: MemoryView, fact: MemoryFact) => {
    let updated: MemoryView;
    try {
      updated = await salesAgentApi.forgetFact(view, fact.id);
    } catch (error) {
      if (statusOf(error) !== 404) {
        toast.error(describeAgentError(error));
        return;
      }
      updated = { ...view, facts: view.facts.filter((item) => item.id !== fact.id) };
    }
    setRemembered((current) =>
      current && (updated.about === 'deal' ? { ...current, deal: updated } : { ...current, account: updated })
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs animate-in fade-in duration-200">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="deal-modal-title"
        className="relative w-full max-w-4xl max-h-[92vh] bg-card border border-border/80 rounded-2xl shadow-2xl overflow-hidden flex flex-col"
      >
        <div className="px-6 py-4 border-b border-border/60 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shrink-0">
              <Handshake className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <h3 id="deal-modal-title" className="text-base font-bold text-foreground truncate">
                {base ? base.title : 'New deal'}
              </h3>
              <p className="text-xs text-muted-foreground truncate">
                {base
                  ? `${base.company} · owner: ${base.owner_name || 'unknown'} · updated ${formatDay(base.updated_at)}${
                      base.source === 'AGENT' ? ' · created by the sales agent' : ''
                    }`
                  : 'Everyone in the workspace will see this deal.'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={close}
            disabled={busy !== null}
            aria-label="Close"
            className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors disabled:opacity-30 cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 grid grid-cols-1 lg:grid-cols-[1fr_18rem] gap-6">
          <div className="space-y-5 min-w-0">
            {clash && (
              <div className="rounded-xl border border-amber-500/35 bg-amber-500/10 px-4 py-3 text-xs text-amber-900 dark:text-amber-200 space-y-2">
                <p className="flex items-start gap-2 font-semibold">
                  <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                  While you were editing, someone else (or the sales agent) changed the same fields of this deal.
                </p>
                <ul className="space-y-0.5 pl-5">
                  {clash.fields.map((field) => (
                    <li key={field}>
                      <span className="font-semibold capitalize">{FIELD_LABEL[field]}</span>: theirs “
                      {showField(field, inputFromDeal(clash.latest))}”, yours “{showField(field, clash.mine)}”
                    </li>
                  ))}
                </ul>
                <div className="flex flex-wrap items-center gap-2 pl-5">
                  <button
                    type="button"
                    onClick={takeTheirs}
                    className="px-3 py-1.5 rounded-lg border border-amber-500/40 bg-card font-semibold hover:bg-amber-500/10 cursor-pointer"
                  >
                    Use theirs
                  </button>
                  <button
                    type="button"
                    onClick={() => void keepMine()}
                    className="px-3 py-1.5 rounded-lg bg-amber-600 text-white font-semibold hover:bg-amber-700 cursor-pointer"
                  >
                    Save mine
                  </button>
                  <span className="text-[11px] opacity-80">Their changes to other fields are kept either way.</span>
                </div>
              </div>
            )}
            {problem && (
              <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2.5 text-xs text-red-700 dark:text-red-300">
                {problem}
              </div>
            )}
            {readOnly && <p className="text-xs text-muted-foreground">Viewers can see deals but not change them.</p>}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field label="Title" htmlFor="deal-title" className="sm:col-span-2">
                <input
                  id="deal-title"
                  className={`${control} w-full`}
                  value={form.title}
                  maxLength={200}
                  placeholder="Acme - 50 Pro seats"
                  disabled={readOnly}
                  onChange={(event) => set('title', event.target.value)}
                />
              </Field>
              <Field label="Company" htmlFor="deal-company">
                <input
                  id="deal-company"
                  className={`${control} w-full`}
                  value={form.company}
                  maxLength={200}
                  placeholder="Acme Corp"
                  disabled={readOnly}
                  onChange={(event) => set('company', event.target.value)}
                />
              </Field>
              <Field label="Stage" htmlFor="deal-stage">
                <select
                  id="deal-stage"
                  className={`${control} w-full`}
                  value={form.stage}
                  disabled={readOnly}
                  onChange={(event) => set('stage', event.target.value as DealStage)}
                >
                  {DEAL_STAGES.map((stage) => (
                    <option key={stage} value={stage}>
                      {STAGE_META[stage].label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Value" htmlFor="deal-amount">
                <div className="flex gap-2">
                  <input
                    id="deal-amount"
                    type="number"
                    min="0"
                    step="0.01"
                    inputMode="decimal"
                    className={`${control} flex-1 min-w-0`}
                    value={form.amount}
                    placeholder="12000"
                    disabled={readOnly}
                    onChange={(event) => set('amount', event.target.value)}
                  />
                  <select
                    aria-label="Currency"
                    className={`${control} w-24`}
                    value={form.currency}
                    disabled={readOnly}
                    onChange={(event) => set('currency', event.target.value)}
                  >
                    {currencies.map((code) => (
                      <option key={code} value={code}>
                        {code}
                      </option>
                    ))}
                  </select>
                </div>
              </Field>
              <Field label="Expected close" htmlFor="deal-close">
                <input
                  id="deal-close"
                  type="date"
                  className={`${control} w-full`}
                  value={form.expectedCloseDate}
                  disabled={readOnly}
                  onChange={(event) => set('expectedCloseDate', event.target.value)}
                />
              </Field>
              <Field label="Next step" htmlFor="deal-next" className="sm:col-span-2">
                <input
                  id="deal-next"
                  className={`${control} w-full`}
                  value={form.nextStep}
                  maxLength={500}
                  placeholder="Send pricing by Friday"
                  disabled={readOnly}
                  onChange={(event) => set('nextStep', event.target.value)}
                />
              </Field>
            </div>

            <section className="space-y-2">
              <div className="flex items-center justify-between">
                <h4 className={sectionTitle}>Contacts</h4>
                {!readOnly && form.contacts.length < 20 && (
                  <button
                    type="button"
                    onClick={() => set('contacts', [...form.contacts, emptyContact()])}
                    className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline cursor-pointer"
                  >
                    <Plus className="w-3.5 h-3.5" /> Add contact
                  </button>
                )}
              </div>
              {form.contacts.length === 0 && <p className="text-xs text-muted-foreground">No contacts yet.</p>}
              {form.contacts.map((contact) => (
                <div key={contact.uid} className="flex items-start gap-2 rounded-xl border border-border/60 bg-background/40 p-2.5">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 flex-1 min-w-0">
                    <input
                      aria-label="Contact name"
                      placeholder="Name"
                      maxLength={150}
                      className={`${control} w-full`}
                      value={contact.name}
                      disabled={readOnly}
                      onChange={(event) => setContact(contact.uid, { name: event.target.value })}
                    />
                    <input
                      aria-label="Contact email"
                      type="email"
                      placeholder="Email"
                      maxLength={320}
                      className={`${control} w-full`}
                      value={contact.email}
                      disabled={readOnly}
                      onChange={(event) => setContact(contact.uid, { email: event.target.value })}
                    />
                    <input
                      aria-label="Contact role"
                      placeholder="Role, e.g. CFO"
                      maxLength={100}
                      className={`${control} w-full`}
                      value={contact.role}
                      disabled={readOnly}
                      onChange={(event) => setContact(contact.uid, { role: event.target.value })}
                    />
                    <input
                      aria-label="Contact phone"
                      placeholder="Phone"
                      maxLength={40}
                      className={`${control} w-full`}
                      value={contact.phone}
                      disabled={readOnly}
                      onChange={(event) => setContact(contact.uid, { phone: event.target.value })}
                    />
                  </div>
                  {!readOnly && (
                    <button
                      type="button"
                      onClick={() => set('contacts', form.contacts.filter((item) => item.uid !== contact.uid))}
                      aria-label="Remove contact"
                      title="Remove contact"
                      className="p-1.5 rounded-lg text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors cursor-pointer"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </div>
              ))}
            </section>

            <Field label="Notes" htmlFor="deal-notes">
              <textarea
                id="deal-notes"
                rows={4}
                maxLength={10000}
                className={`${control} w-full resize-y`}
                value={form.notes}
                disabled={readOnly}
                onChange={(event) => set('notes', event.target.value)}
              />
            </Field>
          </div>

          <aside className="space-y-6 min-w-0">
            <section className="space-y-2">
              <h4 className={sectionTitle}>
                <FileText className="w-3.5 h-3.5" /> Quotes
              </h4>
              {quotes.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  {base ? 'No quotes yet. Ask the sales agent to create a quote for this deal.' : 'Quotes the sales agent creates for this deal appear here.'}
                </p>
              ) : (
                <ul className="space-y-1.5">
                  {quotes.map((quote) => (
                    <li key={quote.number} className="rounded-lg border border-border/60 bg-background/60 px-3 py-2 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono font-semibold text-foreground truncate">{quote.number}</span>
                        <span className="tabular-nums text-foreground shrink-0">{formatMoney(quote.total, quote.currency)}</span>
                      </div>
                      <div className="flex items-center justify-between gap-2 mt-0.5 text-[10px] text-muted-foreground">
                        <span>{formatDay(quote.created_at)}</span>
                        {quote.link && <QuoteLink url={quote.link} />}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {base && (
              <section className="space-y-3">
                <h4 className={sectionTitle}>
                  <Brain className="w-3.5 h-3.5" /> What the agent remembers
                </h4>
                {remembered === null ? (
                  <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                ) : remembered.failed ? (
                  <p className="text-xs text-muted-foreground">The agent’s memory couldn’t be loaded right now.</p>
                ) : (
                  <>
                    <div className="space-y-1.5">
                      <p className="text-[11px] font-semibold text-foreground/80">About this deal</p>
                      <MemoryFactList
                        facts={remembered.deal?.facts ?? []}
                        shared
                        canForget={canEdit}
                        emptyText="Nothing saved yet."
                        onForget={(fact) => (remembered.deal ? forget(remembered.deal, fact) : Promise.resolve())}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <p className="text-[11px] font-semibold text-foreground/80">About {remembered.account?.name || base.company}</p>
                      <MemoryFactList
                        facts={remembered.account?.facts ?? []}
                        shared
                        canForget={canEdit}
                        emptyText="Nothing saved yet."
                        onForget={(fact) => (remembered.account ? forget(remembered.account, fact) : Promise.resolve())}
                      />
                    </div>
                    <p className="text-[10px] text-muted-foreground leading-relaxed">
                      The sales agent saves what it learns while working on this customer, so it doesn’t have to ask again.
                      Your whole workspace shares it{canEdit ? '. Delete anything that’s wrong.' : '.'}
                    </p>
                  </>
                )}
              </section>
            )}
          </aside>
        </div>

        <div className="px-6 py-3 border-t border-border/60 bg-muted/20 flex flex-wrap items-center justify-between gap-3">
          <div>
            {base?.can_delete && !readOnly &&
              (confirmDelete ? (
                <div className="flex items-center gap-2 text-xs">
                  <span className="font-semibold text-destructive">Delete this deal for everyone?</span>
                  <button
                    type="button"
                    onClick={() => void remove()}
                    disabled={busy !== null}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-destructive text-destructive-foreground font-semibold hover:bg-destructive/90 disabled:opacity-50 cursor-pointer"
                  >
                    {busy === 'delete' && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                    Delete
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmDelete(false)}
                    disabled={busy !== null}
                    className="px-3 py-1.5 rounded-lg border border-border/70 text-muted-foreground hover:text-foreground hover:bg-muted/60 cursor-pointer"
                  >
                    Keep it
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmDelete(true)}
                  disabled={busy !== null}
                  className="inline-flex items-center gap-1.5 text-xs font-semibold text-destructive hover:underline cursor-pointer"
                >
                  <Trash2 className="w-3.5 h-3.5" /> Delete deal
                </button>
              ))}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={close}
              disabled={busy !== null}
              className="px-4 py-2 text-xs font-medium rounded-xl border border-border/70 hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            >
              {readOnly ? 'Close' : 'Cancel'}
            </button>
            {!readOnly && (
              <Button
                className="px-4 py-2 w-auto text-xs"
                onClick={() => void save()}
                isLoading={busy === 'save'}
                loadingText="Saving"
                disabled={busy !== null || clash !== null}
              >
                {base ? 'Save changes' : 'Create deal'}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
