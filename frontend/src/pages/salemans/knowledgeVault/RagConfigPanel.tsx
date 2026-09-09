import React from 'react';
import { Sliders, RotateCcw, Save } from 'lucide-react';
import { Button } from '../../../components/common/Button';
import { RAG_PRESETS } from './vaultUtils';

interface RagConfigPanelProps {
  chunkSize: number;
  setChunkSize: (val: number) => void;
  overlap: number;
  setOverlap: (val: number) => void;
  activePreset: string;
  setActivePreset: (val: string) => void;
  embeddingEngine: string;
  isSavingConfig: boolean;
  onApplyPreset: (presetKey: string) => void;
  onResetConfig: () => void;
  onSaveConfig: () => void;
}

export const RagConfigPanel: React.FC<RagConfigPanelProps> = React.memo(
  ({
    chunkSize,
    setChunkSize,
    overlap,
    setOverlap,
    activePreset,
    setActivePreset,
    embeddingEngine,
    isSavingConfig,
    onApplyPreset,
    onResetConfig,
    onSaveConfig,
  }) => {
    return (
      <div className="col-span-12 lg:col-span-4">
        <div className="bg-card border border-border rounded-2xl p-6 shadow-2xs flex flex-col justify-between h-full">
          <div>
            <div className="flex items-center justify-between pb-4 mb-5 border-b border-border/60">
              <div className="flex items-center gap-2">
                <Sliders className="w-4 h-4 text-primary" />
                <h4 className="font-serif text-base font-bold text-foreground">
                  RAG Calibration
                </h4>
              </div>
              <button
                type="button"
                onClick={onResetConfig}
                className="text-[11px] font-mono text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors cursor-pointer"
                title="Reset to recommended defaults"
              >
                <RotateCcw className="w-3 h-3" />
                <span>Reset</span>
              </button>
            </div>

            {/* Presets Selector */}
            <div className="mb-6 space-y-2">
              <label className="text-xs text-muted-foreground font-medium block">
                Tuning Presets
              </label>
              <div className="grid grid-cols-3 gap-1.5 p-1 bg-muted rounded-xl border border-border/60">
                {Object.keys(RAG_PRESETS).map((key) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => onApplyPreset(key)}
                    className={`px-2 py-1.5 text-[11px] font-semibold rounded-lg transition-all truncate cursor-pointer ${
                      activePreset === key
                        ? 'bg-card text-foreground shadow-2xs border border-border/40'
                        : 'text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    {key === 'balanced' ? 'Balanced' : key === 'qa' ? 'Precision' : 'Context'}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-6">
              {/* Chunk Size Slider */}
              <div className="space-y-2">
                <div className="flex justify-between items-center text-xs">
                  <label className="text-muted-foreground font-medium">Chunk Size</label>
                  <span className="font-mono text-foreground font-bold px-2 py-0.5 rounded bg-muted border border-border/60">
                    {chunkSize} tokens
                  </span>
                </div>
                <input
                  className="w-full h-1.5 bg-muted rounded-lg appearance-none cursor-pointer accent-primary focus:outline-none"
                  max="2048"
                  min="128"
                  step="64"
                  type="range"
                  value={chunkSize}
                  onChange={(e) => {
                    setChunkSize(Number(e.target.value));
                    setActivePreset('');
                  }}
                />
                <div className="flex justify-between text-[10px] text-muted-foreground font-mono">
                  <span>128 (Granular)</span>
                  <span>2048 (Broad)</span>
                </div>
              </div>

              {/* Overlap Window Slider */}
              <div className="space-y-2">
                <div className="flex justify-between items-center text-xs">
                  <label className="text-muted-foreground font-medium">Overlap Window</label>
                  <span className="font-mono text-foreground font-bold px-2 py-0.5 rounded bg-muted border border-border/60">
                    {overlap}%
                  </span>
                </div>
                <input
                  className="w-full h-1.5 bg-muted rounded-lg appearance-none cursor-pointer accent-primary focus:outline-none"
                  max="30"
                  min="0"
                  step="1"
                  type="range"
                  value={overlap}
                  onChange={(e) => {
                    setOverlap(Number(e.target.value));
                    setActivePreset('');
                  }}
                />
                <div className="flex justify-between text-[10px] text-muted-foreground font-mono">
                  <span>0% (Disjoint)</span>
                  <span>30% (Dense)</span>
                </div>
              </div>

              {/* Active Vector Engine */}
              <div className="space-y-2">
                <label className="text-xs text-muted-foreground font-medium block">
                  Embedding Engine
                </label>
                <div className="flex items-center justify-between px-3.5 py-2.5 bg-muted/40 border border-border/70 rounded-xl">
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shrink-0" />
                    <span className="text-xs font-semibold text-foreground">
                      {embeddingEngine.split('(')[0].trim() || 'RoleSync Vector Engine'}
                    </span>
                  </div>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-primary/10 text-primary border border-primary/20">
                    1536-dim
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-8 pt-6 border-t border-border/60">
            <Button
              onClick={onSaveConfig}
              isLoading={isSavingConfig}
              loadingText="Committing Parameters..."
              icon={<Save className="w-4 h-4" />}
              className="w-full shadow-2xs"
            >
              Apply Global Config
            </Button>
          </div>
        </div>
      </div>
    );
  }
);

RagConfigPanel.displayName = 'RagConfigPanel';
