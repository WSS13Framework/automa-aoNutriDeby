import { listPatients, getRagCoverage, type Patient, type RagCoverage } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AlertasPage() {
  let patients: Patient[] = [];
  let coverage: RagCoverage[] = [];
  let error = "";

  try {
    [patients, coverage] = await Promise.all([listPatients(200), getRagCoverage(200)]);
  } catch (e: unknown) {
    error = e instanceof Error ? e.message : "Erro ao carregar dados";
  }

  const coverageMap = new Map(coverage.map((c) => [c.patient_id, c]));
  const now = new Date();

  // Alerta 1: Pacientes sem embeddings (IA não consegue atender)
  const semEmbeddings = coverage.filter((c) => c.usable_embedded_chunks === 0);

  // Alerta 2: Pacientes não atualizados há mais de 7 dias
  const inativos = patients.filter((p) => {
    const diff = now.getTime() - new Date(p.updated_at).getTime();
    return diff > 7 * 24 * 60 * 60 * 1000;
  });

  // Alerta 3: Pacientes com muitos placeholders (prontuário 204)
  const comPlaceholder = coverage.filter((c) => c.placeholder_prontuario_embedded > 0 && c.usable_embedded_chunks === 0);

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Alertas Clínicos</h1>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-4">
          <p className="text-sm">{error}</p>
        </div>
      )}

      <div className="space-y-6">
        {/* Alerta: Sem Embeddings */}
        <div className="bg-white rounded-xl shadow p-5">
          <div className="flex items-center gap-2 mb-3">
            <span className="w-3 h-3 rounded-full bg-red-500" />
            <h2 className="text-lg font-bold text-gray-800">
              IA Indisponível ({semEmbeddings.length})
            </h2>
          </div>
          <p className="text-sm text-gray-500 mb-3">
            Pacientes sem embeddings indexados. A busca inteligente (RAG) não funciona para eles.
          </p>
          {semEmbeddings.length === 0 ? (
            <p className="text-green-600 text-sm font-medium">Todos os pacientes estão cobertos.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {semEmbeddings.slice(0, 20).map((c) => (
                <span key={c.patient_id} className="text-xs bg-red-50 text-red-600 px-2 py-1 rounded">
                  {c.display_name || c.external_id}
                </span>
              ))}
              {semEmbeddings.length > 20 && (
                <span className="text-xs text-gray-400">+{semEmbeddings.length - 20} mais</span>
              )}
            </div>
          )}
        </div>

        {/* Alerta: Inativos */}
        <div className="bg-white rounded-xl shadow p-5">
          <div className="flex items-center gap-2 mb-3">
            <span className="w-3 h-3 rounded-full bg-yellow-500" />
            <h2 className="text-lg font-bold text-gray-800">
              Sem Atualização +7 dias ({inativos.length})
            </h2>
          </div>
          <p className="text-sm text-gray-500 mb-3">
            Pacientes sem atualização nos últimos 7 dias. Podem precisar de acompanhamento.
          </p>
          {inativos.length === 0 ? (
            <p className="text-green-600 text-sm font-medium">Todos os pacientes estão atualizados.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {inativos.slice(0, 20).map((p) => (
                <span key={p.id} className="text-xs bg-yellow-50 text-yellow-700 px-2 py-1 rounded">
                  {p.display_name || p.external_id}
                </span>
              ))}
              {inativos.length > 20 && (
                <span className="text-xs text-gray-400">+{inativos.length - 20} mais</span>
              )}
            </div>
          )}
        </div>

        {/* Alerta: Prontuário Placeholder */}
        <div className="bg-white rounded-xl shadow p-5">
          <div className="flex items-center gap-2 mb-3">
            <span className="w-3 h-3 rounded-full bg-orange-500" />
            <h2 className="text-lg font-bold text-gray-800">
              Prontuário Incompleto ({comPlaceholder.length})
            </h2>
          </div>
          <p className="text-sm text-gray-500 mb-3">
            Pacientes com apenas o marcador de prontuário 204 (API Dietbox retornou vazio). Precisam de dados reais.
          </p>
          {comPlaceholder.length === 0 ? (
            <p className="text-green-600 text-sm font-medium">Nenhum paciente com prontuário incompleto.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {comPlaceholder.slice(0, 20).map((c) => (
                <span key={c.patient_id} className="text-xs bg-orange-50 text-orange-600 px-2 py-1 rounded">
                  {c.display_name || c.external_id}
                </span>
              ))}
              {comPlaceholder.length > 20 && (
                <span className="text-xs text-gray-400">+{comPlaceholder.length - 20} mais</span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
