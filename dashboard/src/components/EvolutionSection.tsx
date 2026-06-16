"use client";

import { useEffect, useState } from "react";
import type { PatientEvolution } from "@/lib/api";

interface Props {
  patientId: string;
}

function sparklinePath(points: number[], w: number, h: number): string {
  if (points.length === 0) return "";
  const min = Math.min(...points);
  const max = Math.max(...points) || 1;
  const xs = (i: number) => (i / (points.length - 1)) * w;
  const ys = (v: number) => h - ((v - min) / (max - min)) * (h - 4) - 2;
  return points
    .map((v, i) => `${i === 0 ? "M" : "L"} ${xs(i).toFixed(1)} ${ys(v).toFixed(1)}`)
    .join(" ");
}

export default function EvolutionSection({ patientId }: Props) {
  const [data, setData] = useState<PatientEvolution | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/patients/${patientId}/evolution`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => setError("Não foi possível carregar a evolução."))
      .finally(() => setLoading(false));
  }, [patientId]);

  if (loading) return <p className="text-sm text-gray-400 animate-pulse">Carregando evolução…</p>;
  if (error) return <p className="text-sm text-red-500">{error}</p>;
  if (!data) return null;

  const cals = data.weekly_calories.map((w) => w.avg_calories);
  const weeks = data.weekly_calories.map((w) => w.week);

  return (
    <section className="space-y-6">
      {/* Streak + XP */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard label="🔥 Streak" value={`${data.streak}d`} />
        <StatCard label="⚡ XP" value={data.deby_xp.toLocaleString("pt-BR")} />
        <StatCard label="🏅 Nível" value={`Lv ${data.deby_level}`} />
      </div>

      {/* Gráfico semanal de calorias */}
      {cals.length > 1 && (
        <div className="rounded-xl border border-gray-100 bg-white p-4 shadow-sm">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Média diária de calorias (por semana)
          </p>
          <svg viewBox={`0 0 320 64`} className="w-full" preserveAspectRatio="none">
            <path
              d={sparklinePath(cals, 320, 64)}
              fill="none"
              stroke="#6366f1"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <div className="mt-1 flex justify-between">
            {weeks.slice(0, 6).map((w) => (
              <span key={w} className="text-[10px] text-gray-400">
                {w.split("-W")[1] ? `S${w.split("-W")[1]}` : w}
              </span>
            ))}
          </div>
          {data.calories_target && (
            <p className="mt-2 text-xs text-gray-400">
              Meta: <span className="font-medium text-gray-700">{data.calories_target} kcal/dia</span>
            </p>
          )}
        </div>
      )}

      {/* Body Scans */}
      {data.body_scans.length > 0 && (
        <div className="rounded-xl border border-gray-100 bg-white p-4 shadow-sm">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Avaliações corporais (IA)
          </p>
          <div className="space-y-3">
            {data.body_scans.map((scan) => (
              <div key={scan.id} className="flex items-start justify-between gap-2 border-b border-gray-50 pb-3 last:border-0 last:pb-0">
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] text-gray-400">{new Date(scan.created_at).toLocaleDateString("pt-BR")}</p>
                  {scan.analysis_notes && (
                    <p className="mt-1 text-xs text-gray-600 line-clamp-2">{scan.analysis_notes}</p>
                  )}
                </div>
                <div className="flex gap-3 shrink-0 text-right">
                  {scan.body_fat_pct != null && (
                    <Metric label="% Gordura" value={`${scan.body_fat_pct.toFixed(1)}%`} />
                  )}
                  {scan.muscle_mass_pct != null && (
                    <Metric label="% Músculo" value={`${scan.muscle_mass_pct.toFixed(1)}%`} />
                  )}
                  {scan.lean_mass_kg != null && (
                    <Metric label="Massa Magra" value={`${scan.lean_mass_kg.toFixed(1)}kg`} />
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Medidas Dietbox */}
      {data.medidas.length > 0 && (
        <div className="rounded-xl border border-gray-100 bg-white p-4 shadow-sm">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Medidas (Dietbox)
          </p>
          <div className="space-y-2">
            {data.medidas.map((m, i) => (
              <div key={i} className="flex items-center justify-between text-sm">
                <span className="text-gray-600">
                  {m.data ? new Date(m.data).toLocaleDateString("pt-BR") : "—"}
                  {m.descricao && ` · ${m.descricao}`}
                </span>
                <span className="font-medium text-gray-800">
                  {m.peso_kg != null ? `${m.peso_kg} kg` : ""}
                  {m.imc != null ? ` · IMC ${m.imc}` : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-gray-100 bg-white p-3 text-center shadow-sm">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-1 text-lg font-bold text-gray-800">{value}</p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-right">
      <p className="text-[10px] text-gray-400">{label}</p>
      <p className="text-sm font-semibold text-gray-800">{value}</p>
    </div>
  );
}
