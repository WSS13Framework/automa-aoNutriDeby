"use client";

import { useState, useEffect, useCallback } from "react";

// ── Tipos ────────────────────────────────────────────────────────────────────

type CredStatus = "idle" | "validating" | "valid" | "error";
type SyncStatus = "queued" | "running" | "done" | "failed" | null;

interface SyncState {
  jobId: string;
  status: SyncStatus;
  patientsSync: number;
  startedAt: string | null;
  error: string | null;
}

// ── Componente: passo numerado ────────────────────────────────────────────────

function Step({
  n, title, children,
}: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-4">
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-brand-500 text-white text-sm font-bold flex items-center justify-center shadow-md shadow-brand-500/30">
        {n}
      </div>
      <div className="flex-1 pb-6 border-b border-gray-100 last:border-0">
        <p className="font-semibold text-gray-800 mb-1">{title}</p>
        <div className="text-sm text-gray-500 leading-relaxed">{children}</div>
      </div>
    </div>
  );
}

// ── Componente: badge de status ───────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    valid:    { label: "Ativo",    cls: "bg-green-100 text-green-700 border-green-200" },
    expired:  { label: "Expirado", cls: "bg-red-100 text-red-700 border-red-200" },
    invalid:  { label: "Inválido", cls: "bg-red-100 text-red-700 border-red-200" },
    pending:  { label: "Pendente", cls: "bg-yellow-100 text-yellow-700 border-yellow-200" },
    idle:     { label: "—",        cls: "bg-gray-100 text-gray-500 border-gray-200" },
  };
  const { label, cls } = map[status] ?? map.idle;
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ${cls}`}>
      {label}
    </span>
  );
}

// ── Componente: progresso de sincronização ────────────────────────────────────

function SyncProgress({ sync }: { sync: SyncState }) {
  const steps = [
    { key: "queued",  label: "Na fila" },
    { key: "running", label: "Extraindo pacientes…" },
    { key: "done",    label: "Sincronização completa!" },
  ];
  const idx = steps.findIndex((s) => s.key === sync.status);

  return (
    <div className="mt-6 p-5 bg-brand-50 border border-brand-200 rounded-2xl">
      <p className="text-sm font-semibold text-brand-700 mb-4">
        {sync.status === "done"
          ? `✅ ${sync.patientsSync} pacientes sincronizados com sucesso!`
          : sync.status === "failed"
          ? "❌ Erro na sincronização"
          : "⏳ Importando seus pacientes…"}
      </p>

      {sync.status !== "failed" && (
        <div className="flex items-center gap-2">
          {steps.map((s, i) => (
            <div key={s.key} className="flex items-center gap-2 flex-1">
              <div className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 transition-all duration-500 ${
                i < idx ? "bg-brand-500 text-white" :
                i === idx ? "bg-brand-400 text-white animate-pulse" :
                "bg-gray-200 text-gray-400"
              }`}>
                {i < idx ? "✓" : i + 1}
              </div>
              <span className={`text-xs ${i <= idx ? "text-brand-700 font-medium" : "text-gray-400"}`}>
                {s.label}
              </span>
              {i < steps.length - 1 && (
                <div className={`h-px flex-1 mx-1 transition-all duration-500 ${i < idx ? "bg-brand-400" : "bg-gray-200"}`} />
              )}
            </div>
          ))}
        </div>
      )}

      {sync.status === "done" && (
        <a
          href="/dashboard/pacientes"
          className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-brand-600 hover:text-brand-700"
        >
          Ver meus pacientes →
        </a>
      )}

      {sync.error && (
        <p className="mt-3 text-xs text-red-600">{sync.error}</p>
      )}
    </div>
  );
}

// ── Página principal ──────────────────────────────────────────────────────────

export default function CredenciaisPage() {
  const [token, setToken]           = useState("");
  const [showToken, setShowToken]   = useState(false);
  const [credStatus, setCredStatus] = useState<CredStatus>("idle");
  const [errorMsg, setErrorMsg]     = useState("");
  const [successMsg, setSuccessMsg] = useState("");
  const [sync, setSync]             = useState<SyncState | null>(null);
  const [currentCred, setCurrentCred] = useState<{
    status: string; patientsSync: number; expiresAt: string | null; lastSync: string | null
  } | null>(null);

  // Carrega status atual ao montar
  useEffect(() => {
    fetch("/api/credenciais")
      .then((r) => r.json())
      .then((data: Array<Record<string, unknown>>) => {
        if (data.length > 0) {
          const c = data[0] as Record<string, unknown>;
          setCurrentCred({
            status: String(c.validation_status ?? "pending"),
            patientsSync: Number(c.patients_synced ?? 0),
            expiresAt: c.expires_at ? String(c.expires_at) : null,
            lastSync: c.last_sync_at ? String(c.last_sync_at) : null,
          });
        }
      })
      .catch(() => null);
  }, []);

  // Poll status do job
  const pollJob = useCallback((jobId: string) => {
    const interval = setInterval(async () => {
      const r = await fetch(`/api/credenciais/status/${jobId}`);
      const d = await r.json();
      setSync({
        jobId,
        status: d.status,
        patientsSync: d.patients_synced ?? 0,
        startedAt: d.started_at,
        error: d.error,
      });
      if (d.status === "done" || d.status === "failed") {
        clearInterval(interval);
        if (d.status === "done") {
          setCurrentCred((prev) => ({
            ...(prev ?? { expiresAt: null, lastSync: null }),
            status: "valid",
            patientsSync: d.patients_synced ?? 0,
            lastSync: new Date().toISOString(),
          }));
        }
      }
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setCredStatus("validating");
    setErrorMsg("");
    setSuccessMsg("");
    setSync(null);

    try {
      const res = await fetch("/api/credenciais", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform: "dietbox", bearer_token: token.trim() }),
      });
      const data = await res.json();

      if (!res.ok) {
        setCredStatus("error");
        setErrorMsg(data.detail ?? "Token inválido ou expirado.");
        return;
      }

      setCredStatus("valid");
      setSuccessMsg(data.message);
      setToken("");
      const jobId = data.sync_job_id;
      const initialSync: SyncState = {
        jobId, status: "queued", patientsSync: data.patients_found ?? 0,
        startedAt: null, error: null,
      };
      setSync(initialSync);
      pollJob(jobId);
    } catch {
      setCredStatus("error");
      setErrorMsg("Erro de conexão. Tente novamente.");
    }
  }

  const tokenPreview = token.length > 20
    ? `${token.slice(0, 12)}…${token.slice(-8)}`
    : token;

  return (
    <div className="max-w-3xl mx-auto py-8 px-4 space-y-8">

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Conectar Plataforma</h1>
        <p className="text-gray-500 mt-1 text-sm">
          Conecte seu Dietbox para importar automaticamente seus pacientes, prontuários e exames.
        </p>
      </div>

      {/* Status atual */}
      {currentCred && (
        <div className="bg-white border border-gray-200 rounded-2xl p-5 flex items-center justify-between shadow-sm">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-xl bg-green-50 flex items-center justify-center">
              <svg className="w-5 h-5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            </div>
            <div>
              <p className="font-semibold text-gray-800 text-sm">Dietbox</p>
              <p className="text-xs text-gray-400">
                {currentCred.patientsSync} pacientes · {" "}
                {currentCred.lastSync
                  ? `Última sync: ${new Date(currentCred.lastSync).toLocaleDateString("pt-BR")}`
                  : "Nunca sincronizado"}
              </p>
            </div>
          </div>
          <StatusBadge status={currentCred.status} />
        </div>
      )}

      {/* Guia passo a passo */}
      <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
        <h2 className="text-base font-bold text-gray-800 mb-6 flex items-center gap-2">
          <svg className="w-5 h-5 text-brand-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
          </svg>
          Como obter seu token do Dietbox
        </h2>

        <div className="space-y-5">
          <Step n={1} title="Abra o Dietbox no navegador">
            Acesse{" "}
            <a href="https://dietbox.me" target="_blank" rel="noreferrer"
              className="text-brand-600 font-semibold hover:underline">
              dietbox.me
            </a>{" "}
            e faça login normalmente na sua conta.
          </Step>

          <Step n={2} title="Abra as Ferramentas do Desenvolvedor">
            Pressione{" "}
            <kbd className="px-2 py-0.5 bg-gray-100 border border-gray-300 rounded text-xs font-mono text-gray-700">F12</kbd>
            {" "}(Windows/Linux) ou{" "}
            <kbd className="px-2 py-0.5 bg-gray-100 border border-gray-300 rounded text-xs font-mono text-gray-700">Cmd + Option + I</kbd>
            {" "}(Mac). Uma janela lateral se abrirá.
          </Step>

          <Step n={3} title='Clique na aba "Rede" (Network)'>
            Na janela que abriu, procure a aba chamada{" "}
            <span className="font-mono bg-gray-100 px-1.5 py-0.5 rounded text-xs">Network</span>
            {" "}ou{" "}
            <span className="font-mono bg-gray-100 px-1.5 py-0.5 rounded text-xs">Rede</span>
            . Clique nela.
          </Step>

          <Step n={4} title="Recarregue a página">
            Aperte{" "}
            <kbd className="px-2 py-0.5 bg-gray-100 border border-gray-300 rounded text-xs font-mono text-gray-700">F5</kbd>
            {" "}para recarregar. Você verá uma lista de requisições aparecer.
          </Step>

          <Step n={5} title='Filtre por "api.dietbox"'>
            Na caixa de busca da aba Network, digite{" "}
            <span className="font-mono bg-brand-50 text-brand-700 px-1.5 py-0.5 rounded text-xs font-bold">api.dietbox</span>.
            Clique em qualquer requisição que aparecer.
          </Step>

          <Step n={6} title='Copie o token em "Headers"'>
            <p>No painel direito, clique em <strong>Headers</strong> → <strong>Request Headers</strong>.</p>
            <p className="mt-1">
              Encontre a linha{" "}
              <span className="font-mono bg-gray-100 px-1.5 py-0.5 rounded text-xs">Authorization: Bearer eyJ…</span>
            </p>
            <p className="mt-1">
              Copie <strong>tudo depois de</strong>{" "}
              <span className="font-mono bg-yellow-100 text-yellow-800 px-1.5 py-0.5 rounded text-xs font-bold">Bearer{" "}</span>
              {" "}(o texto longo que começa com <span className="font-mono text-xs">eyJ</span>).
            </p>
            <div className="mt-3 p-3 bg-gray-900 rounded-xl font-mono text-xs text-gray-300 overflow-hidden">
              <span className="text-gray-500">Authorization: Bearer </span>
              <span className="text-green-400">eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9…</span>
              <span className="ml-2 inline-flex items-center gap-1 text-yellow-400">← copie isso</span>
            </div>
          </Step>
        </div>
      </div>

      {/* Formulário do token */}
      <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
        <h2 className="text-base font-bold text-gray-800 mb-4 flex items-center gap-2">
          <svg className="w-5 h-5 text-brand-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
          </svg>
          Cole seu token aqui
        </h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="relative">
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Token Dietbox{" "}
              <span className="text-gray-400 font-normal">(começa com eyJ…)</span>
            </label>
            <div className="relative">
              <textarea
                value={showToken ? token : (token ? tokenPreview : "")}
                onChange={(e) => setToken(showToken ? e.target.value : token)}
                onFocus={() => setShowToken(true)}
                onBlur={() => setShowToken(false)}
                onPaste={(e) => {
                  e.preventDefault();
                  const pasted = e.clipboardData.getData("text").trim();
                  const clean = pasted.replace(/^Bearer\s+/i, "");
                  setToken(clean);
                  setShowToken(false);
                }}
                placeholder="Cole aqui o token copiado do Dietbox…"
                rows={3}
                className="w-full px-4 py-3 border border-gray-300 rounded-xl font-mono text-sm
                           focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none
                           resize-none transition-all duration-200 bg-gray-50 focus:bg-white"
              />
              {token && (
                <button
                  type="button"
                  onClick={() => { setToken(""); setShowToken(false); }}
                  className="absolute top-2 right-2 text-gray-400 hover:text-gray-600 p-1"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              )}
            </div>
            {token && (
              <p className="mt-1.5 text-xs text-brand-600 flex items-center gap-1">
                <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
                Token detectado ({token.length} caracteres)
              </p>
            )}
          </div>

          {/* Feedback de erro */}
          {credStatus === "error" && errorMsg && (
            <div className="p-4 bg-red-50 border border-red-200 rounded-xl flex items-start gap-3">
              <svg className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div>
                <p className="text-sm font-semibold text-red-700">Token inválido</p>
                <p className="text-xs text-red-600 mt-0.5">{errorMsg}</p>
                <p className="text-xs text-red-500 mt-1">
                  Verifique se copiou apenas o texto após "Bearer " (sem espaços extras).
                </p>
              </div>
            </div>
          )}

          {/* Feedback de sucesso */}
          {credStatus === "valid" && successMsg && (
            <div className="p-4 bg-green-50 border border-green-200 rounded-xl flex items-start gap-3">
              <svg className="w-5 h-5 text-green-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <p className="text-sm text-green-700">{successMsg}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={!token || credStatus === "validating"}
            className="w-full py-3 bg-brand-600 text-white font-semibold rounded-xl
                       hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed
                       transition-all duration-200 flex items-center justify-center gap-2
                       shadow-md shadow-brand-500/20 hover:shadow-lg hover:shadow-brand-500/30"
          >
            {credStatus === "validating" ? (
              <>
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Validando token…
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                Conectar e Importar Pacientes
              </>
            )}
          </button>
        </form>

        {/* Progresso de sync */}
        {sync && <SyncProgress sync={sync} />}
      </div>

      {/* Info de segurança */}
      <div className="flex items-start gap-3 p-4 bg-gray-50 border border-gray-200 rounded-xl text-xs text-gray-500">
        <svg className="w-4 h-4 text-gray-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
        </svg>
        <p>
          Seu token é <strong>cifrado com AES-256</strong> antes de ser armazenado e nunca trafega em texto claro.
          Usamos apenas para ler seus pacientes — nunca escrevemos no Dietbox.
          O token pertence à sua conta e pode ser revogado a qualquer momento.
        </p>
      </div>

    </div>
  );
}
