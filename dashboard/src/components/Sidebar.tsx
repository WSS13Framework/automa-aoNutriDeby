"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";

const navItems = [
  { href: "/dashboard/pacientes", label: "Pacientes", icon: "👤" },
  { href: "/dashboard/engajamento", label: "Engajamento", icon: "📊" },
  { href: "/dashboard/alertas", label: "Alertas", icon: "🔔" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 min-h-screen bg-brand-800 text-white flex flex-col">
      <div className="px-4 py-5 border-b border-brand-700">
        <h2 className="text-lg font-bold">NutriDeby</h2>
        <p className="text-xs text-brand-100 mt-0.5">Painel do Profissional</p>
      </div>
      <nav className="flex-1 py-4">
        {navItems.map((item) => {
          const active = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm transition ${
                active ? "bg-brand-700 font-semibold" : "hover:bg-brand-700/50"
              }`}
            >
              <span>{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="px-4 py-4 border-t border-brand-700">
        <button
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="text-sm text-brand-100 hover:text-white transition"
        >
          Sair
        </button>
      </div>
    </aside>
  );
}
