import React from 'react';
import { AlertTriangle, CheckCircle2, CircleSlash, Loader2, Wrench } from 'lucide-react';
import type { TranscriptItem } from '../../../api/salesAgentApi';

const OUTCOME_TONE: Record<string, string> = {
  EXECUTED: 'text-emerald-700 dark:text-emerald-300 bg-emerald-500/10 border-emerald-500/25',
  REJECTED: 'text-amber-800 dark:text-amber-300 bg-amber-500/10 border-amber-500/25',
  EXPIRED: 'text-muted-foreground bg-muted border-border',
};
const FAILURE_TONE = 'text-red-700 dark:text-red-300 bg-red-500/10 border-red-500/25';

const TOOL_LABEL: Record<string, string> = { send_email: 'Send email' };

function describeCall(item: TranscriptItem): string {
  const args = item.args ?? {};
  if (item.tool === 'send_email') {
    const to = Array.isArray(args.to) ? args.to.join(', ') : '';
    return `${to}${args.subject ? ` · “${String(args.subject)}”` : ''}`;
  }
  return Object.keys(args).length ? JSON.stringify(args).slice(0, 140) : '';
}

export const Transcript: React.FC<{ items: TranscriptItem[]; draft: string; step: string | null; running: boolean }> = ({
  items,
  draft,
  step,
  running,
}) => (
  <div className="space-y-4">
    {items.map((item, index) => {
      switch (item.kind) {
        case 'user':
          return (
            <div key={index} className="flex justify-end">
              <div className="max-w-[80%] rounded-2xl rounded-br-md bg-primary text-primary-foreground px-4 py-2.5 text-sm whitespace-pre-wrap leading-relaxed shadow-2xs">
                {item.text}
              </div>
            </div>
          );
        case 'assistant':
          return (
            <div key={index} className="flex justify-start">
              <div className="max-w-[80%] rounded-2xl rounded-bl-md bg-card border border-border/70 px-4 py-2.5 text-sm text-foreground whitespace-pre-wrap leading-relaxed shadow-2xs">
                {item.text}
              </div>
            </div>
          );
        case 'tool_call':
          return (
            <div key={index} className="flex items-center gap-2 text-xs text-muted-foreground pl-1">
              <Wrench className="w-3.5 h-3.5 shrink-0" />
              <span className="font-semibold text-foreground/80">{TOOL_LABEL[item.tool ?? ''] ?? item.tool}</span>
              <span className="truncate">{describeCall(item)}</span>
            </div>
          );
        case 'tool_result': {
          const outcome = item.outcome ?? 'FAILED';
          const tone = OUTCOME_TONE[outcome] ?? FAILURE_TONE;
          const Icon = outcome === 'EXECUTED' ? CheckCircle2 : outcome === 'REJECTED' || outcome === 'EXPIRED' ? CircleSlash : AlertTriangle;
          return (
            <div key={index} className={`flex items-start gap-2 text-xs rounded-xl border px-3 py-2 ${tone}`}>
              <Icon className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span className="font-mono font-bold uppercase tracking-wider text-[10px] pt-0.5 shrink-0">{outcome}</span>
              <span className="min-w-0 break-words">{item.summary || item.error}</span>
            </div>
          );
        }
        default:
          return null;
      }
    })}

    {draft && (
      <div className="flex justify-start">
        <div className="max-w-[80%] rounded-2xl rounded-bl-md bg-card border border-border/70 px-4 py-2.5 text-sm text-foreground whitespace-pre-wrap leading-relaxed shadow-2xs">
          {draft}
          <span className="inline-block w-1.5 h-4 ml-0.5 align-text-bottom bg-primary/70 animate-pulse" />
        </div>
      </div>
    )}

    {running && !draft && (
      <div className="flex items-center gap-2 text-xs text-muted-foreground pl-1">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        <span className="capitalize">{step ?? 'working'}…</span>
      </div>
    )}
  </div>
);
