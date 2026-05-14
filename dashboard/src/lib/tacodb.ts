import { query } from './db';
import type { TacoAlimento } from '@/types/patient';

/**
 * Busca alimentos na tabela TACO relevantes ao objetivo do paciente.
 * Usa busca textual simples no PostgreSQL (ts_vector quando disponível).
 */
export async function buscarAlimentosTACO(
  objetivo: string,
  limite: number = 15
): Promise<TacoAlimento[]> {
  try {
    // Busca por similaridade textual usando ILIKE como fallback robusto
    const termos = extrairTermosBusca(objetivo);
    
    if (termos.length === 0) {
      // Retorna alimentos genéricos saudáveis
      return await query<TacoAlimento>(
        `SELECT id, descricao, energia_kcal, proteina_g, lipideos_g, carboidrato_g, fibra_g
         FROM taco_alimentos
         ORDER BY RANDOM()
         LIMIT $1`,
        [limite]
      );
    }

    const conditions = termos.map((_, i) => `descricao ILIKE $${i + 1}`).join(' OR ');
    const params = termos.map(t => `%${t}%`);
    params.push(String(limite));

    return await query<TacoAlimento>(
      `SELECT id, descricao, energia_kcal, proteina_g, lipideos_g, carboidrato_g, fibra_g
       FROM taco_alimentos
       WHERE ${conditions}
       ORDER BY energia_kcal ASC
       LIMIT $${params.length}`,
      params
    );
  } catch (error) {
    console.error('[TACO] Erro ao buscar alimentos:', error);
    return [];
  }
}

function extrairTermosBusca(objetivo: string): string[] {
  const mapa: Record<string, string[]> = {
    emagrecimento: ['frango', 'peixe', 'salada', 'ovo', 'legume', 'fruta'],
    'ganho de massa': ['frango', 'ovo', 'arroz', 'batata', 'carne', 'leite'],
    hipertrofia: ['frango', 'ovo', 'whey', 'carne', 'arroz', 'batata'],
    diabetes: ['aveia', 'legume', 'peixe', 'ovo', 'folhoso'],
    hipertensão: ['fruta', 'legume', 'peixe', 'aveia', 'banana'],
    gestante: ['leite', 'ovo', 'fruta', 'carne', 'feijão', 'arroz'],
  };

  const objetivoLower = objetivo.toLowerCase();
  for (const [chave, termos] of Object.entries(mapa)) {
    if (objetivoLower.includes(chave)) return termos;
  }

  // Fallback: usar palavras do objetivo como termos
  return objetivoLower
    .split(/\s+/)
    .filter(p => p.length > 3)
    .slice(0, 4);
}
