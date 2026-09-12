import React from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  CircleHelp,
  CircleSlash,
  ExternalLink,
  Loader2,
  Search,
  Undo2,
  UsersRound,
  Wrench,
} from 'lucide-react';
import type { SourceLink, TranscriptItem } from '../../../api/salesAgentApi';
import { isAppLink, isWebLink } from './links';
import { subagentTitle } from './subagents';

const OUTCOME_TONE: Record<string, string> = {
  EXECUTED: 'text-emerald-700 dark:text-emerald-300 bg-emerald-500/10 border-emerald-500/25',
  REJECTED: 'text-amber-800 dark:text-amber-300 bg-amber-500/10 border-amber-500/25',
  EXPIRED: 'text-muted-foreground bg-muted border-border',
  UNKNOWN: 'text-orange-800 dark:text-orange-300 bg-orange-500/10 border-orange-500/30',
};
const FAILURE_TONE = 'text-red-700 dark:text-red-300 bg-red-500/10 border-red-500/25';

const TOOL_LABEL: Record<string, string> = {
  send_email: 'Send email',
  search_emails: 'Search emails',
  read_email_thread: 'Read email thread',
  list_calendar_events: 'Check calendar',
  search_slack_messages: 'Search Slack',
  search_notion: 'Search Notion',
  read_notion_page: 'Read Notion page',
  search_knowledge_base: 'Search knowledge base',
  read_knowledge_document: 'Read document',
  search_catalog: 'Search catalog',
  check_inventory: 'Check stock',
  web_search: 'Search the web',
  research_prospect: 'Research prospect',
  create_calendar_event: 'Create calendar event',
  send_slack_message: 'Post to Slack',
  create_notion_page: 'Create Notion page',
  generate_document: 'Create document',
  create_quote: 'Create quote',
  create_catalog_item: 'Add catalog item',
  update_catalog_item: 'Update catalog item',
  retire_catalog_item: 'Retire catalog item',
  set_stock: 'Set stock',
  reserve_stock: 'Reserve stock',
  release_stock: 'Release reservation',
  undo_actions: 'Undo actions',
  delegate: 'Hand over',
  search_deals: 'Search deals',
  create_deal: 'Create deal',
  update_deal: 'Update deal',
  remember: 'Remember',
  recall: 'Recall',
  forget: 'Forget',
  read_offloaded_result: 'Look in an earlier result',
};
const WRITE_TOOLS = new Set([
  'send_email',
  'create_calendar_event',
  'send_slack_message',
  'create_notion_page',
  'generate_document',
  'create_quote',
  'create_catalog_item',
  'update_catalog_item',
  'retire_catalog_item',
  'set_stock',
  'reserve_stock',
  'release_stock',
  'create_deal',
  'update_deal',
]);
const MEMORY_TOOLS = new Set(['remember', 'forget']);
/** Handing part of the job to a sub-agent; its own steps stream in under its name. */
const DELEGATE_TOOL = 'delegate';
const WHERE_TO_CHECK: Record<string, string> = {
  send_email: ' (check your Sent folder)',
  create_calendar_event: ' (check your calendar)',
  send_slack_message: ' (check the channel)',
  create_notion_page: ' (check Notion)',
  generate_document: ' (check Google Drive or the knowledge base)',
  create_quote: ' (check Google Drive or the knowledge base)',
  create_deal: ' (check Deals)',
  update_deal: ' (check the deal on the Deals page)',
};

function describeResult(item: TranscriptItem): string | null | undefined {
  if (item.outcome === 'UNKNOWN') {
    // The engine's own message is written for the model; this one is for the rep.
    const where = WHERE_TO_CHECK[item.tool ?? ''] ?? '';
    return `No confirmation came back, so this may have gone through. Check before trying again${where}.`;
  }
  return item.summary || item.error;
}

function outcomeIcon(outcome: string) {
  switch (outcome) {
    case 'EXECUTED':
      return CheckCircle2;
    case 'REJECTED':
    case 'EXPIRED':
      return CircleSlash;
    case 'UNKNOWN':
      return CircleHelp;
    default:
      return AlertTriangle;
  }
}

function describeCall(item: TranscriptItem): string {
  const args = item.args ?? {};
  switch (item.tool) {
    case 'send_email': {
      const to = Array.isArray(args.to) ? args.to.join(', ') : '';
      return `${to}${args.subject ? ` · “${String(args.subject)}”` : ''}`;
    }
    case 'research_prospect':
      return [args.company, args.person].filter(Boolean).map(String).join(' · ');
    case 'check_inventory':
      return Array.isArray(args.skus) ? args.skus.join(', ') : '';
    case 'create_calendar_event':
    case 'create_notion_page':
    case 'generate_document':
      return args.title ? `“${String(args.title)}”` : '';
    case 'send_slack_message':
      return args.channel ? `#${String(args.channel).replace(/^#/, '')}` : '';
    case 'create_quote':
      return args.customer_company ? String(args.customer_company) : '';
    case 'create_catalog_item':
      return args.name ? String(args.name) : '';
    case 'set_stock':
    case 'reserve_stock':
      return [args.sku, args.quantity].filter((part) => part !== undefined).map(String).join(' · ');
    case 'undo_actions':
      return Array.isArray(args.action_ids) ? `${args.action_ids.length} action${args.action_ids.length === 1 ? '' : 's'}` : '';
    case 'delegate': {
      const worker = subagentTitle(typeof args.agent === 'string' ? args.agent : null);
      return [worker, typeof args.task === 'string' ? args.task : ''].filter(Boolean).join(' · ');
    }
    case 'create_deal':
      return [args.title, args.company].filter(Boolean).map(String).join(' · ');
    case 'update_deal':
      return args.stage ? `stage → ${String(args.stage)}` : '';
    case 'remember':
      return args.fact ? `“${String(args.fact)}”` : '';
    case 'recall': {
      const about = args.about === 'rep' ? 'about you' : args.about === 'accounts' ? 'customers' : String(args.company ?? args.about ?? '');
      return [about, args.query ? `“${String(args.query)}”` : ''].filter(Boolean).join(' · ');
    }
    case 'update_catalog_item':
    case 'retire_catalog_item':
    case 'release_stock':
    case 'forget':
    case 'read_offloaded_result':
      return '';
    default:
      if (typeof args.query === 'string') {
        return `“${args.query}”`;
      }
      return Object.keys(args).length ? JSON.stringify(args).slice(0, 140) : '';
  }
}

/** Web links and links inside the app only: sources come from tool results, which include pages found on the internet. */
function safeSources(sources: SourceLink[] | null | undefined): SourceLink[] {
  return (sources ?? []).filter((source) => isWebLink(source.url) || isAppLink(source.url)).slice(0, 5);
}

function hostOf(url: string): string | null {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return null;
  }
}

function sourceLabel(source: SourceLink): string {
  if (isAppLink(source.url)) {
    return `${source.title} · ${source.url.startsWith('/salesman/deals') ? 'deals' : 'knowledge base'}`;
  }
  const host = hostOf(source.url);
  // Google Search grounding links are redirects whose title is already the site's domain.
  if (!host || host.endsWith('vertexaisearch.cloud.google.com') || host === source.title) {
    return source.title;
  }
  return `${source.title} · ${host}`;
}

const linkClass =
  'inline-flex items-center gap-1 max-w-[16rem] text-foreground/70 hover:text-foreground underline-offset-2 hover:underline';

const UserBubble: React.FC<{ text: string; sending?: boolean }> = ({ text, sending = false }) => (
  <div className="flex justify-end">
    <div
      className={`max-w-[80%] rounded-2xl rounded-br-md bg-primary text-primary-foreground px-4 py-2.5 text-sm whitespace-pre-wrap leading-relaxed shadow-2xs ${
        sending ? 'opacity-60' : ''
      }`}
    >
      {text}
    </div>
  </div>
);

export const Transcript: React.FC<{
  items: TranscriptItem[];
  outgoing: string | null;
  draft: string;
  step: string | null;
  running: boolean;
}> = ({ items, outgoing, draft, step, running }) => (
  <div className="space-y-4">
    {items.map((item, index) => {
      switch (item.kind) {
        case 'user':
          return <UserBubble key={index} text={item.text ?? ''} />;
        case 'assistant':
          return (
            <div key={index} className="flex justify-start">
              <div className="max-w-[80%] rounded-2xl rounded-bl-md bg-card border border-border/70 px-4 py-2.5 text-sm text-foreground whitespace-pre-wrap leading-relaxed shadow-2xs">
                {item.text}
              </div>
            </div>
          );
        case 'tool_call': {
          const tool = item.tool ?? '';
          const CallIcon =
            tool === 'undo_actions'
              ? Undo2
              : tool === DELEGATE_TOOL
                ? UsersRound
                : MEMORY_TOOLS.has(tool)
                  ? Brain
                  : WRITE_TOOLS.has(tool)
                    ? Wrench
                    : Search;
          return (
            <div key={index} className="flex items-center gap-2 text-xs text-muted-foreground pl-1">
              <CallIcon className="w-3.5 h-3.5 shrink-0" />
              <span className="font-semibold text-foreground/80 shrink-0">{TOOL_LABEL[item.tool ?? ''] ?? item.tool}</span>
              <span className="truncate">{describeCall(item)}</span>
            </div>
          );
        }
        case 'tool_result': {
          const outcome = item.outcome ?? 'FAILED';
          const tone = OUTCOME_TONE[outcome] ?? FAILURE_TONE;
          const Icon = outcomeIcon(outcome);
          const sources = safeSources(item.sources);
          return (
            <div key={index} className={`text-xs rounded-xl border px-3 py-2 ${tone}`}>
              <div className="flex items-start gap-2">
                <Icon className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <span className="font-mono font-bold uppercase tracking-wider text-[10px] pt-0.5 shrink-0">
                  {outcome === 'UNKNOWN' ? 'Unconfirmed' : outcome}
                </span>
                <span className="min-w-0 break-words">{describeResult(item)}</span>
              </div>
              {sources.length > 0 && (
                <ul className="mt-1.5 ml-[1.375rem] flex flex-wrap gap-x-3 gap-y-1">
                  {sources.map((source) => (
                    <li key={source.url} className="min-w-0 max-w-full">
                      {isAppLink(source.url) ? (
                        <Link to={source.url} title={source.title} className={linkClass}>
                          <ExternalLink className="w-3 h-3 shrink-0" />
                          <span className="truncate">{sourceLabel(source)}</span>
                        </Link>
                      ) : (
                        <a href={source.url} target="_blank" rel="noopener noreferrer" title={source.title} className={linkClass}>
                          <ExternalLink className="w-3 h-3 shrink-0" />
                          <span className="truncate">{sourceLabel(source)}</span>
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        }
        default:
          return null;
      }
    })}

    {outgoing && <UserBubble text={outgoing} sending />}

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
