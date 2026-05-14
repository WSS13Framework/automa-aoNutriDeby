"use client";

import OnboardingWizard from "@/components/OnboardingWizard";

// ID fixo para demo — em produção virá do JWT/session
const DEMO_NUTRITIONIST_ID = "00000000-0000-0000-0000-000000000001";

export default function OnboardingPage() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 flex flex-col items-center justify-center p-4">
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Importar pacientes
        </h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Conecte sua plataforma atual e traga todos os seus pacientes em minutos.
        </p>
      </div>
      <OnboardingWizard
        nutritionistId={DEMO_NUTRITIONIST_ID}
        onComplete={(result) => {
          console.log("Importação concluída:", result);
        }}
      />
    </div>
  );
}
