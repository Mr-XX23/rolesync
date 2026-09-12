import React, { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { Bot, Brain, MessageSquarePlus, Send, Sparkles } from 'lucide-react';
import { Button } from '../../../components/common/Button';
import { useToast } from '../../../context/ToastContext';
import { useAppSelector } from '../../../store';
import { describeAgentError, salesAgentApi } from '../../../api/salesAgentApi';
import type { AgentEventType, Decision, SessionStatus, SessionSummary } from '../../../api/salesAgentApi';
import { ApprovalCard } from './ApprovalCard';
import type { ApprovalCardModel } from './chatState';
import { chatReducer, emptyChat } from './chatState';
import { MemoryPanel } from './MemoryPanel';
import { Transcript } from './Transcript';
import { useSessionEvents } from './useSessionEvents';

const STATUS_TONE: Record<SessionStatus, string> = {
  RUNNING: 'bg-amber-500/15 border-amber-500/35 text-amber-800 dark:text-amber-300',
  AWAITING_APPROVAL: 'bg-blue-500/15 border-blue-500/35 text-blue-800 dark:text-blue-300',
  DONE: 'bg-emerald-500/15 border-emerald-500/35 text-emerald-800 dark:text-emerald-300',
  FAILED: 'bg-red-500/15 border-red-500/35 text-red-700 dark:text-red-300',
  HALTED: 'bg-muted border-border text-muted-foreground',
};
const STATUS_LABEL: Record<SessionStatus, string> = {
  RUNNING: 'Working',
  AWAITING_APPROVAL: 'Needs approval',
  DONE: 'Done',
  FAILED: 'Failed',
  HALTED: 'Stopped',
};

const STATUS_AFTER_EVENT: Partial<Record<AgentEventType, SessionStatus>> = {
  user_message: 'RUNNING',
  awaiting_approval: 'AWAITING_APPROVAL',
  approval_resolved: 'RUNNING',
  done: 'DONE',
  halted: 'HALTED',
  error: 'FAILED',
};

const SUGGESTIONS = [
  'Prep me for my call with Acme: recent news, our past emails with them, and which of our products fit.',
  'Email jane@acme.com a short thank-you for today’s demo and book a 30-minute follow-up with her next Tuesday at 3pm.',
  'Create a PDF quote for Acme: 10 seats of our Pro plan with 10% off, valid for 30 days.',
  'Put together a one-page Word summary of what our knowledge base says about competing with Globex.',
  'Log a deal for Acme: 50 Pro seats at about $12,000, closing next month. Next step: send pricing to their CFO, Jane.',
];

const StatusPill: React.FC<{ status: SessionStatus }> = ({ status }) => (
  <span className={`text-[9px] font-mono font-bold tracking-widest uppercase border px-2 py-0.5 rounded-full whitespace-nowrap ${STATUS_TONE[status]}`}>
    {STATUS_LABEL[status]}
  </span>
);

export const SalesAgent: React.FC = () => {
  const toast = useToast();
  const [chat, dispatch] = useReducer(chatReducer, emptyChat);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [streamAfter, setStreamAfter] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [deciding, setDeciding] = useState<string | null>(null);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const role = useAppSelector((state) => state.workspace.currentWorkspace?.role);
  const bottomRef = useRef<HTMLDivElement>(null);

  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await salesAgentApi.listSessions());
    } catch {
      // The chat itself reports errors; the history list just stays as it was.
    }
  }, []);

  useEffect(() => {
    let active = true;
    salesAgentApi
      .listSessions()
      .then((rows) => {
        if (active) setSessions(rows);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  useSessionEvents(chat.sessionId, streamAfter, (event) => {
    dispatch({ type: 'event', event });
    // Status changes arrive on the stream before the engine has saved them, so update the
    // history entry from the event instead of re-fetching a moment too early.
    const status = STATUS_AFTER_EVENT[event.type];
    if (status) {
      setSessions((rows) => rows.map((row) => (row.id === event.session_id ? { ...row, status } : row)));
    }
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [chat.items.length, chat.draft, chat.approvals.length]);

  const openSession = async (sessionId: string) => {
    try {
      const detail = await salesAgentApi.getSession(sessionId);
      dispatch({ type: 'snapshot', detail });
      setStreamAfter(detail.last_event_id);
    } catch (error) {
      toast.error(describeAgentError(error));
    }
  };

  const newConversation = () => {
    dispatch({ type: 'reset' });
    setStreamAfter(null);
    setInput('');
  };

  const busy = sending || chat.status === 'RUNNING' || chat.status === 'AWAITING_APPROVAL';

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || busy) {
      return;
    }
    setSending(true);
    dispatch({ type: 'sending', message });
    try {
      const started = await salesAgentApi.startChat(message, chat.sessionId);
      dispatch({ type: 'started', sessionId: started.session_id });
      setInput('');
      void refreshSessions();
    } catch (error) {
      dispatch({ type: 'send_failed' });
      toast.error(describeAgentError(error));
    } finally {
      setSending(false);
    }
  };

  const decide = async (
    card: ApprovalCardModel,
    decision: Decision,
    options?: { args?: Record<string, unknown>; note?: string }
  ) => {
    setDeciding(card.id);
    try {
      const action = await salesAgentApi.decide(card.id, decision, options);
      dispatch({ type: 'approval_decided', action });
    } catch (error) {
      toast.error(describeAgentError(error));
    } finally {
      setDeciding(null);
    }
  };

  const activeTitle = sessions.find((session) => session.id === chat.sessionId)?.title;
  const pending = chat.approvals.filter((card) => card.status === 'PENDING');
  const decided = chat.approvals.filter((card) => card.status !== 'PENDING');

  return (
    <div className="h-full flex flex-col gap-6 pb-4 animate-in fade-in duration-500">
      <section className="flex flex-col md:flex-row md:items-start justify-between gap-4">
        <div className="space-y-2">
          <h2 className="font-serif text-3xl font-bold text-primary">Sales Agent</h2>
          <p className="text-sm text-muted-foreground max-w-2xl leading-relaxed">
            Ask for research, outreach, documents, quotes, deals or catalog updates in plain language. The agent gathers
            what it needs and prepares each action, and nothing changes until you approve it. It remembers what it learns
            about you and your customers, and if a later step fails it asks before undoing what was already done.
          </p>
        </div>
        <Button
          variant="outline"
          className="px-3.5 py-2 text-xs shrink-0"
          onClick={() => setMemoryOpen(true)}
          icon={<Brain className="w-3.5 h-3.5" />}
        >
          What it remembers
        </Button>
      </section>

      <div className="flex-1 min-h-[34rem] grid grid-cols-1 lg:grid-cols-[17rem_1fr] gap-6">
        {/* Conversation history */}
        <aside className="bg-card border border-border rounded-2xl p-3 shadow-2xs flex flex-col min-h-0">
          <Button
            variant="outline"
            className="px-3 py-2 text-xs w-full justify-center mb-3"
            onClick={newConversation}
            icon={<MessageSquarePlus className="w-3.5 h-3.5" />}
          >
            New conversation
          </Button>
          <p className="px-2 pb-2 text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground/70">
            History
          </p>
          <div className="flex-1 overflow-y-auto space-y-1 pr-1">
            {sessions.length === 0 && <p className="px-2 py-3 text-xs text-muted-foreground">No conversations yet.</p>}
            {sessions.map((session) => (
              <button
                key={session.id}
                onClick={() => void openSession(session.id)}
                className={`w-full text-left rounded-xl px-3 py-2.5 border transition-colors cursor-pointer ${
                  session.id === chat.sessionId
                    ? 'bg-muted/70 border-border'
                    : 'border-transparent hover:bg-muted/40'
                }`}
              >
                <p className="text-xs font-semibold text-foreground truncate">{session.title || 'Untitled conversation'}</p>
                <div className="flex items-center justify-between gap-2 mt-1.5">
                  <span className="text-[10px] text-muted-foreground font-mono">
                    {new Date(session.started_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </span>
                  <StatusPill status={session.status} />
                </div>
              </button>
            ))}
          </div>
        </aside>

        {/* Conversation */}
        <section className="bg-card border border-border rounded-2xl shadow-2xs flex flex-col min-h-0 overflow-hidden">
          <header className="flex items-center justify-between gap-3 px-5 py-3.5 border-b border-border/60">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
                <Bot className="w-4 h-4" />
              </div>
              <p className="text-sm font-bold text-foreground truncate">{activeTitle || 'New conversation'}</p>
            </div>
            {chat.status && <StatusPill status={chat.status} />}
          </header>

          <div className="flex-1 overflow-y-auto px-5 py-5 space-y-4 bg-background/40">
            {chat.items.length === 0 && !chat.draft && !chat.outgoing && pending.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center gap-4 py-10">
                <div className="w-12 h-12 rounded-2xl bg-primary/10 text-primary flex items-center justify-center">
                  <Sparkles className="w-6 h-6" />
                </div>
                <div className="space-y-1">
                  <p className="font-serif text-xl font-bold text-foreground">What should we work on?</p>
                  <p className="text-xs text-muted-foreground">
                    Research uses your connected apps, knowledge base, catalog and the web. Emails, meetings, documents and
                    catalog changes happen only after you approve them.
                  </p>
                </div>
                <div className="flex flex-col gap-2 w-full max-w-lg">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      onClick={() => setInput(suggestion)}
                      className="text-left text-xs rounded-xl border border-border/70 bg-card hover:border-primary/40 hover:bg-primary/5 px-4 py-3 text-foreground transition-colors cursor-pointer"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <Transcript
                items={chat.items}
                outgoing={chat.outgoing}
                draft={chat.draft}
                step={chat.step}
                running={chat.status === 'RUNNING'}
              />
            )}

            {decided.map((card) => (
              <ApprovalCard key={card.id} card={card} busy={false} onDecide={decide} />
            ))}
            {pending.map((card) => (
              <ApprovalCard key={card.id} card={card} busy={deciding === card.id} onDecide={decide} />
            ))}

            {chat.error && (
              <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-xs text-red-700 dark:text-red-300">
                {chat.error}
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <form
            className="border-t border-border/60 p-3 flex items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void send(input);
            }}
          >
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  void send(input);
                }
              }}
              rows={2}
              placeholder={
                chat.status === 'AWAITING_APPROVAL'
                  ? 'Review the action above to continue…'
                  : busy
                    ? 'The agent is working…'
                    : 'Ask the sales agent… (Enter to send, Shift+Enter for a new line)'
              }
              disabled={busy}
              className="flex-1 resize-none rounded-xl border border-input bg-background px-4 py-2.5 text-sm text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20 disabled:opacity-60"
            />
            <Button
              type="submit"
              className="px-4 py-2.5 w-auto h-[3.25rem]"
              disabled={busy || !input.trim()}
              isLoading={sending}
              loadingText="Sending"
              icon={<Send className="w-4 h-4" />}
            >
              Send
            </Button>
          </form>
        </section>
      </div>

      {memoryOpen && <MemoryPanel canEditShared={role !== 'VIEWER'} onClose={() => setMemoryOpen(false)} />}
    </div>
  );
};

export default SalesAgent;
