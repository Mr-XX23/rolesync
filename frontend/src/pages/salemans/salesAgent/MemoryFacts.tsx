import React, { useState } from 'react';
import { Loader2, Trash2 } from 'lucide-react';
import type { MemoryFact } from '../../../api/salesAgentApi';

function savedLabel(fact: MemoryFact, shared: boolean): string {
  const date = fact.saved_at ? new Date(fact.saved_at) : null;
  const when =
    date && !Number.isNaN(date.getTime())
      ? `Saved ${date.toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' })}`
      : 'Saved';
  if (!shared) return when;
  return `${when} ${fact.saved_by_me ? 'by your agent' : 'by a teammate’s agent'}`;
}

/** Facts the sales agent saved, newest first, each with a way to delete it. */
export const MemoryFactList: React.FC<{
  facts: MemoryFact[];
  canForget: boolean;
  onForget: (fact: MemoryFact) => Promise<void>;
  emptyText: string;
  shared?: boolean; // saved by anyone's agent in the workspace
}> = ({ facts, canForget, onForget, emptyText, shared = false }) => {
  const [forgetting, setForgetting] = useState<string | null>(null);

  if (facts.length === 0) {
    return <p className="text-xs text-muted-foreground">{emptyText}</p>;
  }

  const forget = async (fact: MemoryFact) => {
    setForgetting(fact.id);
    try {
      await onForget(fact);
    } finally {
      setForgetting(null);
    }
  };

  return (
    <ul className="space-y-1.5">
      {facts.map((fact) => (
        <li key={fact.id} className="flex items-start gap-2 rounded-lg border border-border/60 bg-background/60 px-3 py-2">
          <div className="min-w-0 flex-1">
            <p className="text-xs text-foreground break-words leading-relaxed">{fact.text}</p>
            <p className="text-[10px] text-muted-foreground mt-0.5">{savedLabel(fact, shared)}</p>
          </div>
          {canForget && (
            <button
              type="button"
              onClick={() => void forget(fact)}
              disabled={forgetting !== null}
              title="Delete this memory"
              aria-label={`Delete this memory: ${fact.text}`}
              className="p-1 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
            >
              {forgetting === fact.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
            </button>
          )}
        </li>
      ))}
    </ul>
  );
};
