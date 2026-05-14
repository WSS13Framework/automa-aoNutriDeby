"use client";

import { useState, useRef, useCallback } from "react";

type Platform = {
  id: string;
  label: string;
  descricao: string;
  rota: string;
  complexidade: "Baixa" | "Média" | "Alta";
};

const PLATFORMS: Platform[] = [
  { id: "dietbox", label: "Dietbox", descricao: "API REST autenticada", rota: "API", complexidade: "Baixa" },
  { id: "dietsmart", label: "DietSmart", descricao: "Banco Firebird local / CSV", rota: "CSV/DB", complexidade: "Média" },
  { id: "nutrium", label: "Nutrium", descricao: "PDF exportado + OCR", rota: "PDF", complexidade: "Média" },
  { id: "nutricloud", label: "NutriCloud", descricao: "CSV nativo", rota: "CSV", complexidade: "Baixa" },
  { id: "dietsystem", label: "DietSystem", descricao: "CSV / PDF exportado", rota: "CSV", complexidade: "Alta" },
  { id: "generic", label: "Outro / Genérico", descricao: "Qualquer CSV ou XLSX", rota: "CSV/XLSX", complexidade: "Baixa" },
];

type ImportResult = {
  source_platform: string;
  total_recebidos: number;
  inseridos: number;
  atualizados: number;
  ignorados: number;
  erros: string[];
  duracao_ms: number;
};

export default function ImportPacientes() {
  const [platform, setPlatform] = useState<string>("dietbox");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) setFile(dropped);
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) setFile(f);
  };

  const handleSubmit = async () => {
    if (!file) {
      setError("Selecione um arquivo JSON para importar.");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const text = await file.text();
      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(text);
      } catch {
        throw new Error("Arquivo inválido — não é um JSON válido.");
      }

      // Garantir source_platform no payload
      if (!payload.source_platform) {
        payload.source_platform = platform;
      }
      if (!payload.pacientes) {
        throw new Error("JSON inválido — campo 'pacientes' não encontrado.");
      }

      const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8081";
      const apiKey = process.env.NEXT_PUBLIC_API_KEY || "";

      const resp = await fetch(`${apiBase}/api/importar`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(apiKey ? { "X-API-Key": apiKey } : {}),
        },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `Erro HTTP ${resp.status}`);
      }

      const data: ImportResult = await resp.json();
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Erro desconhecido");
    } finally {
      setLoading(false);
    }
  };

  const selectedPlatform = PLATFORMS.find((p) => p.id === platform);
  const complexidadeCor = {
    Baixa: "text-green-600 dark:text-green-400",
    Média: "text-yellow-600 dark:text-yellow-400",
    Alta: "text-red-600 dark:text-red-400",
  };

  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl shadow p-6 space-y-6 max-w-2xl">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">Importar Pacientes</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Importe dados de qualquer plataforma de nutrição para o NutriDeby.
        </p>
      </div>

      {/* Seleção de plataforma */}
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          Plataforma de origem
        </label>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {PLATFORMS.map((p) => (
            <button
              key={p.id}
              onClick={() => setPlatform(p.id)}
              className={`rounded-xl border-2 p-3 text-left transition-all ${
                platform === p.id
                  ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20"
                  : "border-gray-200 dark:border-gray-700 hover:border-emerald-300"
              }`}
            >
              <div className="font-semibold text-sm text-gray-900 dark:text-white">{p.label}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{p.descricao}</div>
              <div className={`text-xs font-medium mt-1 ${complexidadeCor[p.complexidade]}`}>
                {p.complexidade}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Info da plataforma selecionada */}
      {selectedPlatform && (
        <div className="bg-blue-50 dark:bg-blue-900/20 rounded-xl p-3 text-sm text-blue-800 dark:text-blue-300">
          <strong>{selectedPlatform.label}</strong> — Rota: {selectedPlatform.rota} · Complexidade:{" "}
          <span className={complexidadeCor[selectedPlatform.complexidade]}>
            {selectedPlatform.complexidade}
          </span>
          <div className="mt-1 text-xs text-blue-600 dark:text-blue-400">
            Gere o JSON usando{" "}
            <code className="bg-blue-100 dark:bg-blue-800 px-1 rounded">
              scripts/extractors/{selectedPlatform.id}_extractor.py
            </code>{" "}
            e faça upload aqui.
          </div>
        </div>
      )}

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${
          dragging
            ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20"
            : "border-gray-300 dark:border-gray-600 hover:border-emerald-400"
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          className="hidden"
          onChange={handleFileChange}
        />
        {file ? (
          <div className="space-y-1">
            <div className="text-2xl">📄</div>
            <div className="font-medium text-gray-900 dark:text-white">{file.name}</div>
            <div className="text-sm text-gray-500 dark:text-gray-400">
              {(file.size / 1024).toFixed(1)} KB
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); setFile(null); }}
              className="text-xs text-red-500 hover:text-red-700 mt-1"
            >
              Remover
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            <div className="text-3xl">☁️</div>
            <div className="text-gray-600 dark:text-gray-300 font-medium">
              Arraste o JSON aqui ou clique para selecionar
            </div>
            <div className="text-xs text-gray-400 dark:text-gray-500">
              Arquivo .json gerado pelo extrator da plataforma
            </div>
          </div>
        )}
      </div>

      {/* Botão de importar */}
      <button
        onClick={handleSubmit}
        disabled={loading || !file}
        className="w-full bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-300 dark:disabled:bg-gray-700 text-white font-semibold py-3 rounded-xl transition-all flex items-center justify-center gap-2"
      >
        {loading ? (
          <>
            <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
            </svg>
            Importando...
          </>
        ) : (
          "Importar Pacientes"
        )}
      </button>

      {/* Erro */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-4 text-red-700 dark:text-red-300 text-sm">
          <strong>Erro:</strong> {error}
        </div>
      )}

      {/* Resultado */}
      {result && (
        <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-xl p-4 space-y-3">
          <div className="font-semibold text-green-800 dark:text-green-300">
            Importação concluída — {result.source_platform}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: "Recebidos", value: result.total_recebidos, color: "text-gray-700 dark:text-gray-300" },
              { label: "Inseridos", value: result.inseridos, color: "text-green-700 dark:text-green-400" },
              { label: "Atualizados", value: result.atualizados, color: "text-blue-700 dark:text-blue-400" },
              { label: "Ignorados", value: result.ignorados, color: "text-yellow-700 dark:text-yellow-400" },
            ].map((s) => (
              <div key={s.label} className="bg-white dark:bg-gray-800 rounded-lg p-3 text-center shadow-sm">
                <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">{s.label}</div>
              </div>
            ))}
          </div>
          <div className="text-xs text-gray-500 dark:text-gray-400">
            Duração: {result.duracao_ms}ms
          </div>
          {result.erros.length > 0 && (
            <details className="text-sm">
              <summary className="cursor-pointer text-red-600 dark:text-red-400 font-medium">
                {result.erros.length} erro(s) — ver detalhes
              </summary>
              <ul className="mt-2 space-y-1 text-red-600 dark:text-red-400 text-xs">
                {result.erros.map((e, i) => (
                  <li key={i} className="bg-red-50 dark:bg-red-900/20 rounded px-2 py-1">{e}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
