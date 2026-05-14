import bcrypt from 'bcryptjs';
import jwt from 'jsonwebtoken';
import { query, queryOne } from './db';
import type { UserSession } from '@/types/patient';

const JWT_SECRET = process.env.JWT_SECRET || 'dev-secret-change-me';
const JWT_EXPIRATION = '8h';

export interface AuthUser {
  id: string;
  email: string;
  nome: string;
  role: string;
  senha_hash: string;
}

export async function authenticateUser(
  email: string,
  senha: string
): Promise<{ token: string; user: UserSession } | null> {
  const user = await queryOne<AuthUser>(
    'SELECT id, email, nome, role, senha_hash FROM usuarios WHERE email = $1 AND ativo = true',
    [email]
  );

  if (!user) return null;

  const valid = await bcrypt.compare(senha, user.senha_hash);
  if (!valid) return null;

  const session: UserSession = {
    id: user.id,
    email: user.email,
    nome: user.nome,
    role: user.role as 'nutricionista' | 'admin',
  };

  const token = jwt.sign(session, JWT_SECRET, { expiresIn: JWT_EXPIRATION });

  return { token, user: session };
}

export function verifyToken(token: string): UserSession | null {
  try {
    const decoded = jwt.verify(token, JWT_SECRET) as UserSession;
    return decoded;
  } catch {
    return null;
  }
}

export async function hashPassword(senha: string): Promise<string> {
  return bcrypt.hash(senha, 12);
}

export function extractTokenFromHeader(
  authHeader: string | null
): string | null {
  if (!authHeader?.startsWith('Bearer ')) return null;
  return authHeader.slice(7);
}
