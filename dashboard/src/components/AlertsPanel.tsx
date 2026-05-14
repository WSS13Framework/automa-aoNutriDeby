'use client';

import type { AlertaClinico } from '@/types/patient';

interface AlertsPanelProps {
  alertas: AlertaClinico[];
}

const severidadeConfig = {
  alta: {
    bg: 'bg-red-50 dark:bg-red-900/20',
    border: 'border-red-200 dark:border-red-800',
    icon: 'text-red-500',
    badge: 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300',
  },
  media: {
    bg: 'bg-yellow-50 dark:bg-yellow-900/20',
    border: 'border-yellow-200 dark:border-yellow-800',
    icon: 'text-yellow-500',
    badge: 'bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-300',
  },
  baixa: {
    bg: 'bg-blue-50 dark:bg-blue-900/20',
    border: 'border-blue-200 dark:border-blue-800',
    icon: 'text-blue-500',
    badge: 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300',
  },
};

const tipoLabels: Record<string, string> = {
  sem_resposta: 'Sem resposta',
  exame_alterado: 'Exame alterado',
  meta_atrasada: 'Meta atrasada',
  peso_critico: 'Peso crítico',
};

export default function AlertsPanel({ alertas }: AlertsPanelProps) {
  const alertasNaoLidos = alertas.filter(a => !a.lido);

  return (
    <div className="bg-[var(--bg-card)] rounded-xl border border-[var(--border-color)] p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          Alertas Clínicos
        </h3>
        {alertasNaoLidos.length > 0 && (
          <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300">
            {alertasNaoLidos.length} novo{alertasNaoLidos.length > 1 ? 's' : ''}
          </span>
        )}
      </div>

      {alertas.length === 0 ? (
        <div className="text-center py-6">
          <svg className="w-10 h-10 mx-auto text-green-400 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="text-sm text-[var(--text-secondary)]">Nenhum alerta ativo</p>
        </div>
      ) : (
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {alertas.map((alerta) => {
            const config = severidadeConfig[alerta.severidade];
            return (
              <div
                key={alerta.id}
                className={`p-3 rounded-lg border ${config.bg} ${config.border} ${!alerta.lido ? 'ring-1 ring-offset-1' : 'opacity-75'}`}
              >
                <div className="flex items-start gap-2">
                  <svg className={`w-4 h-4 mt-0.5 flex-shrink-0 ${config.icon}`} fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className={`px-1.5 py-0.5 text-[10px] font-medium rounded ${config.badge}`}>
                        {tipoLabels[alerta.tipo] || alerta.tipo}
                      </span>
                      <span className="text-[10px] text-[var(--text-secondary)]">
                        {new Date(alerta.created_at).toLocaleDateString('pt-BR')}
                      </span>
                    </div>
                    <p className="text-sm text-[var(--text-primary)]">{alerta.mensagem}</p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
