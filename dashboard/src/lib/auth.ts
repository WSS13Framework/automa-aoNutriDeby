import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import bcrypt from "bcryptjs";

/**
 * Autenticação NextAuth — Credentials Provider
 *
 * Usa ADMIN_EMAIL + ADMIN_PASSWORD como variáveis de ambiente.
 * O hash bcrypt é gerado em runtime, evitando problemas com o caractere "$"
 * em arquivos .env interpretados pelo Docker Compose.
 *
 * Para produção com múltiplos usuários, migrar para tabela `users` no PostgreSQL.
 */

// Cache do hash para não recalcular a cada request
let cachedHash: string | null = null;
let cachedPassword: string | null = null;

async function getAdminHash(): Promise<string> {
  const password = process.env.ADMIN_PASSWORD || "";
  if (!password) return "";
  if (cachedHash && cachedPassword === password) return cachedHash;
  cachedHash = await bcrypt.hash(password, 10);
  cachedPassword = password;
  return cachedHash;
}

export const authOptions: NextAuthOptions = {
  secret: process.env.NEXTAUTH_SECRET,
  session: { strategy: "jwt", maxAge: 7 * 24 * 60 * 60 },
  pages: { signIn: "/login" },
  providers: [
    CredentialsProvider({
      name: "Credenciais",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Senha", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null;

        const adminEmail = process.env.ADMIN_EMAIL || "admin@nutrideby.com.br";
        const adminPassword = process.env.ADMIN_PASSWORD || "";

        if (credentials.email !== adminEmail) return null;
        if (!adminPassword) return null;

        // Comparação direta — sem depender de hash em env var
        if (credentials.password !== adminPassword) return null;

        return { id: "1", name: "Nutricionista", email: adminEmail };
      },
    }),
  ],
};
