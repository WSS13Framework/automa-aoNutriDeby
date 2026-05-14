'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { PatientData } from '@/types/patient';
import ThemeToggle from './ThemeToggle';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function Sidebar({ isOpen, onClose }: SidebarProps) {
  const pathname = usePathname();
  const [busca, setBusca] = useState('');
  const [pacientes, setPacientes] = useState<PatientData[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchPacientes = useCallback(async (termo: string) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (termo) params.set('busca', termo);
      const res = await fetch(`/api/pacientes?${params}`);
      if (res.ok) {
        const data = await res.json();
        setPacientes(data.pacientes || []);
      }
    } catch (err) {
      console.error('Erro ao buscar pacientes:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPacientes('');
  }, [fetchPacientes]);

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchPacientes(busca);
    }, 300);
    return () => clearTimeout(timer);
  }, [busca, fetchPacientes]);

  const handleLogout = () => {
    document.cookie = 'nutrideby_token=; path=/; max-age=0';
    localStorage.removeItem('nutrideby_token');
    window.location.href = '/login';
  };

  return (
    <>
      {/* Overlay mobile */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={`
          fixed top-0 left-0 h-full z-50 w-72
          bg-[var(--sidebar-bg)] border-r border-[var(--border-color)]
          transform transition-transform duration-300 ease-in-out
          lg:translate-x-0 lg:static lg:z-auto
          ${isOpen ? 'translate-x-0' : '-translate-x-full'}
          flex flex-col
        `}
      >
        {/* Header */}
        <div className="p-4 border-b border-[var(--border-color)]">
          <div className="flex items-center justify-between mb-4">
            <Link href="/" className="flex items-center gap-2">
              <div className="w-8 h-8 bg-primary-600 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-sm">ND</span>
              </div>
              <span className="font-bold text-lg text-[var(--text-primary)]">NutriDeby</span>
            </Link>
            <div className="flex items-center gap-1">
              <ThemeToggle />
              <button
                onClick={onClose}
                className="lg:hidden p-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>

          {/* Busca */}
          <div className="relative">
            <svg
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-secondary)]"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              placeholder="Buscar paciente..."
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              className="w-full pl-10 pr-4 py-2 rounded-lg border border-[var(--border-color)] bg-[var(--bg-primary)] text-[var(--text-primary)] text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
        </div>

        {/* Lista de pacientes */}
        <nav className="flex-1 overflow-y-auto p-2">
          <p className="px-3 py-2 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">
            Pacientes ({pacientes.length})
          </p>

          {loading ? (
            <div className="space-y-2 p-2">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="skeleton h-12 rounded-lg" />
              ))}
            </div>
          ) : pacientes.length === 0 ? (
            <p className="px-3 py-4 text-sm text-[var(--text-secondary)] text-center">
              Nenhum paciente encontrado
            </p>
          ) : (
            <ul className="space-y-1">
              {pacientes.map((p) => {
                const isActive = pathname === `/pacientes/${p.id}`;
                return (
                  <li key={p.id}>
                    <Link
                      href={`/pacientes/${p.id}`}
                      onClick={onClose}
                      className={`
                        flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors
                        ${isActive
                          ? 'bg-primary-600 text-white'
                          : 'text-[var(--text-primary)] hover:bg-primary-100 dark:hover:bg-primary-900/30'
                        }
                      `}
                    >
                      <div className={`
                        w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0
                        ${isActive ? 'bg-white/20 text-white' : 'bg-primary-200 dark:bg-primary-800 text-primary-700 dark:text-primary-200'}
                      `}>
                        {p.nome.split(' ').map(n => n[0]).slice(0, 2).join('')}
                      </div>
                      <div className="min-w-0">
                        <p className="font-medium truncate">{p.nome}</p>
                        <p className={`text-xs truncate ${isActive ? 'text-white/70' : 'text-[var(--text-secondary)]'}`}>
                          IMC: {p.imc?.toFixed(1)} · {p.objetivo}
                        </p>
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-[var(--border-color)]">
          <Link
            href="/"
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors mb-2
              ${pathname === '/' ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'}
            `}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
            </svg>
            Dashboard
          </Link>
          <button
            onClick={handleLogout}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 w-full transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            Sair
          </button>
        </div>
      </aside>
    </>
  );
}
