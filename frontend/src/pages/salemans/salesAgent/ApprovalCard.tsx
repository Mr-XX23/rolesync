import React, { useState } from 'react';
import { Check, Clock, Pencil, X } from 'lucide-react';
import { Button } from '../../../components/common/Button';
import type { Decision } from '../../../api/salesAgentApi';
import type { ApprovalCardModel } from './chatState';
import { describeKind, previewKind } from './approvalKinds';
import { PreviewBody, UndoPreview } from './ApprovalPreview';

interface ApprovalCardProps {
  card: ApprovalCardModel;
  busy: boolean;
  onDecide: (card: ApprovalCardModel, decision: Decision, options?: { args?: Record<string, unknown>; note?: string }) => void;
}

const RESOLVED_LABEL: Record<string, { label: string; tone: string }> = {
  APPROVED: { label: 'Approved', tone: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30' },
  EDITED: { label: 'Approved with edits', tone: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30' },
  REJECTED: { label: 'Rejected', tone: 'bg-amber-500/15 text-amber-800 dark:text-amber-300 border-amber-500/30' },
  EXPIRED: { label: 'Expired', tone: 'bg-muted text-muted-foreground border-border' },
};

const asList = (value: unknown): string[] => (Array.isArray(value) ? value.map(String) : []);
const splitAddresses = (value: string): string[] =>
  value
    .split(/[,;\n]/)
    .map((part) => part.trim())
    .filter(Boolean);

function expiresLabel(expiresAt: string): string {
  const minutes = Math.round((new Date(expiresAt).getTime() - Date.now()) / 60000);
  if (Number.isNaN(minutes)) return '';
  if (minutes <= 0) return 'expired';
  if (minutes < 60) return `expires in ${minutes} min`;
  return `expires in ${Math.round(minutes / 60)} h`;
}

export const ApprovalCard: React.FC<ApprovalCardProps> = ({ card, busy, onDecide }) => {
  const kind = previewKind(card);
  const isEmail = kind === 'email';
  const isUndo = kind === 'undo';
  const { title, approve, icon: Icon } = describeKind(card);
  const [mode, setMode] = useState<'view' | 'edit' | 'reject'>('view');
  const [note, setNote] = useState('');
  const [to, setTo] = useState(asList(card.args.to).join(', '));
  const [cc, setCc] = useState(asList(card.args.cc).join(', '));
  const [subject, setSubject] = useState(String(card.args.subject ?? ''));
  const [body, setBody] = useState(String(card.args.body ?? ''));
  const [json, setJson] = useState(JSON.stringify(card.args, null, 2));
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(asList(card.args.action_ids)));

  const resolved = card.status !== 'PENDING' ? RESOLVED_LABEL[card.status] : null;

  const toggle = (actionId: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(actionId)) {
        next.delete(actionId);
      } else {
        next.add(actionId);
      }
      return next;
    });

  const submitEdit = () => {
    if (isEmail) {
      onDecide(card, 'edit', {
        args: { ...card.args, to: splitAddresses(to), cc: splitAddresses(cc), subject, body },
      });
      return;
    }
    if (isUndo) {
      onDecide(card, 'edit', { args: { ...card.args, action_ids: [...selected] } });
      return;
    }
    try {
      onDecide(card, 'edit', { args: JSON.parse(json) });
      setJsonError(null);
    } catch {
      setJsonError('Arguments must be valid JSON');
    }
  };

  return (
    <div className="rounded-2xl border border-primary/30 bg-card shadow-sm overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-5 py-3 border-b border-border/60 bg-primary/5">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-primary/15 text-primary flex items-center justify-center shrink-0">
            <Icon className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-bold text-foreground truncate">{title}</p>
            <p className="text-[11px] text-muted-foreground truncate">
              {isUndo
                ? 'An action didn’t go through. Nothing is undone unless you say so.'
                : card.reason ?? 'The agent paused for your approval before acting.'}
            </p>
          </div>
        </div>
        {resolved ? (
          <span className={`text-[10px] font-mono font-bold uppercase tracking-wider border px-2.5 py-0.5 rounded-full ${resolved.tone}`}>
            {isUndo && card.status === 'REJECTED' ? 'Kept' : resolved.label}
          </span>
        ) : (
          <span className="flex items-center gap-1 text-[11px] text-muted-foreground font-mono shrink-0">
            <Clock className="w-3.5 h-3.5" />
            {expiresLabel(card.expiresAt)}
          </span>
        )}
      </div>

      <div className="px-5 py-4 space-y-3">
        {mode === 'edit' && isEmail ? (
          <div className="space-y-3">
            <Field label="To">
              <input className={inputClass} value={to} onChange={(e) => setTo(e.target.value)} />
            </Field>
            <Field label="Cc">
              <input className={inputClass} value={cc} onChange={(e) => setCc(e.target.value)} placeholder="optional" />
            </Field>
            <Field label="Subject">
              <input className={inputClass} value={subject} onChange={(e) => setSubject(e.target.value)} />
            </Field>
            <Field label="Message">
              <textarea className={`${inputClass} min-h-40 resize-y`} value={body} onChange={(e) => setBody(e.target.value)} />
            </Field>
          </div>
        ) : mode === 'edit' && isUndo ? (
          <UndoPreview preview={card.preview} selected={selected} onToggle={toggle} />
        ) : mode === 'edit' ? (
          <Field label="Arguments (JSON)">
            <textarea className={`${inputClass} min-h-40 font-mono text-xs`} value={json} onChange={(e) => setJson(e.target.value)} />
            {jsonError && <p className="text-xs text-destructive mt-1">{jsonError}</p>}
          </Field>
        ) : (
          <PreviewBody card={card} />
        )}

        {mode === 'reject' && !isUndo && (
          <Field label="What should change? (optional)">
            <input
              className={inputClass}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. make it shorter and less formal"
            />
          </Field>
        )}
      </div>

      {!resolved && (
        <div className="flex flex-wrap items-center justify-end gap-2 px-5 py-3 border-t border-border/60 bg-muted/20">
          {mode === 'view' && (
            <>
              <Button
                variant="outline"
                className="px-3.5 py-2 text-xs"
                disabled={busy}
                onClick={() => (isUndo ? onDecide(card, 'reject') : setMode('reject'))}
                icon={<X className="w-3.5 h-3.5" />}
              >
                {isUndo ? 'Keep them' : 'Reject'}
              </Button>
              <Button variant="outline" className="px-3.5 py-2 text-xs" disabled={busy} onClick={() => setMode('edit')} icon={<Pencil className="w-3.5 h-3.5" />}>
                {isUndo ? 'Choose' : 'Edit'}
              </Button>
              <Button className="px-4 py-2 text-xs w-auto" isLoading={busy} loadingText="Approving" onClick={() => onDecide(card, 'approve')} icon={<Check className="w-3.5 h-3.5" />}>
                {approve}
              </Button>
            </>
          )}
          {mode === 'edit' && (
            <>
              <Button variant="outline" className="px-3.5 py-2 text-xs" disabled={busy} onClick={() => setMode('view')}>
                Cancel
              </Button>
              <Button
                className="px-4 py-2 text-xs w-auto"
                isLoading={busy}
                loadingText="Sending"
                disabled={isUndo && selected.size === 0}
                onClick={submitEdit}
                icon={<Check className="w-3.5 h-3.5" />}
              >
                {isEmail ? 'Send edited email' : isUndo ? `Undo ${selected.size} selected` : 'Approve edited'}
              </Button>
            </>
          )}
          {mode === 'reject' && (
            <>
              <Button variant="outline" className="px-3.5 py-2 text-xs" disabled={busy} onClick={() => setMode('view')}>
                Cancel
              </Button>
              <Button variant="destructive" className="px-4 py-2 text-xs" isLoading={busy} loadingText="Rejecting" onClick={() => onDecide(card, 'reject', { note })}>
                Reject
              </Button>
            </>
          )}
        </div>
      )}
    </div>
  );
};

const inputClass =
  'w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20';

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <label className="block space-y-1">
    <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground">{label}</span>
    {children}
  </label>
);
