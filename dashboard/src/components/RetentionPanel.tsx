"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

interface AtRiskPatient {
  patient_id: string;
  display_name: string | null;
  risk_level: "yellow" | "red";
  days_without_log: number;
  streak: number;
  last_logged_at: string | null;
}

interface IncentiveState {
  loading: boolean;
  done: boolean;
  message?: string;
}

const RISK_LABELS: Record<string, { label: string; dot: string; row: string }> = {
  yellow: { label: "Atenção", dot: "bg-yellow-400", row: "border-yellow-100 hover:border-yellow-300" },
  red:    { label: "Risco",   dot: "bg-red-500",    row: "border-red-100 hover:border-red-300"       },
};

export default function RetentionPanel() {
  const [patients, setPatients] = useState<AtRiskPatient[]>([]);
  const [loading, setLoading] = useState(true);
  const [incentives, setIncentives] = useState<Record<string, IncentiveState>>({});
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/patients/retention/at-risk")
      .then((r) => r.json())
      .then((data) => setPatients(Array.isArray(data) ? data : []))
      .catch(() => setPatients([]))
      .finally(() => setLoading(false));
  }, []);

  async function sendIncentive(patientId: string) {
    setIncentives((prev) => ({ ...prev, [patientId]: { loading: true, done: false } }));
    try {
      const res = await fetch(`/api/patients/${patientId}/send-incentive`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json();
      setIncentives((prev) => ({
        ...prev,
        [patientId]: { loading: false, done: true, message: data.message },
      }));
      setExpanded(patientId);
    } catch {
      setIncentives((prev) => ({
        ...prev,
        [patientId]: { loading: false, done: false },
      }));
    }
  }

  if (loading) return <p className="text-sm text-gray-400 animate-pulse">Verificando pacientes em risco…</p>;
  if (patients.length === 0) return (
    <div className="flex items-center gap-2 text-sm text-green-600">
      <span className="w-2 h-2 rounded-full bg-green-400 inline-block" />
      Todos os pacientes registraram nos últimos 2 dias.
    </div>
  );

  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-400 mb-3">
        {patients.length} paciente{patients.length > 1 ? "s" : ""} sem registro recente
      </p>
      {patients.map((p) => {
        const risk = RISK_LABELS[p.risk_level] ?? RISK_LABELS.yellow;
        const inc = incentives[p.patient_id];
        return (
          <div
            key={p.patient_id}
            className={`rounded-xl border p-3 transition-all ${risk.row} bg-white`}
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3 min-w-0">
                <span className={`w-2 h-2 rounded-full shrink-0 ${risk.dot}`} />
                <div className="min-w-0">
                  <Link
                    href={`/dashboard/pacientes/${p.patient_id}`}
                    className="text-sm font-medium text-gray-800 hover:text-indigo-600 truncate block"
                  >
                    {p.display_name || "Sem nome"}
                  </Link>
                  <p className="text-[11px] text-gray-400 mt-0.5">
                    {p.days_without_log >= 999
                      ? "Nunca registrou"
                      : `${p.days_without_log} dia${p.days_without_log > 1 ? "s" : ""} sem registro`}
                    {p.streak > 0 && ` · streak: ${p.streak}d`}
                  </p>
                </div>
              </div>
              <button
                onClick={() => sendIncentive(p.patient_id)}
                disabled={inc?.loading || inc?.done}
                className={`shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                  inc?.done
                    ? "bg-green-100 text-green-700"
                    : "bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
                }`}
              >
                {inc?.loading ? "Gerando…" : inc?.done ? "Enviado ✓" : "Enviar incentivo"}
              </button>
            </div>
            {inc?.done && inc.message && expanded === p.patient_id && (
              <div className="mt-2 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-700 italic border border-gray-100">
                "{inc.message}"
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
