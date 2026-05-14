'use client';

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import type { EngagementData } from '@/types/patient';

interface EngagementChartProps {
  dados: EngagementData[];
}

export default function EngagementChart({ dados }: EngagementChartProps) {
  const dadosFormatados = dados.map((d) => ({
    ...d,
    dia: new Date(d.dia).toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit' }),
  }));

  return (
    <div className="bg-[var(--bg-card)] rounded-xl border border-[var(--border-color)] p-6">
      <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-4">
        Engajamento (7 dias)
      </h3>

      {dados.length === 0 ? (
        <p className="text-sm text-[var(--text-secondary)] text-center py-8">
          Sem dados de engajamento no período
        </p>
      ) : (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={dadosFormatados} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
              <XAxis
                dataKey="dia"
                tick={{ fontSize: 12, fill: 'var(--text-secondary)' }}
              />
              <YAxis
                tick={{ fontSize: 12, fill: 'var(--text-secondary)' }}
                allowDecimals={false}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'var(--bg-card)',
                  border: '1px solid var(--border-color)',
                  borderRadius: '8px',
                  color: 'var(--text-primary)',
                }}
              />
              <Legend />
              <Bar
                dataKey="mensagens"
                name="Mensagens recebidas"
                fill="#22c55e"
                radius={[4, 4, 0, 0]}
              />
              <Bar
                dataKey="respostas"
                name="Respostas enviadas"
                fill="#3b82f6"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
