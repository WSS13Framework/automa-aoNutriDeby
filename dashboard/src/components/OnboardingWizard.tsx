"use client";

import { useState, useEffect, useCallback } from "react";

// ─── Types ───────────────────────────────────────────────────────────────────

type Platform = {
  id: string;
  display_name: string;
  rota: string;
  instructions: string;
  icon: string;
};

type DetectResult = {
  platform: string;
  confidence: number;
  display_name: string;
  rota: string;
  instructions: string;
  icon: string;
};

type JobStatus = {
  job_id: string;
  status: string;
  progress: number;
  total_records: number;
  processed: number;
  inserted: number;
  updated: number;
  errors: string[];
  started_at: string | null;
  finished_at: string | null;
  log: string | null;
};

type Step = 1 | 2 | 3;

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8081";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "";

const headers = {
  "Content-Type": "application/json",
  ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
};

// ─── Componente principal ────────────────────────────────────────────────────

export default function OnboardingWizard({
  nutritionistId,
  onComplete,
}: {
  nutritionistId: string;
  onComplete?: (result: JobStatus) => void;
}) {
  const [step, setStep] = useState<Step>(1);
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [searchText, setSearchText] = useState("");
  const [detected, setDetected] = useState<DetectResult | null>(null);
  const [selectedPlatform, setSelectedPlatform] = useState<Platform | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [credentialId, setCredentialId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Carregar plataformas
  useEffect(() => {
    fetch(`${API_BASE}/api/onboarding/platforms`, { headers })
      .then((r) => r.json())
      .then(setPlatforms)
      .catch(() => {});
  }, []);

  // Polling de status do job
  useEffect(() => {
    if (!jobId || jobStatus?.status === "done" || jobStatus?.status === "error") return;
    const interval = setInterval(async () => {
      try {
        const r = await fetch(`${API_BASE}/api/onboarding/status/${jobId}`, { headers });
        if (r.ok) {
          const data: JobStatus = await r.json();
          setJobStatus(data);
          if (data.status === "done") {
            onComplete?.(data);
            clearInterval(interval);
          }
        }
      } catch {}
    }, 3000);
    return () => clearInterval(interval);
  }, [jobId, jobStatus?.status, onComplete]);

  // Detectar plataforma ao digitar
  const handleDetect = useCallback(async (text: string) => {
    if (!text.trim()) { setDetected(null); return; }
    try {
      const r = await fetch(`${API_BASE}/api/onboarding/detect`, {
        method: "POST",
        headers,
        body: JSON.stringify({ text }),
      });
      if (r.ok) {
        const data: DetectResult = await r.json();
        setDetected(data);
        if (data.confidence >= 0.8) {
          const found = platforms.find((p) => p.id === data.platform);
          if (found) setSelectedPlatform(found);
        }
      }
    } catch {}
  }, [platforms]);

  useEffect(() => {
    const t = setTimeout(() => handleDetect(searchText), 400);
    return () => clearTimeout(t);
  }, [searchText, handleDetect]);

  // ── Step 2: Conectar ──────────────────────────────────────────────────────
  const handleConnect = async () => {
    if (!selectedPlatform || !username || !password) {
      setError("Preencha todos os campos.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/api/onboarding/connect`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          nutritionist_id: nutritionistId,
          platform: selectedPlatform.id,
          username,
          password,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || `Erro ${r.status}`);
      setCredentialId(data.credential_id);
      setStep(3);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Erro ao conectar.");
    } finally {
      setLoading(false);
    }
  };

  // ── Step 3: Sincronizar ───────────────────────────────────────────────────
  const handleSync = async () => {
    if (!credentialId) return;
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/api/onboarding/sync`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          nutritionist_id: nutritionistId,
          credential_id: credentialId,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || `Erro ${r.status}`);
      setJobId(data.job_id);
      setJobStatus({ job_id: data.job_id, status: "queued", progress: 0,
        total_records: 0, processed: 0, inserted: 0, updated: 0,
        errors: [], started_at: null, finished_at: null, log: null });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Erro ao iniciar importação.");
    } finally {
      setLoading(false);
    }
  };

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-lg p-6 max-w-xl w-full">
      {/* Header com steps */}
      <div className="flex items-center gap-2 mb-6">
        {([1, 2, 3] as Step[]).map((s) => (
          <div key={s} className="flex items-center gap-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-all ${
              step === s ? "bg-emerald-600 text-white" :
              step > s ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400" :
              "bg-gray-100 text-gray-400 dark:bg-gray-800"
            }`}>{step > s ? "✓" : s}</div>
            {s < 3 && <div className={`h-0.5 w-8 ${step > s ? "bg-emerald-400" : "bg-gray-200 dark:bg-gray-700"}`} />}
          </div>
        ))}
        <div className="ml-2 text-sm text-gray-500 dark:text-gray-400">
          {step === 1 && "Identificar plataforma"}
          {step === 2 && "Conectar conta"}
          {step === 3 && "Importar pacientes"}
        </div>
      </div>

      {/* ── STEP 1: Detectar plataforma ── */}
      {step === 1 && (
        <div className="space-y-4">
          <div>
            <h2 className="text-lg font-bold text-gray-900 dark:text-white">
              De onde vêm seus pacientes?
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              Digite o nome ou URL da plataforma que você usa hoje.
            </p>
          </div>

          <input
            type="text"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Ex: Dietbox, nutrium.com, DietSmart..."
            className="w-full border border-gray-300 dark:border-gray-600 rounded-xl px-4 py-3 text-gray-900 dark:text-white bg-white dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />

          {detected && detected.confidence >= 0.8 && (
            <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-xl p-3 flex items-center gap-3">
              <span className="text-2xl">{detected.icon}</span>
              <div>
                <div className="font-semibold text-emerald-800 dark:text-emerald-300">
                  {detected.display_name} detectado
                </div>
                <div className="text-xs text-emerald-600 dark:text-emerald-400">
                  {detected.instructions}
                </div>
              </div>
            </div>
          )}

          <div className="grid grid-cols-3 gap-2">
            {platforms.map((p) => (
              <button
                key={p.id}
                onClick={() => { setSelectedPlatform(p); setSearchText(p.display_name); }}
                className={`rounded-xl border-2 p-3 text-center transition-all ${
                  selectedPlatform?.id === p.id
                    ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20"
                    : "border-gray-200 dark:border-gray-700 hover:border-emerald-300"
                }`}
              >
                <div className="text-xl">{p.icon}</div>
                <div className="text-xs font-medium text-gray-800 dark:text-gray-200 mt-1">
                  {p.display_name}
                </div>
              </button>
            ))}
          </div>

          <button
            onClick={() => { if (selectedPlatform) setStep(2); }}
            disabled={!selectedPlatform}
            className="w-full bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-300 dark:disabled:bg-gray-700 text-white font-semibold py-3 rounded-xl transition-all"
          >
            Continuar
          </button>
        </div>
      )}

      {/* ── STEP 2: Credenciais ── */}
      {step === 2 && selectedPlatform && (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <span className="text-3xl">{selectedPlatform.icon}</span>
            <div>
              <h2 className="text-lg font-bold text-gray-900 dark:text-white">
                Conectar {selectedPlatform.display_name}
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {selectedPlatform.instructions}
              </p>
            </div>
          </div>

          <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-3 text-xs text-amber-700 dark:text-amber-300">
            Suas credenciais são criptografadas com AES-256 antes de serem armazenadas.
            Nunca são transmitidas em texto puro.
          </div>

          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                E-mail ou usuário
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="seu@email.com"
                autoComplete="username"
                className="w-full border border-gray-300 dark:border-gray-600 rounded-xl px-4 py-3 text-gray-900 dark:text-white bg-white dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Senha
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete="current-password"
                className="w-full border border-gray-300 dark:border-gray-600 rounded-xl px-4 py-3 text-gray-900 dark:text-white bg-white dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
          </div>

          {error && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 rounded-xl p-3 text-sm text-red-700 dark:text-red-300">
              {error}
            </div>
          )}

          <div className="flex gap-3">
            <button
              onClick={() => { setStep(1); setError(null); }}
              className="flex-1 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 font-semibold py-3 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-800 transition-all"
            >
              Voltar
            </button>
            <button
              onClick={handleConnect}
              disabled={loading || !username || !password}
              className="flex-2 flex-grow bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-300 dark:disabled:bg-gray-700 text-white font-semibold py-3 rounded-xl transition-all flex items-center justify-center gap-2"
            >
              {loading ? (
                <><svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/></svg> Conectando...</>
              ) : "Conectar"}
            </button>
          </div>
        </div>
      )}

      {/* ── STEP 3: Importação ── */}
      {step === 3 && (
        <div className="space-y-4">
          <div>
            <h2 className="text-lg font-bold text-gray-900 dark:text-white">
              Importar pacientes
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              {selectedPlatform?.display_name} conectado. Pronto para importar.
            </p>
          </div>

          {!jobId && (
            <>
              {error && (
                <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 rounded-xl p-3 text-sm text-red-700 dark:text-red-300">
                  {error}
                </div>
              )}
              <button
                onClick={handleSync}
                disabled={loading}
                className="w-full bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-300 text-white font-semibold py-3 rounded-xl transition-all flex items-center justify-center gap-2"
              >
                {loading ? (
                  <><svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/></svg> Iniciando...</>
                ) : "Importar agora"}
              </button>
            </>
          )}

          {jobStatus && (
            <div className="space-y-3">
              {/* Barra de progresso */}
              <div className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600 dark:text-gray-400 capitalize">
                    {jobStatus.status === "queued" && "Na fila..."}
                    {jobStatus.status === "running" && "Importando..."}
                    {jobStatus.status === "done" && "Concluído!"}
                    {jobStatus.status === "error" && "Erro na importação"}
                    {jobStatus.status === "queued_db" && "Aguardando worker..."}
                  </span>
                  <span className="font-medium text-gray-800 dark:text-gray-200">
                    {jobStatus.progress}%
                  </span>
                </div>
                <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                  <div
                    className={`h-2 rounded-full transition-all duration-500 ${
                      jobStatus.status === "error" ? "bg-red-500" :
                      jobStatus.status === "done" ? "bg-emerald-500" : "bg-emerald-400"
                    }`}
                    style={{ width: `${jobStatus.progress}%` }}
                  />
                </div>
              </div>

              {/* Métricas */}
              {(jobStatus.inserted > 0 || jobStatus.updated > 0) && (
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { label: "Inseridos", value: jobStatus.inserted, color: "text-green-600 dark:text-green-400" },
                    { label: "Atualizados", value: jobStatus.updated, color: "text-blue-600 dark:text-blue-400" },
                    { label: "Processados", value: jobStatus.processed, color: "text-gray-600 dark:text-gray-400" },
                  ].map((m) => (
                    <div key={m.label} className="bg-gray-50 dark:bg-gray-800 rounded-xl p-3 text-center">
                      <div className={`text-xl font-bold ${m.color}`}>{m.value}</div>
                      <div className="text-xs text-gray-500 dark:text-gray-400">{m.label}</div>
                    </div>
                  ))}
                </div>
              )}

              {jobStatus.status === "done" && (
                <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-xl p-4 text-center">
                  <div className="text-2xl mb-1">✅</div>
                  <div className="font-semibold text-emerald-800 dark:text-emerald-300">
                    Importação concluída!
                  </div>
                  <div className="text-sm text-emerald-600 dark:text-emerald-400 mt-1">
                    {jobStatus.log}
                  </div>
                </div>
              )}

              {jobStatus.errors.length > 0 && (
                <details className="text-sm">
                  <summary className="cursor-pointer text-red-600 dark:text-red-400">
                    {jobStatus.errors.length} erro(s)
                  </summary>
                  <ul className="mt-2 space-y-1 text-xs text-red-600 dark:text-red-400">
                    {jobStatus.errors.slice(0, 10).map((e, i) => (
                      <li key={i} className="bg-red-50 dark:bg-red-900/20 rounded px-2 py-1">{e}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
