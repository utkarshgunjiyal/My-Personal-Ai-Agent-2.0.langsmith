import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../context/AuthContext';

export default function AuthCallback() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const hasProcessed = useRef(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;

    const hash = window.location.hash || '';
    const m = hash.match(/session_id=([^&]+)/);
    const sessionId = m ? decodeURIComponent(m[1]) : null;

    if (!sessionId) {
      setError('Missing session id. Please try signing in again.');
      return;
    }

    (async () => {
      try {
        const { data } = await api.post('/auth/google/session', { session_id: sessionId });
        setUser(data);
        // Clean fragment
        window.history.replaceState(null, '', '/app');
        navigate('/app', { replace: true });
      } catch (e) {
        setError('Authentication failed. Please try again.');
      }
    })();
  }, [navigate, setUser]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-obsidian text-white" data-testid="auth-callback-screen">
      <div className="text-center">
        <div className="font-mono text-[11px] tracking-[0.3em] text-white/40 mb-4">SESSION HANDSHAKE</div>
        {error ? (
          <p className="text-agent-arxiv font-mono text-sm" data-testid="auth-callback-error">{error}</p>
        ) : (
          <div className="flex items-center gap-3 justify-center">
            <span className="w-2 h-2 bg-white animate-pulse" aria-hidden />
            <span className="text-sm tracking-wider uppercase">Finalizing sign-in…</span>
          </div>
        )}
      </div>
    </div>
  );
}
