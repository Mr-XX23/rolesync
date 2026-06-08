import React, { useState } from 'react';
import { MessageSquare, Terminal, Cpu } from 'lucide-react';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';

export const Support: React.FC = () => {
  const [ticketSubject, setTicketSubject] = useState('');
  const [ticketDescription, setTicketDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleTicketSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!ticketSubject || !ticketDescription) return;

    setIsSubmitting(true);
    setTimeout(() => {
      setIsSubmitting(false);
      setTicketSubject('');
      setTicketDescription('');
      alert('Support ticket cataloged! A synchronizer engineer will review the vector trace details shortly.');
    }, 1500);
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500 pb-16">
      {/* Header */}
      <section className="space-y-2">
        <h2 className="font-serif text-3xl font-bold text-primary tracking-tight">Support Desk</h2>
        <p className="text-sm text-muted-foreground max-w-xl leading-relaxed">
          Open communication tickets with synchronizer support teams, inspect running vector node traces, and analyze diagnostic dump reports.
        </p>
      </section>

      {/* Split support and system logs */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">
        {/* Support Ticket Submission */}
        <div className="bg-card border border-border p-6 rounded-2xl shadow-2xs flex flex-col justify-between space-y-6">
          <div className="space-y-4">
            <div className="flex items-center gap-2 border-b border-border/60 pb-4">
              <MessageSquare className="w-5 h-5 text-primary" />
              <h3 className="font-serif text-lg font-bold text-foreground">File Support Ticket</h3>
            </div>

            <form onSubmit={handleTicketSubmit} className="space-y-4 text-left">
              {/* Subject */}
              <Input
                label="Subject Title"
                id="support-ticket-subject"
                type="text"
                value={ticketSubject}
                onChange={(e) => setTicketSubject(e.target.value)}
                placeholder="e.g. pgvector shard indexing slow for CSVs"
                required
              />

              {/* Description */}
              <div className="space-y-1.5 w-full">
                <label htmlFor="support-ticket-desc" className="text-sm font-medium text-foreground block">
                  Detailed Trace Description
                </label>
                <textarea
                  id="support-ticket-desc"
                  rows={4}
                  value={ticketDescription}
                  onChange={(e) => setTicketDescription(e.target.value)}
                  className="w-full bg-background border border-border rounded-lg px-4 py-2.5 text-sm text-foreground placeholder:text-muted-foreground/50 transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-primary/10 focus:border-primary shadow-2xs resize-none"
                  placeholder="Provide context, including file extensions, embedding model chosen, and chunk threshold sizes."
                  required
                />
              </div>

              <div className="pt-2 flex justify-end">
                <Button
                  type="submit"
                  isLoading={isSubmitting}
                  loadingText="Logging Ticket..."
                  className="w-auto px-6 py-2.5 text-xs font-semibold rounded-xl"
                >
                  Dispatch Ticket
                </Button>
              </div>
            </form>
          </div>
        </div>

        {/* Live Vector Nodes Traces Console */}
        <div className="bg-card border border-border p-6 rounded-2xl shadow-2xs flex flex-col justify-between space-y-6">
          <div className="space-y-4">
            <div className="flex items-center gap-2 border-b border-border/60 pb-4">
              <Terminal className="w-5 h-5 text-primary" />
              <h3 className="font-serif text-lg font-bold text-foreground">Diagnostic Node Stream</h3>
            </div>

            <div className="bg-muted/40 font-mono text-[9px] text-muted-foreground p-4 rounded-xl space-y-2 border border-border/40 overflow-y-auto max-h-[220px]">
              <div className="flex gap-2">
                <span className="text-primary font-bold">[SYSTEM]</span>
                <span>Initializing vector partition sync sequence...</span>
              </div>
              <div className="flex gap-2 text-emerald-700 dark:text-emerald-400">
                <span className="font-bold">[SUCCESS]</span>
                <span>pgvector local cluster connected at port 5432</span>
              </div>
              <div className="flex gap-2">
                <span className="text-primary font-bold">[STORAGE]</span>
                <span>Shard partition size: 1.24 GB // Cosine indices configured</span>
              </div>
              <div className="flex gap-2 text-amber-700 dark:text-amber-300 animate-pulse">
                <span className="font-bold">[WARNING]</span>
                <span>OAuth key Salesforce expiring in 12 days. Renew credentials.</span>
              </div>
              <div className="flex gap-2">
                <span className="text-primary font-bold">[ENGINE]</span>
                <span>Embedder allocation: BGE-M3 (Enterprise-Grade) online</span>
              </div>
            </div>
          </div>

          <Button
            variant="outline"
            onClick={() => alert('Diagnostic dump log generated! file:///var/log/rolesync/diagnostics.log')}
            icon={<Cpu className="w-4 h-4 text-primary" />}
            className="w-full py-2.5 text-xs font-semibold rounded-xl"
          >
            Generate Support Trace Dump
          </Button>
        </div>
      </div>
    </div>
  );
};
export default Support;
