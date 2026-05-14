'use client';

import type { MetaNutricional } from '@/types/patient';

interface GoalsCardProps {
  metas: MetaNutricional[];
}

function getProgressColor(progresso: number): string {
  if (progresso >= 80) return 'bg-green-500';
  if (progresso >= 50) return 'bg-yellow-500';
  if (progresso >= 25) return 'bg-orange-500';
  return 'bg-red-500';
}

export default function GoalsCard({ metas }: GoalsCardProps) {
  if (metas.length === 0) {
    return (
      <div className="bg-[var(--bg-card)] rounded-xl border border-[var(--border-color)] p-6">
        <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-4">
          Metas Nutricionais
        </h3>
        <p className="text-sm text-[var(--text-secondary)] text-center py-4">
          Nenhuma meta definida ainda
        </p>
      </div>
    );
  }

  return (
    <div className="bg-[var(--bg-card)] rounded-xl border border-[var(--border-color)] p-6">
      <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-4">
        Metas Nutricionais
      </h3>
      <div className="space-y-4">
        {metas.map((meta) => (
          <div key={meta.id}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-medium text-[var(--text-primary)]">
                {meta.descricao}
              </span>
              <span className="text-xs text-[var(--text-secondary)]">
                {meta.valor_atual} / {meta.valor_meta} {meta.unidade}
              </span>
            </div>
            <div className="w-full h-2.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${getProgressColor(meta.progresso)}`}
                style={{ width: `${Math.min(meta.progresso, 100)}%` }}
              />
            </div>
            <p className="text-xs text-[var(--text-secondary)] mt-0.5 text-right">
              {meta.progresso.toFixed(0)}%
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
