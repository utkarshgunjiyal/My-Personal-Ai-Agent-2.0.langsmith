import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, Graph, Database, Lightning, ShieldCheck, Brain } from '@phosphor-icons/react';

const features = [
  { icon: Graph, color: '#007AFF', name: 'LangGraph workflow', desc: 'Four-agent multi-step pipeline orchestrated as a stateful directed graph.' },
  { icon: Brain, color: '#FFCC00', name: 'LLM-as-judge', desc: 'Independent evaluator scores every candidate answer, then a refiner synthesizes the best.' },
  { icon: Database, color: '#34C759', name: 'Persistent threads', desc: 'Every conversation, score and trace is stored in MongoDB. Resume after server crashes.' },
  { icon: Lightning, color: '#FF3B30', name: 'Hybrid retrieval', desc: 'BM25 + TF-IDF cosine search over an in-process knowledge base. Sub-100ms recall.' },
  { icon: ShieldCheck, color: '#32ADE6', name: 'Semantic cache', desc: 'Embedding-similar past questions reuse prior answers — cutting LLM cost and latency.' }
];

const agents = [
  { color: '#007AFF', name: 'LOCAL', desc: 'Hybrid BM25+TFIDF retrieval over local knowledge.' },
  { color: '#FFCC00', name: 'GENERAL', desc: 'Open-ended LLM reasoning, no retrieval.' },
  { color: '#34C759', name: 'WEB', desc: 'Live web research via Tavily.' },
  { color: '#FF3B30', name: 'ARXIV', desc: 'Research papers from arXiv abstracts.' }
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-obsidian text-white relative overflow-hidden">
      <div className="absolute inset-0 pixel-grid opacity-30 pointer-events-none" aria-hidden />
      <header className="relative border-b border-white/10">
        <div className="max-w-7xl mx-auto px-6 py-5 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-3" data-testid="logo-link">
            <span className="w-3 h-3 bg-white animate-pulse-glow" aria-hidden />
            <span className="font-mono text-xs tracking-[0.3em]">DECISION.ENGINE</span>
          </Link>
          <nav className="flex items-center gap-6 text-xs tracking-[0.18em] uppercase font-bold">
            <Link to="/login" className="text-white/70 hover:text-white transition-colors" data-testid="header-login-link">Sign in</Link>
            <Link
              to="/register"
              className="bg-white text-obsidian px-4 py-2 hover:bg-white/90 transition-colors"
              data-testid="header-cta"
            >
              Start free
            </Link>
          </nav>
        </div>
      </header>

      <main className="relative">
        {/* Hero */}
        <section className="max-w-7xl mx-auto px-6 pt-20 pb-24">
          <div className="grid lg:grid-cols-12 gap-12 items-start">
            <div className="lg:col-span-7">
              <span className="label-eyebrow">v2.0 / multi-agent rag</span>
              <h1 className="mt-6 text-5xl md:text-6xl lg:text-7xl tracking-tight font-bold leading-[0.95]">
                A command center for{' '}
                <span className="text-white/40">multi-agent</span> AI decisions.
              </h1>
              <p className="mt-8 max-w-xl text-white/70 leading-relaxed">
                Four parallel agents debate. A judge scores. A refiner synthesizes. Every answer is grounded,
                cached, and persisted — across server restarts.
              </p>
              <div className="mt-10 flex items-center gap-3">
                <Link
                  to="/register"
                  className="group inline-flex items-center gap-2 bg-white text-obsidian px-6 py-3 text-sm font-bold tracking-wider uppercase hover:bg-white/90 transition-colors"
                  data-testid="hero-get-started-btn"
                >
                  Run the engine
                  <ArrowUpRight size={16} weight="bold" className="group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" />
                </Link>
                <Link
                  to="/login"
                  className="text-sm font-bold tracking-wider uppercase text-white/70 hover:text-white px-2 transition-colors"
                  data-testid="hero-login-link"
                >
                  Sign in
                </Link>
              </div>
            </div>

            {/* Agent quartet card */}
            <div className="lg:col-span-5 surface p-6" data-testid="hero-agent-card">
              <div className="flex items-center justify-between">
                <span className="label-eyebrow">live agents</span>
                <span className="font-mono text-[10px] text-white/40">ENGINE ↻ READY</span>
              </div>
              <div className="mt-6 grid grid-cols-2 gap-px bg-white/10">
                {agents.map((a) => (
                  <div key={a.name} className="bg-obsidian p-5">
                    <div className="flex items-center gap-2">
                      <span
                        className="w-2 h-2"
                        style={{ background: a.color, boxShadow: `0 0 10px ${a.color}` }}
                        aria-hidden
                      />
                      <span className="font-mono text-[11px] tracking-[0.18em] text-white/80">{a.name}</span>
                    </div>
                    <p className="mt-3 text-xs text-white/60 leading-relaxed">{a.desc}</p>
                  </div>
                ))}
              </div>
              <div className="mt-6 flex items-center justify-between text-[11px] font-mono text-white/50">
                <span>JUDGE → REFINE → CACHE</span>
                <span>4 / 4 agents online</span>
              </div>
            </div>
          </div>
        </section>

        {/* Features */}
        <section className="relative border-t border-white/10">
          <div className="max-w-7xl mx-auto px-6 py-20">
            <div className="flex items-end justify-between mb-12">
              <div>
                <span className="label-eyebrow">/ stack</span>
                <h2 className="mt-3 text-3xl md:text-4xl tracking-tight font-bold">Built for production, optimized for clarity.</h2>
              </div>
            </div>
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-px bg-white/10">
              {features.map((f) => (
                <div key={f.name} className="bg-obsidian p-8 flex flex-col gap-4 group hover:bg-surface-2 transition-colors">
                  <f.icon size={24} weight="duotone" style={{ color: f.color }} />
                  <h3 className="text-lg font-bold tracking-tight">{f.name}</h3>
                  <p className="text-sm text-white/60 leading-relaxed">{f.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Closing CTA */}
        <section className="relative border-t border-white/10">
          <div className="max-w-7xl mx-auto px-6 py-20 grid md:grid-cols-12 gap-10 items-end">
            <div className="md:col-span-7">
              <span className="label-eyebrow">/ get started</span>
              <h2 className="mt-3 text-4xl md:text-5xl tracking-tight font-bold">
                Sign in with email. Your threads persist forever.
              </h2>
            </div>
            <div className="md:col-span-5 flex md:justify-end">
              <Link
                to="/register"
                className="inline-flex items-center gap-3 bg-white text-obsidian px-8 py-4 font-bold tracking-wider uppercase text-sm hover:bg-white/90 transition-colors"
                data-testid="footer-cta"
              >
                Create your account
                <ArrowUpRight size={18} weight="bold" />
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-white/10 relative">
        <div className="max-w-7xl mx-auto px-6 py-8 flex items-center justify-between text-[11px] font-mono text-white/40">
          <span>© DECISION.ENGINE / 2026</span>
          <span>BUILT WITH LANGGRAPH · FASTAPI · MONGODB · REACT</span>
        </div>
      </footer>
    </div>
  );
}
