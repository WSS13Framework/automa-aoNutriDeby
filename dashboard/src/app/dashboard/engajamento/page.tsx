import { getRagCoverage, type RagCoverage } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function EngajamentoPage() {
  let coverage: RagCoverage[] = [];
  let error = "";

  try {
    coverage = await getRagCoverage(200);
  } catch (e: unknown) {
    error = e instanceof Error ? e.message : "Erro ao carregar dados";
  }

  const totalPacientes = coverage.length;
  const comEmbeddings = coverage.filter((c) => c.usable_embedded_chunks > 0).length;
  const semEmbeddings = totalPacientes - comEmbeddings;
  const totalChunks = coverage.reduce((acc, c) => acc + c.chunks_total, 0);
  const totalEmbedded = coverage.reduce((acc, c) => acc + c.usable_embedded_chunks, 0);

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Engajamento e Cobertura RAG</h1>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-4">
          <p className="text-sm">{error}</p>
        </div>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <div className="bg-white rounded-xl shadow p-5 text-center">
          <p className="text-xs text-gray-500 uppercase tracking-wide">Total Pacientes</p>
          <p className="text-3xl font-bold text-gray-800 mt-2">{totalPacientes}</p>
        </div>
        <div className="bg-white rounded-xl shadow p-5 text-center">
          <p className="text-xs text-gray-500 uppercase tracking-wide">Com Embeddings</p>
          <p className="text-3xl font-bold text-green-600 mt-2">{comEmbeddings}</p>
        </div>
        <div className="bg-white rounded-xl shadow p-5 text-center">
          <p className="text-xs text-gray-500 uppercase tracking-wide">Sem Embeddings</p>
          <p className="text-3xl font-bold text-red-500 mt-2">{semEmbeddings}</p>
        </div>
        <div className="bg-white rounded-xl shadow p-5 text-center">
          <p className="text-xs text-gray-500 uppercase tracking-wide">Chunks Indexados</p>
          <p className="text-3xl font-bold text-blue-600 mt-2">{totalEmbedded}</p>
          <p className="text-xs text-gray-400 mt-1">de {totalChunks} total</p>
        </div>
      </div>

      {/* Tabela de cobertura */}
      <div className="bg-white rounded-xl shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600 text-left">
            <tr>
              <th className="px-4 py-3 font-medium">Paciente</th>
              <th className="px-4 py-3 font-medium text-center">Total</th>
              <th className="px-4 py-3 font-medium text-center">Embedded</th>
              <th className="px-4 py-3 font-medium text-center">Pendentes</th>
              <th className="px-4 py-3 font-medium text-center">Placeholder 204</th>
              <th className="px-4 py-3 font-medium text-center">Cobertura</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {coverage.map((c) => {
              const pct = c.chunks_total > 0 ? Math.round((c.usable_embedded_chunks / c.chunks_total) * 100) : 0;
              return (
                <tr key={c.patient_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium">{c.display_name || c.external_id}</td>
                  <td className="px-4 py-3 text-center">{c.chunks_total}</td>
                  <td className="px-4 py-3 text-center text-green-600 font-medium">{c.usable_embedded_chunks}</td>
                  <td className="px-4 py-3 text-center text-orange-500">{c.chunks_missing_embedding}</td>
                  <td className="px-4 py-3 text-center text-gray-400">{c.placeholder_prontuario_embedded}</td>
                  <td className="px-4 py-3 text-center">
                    <div className="w-full bg-gray-200 rounded-full h-2">
                      <div
                        className={`h-2 rounded-full ${pct >= 80 ? "bg-green-500" : pct >= 40 ? "bg-yellow-400" : "bg-red-400"}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-500">{pct}%</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
