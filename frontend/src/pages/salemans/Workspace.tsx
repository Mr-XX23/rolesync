import React, { useState } from 'react';
import { Send, Terminal, Cpu, Database, CheckCircle2, ShieldCheck } from 'lucide-react';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';

export const Workspace: React.FC = () => {
  const [prompt, setPrompt] = useState('');
  const [chatLog, setChatLog] = useState<{ query: string; answer: string; chunks: string }[]>([
    {
      query: 'What is the current tier pricing structure for Enterprise sync?',
      answer: 'Our Enterprise sync model comprises three main tiers: Standard ($45/operator/mo), Advanced ($95/operator/mo), and Custom Mesh (requires dedicated sales contact). The Advanced tier includes a private pgvector cluster and high-throughput BGE-M3 embedding allocations.',
      chunks: 'Doc: Q4_Pricing_Guide_Final.pdf (Chunks #14, #15)',
    },
  ]);
  const [isQuerying, setIsQuerying] = useState(false);

  const handleQuery = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;

    setIsQuerying(true);
    const userQuery = prompt;
    setPrompt('');

    setTimeout(() => {
      setChatLog((prev) => [
        {
          query: userQuery,
          answer: 'Vector mesh successfully retrieved 3 matching contexts from pgvector store. RAG Synthesis complete: System is operating at peak token capacity, generating model solutions according to the enterprise sales pipeline handbook.',
          chunks: 'Doc: CRM_Export_NorthAmerica.csv (Chunk #342), Q4_Pricing_Guide_Final.pdf (Chunk #88)',
        },
        ...prev,
      ]);
      setIsQuerying(false);
    }, 1500);
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500 pb-16">
      {/* Header */}
      <section className="space-y-2">
        <h2 className="font-serif text-3xl font-bold text-primary tracking-tight">Salesman Workspace</h2>
        <p className="text-sm text-muted-foreground max-w-xl leading-relaxed">
          Interact with calibrated model templates, review retrieved context embeddings, and verify semantic search alignments.
        </p>
      </section>

      {/* Grid: Health Metrics */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <div className="bg-card border border-border p-4 rounded-xl shadow-2xs">
          <p className="text-[10px] font-mono text-muted-foreground uppercase font-bold tracking-wider">active agent</p>
          <h4 className="text-sm font-bold text-foreground mt-1 flex items-center gap-1.5">
            <Cpu className="w-4 h-4 text-primary animate-pulse" />
            <span>Vanguard Salesman v4.2</span>
          </h4>
        </div>

        <div className="bg-card border border-border p-4 rounded-xl shadow-2xs">
          <p className="text-[10px] font-mono text-muted-foreground uppercase font-bold tracking-wider">vector index size</p>
          <h4 className="text-sm font-bold text-foreground mt-1 flex items-center gap-1.5">
            <Database className="w-4 h-4 text-primary" />
            <span>2,100 Vector Shards</span>
          </h4>
        </div>

        <div className="bg-card border border-border p-4 rounded-xl shadow-2xs">
          <p className="text-[10px] font-mono text-muted-foreground uppercase font-bold tracking-wider">RAG alignment</p>
          <h4 className="text-sm font-bold text-foreground mt-1 flex items-center gap-1.5">
            <CheckCircle2 className="w-4 h-4 text-emerald-500" />
            <span>98.6% Similarity Score</span>
          </h4>
        </div>

        <div className="bg-card border border-border p-4 rounded-xl shadow-2xs">
          <p className="text-[10px] font-mono text-muted-foreground uppercase font-bold tracking-wider">guardrail cluster</p>
          <h4 className="text-sm font-bold text-foreground mt-1 flex items-center gap-1.5">
            <ShieldCheck className="w-4 h-4 text-emerald-500" />
            <span>OAuth2 Active</span>
          </h4>
        </div>
      </div>

      {/* Split: prompt tester and logs */}
      <div className="grid grid-cols-12 gap-6 items-stretch">
        {/* Chat prompt console */}
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

            {/* Ingestion Chat Loop */}
            <div className="flex-1 min-h-[250px] max-h-[350px] overflow-y-auto border border-border/60 bg-muted/20 rounded-2xl p-4 space-y-4">
              {chatLog.map((log, index) => (
                <div key={index} className="space-y-2 animate-in fade-in duration-300">
                  {/* Operator Question */}
                  <div className="flex items-start gap-2 bg-background border border-border/40 rounded-xl p-3 shadow-2xs">
                    <span className="font-mono text-[9px] font-bold bg-primary/10 text-primary px-2 py-0.5 rounded-md uppercase tracking-wider shrink-0 mt-0.5">user</span>
                    <p className="text-xs font-semibold text-foreground leading-relaxed">{log.query}</p>
                  </div>

                  {/* Agent Response */}
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

            {/* Input Submission */}
            <form onSubmit={handleQuery} className="w-full">
              <Input
                id="workspace-sales-prompt"
                label=""
                type="text"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                disabled={isQuerying}
                placeholder="Ask your Knowledge Vault a sales query..."
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

        {/* Retrieved Context Cards */}
        <div className="col-span-12 lg:col-span-5">
          <div className="bg-card border border-border p-6 rounded-2xl shadow-2xs h-full flex flex-col justify-between space-y-6">
            <div className="space-y-4">
              <h3 className="font-serif text-lg font-bold text-foreground">Index Calibration Shards</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Review the primary source vector profiles containing pricing structures, terms of service, and pipeline specifications.
              </p>

              <div className="space-y-3">
                <div className="bg-muted/40 border border-border/40 rounded-xl p-4 flex justify-between items-center gap-3">
                  <div>
                    <h5 className="text-xs font-bold text-foreground">Q4_Pricing_Guide_Final.pdf</h5>
                    <p className="text-[10px] text-muted-foreground font-mono mt-1">Segments: Chunks #1 - #85</p>
                  </div>
                  <span className="font-mono text-[9px] font-bold bg-primary/10 text-primary border border-primary/20 px-2 py-0.5 rounded uppercase tracking-wider">
                    active
                  </span>
                </div>

                <div className="bg-muted/40 border border-border/40 rounded-xl p-4 flex justify-between items-center gap-3">
                  <div>
                    <h5 className="text-xs font-bold text-foreground">CRM_Export_NorthAmerica.csv</h5>
                    <p className="text-[10px] text-muted-foreground font-mono mt-1">Segments: Chunks #86 - #142</p>
                  </div>
                  <span className="font-mono text-[9px] font-bold bg-primary/10 text-primary border border-primary/20 px-2 py-0.5 rounded uppercase tracking-wider">
                    active
                  </span>
                </div>
              </div>
            </div>

            <div className="pt-6 border-t border-border/60">
              <Button
                variant="outline"
                onClick={() => alert('Calibrating vector indexes...')}
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
};
export default Workspace;
