'use client';

import { useState } from 'react';

interface ConductSuggestionsProps {
  pacienteId: string;
  onSendWhatsApp: (texto: string) => void;
}

export default function ConductSuggestions({ pacienteId, onSendWhatsApp }: ConductSuggestionsProps) {
  const [sugestao, setSugestao] = useState('');
  const [editando, setEditando] = useState(false);
  const [textoEditado, setTextoEditado] = useState('');
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState('');
  const [provider, setProvider] = useState('');

  const gerarSugestao = async () => {
    setLoading(true);
    setErro('');
    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paciente_id: pacienteId }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || 'Erro ao gerar sugestão');
      }

      const data = await res.json();
      setSugestao(data.sugestao);
      setTextoEditado(data.sugestao);
      setProvider(data.provider);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Erro desconhecido';
      setErro(message);
    } finally {
      setLoading(false);
    }
  };

  const handleEnviar = () => {
    const texto = editando ? textoEditado : sugestao;
    onSendWhatsApp(texto);
  };

  return (
    <div className="bg-[var(--bg-card)] rounded-xl border border-[var(--border-color)] p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          Sugestão de Conduta (IA)
        </h3>
        {provider && (
          <span className="px-2 py-0.5 text-xs rounded-full bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300">
            {provider}
          </span>
        )}
      </div>

      {!sugestao && !loading && (
        <div className="text-center py-6">
          <svg className="w-12 h-12 mx-auto text-[var(--text-secondary)] mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
          <p className="text-sm text-[var(--text-secondary)] mb-4">
            Clique para gerar uma sugestão de conduta baseada nos dados do paciente e na tabela TACO
          </p>
          <button
            onClick={gerarSugestao}
            className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-sm font-medium transition-colors"
          >
            Gerar Sugestão com IA
          </button>
        </div>
      )}

      {loading && (
        <div className="py-8 text-center">
          <svg className="animate-spin w-8 h-8 mx-auto text-primary-500 mb-3" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <p className="text-sm text-[var(--text-secondary)]">Analisando dados do paciente...</p>
        </div>
      )}

      {erro && (
        <div className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 mb-4">
          <p className="text-sm text-red-600 dark:text-red-400">{erro}</p>
          <button
            onClick={gerarSugestao}
            className="mt-2 text-xs text-red-500 underline"
          >
            Tentar novamente
          </button>
        </div>
      )}

      {sugestao && !loading && (
        <div>
          {editando ? (
            <textarea
              value={textoEditado}
              onChange={(e) => setTextoEditado(e.target.value)}
              rows={10}
              className="w-full p-3 rounded-lg border border-[var(--border-color)] bg-[var(--bg-primary)] text-[var(--text-primary)] text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 resize-y"
            />
          ) : (
            <div className="p-4 rounded-lg bg-[var(--bg-secondary)] text-sm text-[var(--text-primary)] whitespace-pre-wrap max-h-64 overflow-y-auto">
              {sugestao}
            </div>
          )}

          <div className="flex flex-wrap gap-2 mt-4">
            <button
              onClick={() => setEditando(!editando)}
              className="px-3 py-1.5 text-sm rounded-lg border border-[var(--border-color)] text-[var(--text-primary)] hover:bg-[var(--bg-secondary)] transition-colors"
            >
              {editando ? 'Visualizar' : 'Editar'}
            </button>
            <button
              onClick={gerarSugestao}
              className="px-3 py-1.5 text-sm rounded-lg border border-[var(--border-color)] text-[var(--text-primary)] hover:bg-[var(--bg-secondary)] transition-colors"
            >
              Regenerar
            </button>
            <button
              onClick={handleEnviar}
              className="px-4 py-1.5 text-sm rounded-lg bg-green-600 hover:bg-green-700 text-white font-medium transition-colors flex items-center gap-1.5"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z" />
              </svg>
              Enviar via WhatsApp
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
