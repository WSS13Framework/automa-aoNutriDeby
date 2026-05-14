import ImportPacientes from "@/components/ImportPacientes";

export const metadata = { title: "Importar Pacientes — NutriDeby" };

export default function ImportarPage() {
  return (
    <main className="min-h-screen bg-gray-50 dark:bg-gray-950 p-6">
      <div className="max-w-2xl mx-auto space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Importar Pacientes</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1 text-sm">
            Centralize dados de Dietbox, DietSmart, Nutrium, NutriCloud e outros no NutriDeby.
          </p>
        </div>

        {/* Fluxo resumido */}
        <div className="bg-white dark:bg-gray-900 rounded-2xl shadow p-5">
          <h3 className="font-semibold text-gray-800 dark:text-gray-200 mb-3">Como funciona</h3>
          <ol className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
            <li className="flex gap-3">
              <span className="flex-shrink-0 w-6 h-6 bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 rounded-full flex items-center justify-center text-xs font-bold">1</span>
              <span>Rode o extrator da plataforma no servidor ou máquina local:<br/>
                <code className="text-xs bg-gray-100 dark:bg-gray-800 px-1 rounded">
                  python3 scripts/extractors/dietbox_extractor.py --output pacientes.json
                </code>
              </span>
            </li>
            <li className="flex gap-3">
              <span className="flex-shrink-0 w-6 h-6 bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 rounded-full flex items-center justify-center text-xs font-bold">2</span>
              <span>Selecione a plataforma de origem abaixo.</span>
            </li>
            <li className="flex gap-3">
              <span className="flex-shrink-0 w-6 h-6 bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 rounded-full flex items-center justify-center text-xs font-bold">3</span>
              <span>Faça upload do JSON gerado — os pacientes são importados com upsert.</span>
            </li>
            <li className="flex gap-3">
              <span className="flex-shrink-0 w-6 h-6 bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 rounded-full flex items-center justify-center text-xs font-bold">4</span>
              <span>Os documentos são indexados automaticamente para RAG (embeddings gerados pelo worker).</span>
            </li>
          </ol>
        </div>

        <ImportPacientes />
      </div>
    </main>
  );
}
