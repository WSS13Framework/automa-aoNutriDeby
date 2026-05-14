import { NextRequest, NextResponse } from 'next/server';
import { verifyToken, extractTokenFromHeader } from '@/lib/auth';
import { queryOne, execute } from '@/lib/db';
import { getLLMProvider } from '@/lib/llm/provider';
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
    const { paciente_id, query: userQuery } = body;

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

    const provider = getLLMProvider();
    const defaultQuery = `Analise o perfil nutricional deste paciente e sugira uma conduta alimentar personalizada, 
    considerando suas restrições, patologias e objetivo. Inclua sugestões de alimentos da tabela TACO 
    com valores nutricionais.`;

    const resultado = await provider.analyze(paciente, userQuery || defaultQuery);

    // Salvar sugestão no banco
    const sugestaoId = randomUUID();
    await execute(
      `INSERT INTO sugestoes_conduta (id, paciente_id, nutricionista_id, texto, baseado_em, gerado_em, aprovado, editado)
       VALUES ($1, $2, $3, $4, $5, NOW(), false, false)`,
      [sugestaoId, paciente_id, user.id, resultado.sugestao, resultado.baseado_em]
    );

    return NextResponse.json({
      sugestao_id: sugestaoId,
      ...resultado,
      provider: provider.name,
    });
  } catch (error) {
    console.error('[Analyze] Erro:', error);
    return NextResponse.json(
      { error: 'Erro ao gerar análise' },
      { status: 500 }
    );
  }
}
