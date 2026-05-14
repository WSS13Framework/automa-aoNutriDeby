'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Sidebar from '@/components/Sidebar';
import PatientProfile from '@/components/PatientProfile';
import GoalsCard from '@/components/GoalsCard';
import EngagementChart from '@/components/EngagementChart';
import AlertsPanel from '@/components/AlertsPanel';
import ConductSuggestions from '@/components/ConductSuggestions';
import VideoCall from '@/components/VideoCall';
import SendViaWhatsApp from '@/components/SendViaWhatsApp';
import type { PatientData, MetaNutricional, AlertaClinico, EngagementData } from '@/types/patient';

export default function PacienteDetalhePage() {
  const params = useParams();
  const pacienteId = params.id as string;

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [paciente, setPaciente] = useState<PatientData | null>(null);
  const [metas, setMetas] = useState<MetaNutricional[]>([]);
  const [alertas, setAlertas] = useState<AlertaClinico[]>([]);
  const [engajamento, setEngajamento] = useState<EngagementData[]>([]);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState('');
  const [mensagemWhatsApp, setMensagemWhatsApp] = useState('');

  const fetchPaciente = useCallback(async () => {
    setLoading(true);
    setErro('');
    try {
      const res = await fetch(`/api/pacientes?id=${pacienteId}`);
      if (!res.ok) {
        if (res.status === 404) {
          setErro('Paciente não encontrado');
        } else {
          setErro('Erro ao carregar dados do paciente');
        }
        return;
      }

      const data = await res.json();
      setPaciente(data.paciente);
      setMetas(data.metas || []);
      setAlertas(data.alertas || []);
      setEngajamento(data.engajamento || []);
    } catch (err) {
      console.error('Erro ao carregar paciente:', err);
      setErro('Erro de conexão');
    } finally {
      setLoading(false);
    }
  }, [pacienteId]);

  useEffect(() => {
    fetchPaciente();
  }, [fetchPaciente]);

  const handleSendWhatsApp = (texto: string) => {
    setMensagemWhatsApp(texto);
    // Scroll to WhatsApp section
    document.getElementById('whatsapp-section')?.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      <main className="flex-1 overflow-y-auto">
        {/* Header mobile */}
        <header className="sticky top-0 z-30 bg-[var(--bg-primary)]/80 backdrop-blur-sm border-b border-[var(--border-color)] px-4 py-3 lg:px-6">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(true)}
              className="lg:hidden p-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <a href="/" className="text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
              Dashboard
            </a>
            <svg className="w-4 h-4 text-[var(--text-secondary)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            <span className="text-sm font-medium text-[var(--text-primary)] truncate">
              {paciente?.nome || 'Carregando...'}
            </span>
          </div>
        </header>

        <div className="p-4 lg:p-6">
          {loading ? (
            <div className="space-y-4">
              <div className="skeleton h-48 rounded-xl" />
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div className="skeleton h-64 rounded-xl" />
                <div className="skeleton h-64 rounded-xl" />
              </div>
              <div className="skeleton h-48 rounded-xl" />
            </div>
          ) : erro ? (
            <div className="text-center py-12">
              <svg className="w-16 h-16 mx-auto text-red-400 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
              <p className="text-lg font-medium text-[var(--text-primary)]">{erro}</p>
              <button
                onClick={fetchPaciente}
                className="mt-4 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-sm"
              >
                Tentar novamente
              </button>
            </div>
          ) : paciente ? (
            <div className="space-y-6">
              {/* Perfil do paciente */}
              <PatientProfile paciente={paciente} />

              {/* Grid principal */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Metas nutricionais */}
                <GoalsCard metas={metas} />

                {/* Engajamento */}
                <EngagementChart dados={engajamento} />
              </div>

              {/* Alertas */}
              <AlertsPanel alertas={alertas} />

              {/* Sugestão de conduta IA */}
              <ConductSuggestions
                pacienteId={pacienteId}
                onSendWhatsApp={handleSendWhatsApp}
              />

              {/* Grid: Videochamada + WhatsApp */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <VideoCall
                  pacienteId={pacienteId}
                  pacienteNome={paciente.nome}
                />
                <div id="whatsapp-section">
                  <SendViaWhatsApp
                    pacienteId={pacienteId}
                    pacienteTelefone={paciente.telefone}
                    mensagem={mensagemWhatsApp}
                  />
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </main>
    </div>
  );
}
