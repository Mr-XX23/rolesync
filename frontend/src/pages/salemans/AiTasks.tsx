import React, { useState } from 'react';
import { Calendar, Play, CheckCircle2, Cpu, Clock } from 'lucide-react';
import { Button } from '../../components/common/Button';

interface TaskItem {
  id: string;
  name: string;
  status: 'Running' | 'Scheduled' | 'Completed' | 'Failed';
  type: string;
  schedule: string;
  lastRun: string;
}

export const AiTasks: React.FC = () => {
  const [tasks] = useState<TaskItem[]>([
    {
      id: '1',
      name: 'Salesforce Contact Delta Extraction',
      status: 'Running',
      type: 'Sync Data',
      schedule: 'Every 2 hours',
      lastRun: '1 hour ago',
    },
    {
      id: '2',
      name: 'Vector Database Re-indexing Shards',
      status: 'Scheduled',
      type: 'Model Tuning',
      schedule: 'Daily at 02:00 AM',
      lastRun: '22 hours ago',
    },
    {
      id: '3',
      name: 'Ingest Competitor Pricing Portal',
      status: 'Completed',
      type: 'Scraper Ingestion',
      schedule: 'Weekly on Mondays',
      lastRun: '1 day ago',
    },
  ]);

  const handleRunTask = (name: string) => {
    alert(`Manually executing vanguard task pipeline: ${name}`);
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500 pb-16">
      {/* Header */}
      <section className="space-y-2">
        <h2 className="font-serif text-3xl font-bold text-primary">Agent Manager</h2>
        <p className="text-sm text-muted-foreground max-w-xl leading-relaxed">
          Monitor background worker routines, synchronize data pipelines, and verify agent automation triggers in real time.
        </p>
      </section>

      {/* Grid: Stat Overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-card border border-border p-5 rounded-2xl shadow-2xs flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-primary/10 text-primary flex items-center justify-center font-bold">
            <Cpu className="w-6 h-6 animate-pulse" />
          </div>
          <div>
            <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider font-bold">Active Engines</p>
            <p className="text-2xl font-serif font-bold text-foreground">3 Pipelines Running</p>
          </div>
        </div>

        <div className="bg-card border border-border p-5 rounded-2xl shadow-2xs flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-primary/10 text-primary flex items-center justify-center font-bold">
            <Clock className="w-6 h-6" />
          </div>
          <div>
            <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider font-bold">Next Cron Action</p>
            <p className="text-sm font-semibold text-foreground">Re-index Shards (02:00 AM)</p>
          </div>
        </div>

        <div className="bg-card border border-border p-5 rounded-2xl shadow-2xs flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-primary/10 text-primary flex items-center justify-center font-bold">
            <CheckCircle2 className="w-6 h-6" />
          </div>
          <div>
            <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider font-bold">Daily Success Rate</p>
            <p className="text-2xl font-serif font-bold text-foreground">99.84% Optimal</p>
          </div>
        </div>
      </div>

      {/* Task Queue Panel */}
      <div className="bg-card border border-border rounded-2xl p-6 shadow-2xs">
        <h3 className="font-serif text-lg font-bold text-foreground mb-6">Automation Task Registry</h3>

        <div className="space-y-4">
          {tasks.map((task) => (
            <div
              key={task.id}
              className="group bg-muted/30 border border-border/40 hover:border-primary/30 rounded-2xl p-5 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 transition-all duration-200"
            >
              <div className="flex items-start gap-4">
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center font-bold border shrink-0 ${
                  task.status === 'Running'
                    ? 'bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/20'
                    : task.status === 'Scheduled'
                    ? 'bg-blue-500/10 text-blue-700 dark:text-blue-300 border-blue-500/20'
                    : 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/20'
                }`}>
                  {task.status === 'Running' ? (
                    <Cpu className="w-5 h-5 animate-spin" />
                  ) : task.status === 'Scheduled' ? (
                    <Calendar className="w-5 h-5" />
                  ) : (
                    <CheckCircle2 className="w-5 h-5" />
                  )}
                </div>

                <div>
                  <h4 className="text-sm font-bold text-foreground leading-tight">{task.name}</h4>
                  <div className="flex flex-wrap gap-x-3 gap-y-1.5 mt-2 text-xs text-muted-foreground font-mono">
                    <span className="bg-background px-2.5 py-0.5 rounded border border-border/40 font-bold uppercase tracking-wider text-[9px]">
                      {task.type}
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="w-3.5 h-3.5" />
                      <span>{task.schedule}</span>
                    </span>
                    <span>• Last executed {task.lastRun}</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3 w-full md:w-auto justify-end">
                <span className={`text-[10px] font-mono font-bold tracking-widest uppercase border px-2.5 py-0.5 rounded-full ${
                  task.status === 'Running'
                    ? 'bg-amber-500/15 border-amber-500/35 text-amber-800 dark:text-amber-300'
                    : task.status === 'Scheduled'
                    ? 'bg-blue-500/15 border-blue-500/35 text-blue-800 dark:text-blue-300'
                    : 'bg-emerald-500/15 border-emerald-500/35 text-emerald-800 dark:text-emerald-300'
                }`}>
                  {task.status}
                </span>

                <Button
                  variant="outline"
                  onClick={() => handleRunTask(task.name)}
                  className="p-2.5 aspect-square rounded-xl shadow-2xs hover:border-primary/20"
                  title="Run Now"
                  icon={<Play className="w-3.5 h-3.5 text-primary" />}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
export default AiTasks;
