import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight } from '@phosphor-icons/react';
import { api, formatApiErrorDetail } from '../lib/api';
import { useAuth } from '../context/AuthContext';

export default function LoginPage() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const { data } = await api.post('/auth/login', { email, password });
      setUser(data);
      navigate('/app', { replace: true });
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-obsidian text-white">
      {/* Visual side */}
      <div className="hidden lg:block relative overflow-hidden border-r border-white/10">
        <img
          src="https://images.pexels.com/photos/30547577/pexels-photo-30547577.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=900&w=900"
          alt="Abstract digital circuits"
          className="absolute inset-0 w-full h-full object-cover opacity-70"
        />
        <div className="absolute inset-0 bg-black/65" />
        <div className="absolute inset-0 pixel-grid opacity-20" aria-hidden />
        <div className="relative z-10 p-12 flex flex-col h-full">
          <Link to="/" className="flex items-center gap-3" data-testid="auth-logo-link">
            <span className="w-3 h-3 bg-white animate-pulse-glow" aria-hidden />
            <span className="font-mono text-xs tracking-[0.3em]">DECISION.ENGINE</span>
          </Link>
          <div className="mt-auto">
            <span className="label-eyebrow">/ welcome back</span>
            <p className="mt-4 text-3xl tracking-tight font-bold max-w-md leading-tight">
              Four agents. One refined answer. Every conversation persists.
            </p>
            <p className="mt-6 font-mono text-[11px] text-white/50 max-w-sm">
              LANGGRAPH · LLM-AS-JUDGE · HYBRID RETRIEVAL · SEMANTIC CACHE
            </p>
          </div>
        </div>
      </div>

      {/* Form side */}
      <div className="flex flex-col justify-center px-8 sm:px-16 py-12">
        <div className="max-w-md w-full mx-auto">
          <Link to="/" className="lg:hidden flex items-center gap-3 mb-10">
            <span className="w-3 h-3 bg-white" aria-hidden />
            <span className="font-mono text-xs tracking-[0.3em]">DECISION.ENGINE</span>
          </Link>

          <span className="label-eyebrow">/ sign in</span>
          <h1 className="mt-3 text-4xl font-bold tracking-tight">Access your engine.</h1>
          <p className="mt-3 text-sm text-white/60">Sign in with your email and password.</p>

          <form onSubmit={submit} className="mt-8 space-y-4" data-testid="login-form">
            <div>
              <label className="label-eyebrow block mb-2" htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full bg-transparent border border-white/15 px-4 py-3 text-sm focus:border-white focus:ring-2 focus:ring-white/40 transition-colors"
                data-testid="login-email-input"
              />
            </div>
            <div>
              <label className="label-eyebrow block mb-2" htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full bg-transparent border border-white/15 px-4 py-3 text-sm focus:border-white focus:ring-2 focus:ring-white/40 transition-colors"
                data-testid="login-password-input"
              />
            </div>

            {error && (
              <div
                className="border border-agent-arxiv/40 bg-agent-arxiv/10 text-agent-arxiv px-3 py-2 text-xs font-mono"
                data-testid="login-error"
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="w-full bg-white text-obsidian py-3 font-bold tracking-wider uppercase text-xs hover:bg-white/90 transition-colors flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
              data-testid="login-submit-btn"
            >
              {busy ? 'Authenticating…' : 'Sign in'}
              {!busy && <ArrowRight size={14} weight="bold" />}
            </button>
          </form>

          <p className="mt-8 text-xs text-white/50">
            Don't have an account?{' '}
            <Link to="/register" className="text-white underline underline-offset-4 hover:text-white/80" data-testid="register-link">
              Create one
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
