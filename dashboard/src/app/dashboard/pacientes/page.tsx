import Link from "next/link";
import { listPatients, getRagCoverage, type Patient, type RagCoverage } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function PacientesPage() {
  let patients: Patient[] = [];
  let coverage: RagCoverage[] = [];
  let apiError = "";

  try {
    [patients, coverage] = await Promise.all([listPatients(200), getRagCoverage(200)]);
  } catch (e: unknown) {
    apiError = e instanceof Error ? e.message : "Erro ao carregar dados";
  }

  const coverageMap = new Map(coverage.map((c) => [c.patient_id, c]));

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800">Pacientes</h1>
        <span className="text-sm text-gray-500">{patients.length} registros</span>
      </div>

      {apiError && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-4">
          <p className="text-sm font-medium">Erro ao conectar na API</p>
          <p className="text-xs mt-1">{apiError}</p>
        </div>
      )}

      <div className="bg-white rounded-xl shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600 text-left">
            <tr>
              <th className="px-4 py-3 font-medium">Nome</th>
              <th className="px-4 py-3 font-medium">Origem</th>
              <th className="px-4 py-3 font-medium text-center">Chunks RAG</th>
              <th className="px-4 py-3 font-medium text-center">Embeddings</th>
              <th className="px-4 py-3 font-medium">Atualizado</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {patients.map((p) => {
              const cov = coverageMap.get(p.id);
              return (
                <tr key={p.id} className="hover:bg-gray-50 transition">
                  <td className="px-4 py-3">
                    <Link href={`/dashboard/pacientes/${p.id}`} className="text-brand-600 hover:underline font-medium">
                      {p.display_name || p.external_id}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-gray-500">{p.source_system}</td>
                  <td className="px-4 py-3 text-center">
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                      (cov?.chunks_total ?? 0) > 0 ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
                    }`}>
                      {cov?.chunks_total ?? 0}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                      (cov?.usable_embedded_chunks ?? 0) > 0 ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-500"
                    }`}>
                      {cov?.usable_embedded_chunks ?? 0}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {new Date(p.updated_at).toLocaleDateString("pt-BR")}
                  </td>
                </tr>
              );
            })}
            {patients.length === 0 && !apiError && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-gray-400">
                  Nenhum paciente encontrado.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
