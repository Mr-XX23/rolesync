import React, { useState } from 'react';
import { Key, Server } from 'lucide-react';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';

export const Settings: React.FC = () => {
  const [openaiKey, setOpenaiKey] = useState('sk-••••••••••••••••••••••••3a2f');
  const [salesforceUrl, setSalesforceUrl] = useState('https://na42.salesforce.com');
  const [vectorThreshold, setVectorThreshold] = useState(0.72);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setTimeout(() => {
      setIsSubmitting(false);
      alert('Integration settings successfully synced to local cluster vaults!');
    }, 1200);
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500 pb-16">
      {/* Header */}
      <section className="space-y-2">
        <h2 className="font-serif text-3xl font-bold text-primary tracking-tight">Settings</h2>
        <p className="text-sm text-muted-foreground max-w-xl leading-relaxed">
          Manage API authentication keys, adjust vector cluster confidence thresholds, and configure live database sync targets.
        </p>
      </section>

      {/* Settings Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-stretch">
        {/* Core Integrations Form */}
        <div className="col-span-1 lg:col-span-2">
          <form onSubmit={handleSave} className="bg-card border border-border p-6 rounded-2xl shadow-2xs space-y-6">
            <div className="flex items-center gap-2 border-b border-border/60 pb-4">
              <Key className="w-5 h-5 text-primary" />
              <h3 className="font-serif text-lg font-bold text-foreground">API Credentials</h3>
            </div>

            <div className="space-y-4">
              {/* OpenAI Key */}
              <Input
                label="Embedding API Token (OpenAI / Cohere)"
                id="openai-key-setting"
                type="password"
                value={openaiKey}
                onChange={(e) => setOpenaiKey(e.target.value)}
                className="font-mono text-xs"
                placeholder="sk-..."
              />

              {/* Salesforce CRM Target */}
              <Input
                label="Salesforce CRM API Target Endpoint"
                id="salesforce-url-setting"
                type="text"
                value={salesforceUrl}
                onChange={(e) => setSalesforceUrl(e.target.value)}
                className="font-mono text-xs"
                placeholder="https://..."
              />

              {/* Similarity Threshold */}
              <div className="space-y-2">
                <div className="flex justify-between items-center text-xs">
                  <label className="text-muted-foreground font-semibold">Minimum Similarity Filter</label>
                  <span className="font-mono bg-primary/10 text-primary px-2.5 py-0.5 rounded-md font-bold">
                    {vectorThreshold} (Cosine similarity)
                  </span>
                </div>
                <input
                  type="range"
                  max="0.95"
                  min="0.50"
                  step="0.01"
                  value={vectorThreshold}
                  onChange={(e) => setVectorThreshold(parseFloat(e.target.value))}
                  className="w-full h-1 bg-border rounded-lg appearance-none cursor-pointer accent-primary focus:outline-none"
                />
                <p className="text-[10px] text-muted-foreground/75 leading-relaxed">
                  Stricter levels (higher values) return fewer, more highly relevant document matches.
                </p>
              </div>
            </div>

            <div className="pt-4 flex justify-end">
              <Button
                type="submit"
                isLoading={isSubmitting}
                loadingText="Saving Configuration..."
                className="w-auto px-6 py-2.5 text-xs font-semibold rounded-xl"
              >
                Save Environment Configuration
              </Button>
            </div>
          </form>
        </div>

        {/* Diagnostic Metadata Panel */}
        <div className="col-span-1">
          <div className="bg-card border border-border p-6 rounded-2xl shadow-2xs h-full flex flex-col justify-between space-y-6">
            <div className="space-y-4">
              <div className="flex items-center gap-2 border-b border-border/60 pb-4">
                <Server className="w-5 h-5 text-primary" />
                <h3 className="font-serif text-lg font-bold text-foreground">Cluster Diagnostics</h3>
              </div>

              <div className="space-y-3 font-mono text-[10px] leading-relaxed text-muted-foreground">
                <div className="flex justify-between border-b border-border/40 pb-2">
                  <span className="font-bold">pgvector build:</span>
                  <span>v0.5.1 // PostgreSQL 16</span>
                </div>
                <div className="flex justify-between border-b border-border/40 pb-2">
                  <span className="font-bold">Active Shards:</span>
                  <span>4 Vector Partitions</span>
                </div>
                <div className="flex justify-between border-b border-border/40 pb-2">
                  <span className="font-bold">Embedding size:</span>
                  <span>1,536 dimensions</span>
                </div>
                <div className="flex justify-between border-b border-border/40 pb-2">
                  <span className="font-bold">System Status:</span>
                  <span className="text-emerald-700 dark:text-emerald-400 font-bold uppercase">nominal</span>
                </div>
              </div>
            </div>

            <Button
              variant="outline"
              onClick={() => alert('Wiping local index sync cache... Sequence completed.')}
              className="w-full py-2.5 text-xs font-semibold rounded-xl"
            >
              Clear Vector Cache
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};
export default Settings;
