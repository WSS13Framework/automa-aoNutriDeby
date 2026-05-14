"use client";

import { useState } from "react";

interface Hit {
  chunk_id: string;
  document_id: string | null;
  chunk_index: number;
  distance: number;
  score: number;
  text: string;
}

interface RetrieveResult {
  query: string;
  embedding_model: string;
  hits: Hit[];
  embedding_cache_hit: boolean;
}

export default function RagSearch({ patientId }: { patientId: string }) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<RetrieveResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError("");
    setResult(null);

    try {
      const res = await fetch(`/api/patients/${patientId}/retrieve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, k: 5 }),
      });
      if (!res.ok) throw new Error(`Erro ${res.status}`);
      const data = await res.json();
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Erro na busca");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <form onSubmit={handleSearch} className="flex gap-2 mb-4">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ex: Qual o plano alimentar atual?"
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-500 outline-none"
        />
        <button
          type="submit"
          disabled={loading}
          className="px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 disabled:opacity-50 transition"
        >
          {loading ? "Buscando..." : "Buscar"}
        </button>
      </form>

      {error && <p className="text-red-600 text-sm mb-2">{error}</p>}

      {result && (
        <div>
          <p className="text-xs text-gray-400 mb-3">
            Modelo: {result.embedding_model} | Cache: {result.embedding_cache_hit ? "Sim" : "Não"} | {result.hits.length} resultado(s)
          </p>
          {result.hits.length === 0 ? (
            <p className="text-gray-400 text-sm">Nenhum resultado encontrado.</p>
          ) : (
            <div className="space-y-3">
              {result.hits.map((hit) => (
                <div key={hit.chunk_id} className="border border-gray-100 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-xs font-medium bg-blue-100 text-blue-700 px-2 py-0.5 rounded">
                      Score: {(hit.score * 100).toFixed(1)}%
                    </span>
                    <span className="text-xs text-gray-400">Chunk #{hit.chunk_index}</span>
                  </div>
                  <p className="text-sm text-gray-700 whitespace-pre-wrap">{hit.text}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
