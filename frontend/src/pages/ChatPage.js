import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Plus,
  PaperPlaneRight,
  ChartBar,
  SignOut,
  Lightning,
  Trash,
  CaretRight,
  CaretDown,
  Sparkle
} from '@phosphor-icons/react';
import { api, formatApiErrorDetail } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import AgentTracePanel from '../components/AgentTracePanel';

export default function ChatPage() {
  const { threadId } = useParams();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [threads, setThreads] = useState([]);
  const [messages, setMessages] = useState([]);
  const [activeThread, setActiveThread] = useState(null);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [openTraceIndex, setOpenTraceIndex] = useState(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    loadThreads();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (threadId) loadThread(threadId);
    else {
      setMessages([]);
      setActiveThread(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, busy]);

  async function loadThreads() {
    try {
      const { data } = await api.get('/threads');
      setThreads(data.threads || []);
    } catch (e) {
      // ignore
    }
  }

  async function loadThread(id) {
    try {
      const { data } = await api.get(`/threads/${id}`);
      setActiveThread(data.thread);
      setMessages(data.messages || []);
      setOpenTraceIndex(null);
    } catch (e) {
      navigate('/app', { replace: true });
    }
  }

  async function deleteThread(id, e) {
    e.preventDefault();
    e.stopPropagation();
    if (!window.confirm('Delete this thread? This cannot be undone.')) return;
    try {
      await api.delete(`/threads/${id}`);
      if (threadId === id) navigate('/app');
      loadThreads();
    } catch (err) {
      // noop
    }
  }

  async function submit(e) {
    e.preventDefault();
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setError('');

    // optimistic user message
    const optimistic = {
      message_id: `tmp-${Date.now()}`,
      role: 'user',
      content: q,
      created_at: new Date().toISOString()
    };
    setMessages((m) => [...m, optimistic]);
    setQuestion('');

    try {
      const { data } = await api.post('/ask', { question: q, thread_id: threadId || null });
      setMessages((m) => [...m, data.message]);
      if (!threadId) {
        navigate(`/app/t/${data.thread_id}`, { replace: true });
      }
      loadThreads();
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
      setMessages((m) => m.filter((x) => x.message_id !== optimistic.message_id));
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout() {
    await logout();
    navigate('/login', { replace: true });
  }

  return (
    <div className="h-screen flex bg-obsidian text-white">
      {/* Sidebar */}
      <aside className="hidden md:flex w-72 flex-col border-r border-white/10 bg-obsidian" data-testid="thread-sidebar">
        <div className="px-5 py-5 border-b border-white/10 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2" data-testid="sidebar-logo">
            <span className="w-2.5 h-2.5 bg-white animate-pulse-glow" aria-hidden />
            <span className="font-mono text-[10px] tracking-[0.3em]">DECISION.ENGINE</span>
          </Link>
        </div>

        <div className="px-3 py-3">
          <button
            onClick={() => navigate('/app')}
            className="w-full flex items-center justify-center gap-2 border border-white/15 px-3 py-2 text-xs tracking-wider uppercase font-bold hover:bg-white hover:text-obsidian transition-colors"
            data-testid="new-thread-btn"
          >
            <Plus size={14} weight="bold" />
            New conversation
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-2 pb-4">
          <div className="label-eyebrow px-3 py-2">/ threads</div>
          {threads.length === 0 && (
            <div className="px-3 py-2 text-xs text-white/40">No conversations yet.</div>
          )}
          {threads.map((t) => {
            const active = t.thread_id === threadId;
            return (
              <Link
                key={t.thread_id}
                to={`/app/t/${t.thread_id}`}
                className={`group flex items-center justify-between gap-2 px-3 py-2 mb-px text-sm transition-colors ${
                  active ? 'bg-white text-obsidian' : 'text-white/80 hover:bg-white/5'
                }`}
                data-testid={`thread-item-${t.thread_id}`}
              >
                <span className="truncate" title={t.title}>{t.title}</span>
                <button
                  onClick={(e) => deleteThread(t.thread_id, e)}
                  className={`opacity-0 group-hover:opacity-100 transition-opacity ${
                    active ? 'text-obsidian/60 hover:text-obsidian' : 'text-white/40 hover:text-white'
                  }`}
                  data-testid={`delete-thread-${t.thread_id}`}
                  aria-label="Delete thread"
                >
                  <Trash size={14} />
                </button>
              </Link>
            );
          })}
        </div>

        <div className="border-t border-white/10 px-3 py-3 flex flex-col gap-1">
          <Link
            to="/dashboard"
            className="flex items-center gap-2 px-3 py-2 text-xs tracking-wider uppercase font-bold text-white/70 hover:bg-white/5 hover:text-white transition-colors"
            data-testid="sidebar-dashboard-link"
          >
            <ChartBar size={14} weight="bold" />
            Stats dashboard
          </Link>
          <button
            onClick={handleLogout}
            className="flex items-center gap-2 px-3 py-2 text-xs tracking-wider uppercase font-bold text-white/70 hover:bg-white/5 hover:text-white transition-colors"
            data-testid="logout-btn"
          >
            <SignOut size={14} weight="bold" />
            Sign out
          </button>
          {user && (
            <div className="px-3 py-2 text-[10px] font-mono text-white/40 truncate" data-testid="sidebar-user-email">
              {user.email}
            </div>
          )}
        </div>
      </aside>

      {/* Main chat */}
      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-14 border-b border-white/10 px-6 flex items-center justify-between">
          <div className="font-mono text-[11px] tracking-[0.25em] text-white/60 truncate">
            {activeThread ? activeThread.title : 'NEW CONVERSATION'}
          </div>
          <div className="hidden md:flex items-center gap-2 text-[10px] font-mono text-white/40">
            <span className="w-1.5 h-1.5 bg-agent-web animate-pulse-glow" aria-hidden />
            ENGINE READY · 4 AGENTS
          </div>
        </header>

        <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-6">
          <div className="max-w-3xl mx-auto space-y-6">
            {messages.length === 0 && !busy && (
              <EmptyState onPick={setQuestion} />
            )}
            {messages.map((m, idx) => (
              <Message key={m.message_id || idx} msg={m} index={idx} openTraceIndex={openTraceIndex} setOpenTraceIndex={setOpenTraceIndex} />
            ))}
            {busy && <ThinkingIndicator />}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* Composer */}
        <form onSubmit={submit} className="border-t border-white/10 px-4 sm:px-6 py-4">
          <div className="max-w-3xl mx-auto">
            {error && (
              <div className="mb-2 border border-agent-arxiv/40 bg-agent-arxiv/10 text-agent-arxiv px-3 py-2 text-xs font-mono" data-testid="ask-error">
                {error}
              </div>
            )}
            <div className="surface flex items-end gap-2 p-3">
              <textarea
                rows={1}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    submit(e);
                  }
                }}
                placeholder="Ask anything — the engine will route, evaluate and refine…"
                className="flex-1 bg-transparent text-sm leading-relaxed resize-none placeholder:text-white/30 focus:outline-none min-h-[24px] max-h-[160px]"
                data-testid="ask-input"
              />
              <button
                type="submit"
                disabled={busy || !question.trim()}
                className="bg-white text-obsidian px-3 py-2 hover:bg-white/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                data-testid="ask-submit-btn"
                aria-label="Send"
              >
                <PaperPlaneRight size={16} weight="bold" />
              </button>
            </div>
            <div className="mt-2 text-[10px] font-mono text-white/30">
              ENTER to send · SHIFT+ENTER for newline
            </div>
          </div>
        </form>
      </main>
    </div>
  );
}

function EmptyState({ onPick }) {
  const suggestions = [
    'What is Retrieval-Augmented Generation (RAG)?',
    'Explain LangGraph state machines in one paragraph.',
    'Compare BM25 with dense vector retrieval.',
    'How does an LLM-as-judge evaluator work?'
  ];
  return (
    <div className="surface p-8 animate-fade-in-up" data-testid="empty-state">
      <span className="label-eyebrow">/ start here</span>
      <h2 className="mt-3 text-3xl font-bold tracking-tight">Ask the engine.</h2>
      <p className="mt-3 text-sm text-white/60 max-w-xl">
        Four agents will work in parallel — Local retrieval, General LLM, Web (Tavily) and arXiv research. A judge will score them, then a refiner will synthesize a single answer.
      </p>
      <div className="mt-6 grid sm:grid-cols-2 gap-px bg-white/10">
        {suggestions.map((s) => (
          <button
            key={s}
            onClick={() => onPick(s)}
            className="bg-obsidian px-4 py-3 text-left text-sm text-white/80 hover:bg-surface-2 hover:text-white transition-colors flex items-start gap-2"
            data-testid={`suggestion-${s.slice(0, 16)}`}
          >
            <Sparkle size={14} weight="duotone" className="mt-0.5 text-white/40" />
            <span>{s}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function ThinkingIndicator() {
  return (
    <div className="font-mono text-[11px] tracking-[0.25em] text-white/50 flex items-center gap-2 animate-fade-in-up" data-testid="thinking-indicator">
      <span className="w-1.5 h-1.5 bg-white animate-pulse" aria-hidden />
      <span>AGENTS WORKING · LOCAL · GENERAL · WEB · ARXIV · JUDGE · REFINER</span>
    </div>
  );
}

function Message({ msg, index, openTraceIndex, setOpenTraceIndex }) {
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end animate-fade-in-up" data-testid={`message-user-${index}`}>
        <div className="bg-white/10 px-4 py-3 max-w-[80%] text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</div>
      </div>
    );
  }

  const isTraceOpen = openTraceIndex === index;
  return (
    <div className="animate-fade-in-up" data-testid={`message-assistant-${index}`}>
      <div className="flex items-center gap-2 mb-2">
        <Lightning size={14} weight="fill" className="text-white" />
        <span className="font-mono text-[10px] tracking-[0.25em] text-white/50">ENGINE</span>
        {msg.cache_hit && (
          <span
            className="inline-flex items-center gap-1.5 ml-2 text-[10px] font-mono tracking-wider px-2 py-0.5 border border-cache/40 bg-cache/10 text-cache"
            data-testid={`cache-hit-badge-${index}`}
            title={`Matched: "${msg.cached_question}" (sim ${(msg.cache_similarity * 100).toFixed(1)}%)`}
          >
            <span
              className="w-1.5 h-1.5 bg-cache animate-pulse-glow"
              style={{ boxShadow: '0 0 8px rgba(50,173,230,0.6)' }}
              aria-hidden
            />
            CACHE HIT · {(msg.cache_similarity * 100).toFixed(0)}%
          </span>
        )}
        {!msg.cache_hit && typeof msg.elapsed_ms === 'number' && (
          <span className="text-[10px] font-mono text-white/40 ml-2">
            {(msg.elapsed_ms / 1000).toFixed(1)}s
          </span>
        )}
      </div>
      <div className="text-sm leading-relaxed whitespace-pre-wrap text-white/90">{msg.content}</div>

      {!msg.cache_hit && Array.isArray(msg.traces) && msg.traces.length > 0 && (
        <div className="mt-4">
          <button
            onClick={() => setOpenTraceIndex(isTraceOpen ? null : index)}
            className="flex items-center gap-2 text-[10px] font-mono tracking-[0.25em] uppercase text-white/50 hover:text-white transition-colors"
            data-testid={`toggle-trace-${index}`}
          >
            {isTraceOpen ? <CaretDown size={12} weight="bold" /> : <CaretRight size={12} weight="bold" />}
            Agent trace · scores [{(msg.scores || []).map((s) => s.toFixed(1)).join(' · ')}]
          </button>
          {isTraceOpen && (
            <AgentTracePanel traces={msg.traces} scores={msg.scores || []} bestIndex={msg.best_index} />
          )}
        </div>
      )}
    </div>
  );
}
