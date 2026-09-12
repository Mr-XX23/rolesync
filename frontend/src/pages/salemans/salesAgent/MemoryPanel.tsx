import React, { useEffect, useState } from 'react';
import { Brain, Building2, ChevronDown, ChevronRight, Loader2, Search, UserRound, X } from 'lucide-react';
import { describeAgentError, salesAgentApi } from '../../../api/salesAgentApi';
import type { MemoryFact, MemoryView, RememberedAccount } from '../../../api/salesAgentApi';
import { useToast } from '../../../context/ToastContext';
import { MemoryFactList } from './MemoryFacts';

type Tab = 'rep' | 'accounts';

const statusOf = (error: unknown): number | undefined => (error as { response?: { status?: number } })?.response?.status;

/** "What the agent remembers": facts it saved on its own, for the rep to review and delete. */
export const MemoryPanel: React.FC<{ canEditShared: boolean; onClose: () => void }> = ({ canEditShared, onClose }) => {
  const toast = useToast();
  const notifyError = toast.error;
  const [tab, setTab] = useState<Tab>('rep');
  const [rep, setRep] = useState<MemoryView | null>(null);
  const [accounts, setAccounts] = useState<RememberedAccount[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [query, setQuery] = useState('');
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [account, setAccount] = useState<MemoryView | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([salesAgentApi.repMemory(), salesAgentApi.listRememberedAccounts()])
      .then(([repMemory, rows]) => {
        if (active) {
          setRep(repMemory);
          setAccounts(rows);
        }
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!openKey) return;
    let active = true;
    salesAgentApi
      .accountMemory(openKey)
      .then((view) => {
        if (active) setAccount(view);
      })
      .catch((error) => {
        if (active) notifyError(describeAgentError(error));
      });
    return () => {
      active = false;
    };
  }, [openKey, notifyError]);

  const apply = (updated: MemoryView) => {
    if (updated.about === 'rep') {
      setRep(updated);
      return;
    }
    setAccount(updated);
    setAccounts((rows) =>
      rows && rows.map((row) => (row.key === updated.key ? { ...row, facts: updated.facts.length } : row)).filter((row) => row.facts > 0)
    );
  };

  const forget = async (view: MemoryView, fact: MemoryFact) => {
    try {
      apply(await salesAgentApi.forgetFact(view, fact.id));
    } catch (error) {
      if (statusOf(error) === 404) {
        apply({ ...view, facts: view.facts.filter((item) => item.id !== fact.id) });
      } else {
        notifyError(describeAgentError(error));
      }
    }
  };

  const needle = query.trim().toLowerCase();
  const shown = (accounts ?? []).filter((row) => !needle || `${row.name} ${row.key}`.toLowerCase().includes(needle));
  const openAccount = account && account.key === openKey ? account : null;

  const tabClass = (active: boolean) =>
    `inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors cursor-pointer ${
      active ? 'bg-muted border-border text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/40'
    }`;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-xs animate-in fade-in duration-200" onClick={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="memory-panel-title"
        className="h-full w-full max-w-md bg-card border-l border-border shadow-2xl flex flex-col"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3 px-5 py-4 border-b border-border/60">
          <div className="flex items-start gap-2.5 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
              <Brain className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <p id="memory-panel-title" className="text-sm font-bold text-foreground">
                What the agent remembers
              </p>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                The agent saves facts it learns while working, so it doesn’t have to ask again. Delete anything that’s wrong or
                out of date.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="px-5 pt-3 flex gap-1.5">
          <button type="button" className={tabClass(tab === 'rep')} onClick={() => setTab('rep')}>
            <UserRound className="w-3.5 h-3.5" /> About you
          </button>
          <button type="button" className={tabClass(tab === 'accounts')} onClick={() => setTab('accounts')}>
            <Building2 className="w-3.5 h-3.5" /> Customers
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          {failed ? (
            <p className="text-xs text-muted-foreground">The agent’s memory couldn’t be loaded right now. Try again shortly.</p>
          ) : rep === null || accounts === null ? (
            <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
          ) : tab === 'rep' ? (
            <>
              <p className="text-[11px] text-muted-foreground">Only you can see these. The agent uses them to work the way you do.</p>
              <MemoryFactList
                facts={rep.facts}
                canForget
                onForget={(fact) => forget(rep, fact)}
                emptyText="Nothing yet. Tell the agent how you like to work, such as “sign my emails as Sam”, and it will remember."
              />
            </>
          ) : (
            <>
              <p className="text-[11px] text-muted-foreground">
                Shared with everyone in your workspace{canEditShared ? '.' : '. Viewers can’t delete them.'}
              </p>
              {accounts.length > 0 && (
                <div className="relative">
                  <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/70" />
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Find a customer"
                    aria-label="Find a customer"
                    className="w-full pl-8 pr-3 py-2 rounded-xl border border-border bg-background text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary/10 focus:border-primary"
                  />
                </div>
              )}
              {accounts.length === 0 && (
                <p className="text-xs text-muted-foreground">Nothing yet. The agent saves what it learns about customers as it works on them.</p>
              )}
              {accounts.length > 0 && shown.length === 0 && <p className="text-xs text-muted-foreground">No customers match.</p>}
              <ul className="space-y-1.5">
                {shown.map((row) => {
                  const expanded = row.key === openKey;
                  return (
                    <li key={row.key} className="rounded-xl border border-border/60">
                      <button
                        type="button"
                        onClick={() => setOpenKey(expanded ? null : row.key)}
                        aria-expanded={expanded}
                        className="w-full flex items-center justify-between gap-2 px-3 py-2.5 text-left cursor-pointer hover:bg-muted/30 rounded-xl"
                      >
                        <span className="text-xs font-semibold text-foreground truncate">{row.name}</span>
                        <span className="flex items-center gap-1.5 text-[10px] text-muted-foreground shrink-0">
                          {row.facts} {row.facts === 1 ? 'fact' : 'facts'}
                          {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                        </span>
                      </button>
                      {expanded && (
                        <div className="px-3 pb-3">
                          {openAccount ? (
                            <MemoryFactList
                              facts={openAccount.facts}
                              shared
                              canForget={canEditShared}
                              onForget={(fact) => forget(openAccount, fact)}
                              emptyText="Nothing left."
                            />
                          ) : (
                            <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                          )}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>
      </aside>
    </div>
  );
};
