import React, { useState } from 'react';
import { X, Rocket, Plus } from 'lucide-react';
import { useAppDispatch, useAppSelector } from '../../store';
import { addTask, setModalOpen } from '../../store/taskSlice';
import { Button } from './Button';

export const NewInstanceModal: React.FC = () => {
  const dispatch = useAppDispatch();
  const isOpen = useAppSelector((state) => state.task.isModalOpen);

  const [aliasName, setAliasName] = useState('');
  const [clientInput, setClientInput] = useState('');
  const [clients, setClients] = useState<string[]>(['Acme Corp']);
  const [instruction, setInstruction] = useState('');
  const [clientKnowledge, setClientKnowledge] = useState(true);
  const [interactionData, setInteractionData] = useState(false);
  const [benchmarks, setBenchmarks] = useState(false);
  const [error, setError] = useState('');

  if (!isOpen) return null;

  const handleAddClient = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const trimmed = clientInput.trim();
      if (trimmed && !clients.includes(trimmed)) {
        setClients([...clients, trimmed]);
        setClientInput('');
      }
    }
  };

  const handleAddClientButton = () => {
    const trimmed = clientInput.trim();
    if (trimmed && !clients.includes(trimmed)) {
      setClients([...clients, trimmed]);
      setClientInput('');
    }
  };

  const handleRemoveClient = (clientToRemove: string) => {
    setClients(clients.filter((c) => c !== clientToRemove));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!aliasName.trim()) {
      setError('Instance Alias Name is required');
      return;
    }

    const groundingData: string[] = [];
    if (clientKnowledge) groundingData.push('Client-Specific Knowledge Base');
    if (interactionData) groundingData.push('Historical Client Interaction Data');
    if (benchmarks) groundingData.push('Proprietary Industry Benchmarks');

    dispatch(
      addTask({
        name: aliasName.trim(),
        type: 'Agent Instance',
        schedule: 'On Demand',
        clients,
        instruction: instruction.trim(),
        groundingData,
      })
    );

    // Reset Form
    setAliasName('');
    setClientInput('');
    setClients(['Acme Corp']);
    setInstruction('');
    setClientKnowledge(true);
    setInteractionData(false);
    setBenchmarks(false);
    setError('');

    // Close Modal
    dispatch(setModalOpen(false));
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-md animate-in fade-in duration-300">
      <div className="bg-card w-full max-w-xl rounded-xl border border-border shadow-2xl flex flex-col max-h-[90vh] overflow-hidden text-left">
        {/* Header */}
        <div className="p-6 border-b border-border flex items-center justify-between bg-card">
          <h3 className="font-serif text-2xl font-bold text-primary">Initialize New Agent Instance</h3>
          <button
            onClick={() => dispatch(setModalOpen(false))}
            className="p-1 text-muted-foreground hover:text-destructive transition-colors rounded-lg hover:bg-muted focus:outline-none"
            aria-label="Close modal"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form Container */}
        <form onSubmit={handleSubmit} className="flex flex-col overflow-hidden">
          {/* Content */}
          <div className="p-6 overflow-y-auto space-y-6 max-h-[calc(90vh-140px)]">
            {error && (
              <div className="bg-destructive/10 border border-destructive/20 text-destructive text-xs py-2 px-3 rounded-lg font-semibold">
                {error}
              </div>
            )}

            {/* Section 1: Meta */}
            <div className="space-y-2">
              <label className="font-mono text-[10px] uppercase text-muted-foreground tracking-wider font-bold">
                Instance Alias Name
              </label>
              <input
                className="w-full px-4 py-3 rounded-xl border border-border bg-background text-foreground placeholder:text-muted-foreground/40 focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all text-sm outline-none"
                placeholder="e.g., Acme Corp Strategy"
                type="text"
                value={aliasName}
                onChange={(e) => {
                  setAliasName(e.target.value);
                  if (error) setError('');
                }}
                required
              />
            </div>

            {/* Section 2: Role Specifics */}
            <div className="space-y-4">
              {/* Target Clients */}
              <div className="space-y-2">
                <label className="font-mono text-[10px] uppercase text-muted-foreground tracking-wider font-bold">
                  Target Client(s)
                </label>
                <div className="flex flex-wrap gap-2 p-2.5 min-h-[48px] rounded-xl border border-border bg-background focus-within:ring-2 focus-within:ring-primary/20 focus-within:border-primary transition-all items-center">
                  {clients.map((client) => (
                    <div
                      key={client}
                      className="flex items-center gap-1.5 px-2.5 py-1 bg-muted text-foreground rounded-lg text-xs font-semibold border border-border/50"
                    >
                      <span>{client}</span>
                      <button
                        type="button"
                        onClick={() => handleRemoveClient(client)}
                        className="text-muted-foreground hover:text-destructive transition-colors focus:outline-none"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                  <div className="flex items-center flex-1 min-w-[150px] gap-1">
                    <input
                      className="w-full bg-transparent border-none focus:ring-0 p-1 text-sm outline-none text-foreground placeholder:text-muted-foreground/45"
                      placeholder={clients.length === 0 ? "Select particular or multiple clients..." : "Add client..."}
                      type="text"
                      value={clientInput}
                      onChange={(e) => setClientInput(e.target.value)}
                      onKeyDown={handleAddClient}
                    />
                    {clientInput.trim() && (
                      <button
                        type="button"
                        onClick={handleAddClientButton}
                        className="p-1 rounded-md bg-primary/10 text-primary hover:bg-primary/20 transition-all focus:outline-none"
                        title="Add client tag"
                      >
                        <Plus className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {/* Instruction */}
              <div className="space-y-2">
                <label className="font-mono text-[10px] uppercase text-muted-foreground tracking-wider font-bold">
                  Instruction
                </label>
                <textarea
                  className="w-full px-4 py-3 rounded-xl border border-border bg-background text-foreground placeholder:text-muted-foreground/40 focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all text-sm outline-none resize-none"
                  placeholder="Define specific client objections, lead info, or negotiation goals..."
                  rows={4}
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                />
              </div>
            </div>

            {/* Section 3: Grounding */}
            <div className="space-y-3">
              <h4 className="font-mono text-[10px] uppercase text-muted-foreground tracking-wider font-bold">
                Knowledge and Data
              </h4>
              <div className="space-y-2">
                <label className="flex items-center gap-3 p-3.5 rounded-xl border border-border bg-muted/20 cursor-pointer hover:bg-muted/40 transition-colors select-none">
                  <input
                    type="checkbox"
                    checked={clientKnowledge}
                    onChange={(e) => setClientKnowledge(e.target.checked)}
                    className="w-4 h-4 rounded border-border text-primary accent-primary focus:ring-primary"
                  />
                  <span className="text-xs font-semibold text-foreground">Client-Specific Knowledge Base</span>
                </label>
                <label className="flex items-center gap-3 p-3.5 rounded-xl border border-border bg-muted/20 cursor-pointer hover:bg-muted/40 transition-colors select-none">
                  <input
                    type="checkbox"
                    checked={interactionData}
                    onChange={(e) => setInteractionData(e.target.checked)}
                    className="w-4 h-4 rounded border-border text-primary accent-primary focus:ring-primary"
                  />
                  <span className="text-xs font-semibold text-foreground">Historical Client Interaction Data</span>
                </label>
                <label className="flex items-center gap-3 p-3.5 rounded-xl border border-border bg-muted/20 cursor-pointer hover:bg-muted/40 transition-colors select-none">
                  <input
                    type="checkbox"
                    checked={benchmarks}
                    onChange={(e) => setBenchmarks(e.target.checked)}
                    className="w-4 h-4 rounded border-border text-primary accent-primary focus:ring-primary"
                  />
                  <span className="text-xs font-semibold text-foreground">Proprietary Industry Benchmarks</span>
                </label>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="p-6 border-t border-border flex gap-3 bg-card shrink-0">
            <Button
              type="button"
              variant="outline"
              onClick={() => dispatch(setModalOpen(false))}
              className="flex-1 py-3 px-4 rounded-xl text-sm font-semibold hover:bg-muted"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              className="flex-[2] py-3 px-4 rounded-xl text-sm font-semibold flex items-center justify-center gap-2"
              icon={<Rocket className="w-4 h-4" />}
            >
              DEPLOY INSTANCE
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};
