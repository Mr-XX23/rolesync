import React, { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Bot, CalendarClock, FileText, Handshake, Loader2, Plus, RefreshCw, Search, UserRound, Users } from 'lucide-react';
import { Button } from '../../../components/common/Button';
import { useToast } from '../../../context/ToastContext';
import { useAppSelector } from '../../../store';
import { DEAL_STAGES, dealsApi, describeDealError } from '../../../api/dealsApi';
import type { Deal } from '../../../api/dealsApi';
import { DealModal } from './DealModal';
import { CLOSED_STAGES, STAGE_META, formatDay, formatMoney, matchesDeal, totalByCurrency } from './dealFormat';

const LIMIT = 500;

interface Loaded {
  key: string;
  workspaceId: string | undefined;
  deals: Deal[];
  error: string | null;
}

const Stat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="bg-card border border-border/70 rounded-xl px-4 py-3 shadow-2xs min-w-0">
    <p className="text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground">{label}</p>
    <p className="text-lg font-bold text-foreground tabular-nums truncate">{value}</p>
  </div>
);

const DealCard: React.FC<{ deal: Deal; onOpen: () => void }> = ({ deal, onOpen }) => {
  const contacts = deal.contacts ?? [];
  const quotes = deal.quotes ?? [];
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full text-left bg-card border border-border/70 rounded-xl p-3 shadow-2xs hover:border-primary/40 hover:shadow-xs transition-all cursor-pointer space-y-2"
    >
      <div className="space-y-0.5">
        <p className="text-xs font-bold text-foreground line-clamp-2">{deal.title}</p>
        <p className="text-[11px] text-muted-foreground truncate">{deal.company}</p>
      </div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-bold text-foreground tabular-nums truncate">{formatMoney(deal.amount, deal.currency) || '—'}</span>
        {deal.expected_close_date && (
          <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground font-mono shrink-0" title="Expected close">
            <CalendarClock className="w-3 h-3" />
            {formatDay(deal.expected_close_date)}
          </span>
        )}
      </div>
      {deal.next_step && <p className="text-[11px] text-foreground/80 line-clamp-2">Next: {deal.next_step}</p>}
      <div className="flex items-center justify-between gap-2 pt-1.5 border-t border-border/50">
        <span className="text-[10px] text-muted-foreground truncate">{deal.owner_name || 'No owner'}</span>
        <span className="flex items-center gap-2 text-[10px] text-muted-foreground shrink-0">
          {contacts.length > 0 && (
            <span className="inline-flex items-center gap-0.5" title="Contacts">
              <Users className="w-3 h-3" />
              {contacts.length}
            </span>
          )}
          {quotes.length > 0 && (
            <span className="inline-flex items-center gap-0.5" title="Quotes">
              <FileText className="w-3 h-3" />
              {quotes.length}
            </span>
          )}
          {deal.source === 'AGENT' && (
            <span className="inline-flex items-center gap-0.5 text-primary" title="Created by the sales agent">
              <Bot className="w-3 h-3" />
              Agent
            </span>
          )}
        </span>
      </div>
    </button>
  );
};

export const Deals: React.FC = () => {
  const toast = useToast();
  const notifyError = toast.error;
  const workspaceId = useAppSelector((state) => state.workspace.currentWorkspace?.workspaceId);
  const role = useAppSelector((state) => state.workspace.currentWorkspace?.role);
  const canEdit = role !== 'VIEWER';
  const [mine, setMine] = useState(false);
  const [query, setQuery] = useState('');
  const [refreshes, setRefreshes] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [linked, setLinked] = useState<Deal | null>(null); // a deal opened by link that isn't in the list
  const [searchParams, setSearchParams] = useSearchParams();

  const requestKey = `${workspaceId}:${mine}:${refreshes}`;
  useEffect(() => {
    let active = true;
    dealsApi
      .list({ mine, limit: LIMIT })
      .then((deals) => {
        if (active) setLoaded({ key: requestKey, workspaceId, deals, error: null });
      })
      .catch((error) => {
        if (active) setLoaded({ key: requestKey, workspaceId, deals: [], error: describeDealError(error) });
      });
    return () => {
      active = false;
    };
  }, [requestKey, mine, workspaceId]);

  const loading = loaded?.key !== requestKey;
  const current = loaded && loaded.workspaceId === workspaceId ? loaded : null;
  const deals = useMemo(() => current?.deals ?? [], [current]);
  const visible = useMemo(() => deals.filter((deal) => matchesDeal(deal, query)), [deals, query]);

  // The open deal lives in the URL (?deal=<id>), so the agent's links and the back button work.
  const selectedId = searchParams.get('deal');
  const listed = selectedId ? deals.find((deal) => deal.deal_id === selectedId) : undefined;
  const selected: Deal | 'new' | null =
    selectedId === 'new' ? (canEdit ? 'new' : null) : (listed ?? (linked && linked.deal_id === selectedId ? linked : null));
  const fetchLinked = Boolean(selectedId && selectedId !== 'new' && !listed && linked?.deal_id !== selectedId && current && !loading);

  useEffect(() => {
    if (!fetchLinked || !selectedId) return;
    let active = true;
    dealsApi
      .get(selectedId)
      .then((deal) => {
        if (active) setLinked(deal);
      })
      .catch((error) => {
        if (!active) return;
        notifyError(describeDealError(error));
        setSearchParams(
          (params) => {
            const next = new URLSearchParams(params);
            next.delete('deal');
            return next;
          },
          { replace: true }
        );
      });
    return () => {
      active = false;
    };
  }, [fetchLinked, selectedId, notifyError, setSearchParams]);

  const openDeal = (dealId: string) => setSearchParams({ deal: dealId });
  const closeDeal = () =>
    setSearchParams((params) => {
      const next = new URLSearchParams(params);
      next.delete('deal');
      return next;
    });

  const keepSaved = (saved: Deal) => {
    setLoaded((state) => state && { ...state, deals: [saved, ...state.deals.filter((deal) => deal.deal_id !== saved.deal_id)] });
    setLinked((deal) => (deal && deal.deal_id === saved.deal_id ? saved : deal));
    closeDeal();
  };
  const dropDeleted = (dealId: string) => {
    setLoaded((state) => state && { ...state, deals: state.deals.filter((deal) => deal.deal_id !== dealId) });
    setLinked((deal) => (deal && deal.deal_id === dealId ? null : deal));
    closeDeal();
  };

  const open = visible.filter((deal) => !CLOSED_STAGES.has(deal.stage));
  const won = visible.filter((deal) => deal.stage === 'WON');

  return (
    <div className="h-full flex flex-col gap-6 pb-4 animate-in fade-in duration-500">
      <section className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div className="space-y-2">
          <h2 className="font-serif text-3xl font-bold text-primary">Deals</h2>
          <p className="text-sm text-muted-foreground max-w-2xl leading-relaxed">
            Your workspace’s sales pipeline, shared with everyone in the workspace. The sales agent can create and update deals
            too, and nothing changes until you approve it. Quotes it creates for a deal are listed on the deal.
          </p>
        </div>
        {canEdit && (
          <Button className="px-4 py-2.5 w-auto text-xs" onClick={() => openDeal('new')} icon={<Plus className="w-4 h-4" />}>
            New deal
          </Button>
        )}
      </section>

      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
        <div className="flex items-center gap-2 flex-1 max-w-xl">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/70" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search deals, companies, contacts…"
              aria-label="Search deals"
              className="w-full pl-9 pr-3 py-2 rounded-xl border border-border bg-background text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-primary/10 focus:border-primary"
            />
          </div>
          <button
            type="button"
            aria-pressed={mine}
            onClick={() => setMine((value) => !value)}
            className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border text-xs font-semibold transition-colors cursor-pointer whitespace-nowrap ${
              mine ? 'bg-primary/10 border-primary/40 text-primary' : 'border-border text-muted-foreground hover:text-foreground hover:bg-muted/50'
            }`}
          >
            <UserRound className="w-3.5 h-3.5" /> My deals
          </button>
          <button
            type="button"
            onClick={() => setRefreshes((count) => count + 1)}
            disabled={loading}
            title="Refresh"
            aria-label="Refresh deals"
            className="p-2 rounded-xl border border-border text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer disabled:cursor-default"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
        <div className="grid grid-cols-3 gap-3 lg:w-[30rem]">
          <Stat label="Open deals" value={String(open.length)} />
          <Stat label="Open pipeline" value={totalByCurrency(open) || '—'} />
          <Stat label="Won" value={totalByCurrency(won) || '—'} />
        </div>
      </div>

      {!current ? (
        <div className="flex-1 flex items-center justify-center py-16 text-muted-foreground">
          <Loader2 className="w-5 h-5 animate-spin" />
        </div>
      ) : current.error ? (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-5 py-4 text-sm text-red-700 dark:text-red-300 flex items-center justify-between gap-3">
          <span>{current.error}</span>
          <Button variant="outline" className="px-3 py-1.5 text-xs" onClick={() => setRefreshes((count) => count + 1)}>
            Try again
          </Button>
        </div>
      ) : deals.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-center gap-3 py-16 bg-card border border-border/70 rounded-2xl">
          <div className="w-12 h-12 rounded-2xl bg-primary/10 text-primary flex items-center justify-center">
            <Handshake className="w-6 h-6" />
          </div>
          <p className="font-serif text-xl font-bold text-foreground">{mine ? 'You don’t own any deals yet' : 'No deals yet'}</p>
          <p className="text-xs text-muted-foreground max-w-md">
            Add one yourself, or tell the sales agent about a new opportunity after a call and it will log the deal for your
            approval.
          </p>
          {canEdit && (
            <Button className="px-4 py-2 w-auto text-xs mt-1" onClick={() => openDeal('new')} icon={<Plus className="w-4 h-4" />}>
              New deal
            </Button>
          )}
        </div>
      ) : (
        <>
          {query.trim() && visible.length === 0 && (
            <p className="text-xs text-muted-foreground">No deals match “{query.trim()}”.</p>
          )}
          <div className="overflow-x-auto pb-2 -mx-1 px-1">
            <div className="grid grid-flow-col auto-cols-[minmax(15rem,1fr)] gap-3">
              {DEAL_STAGES.map((stage) => {
                const column = visible.filter((deal) => deal.stage === stage);
                return (
                  <section key={stage} className="bg-muted/30 border border-border/60 rounded-2xl p-2.5 flex flex-col min-h-[22rem]">
                    <header className="flex items-center justify-between gap-2 px-1 pb-2.5">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className={`w-2 h-2 rounded-full shrink-0 ${STAGE_META[stage].dot}`} />
                        <h3 className="text-xs font-bold text-foreground">{STAGE_META[stage].label}</h3>
                        <span className="text-[10px] font-mono text-muted-foreground">{column.length}</span>
                      </div>
                      <span className="text-[10px] font-mono text-muted-foreground truncate">{totalByCurrency(column)}</span>
                    </header>
                    <div className="space-y-2 flex-1">
                      {column.map((deal) => (
                        <DealCard key={deal.deal_id} deal={deal} onOpen={() => openDeal(deal.deal_id)} />
                      ))}
                      {column.length === 0 && <p className="text-[11px] text-muted-foreground/70 px-1">No deals</p>}
                    </div>
                  </section>
                );
              })}
            </div>
          </div>
          {deals.length >= LIMIT && (
            <p className="text-[11px] text-muted-foreground">Showing the {LIMIT} most recently updated deals.</p>
          )}
        </>
      )}

      {selected && (
        <DealModal
          key={selected === 'new' ? 'new' : selected.deal_id}
          deal={selected === 'new' ? null : selected}
          canEdit={canEdit}
          onClose={closeDeal}
          onSaved={keepSaved}
          onDeleted={dropDeleted}
        />
      )}
    </div>
  );
};

export default Deals;
