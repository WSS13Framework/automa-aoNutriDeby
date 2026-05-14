import { getPatient, getPatientDocuments, type PatientDetail, type Document } from "@/lib/api";
import Link from "next/link";
import RagSearch from "@/components/RagSearch";

export const dynamic = "force-dynamic";

export default async function PacienteDetailPage({ params }: { params: { id: string } }) {
  let patient: PatientDetail | null = null;
  let documents: Document[] = [];
  let error = "";

  try {
    [patient, documents] = await Promise.all([
      getPatient(params.id),
      getPatientDocuments(params.id),
    ]);
  } catch (e: unknown) {
    error = e instanceof Error ? e.message : "Erro ao carregar dados";
  }

  if (error || !patient) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
        <p className="font-medium">Erro</p>
        <p className="text-sm mt-1">{error || "Paciente não encontrado"}</p>
        <Link href="/dashboard/pacientes" className="text-sm underline mt-2 inline-block">Voltar</Link>
      </div>
    );
  }

  const meta = patient.metadata || {};
  const metaExport = (meta as Record<string, unknown>).meta_export as Record<string, unknown> | undefined;

  return (
    <div className="space-y-6">
      {/* Cabeçalho */}
      <div className="flex items-center gap-4">
        <Link href="/dashboard/pacientes" className="text-brand-600 hover:underline text-sm">&larr; Voltar</Link>
        <h1 className="text-2xl font-bold text-gray-800">{patient.display_name || patient.external_id}</h1>
      </div>

      {/* Cards de resumo */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl shadow p-5">
          <p className="text-xs text-gray-500 uppercase tracking-wide">Origem</p>
          <p className="text-lg font-semibold mt-1">{patient.source_system}</p>
          <p className="text-xs text-gray-400 mt-1">ID externo: {patient.external_id}</p>
        </div>
        <div className="bg-white rounded-xl shadow p-5">
          <p className="text-xs text-gray-500 uppercase tracking-wide">Documentos</p>
          <p className="text-3xl font-bold text-brand-600 mt-1">{patient.documents_count}</p>
        </div>
        <div className="bg-white rounded-xl shadow p-5">
          <p className="text-xs text-gray-500 uppercase tracking-wide">Atualizado</p>
          <p className="text-lg font-semibold mt-1">
            {new Date(patient.updated_at).toLocaleDateString("pt-BR")}
          </p>
        </div>
      </div>

      {/* Metas Nutricionais (meta_export) */}
      {metaExport && (
        <div className="bg-white rounded-xl shadow p-5">
          <h2 className="text-lg font-bold text-gray-800 mb-3">Metas Nutricionais</h2>
          <div className="overflow-x-auto">
            <pre className="text-xs bg-gray-50 p-4 rounded-lg overflow-auto max-h-64">
              {JSON.stringify(metaExport, null, 2)}
            </pre>
          </div>
        </div>
      )}

      {/* Metadata geral */}
      {Object.keys(meta).length > 0 && !metaExport && (
        <div className="bg-white rounded-xl shadow p-5">
          <h2 className="text-lg font-bold text-gray-800 mb-3">Dados Complementares</h2>
          <pre className="text-xs bg-gray-50 p-4 rounded-lg overflow-auto max-h-64">
            {JSON.stringify(meta, null, 2)}
          </pre>
        </div>
      )}

      {/* Documentos */}
      <div className="bg-white rounded-xl shadow p-5">
        <h2 className="text-lg font-bold text-gray-800 mb-3">Documentos Clínicos</h2>
        {documents.length === 0 ? (
          <p className="text-gray-400 text-sm">Nenhum documento encontrado.</p>
        ) : (
          <div className="space-y-3">
            {documents.map((doc) => (
              <div key={doc.id} className="border border-gray-100 rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
                    {doc.doc_type}
                  </span>
                  <span className="text-xs text-gray-400">
                    {new Date(doc.collected_at).toLocaleDateString("pt-BR")}
                  </span>
                </div>
                <p className="text-sm text-gray-700 whitespace-pre-wrap">{doc.content_preview}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Busca RAG */}
      <div className="bg-white rounded-xl shadow p-5">
        <h2 className="text-lg font-bold text-gray-800 mb-3">Busca Inteligente (RAG)</h2>
        <RagSearch patientId={params.id} />
      </div>
    </div>
  );
}
