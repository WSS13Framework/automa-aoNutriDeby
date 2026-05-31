"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

// ── helpers ───────────────────────────────────────────────────────────────────

function InputField({
  label, type = "text", value, onChange, placeholder, error, hint, icon,
}: {
  label: string; type?: string; value: string;
  onChange: (v: string) => void; placeholder?: string;
  error?: string; hint?: string;
  icon: React.ReactNode;
}) {
  const [show, setShow] = useState(false);
  const isPassword = type === "password";
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1.5">{label}</label>
      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">{icon}</span>
        <input
          type={isPassword && show ? "text" : type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={`w-full pl-10 pr-10 py-2.5 border rounded-xl text-sm outline-none transition-all duration-200
            focus:ring-2 focus:ring-brand-500 focus:border-brand-500 bg-gray-50 focus:bg-white
            ${error ? "border-red-400 focus:ring-red-400" : "border-gray-300"}`}
        />
        {isPassword && (
          <button type="button" onClick={() => setShow((s) => !s)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
            {show
              ? <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 4.411m0 0L21 21" /></svg>
              : <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
            }
          </button>
        )}
      </div>
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
      {hint && !error && <p className="mt-1 text-xs text-gray-400">{hint}</p>}
    </div>
  );
}

function PasswordStrength({ password }: { password: string }) {
  const checks = [
    { label: "8+ caracteres", ok: password.length >= 8 },
    { label: "Letra maiúscula", ok: /[A-Z]/.test(password) },
    { label: "Número", ok: /[0-9]/.test(password) },
  ];
  const score = checks.filter((c) => c.ok).length;
  const colors = ["bg-red-400", "bg-yellow-400", "bg-brand-500"];
  const labels = ["Fraca", "Média", "Forte"];
  if (!password) return null;
  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <div key={i}
            className={`h-1 flex-1 rounded-full transition-all duration-300 ${i < score ? colors[score - 1] : "bg-gray-200"}`}
          />
        ))}
      </div>
      <div className="flex items-center justify-between">
        <div className="flex gap-3">
          {checks.map((c) => (
            <span key={c.label}
              className={`text-xs flex items-center gap-1 ${c.ok ? "text-brand-600" : "text-gray-400"}`}>
              {c.ok
                ? <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>
                : <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" /></svg>
              }
              {c.label}
            </span>
          ))}
        </div>
        {score > 0 && (
          <span className={`text-xs font-semibold ${score === 3 ? "text-brand-600" : score === 2 ? "text-yellow-600" : "text-red-500"}`}>
            {labels[score - 1]}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Página ────────────────────────────────────────────────────────────────────

export default function RegisterPage() {
  const router = useRouter();

  const [name, setName]           = useState("");
  const [email, setEmail]         = useState("");
  const [password, setPassword]   = useState("");
  const [confirm, setConfirm]     = useState("");
  const [crn, setCrn]             = useState("");
  const [agreed, setAgreed]       = useState(false);

  const [errors, setErrors]       = useState<Record<string, string>>({});
  const [loading, setLoading]     = useState(false);
  const [apiError, setApiError]   = useState("");
  const [step, setStep]           = useState<"form" | "success">("form");

  function validate() {
    const e: Record<string, string> = {};
    if (!name.trim() || name.trim().length < 3)   e.name     = "Nome completo obrigatório (mín. 3 caracteres)";
    if (!email.includes("@"))                      e.email    = "Email inválido";
    if (password.length < 8)                       e.password = "Senha precisa ter no mínimo 8 caracteres";
    if (password !== confirm)                      e.confirm  = "Senhas não coincidem";
    if (!agreed)                                   e.agreed   = "Aceite os termos para continuar";
    return e;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const errs = validate();
    setErrors(errs);
    if (Object.keys(errs).length > 0) return;

    setLoading(true);
    setApiError("");

    try {
      const res = await fetch("/api/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), email: email.toLowerCase().trim(), password }),
      });
      const data = await res.json();

      if (!res.ok) {
        if (res.status === 409) {
          setErrors({ email: "Este email já está cadastrado." });
        } else {
          setApiError(data.detail ?? "Erro ao criar conta. Tente novamente.");
        }
        return;
      }

      setStep("success");
    } catch {
      setApiError("Erro de conexão. Tente novamente em instantes.");
    } finally {
      setLoading(false);
    }
  }

  // ── Tela de sucesso ─────────────────────────────────────────────────────────
  if (step === "success") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-brand-50 via-white to-green-50 p-4">
        <div className="w-full max-w-sm bg-white rounded-3xl shadow-xl p-8 text-center space-y-4">
          <div className="w-16 h-16 bg-brand-100 rounded-full flex items-center justify-center mx-auto">
            <svg className="w-8 h-8 text-brand-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-gray-900">Conta criada!</h2>
          <p className="text-sm text-gray-500">
            Bem-vinda ao NutriDeby, <strong>{name.split(" ")[0]}</strong>! 🎉<br />
            Agora conecte seu Dietbox para importar seus pacientes.
          </p>
          <button
            onClick={() => router.push("/login")}
            className="w-full py-2.5 bg-brand-600 text-white font-semibold rounded-xl hover:bg-brand-700 transition text-sm shadow-md shadow-brand-500/20"
          >
            Fazer login →
          </button>
        </div>
      </div>
    );
  }

  // ── Formulário ──────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen flex bg-gradient-to-br from-brand-50 via-white to-green-50">

      {/* Painel esquerdo — hero */}
      <div className="hidden lg:flex w-[420px] flex-shrink-0 bg-gray-900 flex-col justify-between p-10 relative overflow-hidden">
        <div className="absolute inset-0 opacity-10"
          style={{ backgroundImage: "radial-gradient(circle at 30% 50%, #22c55e 0%, transparent 60%)" }} />

        <div className="relative z-10">
          <h1 className="text-3xl font-light tracking-tighter text-white">
            Nutri<span className="font-bold text-brand-400">Deby</span>
          </h1>
          <p className="text-xs uppercase tracking-widest text-gray-500 mt-2 font-bold">
            Agente de Execução
          </p>
        </div>

        <div className="relative z-10 space-y-6">
          {[
            { icon: "🤖", title: "IA que trabalha por você", desc: "Reativa pacientes inativos automaticamente com mensagens personalizadas via WhatsApp." },
            { icon: "📊", title: "Seus dados, sua plataforma", desc: "Importamos do Dietbox e colocamos tudo num painel que você controla." },
            { icon: "🔒", title: "100% seguro", desc: "Credenciais cifradas com AES-256. Nunca escrevemos no Dietbox." },
          ].map((f) => (
            <div key={f.title} className="flex gap-4">
              <span className="text-2xl flex-shrink-0 mt-0.5">{f.icon}</span>
              <div>
                <p className="text-sm font-semibold text-white">{f.title}</p>
                <p className="text-xs text-gray-400 mt-0.5 leading-relaxed">{f.desc}</p>
              </div>
            </div>
          ))}
        </div>

        <p className="relative z-10 text-xs text-gray-600">
          Já tem conta?{" "}
          <Link href="/login" className="text-brand-400 font-semibold hover:underline">
            Fazer login →
          </Link>
        </p>
      </div>

      {/* Painel direito — formulário */}
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-md space-y-6">

          {/* Header mobile */}
          <div className="lg:hidden text-center">
            <h1 className="text-2xl font-light tracking-tighter text-gray-900">
              Nutri<span className="font-bold text-brand-600">Deby</span>
            </h1>
          </div>

          <div>
            <h2 className="text-2xl font-bold text-gray-900">Criar sua conta</h2>
            <p className="text-sm text-gray-500 mt-1">
              14 dias grátis · Sem cartão de crédito
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">

            <InputField
              label="Nome completo"
              value={name}
              onChange={setName}
              placeholder="Dra. Maria da Silva"
              error={errors.name}
              icon={<svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" /></svg>}
            />

            <InputField
              label="Email profissional"
              type="email"
              value={email}
              onChange={setEmail}
              placeholder="dra.maria@clinica.com.br"
              error={errors.email}
              icon={<svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>}
            />

            <InputField
              label="CRN (opcional)"
              value={crn}
              onChange={setCrn}
              placeholder="CRN-3 12345"
              hint="Usado para identificação profissional"
              icon={<svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V8a2 2 0 00-2-2h-5m-4 0V5a2 2 0 114 0v1m-4 0a2 2 0 104 0m-5 8a2 2 0 100-4 2 2 0 000 4zm0 0c1.306 0 2.417.835 2.83 2M9 14a3.001 3.001 0 00-2.83 2M15 11h3m-3 4h2" /></svg>}
            />

            <div>
              <InputField
                label="Senha"
                type="password"
                value={password}
                onChange={setPassword}
                placeholder="Mínimo 8 caracteres"
                error={errors.password}
                icon={<svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" /></svg>}
              />
              <PasswordStrength password={password} />
            </div>

            <InputField
              label="Confirmar senha"
              type="password"
              value={confirm}
              onChange={setConfirm}
              placeholder="Repita a senha"
              error={errors.confirm}
              icon={<svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>}
            />

            {/* Checkbox termos */}
            <div className="flex items-start gap-3 pt-1">
              <button
                type="button"
                onClick={() => setAgreed((a) => !a)}
                className={`mt-0.5 w-5 h-5 rounded flex-shrink-0 border-2 flex items-center justify-center transition-all duration-200 ${
                  agreed ? "bg-brand-500 border-brand-500" : "border-gray-300 bg-white"
                }`}
              >
                {agreed && (
                  <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </button>
              <label className="text-xs text-gray-500 leading-relaxed cursor-pointer" onClick={() => setAgreed((a) => !a)}>
                Li e aceito os{" "}
                <span className="text-brand-600 font-semibold hover:underline">Termos de Uso</span>
                {" "}e a{" "}
                <span className="text-brand-600 font-semibold hover:underline">Política de Privacidade</span>
                . Entendo que meus dados de pacientes são tratados em conformidade com a LGPD.
              </label>
            </div>
            {errors.agreed && <p className="text-xs text-red-600 -mt-2">{errors.agreed}</p>}

            {/* Erro da API */}
            {apiError && (
              <div className="p-3 bg-red-50 border border-red-200 rounded-xl flex items-center gap-2 text-sm text-red-700">
                <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                {apiError}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 bg-brand-600 text-white font-bold rounded-xl
                         hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed
                         transition-all duration-200 flex items-center justify-center gap-2
                         shadow-lg shadow-brand-500/25 hover:shadow-xl hover:shadow-brand-500/30
                         text-sm tracking-wide"
            >
              {loading ? (
                <>
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Criando sua conta…
                </>
              ) : (
                "Criar conta grátis →"
              )}
            </button>
          </form>

          <p className="text-center text-xs text-gray-400">
            Já tem conta?{" "}
            <Link href="/login" className="text-brand-600 font-semibold hover:underline">
              Fazer login
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
