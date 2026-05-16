import Link from "next/link";
import { listPatients, getRagCoverage, type Patient, type RagCoverage } from "@/lib/api";

export const dynamic = "force-dynamic";

// Função para determinar o status humano do paciente
function getPatientStatus(p: Patient, cov?: RagCoverage) {
  const lastUpdate = new Date(p.updated_at);
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - lastUpdate.getTime()) / (1000 * 3600 * 24));

  if (diffDays > 10) return { label: "Inativo", color: "bg-red-100 text-red-700" };
  if (diffDays > 5) return { label: "Atenção", color: "bg-yellow-100 text-yellow-700" };
  if ((cov?.usable_embedded_chunks ?? 0) === 0) return { label: "Processando", color: "bg-blue-100 text-blue-700" };
  return { label: "Em dia", color: "bg-green-100 text-green-700" };
}

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
    <div className="max-w-5xl mx-auto">
      <div className="flex items-baseline justify-between mb-10">
        <h1 className="text-3xl font-light text-gray-900 tracking-tight">Pacientes</h1>
        <span className="text-sm font-medium text-gray-400 uppercase tracking-widest">
          {patients.length} Acompanhados
        </span>
      </div>

      {apiError && (
        <div className="bg-red-50 border-l-4 border-red-400 p-4 mb-8">
          <p className="text-sm text-red-700">Sistema temporariamente indisponível. Nossa equipe já foi notificada.</p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4">
        {patients.map((p) => {
          const cov = coverageMap.get(p.id);
          const status = getPatientStatus(p, cov);
          
          return (
            <Link 
              key={p.id} 
              href={`/dashboard/pacientes/${p.id}`}
              className="group bg-white border border-gray-100 rounded-2xl p-5 flex items-center justify-between hover:shadow-xl hover:border-brand-200 transition-all duration-300"
            >
              <div className="flex items-center space-x-4">
                <div className="w-12 h-12 bg-gray-50 rounded-full flex items-center justify-center text-xl font-light text-gray-400 group-hover:bg-brand-50 group-hover:text-brand-500 transition-colors">
                  {p.display_name?.charAt(0) || "?"}
                </div>
                <div>
                  <h2 className="text-lg font-medium text-gray-800 group-hover:text-brand-600 transition-colors">
                    {p.display_name || "Paciente sem nome"}
                  </h2>
                  <p className="text-sm text-gray-400 font-light">
                    Última interação: {new Date(p.updated_at).toLocaleDateString("pt-BR")}
                  </p>
                </div>
              </div>

              <div className="flex items-center space-x-6">
                <span className={`px-3 py-1 rounded-full text-xs font-semibold tracking-wide uppercase ${status.color}`}>
                  {status.label}
                </span>
                <svg className="w-5 h-5 text-gray-300 group-hover:text-brand-400 transform group-hover:translate-x-1 transition-all" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="9 5l7 7-7 7" />
                </svg>
              </div>
            </Link>
          );
        })}

        {patients.length === 0 && !apiError && (
          <div className="py-20 text-center">
            <p className="text-gray-400 font-light italic">Sua lista de pacientes está vazia.</p>
          </div>
        )}
      </div>
    </div>
  );
}
