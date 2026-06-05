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
  Sparkle,
  Paperclip,
  FilePdf,
  FileText,
  Image as ImageIcon,
  X,
  CircleNotch
} from '@phosphor-icons/react';
import { api, formatApiErrorDetail } from '../lib/api';
import { streamAsk } from '../lib/sse';
import { useAuth } from '../context/AuthContext';
import AgentTracePanel from '../components/AgentTracePanel';
import LivePipeline from '../components/LivePipeline';

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
  const [pipeline, setPipeline] = useState(null); // live streaming state
  const [streamingAnswer, setStreamingAnswer] = useState(''); // accumulated tokens
  const [uploads, setUploads] = useState([]); // attached files for current thread
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const fileInputRef = useRef(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    loadThreads();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (threadId) {
      loadThread(threadId);
      loadUploads(threadId);
    } else {
      setMessages([]);
      setActiveThread(null);
      setUploads([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, busy, streamingAnswer.length, pipeline]);

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

  async function loadUploads(id) {
    try {
      const { data } = await api.get(`/uploads?thread_id=${id}`);
      setUploads(data.files || []);
    } catch (e) {
      setUploads([]);
    }
  }

  async function handleFilePick(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = ''; // reset so same file can be picked again
    if (files.length === 0) return;
    setUploadError('');
    setUploading(true);
    let currentThreadId = threadId || null;
    try {
      for (const f of files) {
        const form = new FormData();
        form.append('file', f);
        if (currentThreadId) form.append('thread_id', currentThreadId);
        const { data } = await api.post('/uploads', form, {
          headers: { 'Content-Type': undefined }
        });
        // If we just created a new thread on first upload, route into it
        if (!currentThreadId) {
          currentThreadId = data.thread_id;
          navigate(`/app/t/${data.thread_id}`, { replace: true });
        }
        setUploads((u) => [...u, data]);
      }
      loadThreads();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setUploadError(formatApiErrorDetail(detail) || err.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  }

  async function removeUpload(fileId) {
    try {
      await api.delete(`/uploads/${fileId}`);
      setUploads((u) => u.filter((f) => f.file_id !== fileId));
    } catch (err) {
      // noop
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
    setStreamingAnswer('');
    setPipeline({
      phase: 'checking cache',
      agents: { local_retrieval: 'pending', general_llm: 'pending', tavily_web: 'pending', arxiv_research: 'pending' },
      scores: null,
      bestIndex: null
    });

    // optimistic user message
    const optimistic = {
      message_id: `tmp-${Date.now()}`,
      role: 'user',
      content: q,
      created_at: new Date().toISOString()
    };
    setMessages((m) => [...m, optimistic]);
    setQuestion('');

    let newThreadId = threadId || null;

    try {
      await streamAsk({
        url: `${process.env.REACT_APP_BACKEND_URL}/api/ask/stream`,
        body: { question: q, thread_id: threadId || null },
        onEvent: ({ event, data }) => {
          if (event === 'thread') {
            newThreadId = data.thread_id;
          } else if (event === 'cache_check') {
            if (data.hit) {
              setPipeline((p) => ({ ...(p || {}), phase: 'cache hit' }));
              setStreamingAnswer(data.answer || '');
            } else {
              setPipeline((p) => ({ ...(p || {}), phase: 'running agents' }));
            }
          } else if (event === 'uploads_used') {
            setPipeline((p) => ({
              ...(p || {}),
              phase: `grounding · ${data.matched_chunks || 0} chunk${(data.matched_chunks || 0) === 1 ? '' : 's'} from ${data.file_count} file${(data.file_count || 0) === 1 ? '' : 's'}`
            }));
          } else if (event === 'agent_start') {
            setPipeline((p) => ({
              ...(p || {}),
              agents: { ...(p?.agents || {}), [data.name]: 'running' }
            }));
          } else if (event === 'agent_complete') {
            setPipeline((p) => ({
              ...(p || {}),
              agents: { ...(p?.agents || {}), [data.name]: 'done' }
            }));
          } else if (event === 'judge_scores') {
            setPipeline((p) => ({
              ...(p || {}),
              phase: 'refining',
              scores: data.scores,
              bestIndex: data.best_index
            }));
          } else if (event === 'refine_token') {
            setStreamingAnswer((s) => s + (data.delta || ''));
          } else if (event === 'done') {
            // build final assistant message from `done` payload
            const finalMsg = {
              message_id: data.message_id,
              role: 'assistant',
              content: data.final_answer,
              cache_hit: !!data.cache_hit,
              cache_similarity: data.cache_similarity || 0,
              cached_question: data.cached_question || null,
              traces: data.traces || [],
              scores: data.scores || [],
              best_index: typeof data.best_index === 'number' ? data.best_index : -1,
              elapsed_ms: data.elapsed_ms || 0,
              created_at: new Date().toISOString()
            };
            setMessages((m) => [...m, finalMsg]);
            setPipeline(null);
            setStreamingAnswer('');
          } else if (event === 'error') {
            throw new Error(data.message || 'Stream error');
          }
        }
      });

      if (!threadId && newThreadId) {
        navigate(`/app/t/${newThreadId}`, { replace: true });
      }
      loadThreads();
    } catch (err) {
      setError(formatApiErrorDetail(err.message) || 'Stream error');
      setMessages((m) => m.filter((x) => x.message_id !== optimistic.message_id));
      setPipeline(null);
      setStreamingAnswer('');
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
            {busy && (
              <div className="space-y-3 animate-fade-in-up">
                <LivePipeline pipeline={pipeline} />
                {streamingAnswer && (
                  <div data-testid="streaming-answer">
                    <div className="flex items-center gap-2 mb-2">
                      <Lightning size={14} weight="fill" className="text-white" />
                      <span className="font-mono text-[10px] tracking-[0.25em] text-white/50">REFINER · STREAMING</span>
                    </div>
                    <div className="text-sm leading-relaxed whitespace-pre-wrap text-white/90">
                      {streamingAnswer}
                      <span className="inline-block w-1.5 h-3.5 bg-white/80 ml-0.5 align-middle animate-pulse" />
                    </div>
                  </div>
                )}
              </div>
            )}
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
            {uploadError && (
              <div className="mb-2 border border-agent-arxiv/40 bg-agent-arxiv/10 text-agent-arxiv px-3 py-2 text-xs font-mono" data-testid="upload-error">
                {uploadError}
              </div>
            )}
            <AttachmentBar uploads={uploads} onRemove={removeUpload} uploading={uploading} />
            <div className="surface flex items-end gap-2 p-3">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.txt,.md,.csv,.json,.xml,.html,.py,.js,.ts,.png,.jpg,.jpeg,.webp,application/pdf,text/*,image/png,image/jpeg,image/webp"
                onChange={handleFilePick}
                className="hidden"
                data-testid="file-input"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="text-white/60 hover:text-white p-2 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                data-testid="attach-file-btn"
                aria-label="Attach file"
                title="Attach PDF / text / image"
              >
                {uploading
                  ? <CircleNotch size={18} weight="bold" className="animate-spin" />
                  : <Paperclip size={18} weight="bold" />}
              </button>
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
                placeholder={uploads.length > 0 ? "Ask anything about your files — or anything else…" : "Ask anything — the engine will route, evaluate and refine…"}
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
              ENTER to send · SHIFT+ENTER for newline · PDF / TXT / PNG · JPG up to 15MB
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
    'Summarize the attached document for me.',
    'Compare BM25 with dense vector retrieval.',
    'What do you see in the uploaded image?'
  ];
  return (
    <div className="surface p-8 animate-fade-in-up" data-testid="empty-state">
      <span className="label-eyebrow">/ start here</span>
      <h2 className="mt-3 text-3xl font-bold tracking-tight">Ask the engine.</h2>
      <p className="mt-3 text-sm text-white/60 max-w-xl">
        Four agents work in parallel — Local retrieval (KB + your uploads), General LLM, Web (Tavily) and arXiv research. A judge scores them, then a refiner synthesizes the final answer.
      </p>
      <p className="mt-2 text-sm text-white/50 max-w-xl">
        Attach <span className="text-white/80 font-mono text-[11px]">PDFs · text · images</span> via the paperclip — they&apos;ll be parsed, chunked, and grounded into every answer in this thread.
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

function ThinkingIndicator() {  // eslint-disable-line no-unused-vars
  return (
    <div className="font-mono text-[11px] tracking-[0.25em] text-white/50 flex items-center gap-2 animate-fade-in-up">
      <span className="w-1.5 h-1.5 bg-white animate-pulse" aria-hidden />
      <span>AGENTS WORKING</span>
    </div>
  );
}

function fmtSize(bytes) {
  if (!bytes && bytes !== 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function FileIcon({ kind, size = 14 }) {
  if (kind === 'pdf') return <FilePdf size={size} weight="duotone" className="text-agent-arxiv" />;
  if (kind === 'image') return <ImageIcon size={size} weight="duotone" className="text-agent-web" />;
  return <FileText size={size} weight="duotone" className="text-agent-local" />;
}

function AttachmentBar({ uploads, onRemove, uploading }) {
  if (!uploads || uploads.length === 0) {
    if (!uploading) return null;
    return (
      <div className="mb-2 flex items-center gap-2 text-[11px] font-mono text-white/50" data-testid="upload-progress">
        <CircleNotch size={12} weight="bold" className="animate-spin" />
        Processing file…
      </div>
    );
  }
  return (
    <div className="mb-2 flex flex-wrap gap-2" data-testid="attachment-bar">
      {uploads.map((f) => (
        <div
          key={f.file_id}
          className="group flex items-center gap-2 border border-white/15 bg-white/[0.04] px-2.5 py-1.5 text-[11px]"
          data-testid={`attachment-chip-${f.file_id}`}
        >
          <FileIcon kind={f.kind} />
          <span className="font-mono text-white/85 max-w-[180px] truncate" title={f.filename}>{f.filename}</span>
          <span className="font-mono text-white/35 text-[10px]">{fmtSize(f.size)}</span>
          {f.kind === 'image' && (
            <span className="font-mono text-[9px] tracking-wider uppercase text-agent-web/80">vision</span>
          )}
          {typeof f.chunk_count === 'number' && f.chunk_count > 0 && (
            <span className="font-mono text-[9px] tracking-wider uppercase text-white/40">
              {f.chunk_count} chunk{f.chunk_count === 1 ? '' : 's'}
            </span>
          )}
          <button
            onClick={() => onRemove(f.file_id)}
            className="text-white/40 hover:text-white transition-colors ml-1"
            data-testid={`attachment-remove-${f.file_id}`}
            aria-label={`Remove ${f.filename}`}
          >
            <X size={11} weight="bold" />
          </button>
        </div>
      ))}
      {uploading && (
        <div className="flex items-center gap-2 text-[11px] font-mono text-white/50 px-2 py-1.5" data-testid="upload-progress">
          <CircleNotch size={12} weight="bold" className="animate-spin" />
          Processing…
        </div>
      )}
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
