import React from 'react';
import { Trophy } from '@phosphor-icons/react';

const COLORS = {
  local_retrieval: '#007AFF',
  general_llm: '#FFCC00',
  tavily_web: '#34C759',
  arxiv_research: '#FF3B30',
  thread_files: '#AF52DE'
};

const LABELS = {
  local_retrieval: 'GLOBAL KB · BM25 + TFIDF',
  general_llm: 'GENERAL · LLM',
  tavily_web: 'WEB · TAVILY',
  arxiv_research: 'RESEARCH · ARXIV',
  thread_files: 'YOUR FILES · HYBRID + FAISS'
};

export default function AgentTracePanel({ traces, scores, bestIndex }) {
  return (
    <div className="mt-3 surface" data-testid="agent-trace-panel">
      {traces.map((t, idx) => {
        const color = COLORS[t.name] || '#FFFFFF';
        const isBest = idx === bestIndex;
        return (
          <div
            key={idx}
            className={`p-4 border-b border-white/10 last:border-b-0 ${isBest ? 'bg-white/[0.03]' : ''}`}
            data-testid={`trace-row-${idx}`}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2.5">
                <span
                  className="w-2.5 h-2.5"
                  style={{ background: color, boxShadow: `0 0 8px ${color}` }}
                  aria-hidden
                />
                <span className="font-mono text-[11px] tracking-[0.2em]" style={{ color }}>
                  {LABELS[t.name] || t.name?.toUpperCase()}
                </span>
                {isBest && (
                  <span className="inline-flex items-center gap-1 text-[9px] tracking-[0.2em] uppercase font-bold px-2 py-0.5 bg-white text-obsidian">
                    <Trophy size={10} weight="fill" />
                    Best
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3 font-mono text-[10px] text-white/50">
                <span>{t.elapsed_ms}ms</span>
                <ScoreBadge score={scores[idx] ?? t.score ?? 0} />
              </div>
            </div>
            <pre className="font-mono text-[11px] leading-relaxed text-white/80 whitespace-pre-wrap">
{t.answer}
            </pre>
            {t.context && (
              <details className="mt-3">
                <summary className="cursor-pointer text-[10px] font-mono tracking-[0.2em] uppercase text-white/40 hover:text-white/70 transition-colors">
                  Context
                </summary>
                <pre className="mt-2 font-mono text-[10px] leading-relaxed text-white/50 whitespace-pre-wrap">
{t.context}
                </pre>
              </details>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ScoreBadge({ score }) {
  const s = Number(score) || 0;
  // Color ramp: 0-4 red, 4-7 yellow, 7-10 green
  let color = '#FF3B30';
  if (s >= 7) color = '#34C759';
  else if (s >= 4) color = '#FFCC00';
  return (
    <span
      className="font-mono text-[11px] font-bold px-2 py-0.5 border"
      style={{ color, borderColor: `${color}55` }}
      data-testid={`score-badge`}
    >
      {s.toFixed(1)} / 10
    </span>
  );
}
