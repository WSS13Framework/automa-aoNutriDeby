import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NutriDeby — Painel do Profissional",
  description: "Painel de acompanhamento nutricional com inteligência artificial",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <head>
        {/* Desabilita Google One Tap / FedCM do Chrome */}
        <meta name="google" content="notranslate" />
        <meta name="google-signin-client_id" content="" />
      </head>
      <body>{children}</body>
    </html>
  );
}
