'use client';

import { useState } from 'react';

interface VideoCallProps {
  pacienteId: string;
  pacienteNome: string;
}

export default function VideoCall({ pacienteId, pacienteNome }: VideoCallProps) {
  const [link, setLink] = useState('');
  const [provider, setProvider] = useState<'google_meet' | 'zoom'>('google_meet');
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState('');
  const [chamadaAtiva, setChamadaAtiva] = useState(false);

  const iniciarConsulta = async () => {
    setLoading(true);
    setErro('');
    try {
      const res = await fetch('/api/consulta/iniciar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paciente_id: pacienteId, provider }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || 'Erro ao iniciar consulta');
      }

      const data = await res.json();
      setLink(data.link);
      setChamadaAtiva(true);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Erro desconhecido';
      setErro(message);
    } finally {
      setLoading(false);
    }
  };

  const encerrarChamada = () => {
    setChamadaAtiva(false);
    setLink('');
  };

  return (
    <div className="bg-[var(--bg-card)] rounded-xl border border-[var(--border-color)] p-6">
      <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-4">
        Videochamada
      </h3>

      {!chamadaAtiva ? (
        <div>
          <p className="text-sm text-[var(--text-secondary)] mb-4">
            Inicie uma consulta por vídeo com <strong>{pacienteNome}</strong>. O link será enviado automaticamente via WhatsApp.
          </p>

          <div className="flex items-center gap-3 mb-4">
            <label className="text-sm text-[var(--text-primary)]">Plataforma:</label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value as 'google_meet' | 'zoom')}
              className="px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--bg-primary)] text-[var(--text-primary)] text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              <option value="google_meet">Google Meet</option>
              <option value="zoom">Zoom</option>
            </select>
          </div>

          {erro && (
            <div className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 mb-4">
              <p className="text-sm text-red-600 dark:text-red-400">{erro}</p>
            </div>
          )}

          <button
            onClick={iniciarConsulta}
            disabled={loading}
            className="w-full sm:w-auto px-6 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Iniciando...
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                Iniciar Consulta
              </>
            )}
          </button>
        </div>
      ) : (
        <div>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
              <span className="text-sm font-medium text-green-600 dark:text-green-400">Chamada ativa</span>
            </div>
            <button
              onClick={encerrarChamada}
              className="px-3 py-1 text-sm rounded-lg bg-red-600 hover:bg-red-700 text-white transition-colors"
            >
              Encerrar
            </button>
          </div>

          {/* Iframe da videochamada */}
          <div className="relative w-full rounded-lg overflow-hidden bg-gray-900" style={{ paddingBottom: '56.25%' }}>
            <iframe
              src={link}
              className="absolute inset-0 w-full h-full"
              allow="camera; microphone; fullscreen; display-capture"
              sandbox="allow-same-origin allow-scripts allow-popups allow-forms"
            />
          </div>

          <div className="mt-3 flex items-center gap-2">
            <input
              type="text"
              value={link}
              readOnly
              className="flex-1 px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] text-[var(--text-secondary)] text-xs"
            />
            <button
              onClick={() => navigator.clipboard.writeText(link)}
              className="px-3 py-1.5 text-xs rounded-lg border border-[var(--border-color)] text-[var(--text-primary)] hover:bg-[var(--bg-secondary)] transition-colors"
            >
              Copiar link
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
