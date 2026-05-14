'use client';

import type { PatientData } from '@/types/patient';

interface PatientProfileProps {
  paciente: PatientData;
}

function classificarIMC(imc: number): { label: string; color: string } {
  if (imc < 18.5) return { label: 'Abaixo do peso', color: 'text-yellow-600' };
  if (imc < 25) return { label: 'Peso normal', color: 'text-green-600' };
  if (imc < 30) return { label: 'Sobrepeso', color: 'text-orange-500' };
  if (imc < 35) return { label: 'Obesidade I', color: 'text-red-500' };
  if (imc < 40) return { label: 'Obesidade II', color: 'text-red-600' };
  return { label: 'Obesidade III', color: 'text-red-700' };
}

export default function PatientProfile({ paciente }: PatientProfileProps) {
  const imcInfo = classificarIMC(paciente.imc);

  return (
    <div className="bg-[var(--bg-card)] rounded-xl border border-[var(--border-color)] p-6">
      <div className="flex flex-col sm:flex-row items-start gap-4">
        {/* Avatar */}
        <div className="w-16 h-16 rounded-full bg-primary-200 dark:bg-primary-800 flex items-center justify-center flex-shrink-0">
          {paciente.foto_url ? (
            <img
              src={paciente.foto_url}
              alt={paciente.nome}
              className="w-16 h-16 rounded-full object-cover"
            />
          ) : (
            <span className="text-2xl font-bold text-primary-700 dark:text-primary-200">
              {paciente.nome.split(' ').map(n => n[0]).slice(0, 2).join('')}
            </span>
          )}
        </div>

        {/* Info principal */}
        <div className="flex-1 min-w-0">
          <h2 className="text-xl font-bold text-[var(--text-primary)] truncate">
            {paciente.nome}
          </h2>
          <p className="text-sm text-[var(--text-secondary)]">
            {paciente.idade} anos · {paciente.sexo === 'M' ? 'Masculino' : 'Feminino'}
          </p>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            {paciente.email}
          </p>
          <p className="text-sm text-[var(--text-secondary)]">
            {paciente.telefone}
          </p>
        </div>
      </div>

      {/* Métricas */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6">
        <div className="text-center p-3 rounded-lg bg-[var(--bg-secondary)]">
          <p className="text-xs text-[var(--text-secondary)] uppercase tracking-wide">Altura</p>
          <p className="text-lg font-bold text-[var(--text-primary)]">{paciente.altura_cm} cm</p>
        </div>
        <div className="text-center p-3 rounded-lg bg-[var(--bg-secondary)]">
          <p className="text-xs text-[var(--text-secondary)] uppercase tracking-wide">Peso</p>
          <p className="text-lg font-bold text-[var(--text-primary)]">{paciente.peso_kg} kg</p>
        </div>
        <div className="text-center p-3 rounded-lg bg-[var(--bg-secondary)]">
          <p className="text-xs text-[var(--text-secondary)] uppercase tracking-wide">IMC</p>
          <p className={`text-lg font-bold ${imcInfo.color}`}>{paciente.imc.toFixed(1)}</p>
          <p className={`text-xs ${imcInfo.color}`}>{imcInfo.label}</p>
        </div>
        <div className="text-center p-3 rounded-lg bg-[var(--bg-secondary)]">
          <p className="text-xs text-[var(--text-secondary)] uppercase tracking-wide">Objetivo</p>
          <p className="text-sm font-medium text-[var(--text-primary)] mt-1">{paciente.objetivo}</p>
        </div>
      </div>

      {/* Tags */}
      <div className="mt-4 space-y-2">
        {paciente.restricoes_alimentares.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-[var(--text-secondary)] mb-1">Restrições:</p>
            <div className="flex flex-wrap gap-1">
              {paciente.restricoes_alimentares.map((r, i) => (
                <span key={i} className="px-2 py-0.5 text-xs rounded-full bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300">
                  {r}
                </span>
              ))}
            </div>
          </div>
        )}
        {paciente.patologias.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-[var(--text-secondary)] mb-1">Patologias:</p>
            <div className="flex flex-wrap gap-1">
              {paciente.patologias.map((p, i) => (
                <span key={i} className="px-2 py-0.5 text-xs rounded-full bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300">
                  {p}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
