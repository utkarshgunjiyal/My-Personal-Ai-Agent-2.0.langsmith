import React from 'react';
import { Check, CircleNotch, Trophy } from '@phosphor-icons/react';

const ORDER = ['local_retrieval', 'general_llm', 'tavily_web', 'arxiv_research', 'thread_files'];
const LABEL = {
  local_retrieval: 'KB',
  general_llm: 'GENERAL',
  tavily_web: 'WEB',
  arxiv_research: 'ARXIV',
  thread_files: 'YOUR FILES'
};
const COLOR = {
  local_retrieval: '#007AFF',
  general_llm: '#FFCC00',
  tavily_web: '#34C759',
  arxiv_research: '#FF3B30',
  thread_files: '#AF52DE'
};

/**
 * Live pipeline indicator shown while the engine is streaming.
 * `pipeline` is { agents: {name: 'pending'|'running'|'done'}, scores?: number[], bestIndex?: number, phase: string, hasFiles?: bool }
 */
export default function LivePipeline({ pipeline }) {
  if (!pipeline) return null;
  const { agents = {}, scores = null, bestIndex = null, phase = 'starting', hasFiles = false } = pipeline;
  const order = hasFiles ? ORDER : ORDER.slice(0, 4);
  const gridCols = hasFiles ? 'sm:grid-cols-5' : 'sm:grid-cols-4';

  return (
    <div className="animate-fade-in-up surface p-4" data-testid="live-pipeline">
      <div className="flex items-center gap-2 text-[10px] font-mono tracking-[0.25em] text-white/60 mb-3">
        <span className="w-1.5 h-1.5 bg-white animate-pulse" aria-hidden />
        <span>ENGINE · {phase.toUpperCase()}</span>
      </div>
      <div className={`grid grid-cols-2 ${gridCols} gap-px bg-white/10`}>
        {order.map((name, idx) => {
          const status = agents[name] || 'pending';
          const score = scores && typeof scores[idx] === 'number' ? scores[idx] : null;
          const isBest = bestIndex === idx;
          const c = COLOR[name];
          return (
            <div
              key={name}
              className="bg-obsidian p-3 flex flex-col gap-2"
              data-testid={`live-agent-${name}`}
            >
              <div className="flex items-center gap-2">
                <span
                  className={`w-2 h-2 ${status === 'running' ? 'animate-pulse-glow' : ''}`}
                  style={{
                    background: status === 'pending' ? '#ffffff20' : c,
                    boxShadow: status === 'pending' ? 'none' : `0 0 8px ${c}`
                  }}
                  aria-hidden
                />
                <span className="font-mono text-[10px] tracking-[0.18em]" style={{ color: status === 'pending' ? '#ffffff60' : c }}>
                  {LABEL[name]}
                </span>
                {status === 'done' && <Check size={11} weight="bold" className="text-white/60 ml-auto" />}
                {status === 'running' && <CircleNotch size={11} weight="bold" className="text-white/60 ml-auto animate-spin" />}
              </div>
              <div className="flex items-center justify-between text-[10px] font-mono">
                <span className="text-white/40">
                  {status === 'pending' && 'waiting'}
                  {status === 'running' && 'thinking…'}
                  {status === 'done' && (score !== null ? `score ${score.toFixed(1)}` : 'done')}
                </span>
                {isBest && (
                  <span className="inline-flex items-center gap-1 text-[9px] tracking-[0.2em] uppercase font-bold px-1.5 py-0.5 bg-white text-obsidian">
                    <Trophy size={9} weight="fill" />
                    best
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
