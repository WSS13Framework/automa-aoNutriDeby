"use client";

import { useEffect, useState } from "react";

interface BioRecord {
  id: string;
  created_at: string;
  peso_kg: number;
  imc: number;
  gordura_pct: number;
  massa_muscular_kg: number;
  massa_muscular_pct: number;
  massa_gorda_kg: number;
  massa_magra_kg: number;
  classificacao_gordura: string;
  classificacao_imc: string;
}

interface ComposicaoRecord {
  id: string;
  created_at: string;
  peso_kg: number;
  fonte: string;
  foto_count: number;
  imc: number;
  gordura_pct: number;
  massa_muscular_kg: number;
  massa_muscular_pct: number;
  massa_magra_kg: number;
  classificacao_gordura: string;
  classificacao_imc: string;
  notas_clinicas: string | null;
  gordura_pct_bio: number | null;
  gordura_pct_visao: number | null;
  gordura_intervalo?: { lo: number | null; hi: number | null };
}

function sparkline(points: number[], w: number, h: number) {
  if (points.length < 2) return "";
  const mn = Math.min(...points), mx = Math.max(...points) || mn + 1;
  const xs = (i: number) => (i / (points.length - 1)) * w;
  const ys = (v: number) => h - ((v - mn) / (mx - mn)) * (h - 6) - 3;
  return points.map((v, i) => `${i === 0 ? "M" : "L"}${xs(i).toFixed(1)} ${ys(v).toFixed(1)}`).join(" ");
}

function classColor(label: string) {
  if (label.includes("atlético") || label.includes("bom") || label.includes("normal"))
    return "bg-green-50 text-green-700";
  if (label.includes("aceitável") || label.includes("sobrepeso"))
    return "bg-yellow-50 text-yellow-700";
  return "bg-red-50 text-red-700";
}

export default function ComposicaoSection({ patientId }: { patientId: string }) {
  const [bio, setBio] = useState<BioRecord[]>([]);
  const [comp, setComp] = useState<ComposicaoRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch(`/api/patients/${patientId}/bioimpedancia`).then((r) => r.json()),
      fetch(`/api/patients/${patientId}/composicao`).then((r) => r.json()),
    ])
      .then(([b, c]) => {
        setBio(Array.isArray(b) ? b : []);
        setComp(Array.isArray(c) ? c : []);
      })
      .finally(() => setLoading(false));
  }, [patientId]);

  if (loading)
    return <p className="text-sm text-gray-400 animate-pulse">Carregando avaliação física…</p>;

  // Usa composicao (ML+Visão) se disponível, senão bioimpedancia
  const latest: (ComposicaoRecord & { _tipo: string }) | (BioRecord & { _tipo: string }) | null =
    comp.length > 0
      ? { ...comp[0], _tipo: "composicao" }
      : bio.length > 0
      ? { ...bio[0], _tipo: "bio" }
      : null;

  if (!latest)
    return (
      <p className="text-sm text-gray-400 italic">
        Nenhuma avaliação física registrada ainda.
      </p>
    );

  const isComp = latest._tipo === "composicao";
  const latestComp = isComp ? (latest as ComposicaoRecord & { _tipo: string }) : null;

  // Histórico para sparkline (% gordura ao longo do tempo)
  const history: { date: string; gordura: number; fonte: string }[] = [
    ...comp.map((c) => ({ date: c.created_at, gordura: c.gordura_pct, fonte: c.fonte === "ml_fusao" ? "IA+Foto" : "ML" })),
    ...bio.map((b) => ({ date: b.created_at, gordura: b.gordura_pct, fonte: "Fórmula" })),
  ]
    .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
    .slice(-12);

  const gorduraPoints = history.map((h) => h.gordura);

  return (
    <div className="space-y-4">
      {/* Fonte badge */}
      <div className="flex items-center gap-2">
        {isComp && latestComp?.fonte === "ml_fusao" && (
          <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-indigo-50 text-indigo-600">
            IA + Foto
          </span>
        )}
        {isComp && latestComp?.fonte !== "ml_fusao" && (
          <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-blue-50 text-blue-600">
            Modelo ML
          </span>
        )}
        {!isComp && (
          <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-gray-100 text-gray-500">
            Gallagher / Lee
          </span>
        )}
        <span className="text-xs text-gray-400">
          {new Date(latest.created_at).toLocaleDateString("pt-BR")}
        </span>
      </div>

      {/* Métricas principais */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MetricCard
          label="% Gordura"
          value={`${latest.gordura_pct.toFixed(1)}%`}
          sub={latest.classificacao_gordura}
          subColor={classColor(latest.classificacao_gordura)}
        />
        <MetricCard
          label="% Músculo"
          value={`${latest.massa_muscular_pct.toFixed(1)}%`}
          sub={`${latest.massa_muscular_kg.toFixed(1)} kg`}
        />
        <MetricCard
          label="IMC"
          value={latest.imc.toFixed(1)}
          sub={latest.classificacao_imc}
          subColor={classColor(latest.classificacao_imc)}
        />
        <MetricCard
          label="Massa Magra"
          value={`${latest.massa_magra_kg.toFixed(1)} kg`}
          sub={`Peso: ${latest.peso_kg} kg`}
        />
      </div>

      {/* Detalhe de fusão (só composicao com foto) */}
      {isComp && latestComp?.gordura_pct_bio != null && latestComp?.gordura_pct_visao != null && (
        <div className="rounded-xl border border-indigo-100 bg-indigo-50/40 p-4">
          <p className="text-[10px] font-bold uppercase tracking-wider text-indigo-500 mb-3">
            Fusão IA · Gordura Corporal
          </p>
          <div className="flex items-center gap-6">
            <div className="text-center">
              <p className="text-xs text-gray-500">Modelo ML</p>
              <p className="text-lg font-bold text-gray-800">
                {latestComp.gordura_pct_bio.toFixed(1)}%
              </p>
            </div>
            <div className="flex-1 h-2 rounded-full bg-gray-200 relative">
              <div
                className="absolute inset-y-0 left-0 rounded-full bg-indigo-400"
                style={{ width: `${Math.min(latestComp.gordura_pct_visao, 60) / 60 * 100}%` }}
              />
            </div>
            <div className="text-center">
              <p className="text-xs text-gray-500">Visão IA</p>
              <p className="text-lg font-bold text-gray-800">
                {latestComp.gordura_pct_visao.toFixed(1)}%
              </p>
            </div>
          </div>
          {latestComp.notas_clinicas && (
            <p className="mt-3 text-xs text-indigo-800 font-light leading-relaxed">
              {latestComp.notas_clinicas}
            </p>
          )}
        </div>
      )}

      {/* Sparkline histórico */}
      {gorduraPoints.length > 1 && (
        <div className="rounded-xl border border-gray-100 bg-white p-4">
          <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-3">
            Tendência · % Gordura
          </p>
          <svg viewBox="0 0 280 48" className="w-full" preserveAspectRatio="none">
            <path
              d={sparkline(gorduraPoints, 280, 48)}
              fill="none"
              stroke="#6366f1"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <div className="flex justify-between mt-1">
            <span className="text-[10px] text-gray-400">
              {new Date(history[0].date).toLocaleDateString("pt-BR")}
            </span>
            <span className="text-[10px] text-gray-400">
              {new Date(history[history.length - 1].date).toLocaleDateString("pt-BR")}
            </span>
          </div>
        </div>
      )}

      {/* Histórico tabela */}
      {(bio.length + comp.length) > 1 && (
        <details className="group">
          <summary className="cursor-pointer text-xs text-gray-400 hover:text-gray-600 select-none">
            Ver histórico completo ({bio.length + comp.length} avaliações)
          </summary>
          <div className="mt-3 space-y-2">
            {[...comp.map((c) => ({ ...c, _tipo: "comp" })), ...bio.map((b) => ({ ...b, _tipo: "bio" }))]
              .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
              .map((r) => (
                <div
                  key={`${r._tipo}-${r.id}`}
                  className="flex items-center justify-between text-xs text-gray-600 border-b border-gray-50 pb-2"
                >
                  <span className="text-gray-400">
                    {new Date(r.created_at).toLocaleDateString("pt-BR")}
                    <span className="ml-2 text-[10px] uppercase tracking-wide text-gray-300">
                      {r._tipo === "comp"
                        ? (r as ComposicaoRecord).fonte === "ml_fusao" ? "IA+Foto" : "ML"
                        : "Fórmula"}
                    </span>
                  </span>
                  <div className="flex gap-4">
                    <span>IMC {r.imc.toFixed(1)}</span>
                    <span>Gord. {r.gordura_pct.toFixed(1)}%</span>
                    <span>Musc. {r.massa_muscular_pct.toFixed(1)}%</span>
                    <span className="text-gray-400">{r.peso_kg} kg</span>
                  </div>
                </div>
              ))}
          </div>
        </details>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  sub,
  subColor,
}: {
  label: string;
  value: string;
  sub?: string;
  subColor?: string;
}) {
  return (
    <div className="rounded-xl border border-gray-100 bg-white p-3 shadow-sm">
      <p className="text-[10px] text-gray-400 uppercase tracking-wider">{label}</p>
      <p className="text-xl font-bold text-gray-800 mt-1">{value}</p>
      {sub && (
        <span
          className={`mt-1 inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded ${
            subColor ?? "bg-gray-50 text-gray-500"
          }`}
        >
          {sub}
        </span>
      )}
    </div>
  );
}
