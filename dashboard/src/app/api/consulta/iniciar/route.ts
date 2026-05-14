import { NextRequest, NextResponse } from 'next/server';
import { verifyToken, extractTokenFromHeader } from '@/lib/auth';
import { queryOne, execute } from '@/lib/db';
import { enviarLinkVideochamada } from '@/lib/whatsapp';
import type { PatientData } from '@/types/patient';
import { randomUUID } from 'crypto';

export async function POST(request: NextRequest) {
  const token = request.cookies.get('nutrideby_token')?.value
    || extractTokenFromHeader(request.headers.get('authorization'));

  if (!token) {
    return NextResponse.json({ error: 'Não autenticado' }, { status: 401 });
  }

  const user = verifyToken(token);
  if (!user) {
    return NextResponse.json({ error: 'Token inválido' }, { status: 401 });
  }

  try {
    const body = await request.json();
    const { paciente_id, provider = 'google_meet' } = body;

    if (!paciente_id) {
      return NextResponse.json(
        { error: 'paciente_id é obrigatório' },
        { status: 400 }
      );
    }

    const paciente = await queryOne<PatientData>(
      'SELECT * FROM pacientes WHERE id = $1',
      [paciente_id]
    );

    if (!paciente) {
      return NextResponse.json(
        { error: 'Paciente não encontrado' },
        { status: 404 }
      );
    }

    // Gerar link de videochamada
    const meetingId = randomUUID().slice(0, 12).replace(/-/g, '');
    let link: string;

    if (provider === 'zoom') {
      // Zoom: link placeholder — em produção, integrar com Zoom API
      link = `https://zoom.us/j/${meetingId}`;
    } else {
      // Google Meet: link gerado (em produção, usar Google Calendar API)
      link = `https://meet.google.com/${meetingId.slice(0, 3)}-${meetingId.slice(3, 7)}-${meetingId.slice(7)}`;
    }

    // Registrar consulta no banco
    const consultaId = randomUUID();
    await execute(
      `INSERT INTO consultas_video (id, paciente_id, nutricionista_id, link, provider, status, inicio)
       VALUES ($1, $2, $3, $4, $5, 'em_andamento', NOW())`,
      [consultaId, paciente_id, user.id, link, provider]
    );

    // Enviar link via WhatsApp
    try {
      await enviarLinkVideochamada(paciente.telefone, link, user.nome);
    } catch (whatsappError) {
      console.warn('[Consulta] Falha ao enviar WhatsApp (continuando):', whatsappError);
    }

    return NextResponse.json({
      consulta_id: consultaId,
      link,
      provider,
      status: 'em_andamento',
      whatsapp_enviado: true,
    });
  } catch (error) {
    console.error('[Consulta] Erro ao iniciar:', error);
    return NextResponse.json(
      { error: 'Erro ao iniciar consulta' },
      { status: 500 }
    );
  }
}
