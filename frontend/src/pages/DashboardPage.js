import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, Lightning, Database, Timer, ChartBar } from '@phosphor-icons/react';
import { BarChart, Bar, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { api } from '../lib/api';
import { useAuth } from '../context/AuthContext';

const AGENT_COLORS = {
  local_retrieval: '#007AFF',
  general_llm: '#FFCC00',
  tavily_web: '#34C759',
  arxiv_research: '#FF3B30'
};

const AGENT_LABEL = {
  local_retrieval: 'LOCAL',
  general_llm: 'GENERAL',
  tavily_web: 'WEB',
  arxiv_research: 'ARXIV'
};

export default function DashboardPage() {
  const [overview, setOverview] = useState(null);
  const [recent, setRecent] = useState([]);
  const { user } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    (async () => {
      try {
        const [a, b] = await Promise.all([api.get('/stats/overview'), api.get('/stats/recent')]);
        setOverview(a.data);
        setRecent(b.data.items || []);
      } catch (e) {
        // ignore
      }
    })();
  }, []);

  if (!overview) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-obsidian text-white/50 font-mono text-xs">
        Loading dashboard…
      </div>
    );
  }

  const t = overview.totals;
  const agents = overview.agents || [];
  const chartData = agents.map((a) => ({
    name: AGENT_LABEL[a.name] || a.name,
    Avg: a.avg_score,
    Wins: a.wins,
    color: AGENT_COLORS[a.name] || '#FFFFFF'
  }));

  return (
    <div className="min-h-screen bg-obsidian text-white">
      <header className="border-b border-white/10">
        <div className="max-w-7xl mx-auto px-6 py-5 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/app')}
              className="text-white/60 hover:text-white transition-colors"
              data-testid="back-to-chat-btn"
              aria-label="Back to chat"
            >
              <ArrowLeft size={16} weight="bold" />
            </button>
            <Link to="/" className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 bg-white" aria-hidden />
              <span className="font-mono text-[10px] tracking-[0.3em]">DECISION.ENGINE / STATS</span>
            </Link>
          </div>
          <div className="text-[10px] font-mono text-white/40">
            {overview.is_admin_view ? 'ADMIN VIEW · ALL USERS' : `${user?.email || ''}`}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-10">
        <div className="flex items-end justify-between mb-10">
          <div>
            <span className="label-eyebrow">/ overview</span>
            <h1 className="mt-3 text-4xl font-bold tracking-tight">Engine performance</h1>
          </div>
          <Link
            to="/app"
            className="hidden sm:inline-flex items-center gap-2 text-[11px] tracking-[0.25em] uppercase font-bold text-white/60 hover:text-white transition-colors"
            data-testid="dashboard-to-chat-link"
          >
            Back to chat →
          </Link>
        </div>

        {/* Metric tiles */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-white/10 mb-12" data-testid="metric-tiles">
          <MetricTile icon={Lightning} label="Total queries" value={t.queries} testid="metric-total-queries" />
          <MetricTile
            icon={Database}
            label="Cache hit rate"
            value={`${(t.cache_hit_rate * 100).toFixed(1)}%`}
            sub={`${t.cache_hits} of ${t.queries}`}
            testid="metric-cache-rate"
          />
          <MetricTile icon={Timer} label="Avg latency (miss)" value={`${(t.avg_latency_ms / 1000).toFixed(1)}s`} testid="metric-latency" />
          <MetricTile icon={ChartBar} label="Last 7 days" value={t.queries_last_7d} sub={`${t.threads} threads`} testid="metric-7d" />
        </div>

        {/* Agent performance */}
        <section className="surface p-8 mb-12" data-testid="agent-perf-section">
          <div className="flex items-end justify-between mb-6">
            <div>
              <span className="label-eyebrow">/ leaderboard</span>
              <h2 className="mt-2 text-2xl font-bold tracking-tight">Agent performance</h2>
            </div>
            <span className="hidden sm:block text-[10px] font-mono text-white/40">SCORED BY LLM-AS-JUDGE · 0—10</span>
          </div>

          <div className="grid md:grid-cols-2 gap-8">
            <div>
              <div className="space-y-3">
                {agents.map((a) => (
                  <div key={a.name} className="flex items-center gap-3" data-testid={`agent-row-${a.name}`}>
                    <span
                      className="w-2.5 h-2.5 flex-shrink-0"
                      style={{ background: AGENT_COLORS[a.name], boxShadow: `0 0 8px ${AGENT_COLORS[a.name]}` }}
                      aria-hidden
                    />
                    <span className="font-mono text-[11px] tracking-[0.2em] w-20" style={{ color: AGENT_COLORS[a.name] }}>
                      {AGENT_LABEL[a.name]}
                    </span>
                    <div className="flex-1 h-2 bg-white/5 relative">
                      <div
                        className="absolute inset-y-0 left-0"
                        style={{ width: `${(a.avg_score / 10) * 100}%`, background: AGENT_COLORS[a.name] }}
                      />
                    </div>
                    <span className="font-mono text-xs text-white/80 w-12 text-right">{a.avg_score.toFixed(1)}</span>
                    <span className="font-mono text-[10px] text-white/40 w-16 text-right">{a.wins} wins</span>
                  </div>
                ))}
                {agents.every((a) => a.samples === 0) && (
                  <div className="text-xs text-white/40 font-mono">No agent runs yet. Ask a question to populate the leaderboard.</div>
                )}
              </div>
            </div>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <CartesianGrid stroke="#ffffff15" vertical={false} />
                  <XAxis dataKey="name" tick={{ fill: '#ffffff80', fontSize: 10, fontFamily: 'JetBrains Mono' }} axisLine={{ stroke: '#ffffff20' }} tickLine={false} />
                  <YAxis domain={[0, 10]} tick={{ fill: '#ffffff60', fontSize: 10, fontFamily: 'JetBrains Mono' }} axisLine={{ stroke: '#ffffff20' }} tickLine={false} />
                  <Tooltip
                    contentStyle={{
                      background: '#0A0A0A',
                      border: '1px solid #ffffff20',
                      borderRadius: 0,
                      fontFamily: 'JetBrains Mono',
                      fontSize: 11
                    }}
                    cursor={{ fill: '#ffffff08' }}
                  />
                  <Bar dataKey="Avg" radius={0}>
                    {chartData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>

        {/* Recent runs */}
        <section className="surface" data-testid="recent-runs-section">
          <div className="px-6 py-5 border-b border-white/10 flex items-center justify-between">
            <span className="label-eyebrow">/ recent runs</span>
            <span className="text-[10px] font-mono text-white/40">{recent.length} shown</span>
          </div>
          <div className="divide-y divide-white/5">
            {recent.length === 0 && (
              <div className="px-6 py-8 text-sm text-white/40 font-mono">No runs yet.</div>
            )}
            {recent.map((r, i) => (
              <div key={i} className="px-6 py-3 flex items-center gap-4 text-sm" data-testid={`recent-row-${i}`}>
                <span className={`w-1.5 h-1.5 ${r.cache_hit ? 'bg-cache' : 'bg-white/60'}`} aria-hidden />
                <span className="flex-1 truncate text-white/80">{r.question}</span>
                <span className="font-mono text-[10px] text-white/40 hidden sm:inline">
                  {(r.elapsed_ms / 1000).toFixed(1)}s
                </span>
                <span className="font-mono text-[10px] text-white/40 hidden md:inline">
                  {r.cache_hit ? 'CACHE' : `BEST=${AGENT_LABEL[Object.keys(AGENT_LABEL)[r.best_index]] || '—'}`}
                </span>
                <span className="font-mono text-[10px] text-white/30 hidden lg:inline">
                  {new Date(r.created_at).toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

function MetricTile({ icon: Icon, label, value, sub, testid }) {
  return (
    <div className="bg-obsidian p-8 flex flex-col gap-3" data-testid={testid}>
      <div className="flex items-center justify-between text-white/40">
        <Icon size={16} weight="duotone" />
        <span className="label-eyebrow">{label}</span>
      </div>
      <div className="text-4xl font-bold tracking-tight">{value}</div>
      {sub && <div className="text-[10px] font-mono tracking-wider text-white/40">{sub}</div>}
    </div>
  );
}

// (end)
