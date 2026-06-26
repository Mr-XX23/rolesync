import React, { useState } from 'react';
import { 
  Send, Terminal, Cpu, Database, CheckCircle2, ShieldCheck, 
  ArrowLeft, Plus, ChevronRight 
} from 'lucide-react';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';
import { useAppDispatch } from '../../store';
import { setModalOpen } from '../../store/taskSlice';

interface Agent {
  id: string;
  name: string;
  description: string;
  lastRun: string;
  successRate: string;
  usage: string;
  scenariosCount: number;
  badge?: {
    text: string;
    type: 'danger' | 'warning' | 'success';
  };
  connectedApps: { name: string; logoUrl: string }[];
  terminalLogs: string[];
  metrics: {
    vectorIndexSize: string;
    ragAlignment: string;
    guardrailCluster: string;
    activeName: string;
  };
  initialChat: { query: string; answer: string; chunks: string }[];
  calibrationShards: { name: string; chunks: string }[];
}

const AGENTS_DATA: Agent[] = [
  {
    id: 'sales-intel',
    name: 'Sales Intelligence',
    description: 'Drafts weekly digests from CRM and comms data.',
    lastRun: '19m ago',
    successRate: '99%',
    usage: '22%',
    scenariosCount: 6,
    badge: { text: '3 to Review', type: 'danger' },
    connectedApps: [
      {
        name: 'Salesforce',
        logoUrl: 'https://lh3.googleusercontent.com/aida-public/AB6AXuDuoLUtTBK5mypne1nrv3fj6QsbZ1lF_ccFiLQBmCnr7onOc537LZD8aWdMqitHhgKiJYc6WJtPxUgFaWLm19vHjbSDLtkqwgdDE6m2K1sCCSSCmOX_DeLb-6n9EYL0xVLEofzAuizfeA-jLjJQ6jGgeza9zNNYS8ZfW5fZxXeo57RElCmjCqfPPmXn72teeKDFGrHcfJvJIkJ5ZousPkb2ipZga0xZjG0FbC7WXTAA8XhVyz7Ydd-6nEQdAr1SbWn0n8NN3RSzo7Zf'
      },
      {
        name: 'Slack',
        logoUrl: 'https://lh3.googleusercontent.com/aida-public/AB6AXuBKIaGN6P_2RUxSPKnyBECYiBo63t8bi7Xthz1XiTbMtjSEzQVA5ymuAKmTbeO_zVAkBPZyQKiFzhw3A2bnL71y8XDpYknEoqlEoU6kOxeoMbw5Fm3z4xr2-jU9oHNcQLmpZNvuNJGkomaV5V8g1QBM17p1f7OI6HG5xRjxvf-svEqipupPhC5Kr-Bs959cuSMTITCq_alg2ux3K5Zu_eWW5xzJ2JfuHxxML2gLb4Z7PGBnjtdpfkqWc0XH7L136NyFYPsOUVKKrnt0'
      }
    ],
    terminalLogs: [
      '# Initiating Reasoning Loop...',
      '> Analyzing CRM context vectors (5.4k)',
      '> Syncing accounts to Slack webhook'
    ],
    metrics: {
      vectorIndexSize: '1,850 Vector Shards',
      ragAlignment: '99.1% Similarity Score',
      guardrailCluster: 'Salesforce Sync Active',
      activeName: 'Sales Intelligence v1.0'
    },
    initialChat: [
      {
        query: 'What is the CRM sales pipeline summary for active Enterprise accounts?',
        answer: 'Retrieved CRM accounts matching criteria. Synthesis of active accounts complete: 4 accounts require contact update, 2 pipeline leads escalated to stage 4.',
        chunks: 'Doc: CRM_Pipeline_Export.xlsx (Chunks #12, #14)',
      }
    ],
    calibrationShards: [
      { name: 'CRM_Pipeline_Export.xlsx', chunks: 'Chunks #1 - #120' },
      { name: 'Salesforce_Integration_Manifest.json', chunks: 'Chunks #121 - #200' }
    ]
  },
  {
    id: 'dev-standup',
    name: 'Dev Standup',
    description: 'Compiles async standup from Jira + GitHub, posts to Slack.',
    lastRun: '6h ago',
    successRate: '100%',
    usage: '8%',
    scenariosCount: 1,
    connectedApps: [
      {
        name: 'Jira',
        logoUrl: 'https://lh3.googleusercontent.com/aida-public/AB6AXuCDv4OC71o4lcJatt7XyY4jhSnkoDsRnX71A9fLFLZotzfrcDBZu2JtVRonlX4kzSj4ZuZhbM4_tAaZu4LJ8-T4b13guspkmgcG1tTmeGOnqAofE3O3Y1Pnuj1j3yyUMSxGghk6dmuGBCStYt3A6oId_W3UfPJV6Gd1ru8Vg5xp7dT1LgPtVylVKuEvXqG5cdYq4qIJTE2myU4EEUYwLLGShtVHXD6pdu6eyfkCa1qhO6CgME9GlaO4TxeT7pV9bDDengWqI9x-Hriu'
      }
    ],
    terminalLogs: [
      '# Initiating Reasoning Loop...',
      '> Fetching Jira backlog updates',
      '> Compiling Github pull requests'
    ],
    metrics: {
      vectorIndexSize: '950 Vector Shards',
      ragAlignment: '97.4% Similarity Score',
      guardrailCluster: 'GitHub Webhook Checked',
      activeName: 'Dev Standup Bot v2.1'
    },
    initialChat: [
      {
        query: "Draft today's async standup notes based on recent commits.",
        answer: 'Fetched 5 active commits and 2 merged PRs. Daily Standup Draft: 1. Completed signup page autofill styling fix. 2. Currently integrating the agent workspace grid layout. 3. No blockers.',
        chunks: 'Source: github_commits_feed.json (Chunks #32, #33)',
      }
    ],
    calibrationShards: [
      { name: 'standup_template.md', chunks: 'Chunks #1 - #10' },
      { name: 'github_commits_feed.json', chunks: 'Chunks #11 - #95' }
    ]
  },
  {
    id: 'content-pipeline',
    name: 'Content Pipeline',
    description: 'Tracks Notion briefs, syncs Asana tasks, emails status.',
    lastRun: '2h ago',
    successRate: '98%',
    usage: '14%',
    scenariosCount: 4,
    connectedApps: [
      {
        name: 'Notion',
        logoUrl: 'https://lh3.googleusercontent.com/aida-public/AB6AXuCygN85_JOUqwiRfOO-JI8tC2l8wWZL2Su5WsyLvQk1FCx8zja39vK1AYNkQf9X9lCFc9je7mENqGpb0UNt__0Wzmd0uUBEm8VCK1ykNC81KA0ZWrNWWCfUsyReippElbUAZa48rf1it0dkq3fx4kt3wBd_dUdDcQpFzNOjGDbYWNmB4qB7LMjRo24pokHlpVuw0rXRMXkFbyKBR4QDJUCSjWBlYXdJbb2fyXOUo1dRQnPVQEWEMaTgnuU6X1Ei9R9h60xLJ-XLY_sK'
      }
    ],
    terminalLogs: [
      '# Initiating Reasoning Loop...',
      '> Loading Notion briefs cache',
      '> Updating Asana task statuses'
    ],
    metrics: {
      vectorIndexSize: '1,420 Vector Shards',
      ragAlignment: '95.8% Similarity Score',
      guardrailCluster: 'Notion API V2 Verified',
      activeName: 'Content Pipeline Engine v0.8'
    },
    initialChat: [
      {
        query: 'Synchronize the current Notion content brief statuses with Asana tasks.',
        answer: 'Checked 12 Notion briefs. 3 briefs updated to "In Review". Synchronizing Asana cards: Updated task IDs #201, #204, and #212 to matched statuses.',
        chunks: 'Source: content_briefs_sync.db (Chunks #41, #45)',
      }
    ],
    calibrationShards: [
      { name: 'content_briefs_sync.db', chunks: 'Chunks #1 - #88' },
      { name: 'asana_tasks_overview.csv', chunks: 'Chunks #89 - #142' }
    ]
  },
  {
    id: 'vanguard',
    name: 'Vanguard Salesman',
    description: 'Interact with calibrated model templates, review retrieved context embeddings, and verify semantic search alignments.',
    lastRun: '2m ago',
    successRate: '98.6%',
    usage: '45%',
    scenariosCount: 12,
    connectedApps: [
      {
        name: 'Salesforce',
        logoUrl: 'https://lh3.googleusercontent.com/aida-public/AB6AXuDuoLUtTBK5mypne1nrv3fj6QsbZ1lF_ccFiLQBmCnr7onOc537LZD8aWdMqitHhgKiJYc6WJtPxUgFaWLm19vHjbSDLtkqwgdDE6m2K1sCCSSCmOX_DeLb-6n9EYL0xVLEofzAuizfeA-jLjJQ6jGgeza9zNNYS8ZfW5fZxXeo57RElCmjCqfPPmXn72teeKDFGrHcfJvJIkJ5ZousPkb2ipZga0xZjG0FbC7WXTAA8XhVyz7Ydd-6nEQdAr1SbWn0n8NN3RSzo7Zf'
      },
      {
        name: 'Slack',
        logoUrl: 'https://lh3.googleusercontent.com/aida-public/AB6AXuBKIaGN6P_2RUxSPKnyBECYiBo63t8bi7Xthz1XiTbMtjSEzQVA5ymuAKmTbeO_zVAkBPZyQKiFzhw3A2bnL71y8XDpYknEoqlEoU6kOxeoMbw5Fm3z4xr2-jU9oHNcQLmpZNvuNJGkomaV5V8g1QBM17p1f7OI6HG5xRjxvf-svEqipupPhC5Kr-Bs959cuSMTITCq_alg2ux3K5Zu_eWW5xzJ2JfuHxxML2gLb4Z7PGBnjtdpfkqWc0XH7L136NyFYPsOUVKKrnt0'
      }
    ],
    terminalLogs: [
      '# Initiating Reasoning Loop...',
      '> Analyzing context vectors (8.2k)',
      '> Validating embedding bounds'
    ],
    metrics: {
      vectorIndexSize: '2,100 Vector Shards',
      ragAlignment: '98.6% Similarity Score',
      guardrailCluster: 'OAuth2 Active',
      activeName: 'Vanguard Salesman v4.2'
    },
    initialChat: [
      {
        query: 'What is the current tier pricing structure for Enterprise sync?',
        answer: 'Our Enterprise sync model comprises three main tiers: Standard ($45/operator/mo), Advanced ($95/operator/mo), and Custom Mesh (requires dedicated sales contact). The Advanced tier includes a private pgvector cluster and high-throughput BGE-M3 embedding allocations.',
        chunks: 'Doc: Q4_Pricing_Guide_Final.pdf (Chunks #14, #15)',
      }
    ],
    calibrationShards: [
      { name: 'Q4_Pricing_Guide_Final.pdf', chunks: 'Chunks #1 - #85' },
      { name: 'CRM_Export_NorthAmerica.csv', chunks: 'Chunks #86 - #142' }
    ]
  }
];

export const Workspace: React.FC = () => {
  const dispatch = useAppDispatch();
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState('');
  const [isQuerying, setIsQuerying] = useState(false);

  const [activeStatus, setActiveStatus] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    AGENTS_DATA.forEach(agent => {
      initial[agent.id] = true;
    });
    return initial;
  });

  const [chatLogsByAgent, setChatLogsByAgent] = useState<Record<string, { query: string; answer: string; chunks: string }[]>>(() => {
    const initial: Record<string, { query: string; answer: string; chunks: string }[]> = {};
    AGENTS_DATA.forEach(agent => {
      initial[agent.id] = agent.initialChat;
    });
    return initial;
  });

  const selectedAgent = AGENTS_DATA.find(a => a.id === selectedAgentId);
  const currentChatLog = selectedAgentId ? chatLogsByAgent[selectedAgentId] || [] : [];

  const handleQuery = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || !selectedAgentId) return;

    setIsQuerying(true);
    const userQuery = prompt;
    setPrompt('');

    setTimeout(() => {
      let answer = 'Vector mesh successfully retrieved 3 matching contexts from pgvector store. RAG Synthesis complete: System is operating at peak token capacity.';
      let chunks = 'Source: Custom_Mesh_Segments.db (Chunk #42)';

      if (selectedAgentId === 'sales-intel') {
        answer = 'Retrieved Salesforce accounts and customer communication digests. RAG Synthesis: Client Acme Corp sentiment remains positive. Weekly summary compiled successfully.';
        chunks = 'Source: Salesforce_Integration_Manifest.json (Chunk #112)';
      } else if (selectedAgentId === 'dev-standup') {
        answer = 'Scanned Jira issues and active git branch logs. Standing notes: Completed main tasks. Verified test coverages at 96.4%. Slack standup message queued.';
        chunks = 'Source: standup_template.md (Chunk #8)';
      } else if (selectedAgentId === 'content-pipeline') {
        answer = 'Synchronized active Notion brief statuses with Asana tasks. 2 items moved to Completed, 1 item flagged for priority scheduling.';
        chunks = 'Source: content_briefs_sync.db (Chunk #59)';
      } else if (selectedAgentId === 'vanguard') {
        answer = 'Vector mesh successfully retrieved 3 matching contexts from pgvector store. RAG Synthesis complete: System is operating at peak token capacity, generating model solutions according to the enterprise sales pipeline handbook.';
        chunks = 'Doc: CRM_Export_NorthAmerica.csv (Chunk #342), Q4_Pricing_Guide_Final.pdf (Chunk #88)';
      }

      setChatLogsByAgent((prev) => ({
        ...prev,
        [selectedAgentId]: [
          {
            query: userQuery,
            answer,
            chunks,
          },
          ...prev[selectedAgentId],
        ],
      }));
      setIsQuerying(false);
    }, 1500);
  };

  if (selectedAgentId && selectedAgent) {
    return (
      <div className="space-y-8 animate-in fade-in duration-500 pb-16">
        <section className="space-y-4">
          <button
            onClick={() => setSelectedAgentId(null)}
            className="flex items-center gap-2 text-xs font-semibold text-muted-foreground hover:text-primary transition-colors cursor-pointer group"
          >
            <ArrowLeft className="w-4 h-4 group-hover:-translate-x-0.5 transition-transform" />
            <span>Back to Deployed Agents</span>
          </button>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border/40 pb-4">
            <div>
              <h2 className="font-serif text-3xl font-bold text-primary tracking-tight">
                {selectedAgent.name} Workspace
              </h2>
              <p className="text-sm text-muted-foreground max-w-xl leading-relaxed mt-1">
                {selectedAgent.description}
              </p>
            </div>
            
            <div className="flex items-center gap-2">
              <span className={`text-[10px] font-mono font-bold tracking-widest uppercase border px-2.5 py-1 rounded-full ${
                activeStatus[selectedAgent.id]
                  ? 'bg-primary/10 border-primary/20 text-primary'
                  : 'bg-muted border-border/80 text-muted-foreground'
              }`}>
                {activeStatus[selectedAgent.id] ? 'Active' : 'Inactive'}
              </span>
            </div>
          </div>
        </section>

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          <div className="bg-card border border-border p-4 rounded-xl shadow-2xs">
            <p className="text-[10px] font-mono text-muted-foreground uppercase font-bold tracking-wider">active agent</p>
            <h4 className="text-sm font-bold text-foreground mt-1 flex items-center gap-1.5">
              <Cpu className="w-4 h-4 text-primary animate-pulse" />
              <span>{selectedAgent.metrics.activeName}</span>
            </h4>
          </div>

          <div className="bg-card border border-border p-4 rounded-xl shadow-2xs">
            <p className="text-[10px] font-mono text-muted-foreground uppercase font-bold tracking-wider">vector index size</p>
            <h4 className="text-sm font-bold text-foreground mt-1 flex items-center gap-1.5">
              <Database className="w-4 h-4 text-primary" />
              <span>{selectedAgent.metrics.vectorIndexSize}</span>
            </h4>
          </div>

          <div className="bg-card border border-border p-4 rounded-xl shadow-2xs">
            <p className="text-[10px] font-mono text-muted-foreground uppercase font-bold tracking-wider">RAG alignment</p>
            <h4 className="text-sm font-bold text-foreground mt-1 flex items-center gap-1.5">
              <CheckCircle2 className="w-4 h-4 text-emerald-500" />
              <span>{selectedAgent.metrics.ragAlignment}</span>
            </h4>
          </div>

          <div className="bg-card border border-border p-4 rounded-xl shadow-2xs">
            <p className="text-[10px] font-mono text-muted-foreground uppercase font-bold tracking-wider">guardrail cluster</p>
            <h4 className="text-sm font-bold text-foreground mt-1 flex items-center gap-1.5">
              <ShieldCheck className="w-4 h-4 text-emerald-500" />
              <span>{selectedAgent.metrics.guardrailCluster}</span>
            </h4>
          </div>
        </div>

        <div className="grid grid-cols-12 gap-6 items-stretch">
          <div className="col-span-12 lg:col-span-7 flex flex-col">
            <div className="bg-card border border-border rounded-2xl p-6 shadow-2xs flex-1 flex flex-col justify-between space-y-6">
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Terminal className="w-5 h-5 text-primary" />
                  <h3 className="font-serif text-lg font-bold text-foreground">Semantic Query Console</h3>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  Test the retrieval augmented generation system. Input a question, and the model will execute vector cosine similarity matching on your Knowledge Vault.
                </p>
              </div>

              <div className="flex-1 min-h-[250px] max-h-[350px] overflow-y-auto border border-border/60 bg-muted/20 rounded-2xl p-4 space-y-4">
                {currentChatLog.map((log, index) => (
                  <div key={index} className="space-y-2 animate-in fade-in duration-300">
                    <div className="flex items-start gap-2 bg-background border border-border/40 rounded-xl p-3 shadow-2xs">
                      <span className="font-mono text-[9px] font-bold bg-primary/10 text-primary px-2 py-0.5 rounded-md uppercase tracking-wider shrink-0 mt-0.5">user</span>
                      <p className="text-xs font-semibold text-foreground leading-relaxed">{log.query}</p>
                    </div>

                    <div className="bg-primary/5 dark:bg-primary/2 border border-primary/10 rounded-xl p-3 pl-4 relative">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="font-mono text-[9px] font-bold bg-primary/20 text-primary px-2 py-0.5 rounded-md uppercase tracking-wider">retrieved agent</span>
                        <span className="font-mono text-[8px] text-muted-foreground/80 font-semibold">{log.chunks}</span>
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">{log.answer}</p>
                    </div>
                  </div>
                ))}
                {isQuerying && (
                  <div className="flex items-center justify-center py-6 gap-2 text-xs font-medium text-muted-foreground animate-pulse">
                    <Cpu className="w-4 h-4 animate-spin text-primary" />
                    <span>Quarrying vector mesh segments...</span>
                  </div>
                )}
              </div>

              <form onSubmit={handleQuery} className="w-full">
                <Input
                  id="workspace-sales-prompt"
                  label=""
                  type="text"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  disabled={isQuerying}
                  placeholder={`Ask ${selectedAgent.name} a query...`}
                  className="pr-12 text-xs py-3"
                  rightElementInside={
                    <button
                      type="submit"
                      disabled={isQuerying || !prompt.trim()}
                      className="bg-primary text-primary-foreground p-2 rounded-lg hover:opacity-95 active:scale-95 transition-all disabled:opacity-30 cursor-pointer"
                    >
                      <Send className="w-3.5 h-3.5" />
                    </button>
                  }
                />
              </form>
            </div>
          </div>

          <div className="col-span-12 lg:col-span-5">
            <div className="bg-card border border-border p-6 rounded-2xl shadow-2xs h-full flex flex-col justify-between space-y-6">
              <div className="space-y-4">
                <h3 className="font-serif text-lg font-bold text-foreground">Index Calibration Shards</h3>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  Review the primary source vector profiles containing pricing structures, terms of service, and pipeline specifications.
                </p>

                <div className="space-y-3">
                  {selectedAgent.calibrationShards.map((shard, idx) => (
                    <div key={idx} className="bg-muted/40 border border-border/40 rounded-xl p-4 flex justify-between items-center gap-3">
                      <div>
                        <h5 className="text-xs font-bold text-foreground">{shard.name}</h5>
                        <p className="text-[10px] text-muted-foreground font-mono mt-1">Segments: {shard.chunks}</p>
                      </div>
                      <span className="font-mono text-[9px] font-bold bg-primary/10 text-primary border border-primary/20 px-2 py-0.5 rounded uppercase tracking-wider">
                        active
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="pt-6 border-t border-border/60">
                <Button
                  variant="outline"
                  onClick={() => alert(`Calibrating vector indexes for ${selectedAgent.name}...`)}
                  className="w-full py-2.5 text-xs font-semibold rounded-xl"
                >
                  Re-index Entire Shard Mesh
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-in fade-in duration-500 pb-16">
      <section className="space-y-2">
        <h2 className="font-serif text-3xl font-bold text-primary tracking-tight">Agent Workspace</h2>
        <p className="text-sm text-muted-foreground max-w-xl leading-relaxed">
          Monitor your deployed agent mesh cluster. Click an agent card below to enter their console and execute query synthesis loops.
        </p>
      </section>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {AGENTS_DATA.map((agent) => (
          <article 
            key={agent.id}
            onClick={() => setSelectedAgentId(agent.id)}
            className="group cursor-pointer bg-card border border-border hover:border-primary/45 rounded-xl p-5 flex flex-col justify-between shadow-2xs hover:shadow-md hover:-translate-y-0.5 transition-all duration-300"
          >
            <div>
              <div className="flex justify-between items-start mb-4">
                <div>
                  <h3 className="font-bold text-sm text-foreground group-hover:text-primary transition-colors flex items-center gap-1.5">
                    {agent.name}
                    <ChevronRight className="w-3.5 h-3.5 text-muted-foreground/60 opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all" />
                  </h3>
                  <p className="text-[11px] text-muted-foreground mt-1 leading-relaxed line-clamp-2">{agent.description}</p>
                </div>
                
                {agent.badge && (
                  <span className="bg-destructive/10 text-destructive text-[9px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1 shrink-0">
                    <span className="w-1.5 h-1.5 bg-destructive rounded-full animate-pulse"></span> 
                    {agent.badge.text}
                  </span>
                )}
              </div>

              <div className="space-y-2 mb-4">
                <div className="flex justify-between text-[10px]">
                  <span className="text-muted-foreground">Last Run</span>
                  <span className="font-semibold text-foreground">{agent.lastRun}</span>
                </div>
                <div className="flex justify-between text-[10px]">
                  <span className="text-muted-foreground">Success</span>
                  <span className="font-semibold text-emerald-600">● {agent.successRate}</span>
                </div>
                <div className="flex justify-between text-[10px]">
                  <span className="text-muted-foreground">Usage</span>
                  <span className="font-semibold text-foreground">● {agent.usage}</span>
                </div>
              </div>

              <div className="mb-4">
                <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-2">Connected Apps</p>
                <div className="flex gap-2">
                  {agent.connectedApps.map((app, appIdx) => (
                    <div key={appIdx} className="w-6 h-6 bg-muted border border-border/60 rounded-md flex items-center justify-center p-1" title={app.name}>
                      <img className="w-full grayscale brightness-95 opacity-80" src={app.logoUrl} alt={app.name} />
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div>
              <div className="mb-4 p-3 bg-neutral-900/95 rounded-lg font-mono text-[9px] text-emerald-400 h-14 overflow-hidden flex flex-col justify-end gap-1 select-none border border-neutral-800">
                <p className="opacity-50"># Initiating Reasoning Loop...</p>
                <p className="animate-pulse">&gt; {agent.terminalLogs[1]}</p>
              </div>

              <div className="border-t border-border/60 pt-3 flex items-center justify-between">
                <div className="text-[10px] text-muted-foreground">Scenarios: <span className="text-foreground font-bold">{agent.scenariosCount}</span></div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-semibold text-muted-foreground">Active</span>
                  
                  <button 
                    onClick={(e) => {
                      e.stopPropagation();
                      setActiveStatus(prev => ({ ...prev, [agent.id]: !prev[agent.id] }));
                    }}
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                      activeStatus[agent.id] ? 'bg-primary' : 'bg-muted-foreground/30'
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow-xs ring-0 transition duration-200 ease-in-out ${
                        activeStatus[agent.id] ? 'translate-x-4' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>
              </div>
            </div>
          </article>
        ))}

        <button 
          onClick={() => dispatch(setModalOpen(true))}
          className="border-2 border-dashed border-border hover:border-primary/50 rounded-xl flex flex-col items-center justify-center p-8 bg-card/40 hover:bg-card transition-all group min-h-[300px] cursor-pointer"
        >
          <div className="w-12 h-12 bg-muted border border-border/80 rounded-full flex items-center justify-center mb-4 shadow-2xs group-hover:scale-105 group-hover:border-primary/20 group-hover:text-primary transition-all">
            <Plus className="w-5 h-5 text-muted-foreground group-hover:text-primary transition-colors" />
          </div>
          <p className="font-bold text-sm text-foreground group-hover:text-primary transition-colors">New Agent</p>
          <p className="text-[11px] text-muted-foreground mt-1">Deploy instance to cluster</p>
        </button>
      </div>

      <section className="bg-primary text-primary-foreground rounded-xl p-6 md:p-8 flex flex-col xl:flex-row items-center justify-between gap-6 md:gap-12 relative overflow-hidden shadow-md">
        <div className="flex-1 space-y-4">
          <span className="bg-white/10 px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest inline-block select-none">
            System Insight
          </span>
          <h2 className="font-serif text-3xl font-bold tracking-tight">Optimize your Orchestration</h2>
          <p className="text-sm opacity-80 max-w-lg leading-relaxed">
            Running at 94% efficiency. We suggest offloading redundant RAG pipelines to the edge cluster to reduce latency by approx 18%.
          </p>
          <div className="flex gap-8 pt-2">
            <div>
              <p className="text-[10px] uppercase opacity-60 tracking-wider font-bold">Compute Saved</p>
              <p className="text-2xl font-bold font-serif">12.4 kWh</p>
            </div>
            <div className="w-px h-10 bg-white/10" />
            <div>
              <p className="text-[10px] uppercase opacity-60 tracking-wider font-bold">Agent Velocity</p>
              <p className="text-2xl font-bold font-serif">+18.2%</p>
            </div>
          </div>
        </div>
        
        <div className="shrink-0 w-72 h-44 rounded-xl overflow-hidden shadow-xl rotate-2 hidden xl:block border border-white/10">
          <img 
            alt="Hardware" 
            className="w-full h-full object-cover grayscale brightness-50 contrast-125" 
            src="https://lh3.googleusercontent.com/aida-public/AB6AXuDnIm42ZMZYhaoGi4rF9iukOGhtsoGIxTVm69ciREa0n7Unc8BQyzdyfT56WOYYlKbPhmLkJmBsfeVcZZPyJAf-lMbq2gNQ4jSsejM3b19XV0Wl5l-WfcH1BLebzP2wmFr8tWybSKtDkhwDDwgFaeVDC-KKfp8LQobYyUzO7amYG4OUC-NRGHzRJDpiaCeFzqFKCsxsH4IhCuAqMW8yO5Q4pFuCw2LUoZUbqe6QUqutxEq2lhdGS8ZGAbgwCWTNmMgJcGcxUiE9R42c" 
          />
        </div>
      </section>
    </div>
  );
};

export default Workspace;
