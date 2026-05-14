import { NextRequest, NextResponse } from 'next/server';
import { verifyToken, extractTokenFromHeader } from '@/lib/auth';
import { query } from '@/lib/db';
import type { PatientData, MetaNutricional, AlertaClinico, EngagementData } from '@/types/patient';

export async function GET(request: NextRequest) {
  const token = request.cookies.get('nutrideby_token')?.value
    || extractTokenFromHeader(request.headers.get('authorization'));

  if (!token) {
    return NextResponse.json({ error: 'Não autenticado' }, { status: 401 });
  }

  const user = verifyToken(token);
  if (!user) {
    return NextResponse.json({ error: 'Token inválido' }, { status: 401 });
  }

  const { searchParams } = new URL(request.url);
  const busca = searchParams.get('busca') || '';
  const pacienteId = searchParams.get('id');

  try {
    // Detalhe de um paciente específico
    if (pacienteId) {
      const paciente = await query<PatientData>(
        `SELECT * FROM pacientes WHERE id = $1`,
        [pacienteId]
      );

      if (paciente.length === 0) {
        return NextResponse.json({ error: 'Paciente não encontrado' }, { status: 404 });
      }

      const metas = await query<MetaNutricional>(
        `SELECT * FROM metas_nutricionais WHERE paciente_id = $1 ORDER BY created_at DESC`,
        [pacienteId]
      );

      const alertas = await query<AlertaClinico>(
        `SELECT * FROM alertas_clinicos WHERE paciente_id = $1 ORDER BY created_at DESC LIMIT 10`,
        [pacienteId]
      );

      const engajamento = await query<EngagementData>(
        `SELECT 
           DATE(timestamp) as dia,
           COUNT(*) FILTER (WHERE direcao = 'entrada') as mensagens,
           COUNT(*) FILTER (WHERE direcao = 'saida') as respostas
         FROM mensagens_whatsapp
         WHERE paciente_id = $1 AND timestamp >= NOW() - INTERVAL '7 days'
         GROUP BY DATE(timestamp)
         ORDER BY dia ASC`,
        [pacienteId]
      );

      return NextResponse.json({
        paciente: paciente[0],
        metas,
        alertas,
        engajamento,
      });
    }

    // Lista de pacientes com busca
    let pacientes: PatientData[];
    if (busca) {
      pacientes = await query<PatientData>(
        `SELECT * FROM pacientes WHERE nome ILIKE $1 OR email ILIKE $1 ORDER BY nome ASC LIMIT 50`,
        [`%${busca}%`]
      );
    } else {
      pacientes = await query<PatientData>(
        `SELECT * FROM pacientes ORDER BY updated_at DESC LIMIT 50`
      );
    }

    return NextResponse.json({ pacientes });
  } catch (error) {
    console.error('[Pacientes] Erro:', error);
    return NextResponse.json(
      { error: 'Erro ao buscar pacientes' },
      { status: 500 }
    );
  }
}
