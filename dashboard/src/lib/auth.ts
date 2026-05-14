import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import bcrypt from "bcryptjs";

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
        const adminHash = process.env.ADMIN_PASSWORD_HASH || "";

        if (credentials.email !== adminEmail) return null;
        if (!adminHash) return null;

        const valid = await bcrypt.compare(credentials.password, adminHash);
        if (!valid) return null;

        return { id: "1", name: "Nutricionista", email: adminEmail };
      },
    }),
  ],
};
