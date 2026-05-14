import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NutriDeby — Painel do Profissional",
  description: "Painel de acompanhamento nutricional com inteligência artificial",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
