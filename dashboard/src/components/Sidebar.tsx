"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";

const navItems = [
  { href: "/dashboard/pacientes", label: "Pacientes", icon: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
    </svg>
  )},
  { href: "/dashboard/engajamento", label: "Engajamento", icon: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
    </svg>
  )},
  { href: "/dashboard/alertas", label: "Alertas", icon: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
    </svg>
  )},
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-64 min-h-screen bg-gray-900 text-white flex flex-col shadow-2xl">
      {/* Logo / Brand */}
      <div className="px-8 py-10">
        <h2 className="text-2xl font-light tracking-tighter text-white">
          Nutri<span className="font-bold text-brand-400">Deby</span>
        </h2>
        <p className="text-[10px] uppercase tracking-[0.2em] text-gray-500 mt-2 font-bold">
          Agente de Execução
        </p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-4 space-y-2">
        {navItems.map((item) => {
          const active = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-4 px-4 py-3 rounded-xl text-sm transition-all duration-200 ${
                active 
                  ? "bg-brand-500 text-white shadow-lg shadow-brand-500/20 font-medium" 
                  : "text-gray-400 hover:bg-gray-800 hover:text-white"
              }`}
            >
              <span className={active ? "text-white" : "text-gray-500"}>{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Footer / Logout */}
      <div className="p-6 border-t border-gray-800">
        <button
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="w-full flex items-center justify-center gap-3 px-4 py-3 rounded-xl text-sm font-medium text-gray-400 hover:bg-red-500/10 hover:text-red-400 transition-all duration-200 border border-transparent hover:border-red-500/20"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
          </svg>
          Sair da Sessão
        </button>
      </div>
    </aside>
  );
}
