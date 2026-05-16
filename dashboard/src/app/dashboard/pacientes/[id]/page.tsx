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
      <div className="max-w-4xl mx-auto py-20 text-center">
        <p className="text-red-500 font-light">{error || "Paciente não encontrado"}</p>
        <Link href="/dashboard/pacientes" className="text-brand-600 underline mt-4 inline-block">Voltar para a lista</Link>
      </div>
    );
  }

  const meta = (patient.metadata || {}) as Record<string, any>;
  
  // Extração de metas do dietbox_meta_export
  const metaExportDoc = documents.find(d => d.doc_type === 'dietbox_meta_export');
  let goals: any[] = [];
  if (metaExportDoc) {
    try {
      const parsed = JSON.parse(metaExportDoc.content_preview);
      goals = parsed.items || [];
    } catch (e) {
      // Se não for JSON válido, tenta extrair do metadata do paciente
      goals = meta.meta_export_items ? [{ nome: "Metas registradas no Dietbox" }] : [];
    }
  }

  return (
    <div className="max-w-5xl mx-auto pb-20">
      {/* Navegação e Título */}
      <div className="flex items-center justify-between mb-12">
        <div className="flex items-center space-x-6">
          <Link href="/dashboard/pacientes" className="w-10 h-10 rounded-full bg-gray-50 flex items-center justify-center text-gray-400 hover:bg-brand-50 hover:text-brand-600 transition-all">
            &larr;
          </Link>
          <div>
            <h1 className="text-3xl font-light text-gray-900 tracking-tight">{patient.display_name || "Paciente"}</h1>
            <p className="text-sm text-gray-400 font-light uppercase tracking-widest mt-1">
              {patient.source_system} • ID {patient.external_id}
            </p>
          </div>
        </div>
        <div className="text-right">
          <span className="px-4 py-1.5 rounded-full bg-green-50 text-green-600 text-xs font-bold uppercase tracking-wider">
            Monitoramento Ativo
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Coluna Esquerda: Dados e Metas */}
        <div className="lg:col-span-2 space-y-8">
          
          {/* Metas de Execução (O Coração do Agente) */}
          <section className="bg-white rounded-3xl border border-gray-100 p-8 shadow-sm">
            <h2 className="text-sm font-bold text-gray-400 uppercase tracking-widest mb-6">Metas de Execução</h2>
            {goals.length > 0 ? (
              <div className="space-y-4">
                {goals.map((goal: any, idx: number) => (
                  <div key={idx} className="flex items-start space-x-4 p-4 bg-brand-50 rounded-2xl border border-brand-100">
                    <div className="w-6 h-6 rounded-full bg-brand-500 flex-shrink-0 flex items-center justify-center text-white text-xs">
                      {idx + 1}
                    </div>
                    <div>
                      <p className="text-brand-900 font-medium">{goal.nome}</p>
                      {goal.descricao && <p className="text-brand-700 text-sm mt-1 font-light">{goal.descricao}</p>}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-gray-400 font-light italic">Nenhuma meta ativa para este paciente.</p>
            )}
          </section>

          {/* Busca Inteligente */}
          <section className="bg-white rounded-3xl border border-gray-100 p-8 shadow-sm">
            <h2 className="text-sm font-bold text-gray-400 uppercase tracking-widest mb-6">Busca Inteligente (RAG)</h2>
            <RagSearch patientId={params.id} />
          </section>

          {/* Documentos Clínicos */}
          <section className="bg-white rounded-3xl border border-gray-100 p-8 shadow-sm">
            <h2 className="text-sm font-bold text-gray-400 uppercase tracking-widest mb-6">Histórico Clínico</h2>
            <div className="space-y-4">
              {documents.filter(d => d.doc_type !== 'dietbox_meta_export').map((doc) => (
                <div key={doc.id} className="group p-4 hover:bg-gray-50 rounded-2xl transition-colors border border-transparent hover:border-gray-100">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] font-bold uppercase tracking-tighter text-gray-400 bg-gray-100 px-2 py-0.5 rounded">
                      {doc.doc_type.replace('dietbox_', '')}
                    </span>
                    <span className="text-xs text-gray-300">
                      {new Date(doc.collected_at).toLocaleDateString("pt-BR")}
                    </span>
                  </div>
                  <p className="text-sm text-gray-600 font-light line-clamp-3 group-hover:line-clamp-none transition-all">
                    {doc.content_preview}
                  </p>
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* Coluna Direita: Perfil e Status */}
        <div className="space-y-8">
          <section className="bg-gray-900 rounded-3xl p-8 text-white shadow-xl">
            <h2 className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-6">Perfil do Paciente</h2>
            <div className="space-y-6">
              <div>
                <p className="text-[10px] text-gray-500 uppercase">Idade</p>
                <p className="text-xl font-light">
                  {meta.Birthday ? Math.floor((new Date().getTime() - new Date(meta.Birthday).getTime()) / (1000 * 3600 * 24 * 365.25)) : "--"} anos
                </p>
              </div>
              <div>
                <p className="text-[10px] text-gray-500 uppercase">Ocupação</p>
                <p className="text-xl font-light">{meta.Occupancy || "Não informada"}</p>
              </div>
              <div>
                <p className="text-[10px] text-gray-500 uppercase">Contato</p>
                <p className="text-sm font-light text-gray-300">{meta.Email || "Sem e-mail"}</p>
                <p className="text-sm font-light text-gray-300">{meta.MobilePhone || "Sem telefone"}</p>
              </div>
            </div>
          </section>

          <section className="bg-white rounded-3xl border border-gray-100 p-8 shadow-sm">
            <h2 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-6">Status da IA</h2>
            <div className="flex items-center space-x-3">
              <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
              <p className="text-sm text-gray-600 font-medium">Gerente de Operações Ativo</p>
            </div>
            <p className="text-xs text-gray-400 mt-4 font-light leading-relaxed">
              A IA está monitorando as metas de execução e o engajamento deste paciente via WhatsApp.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
