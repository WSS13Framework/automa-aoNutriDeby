import type { LLMProvider } from './provider';
import type { PatientData, LLMResponse, TacoAlimento } from '@/types/patient';
import { buscarAlimentosTACO } from '../tacodb';

const DEEPSEEK_API_URL = 'https://api.deepseek.com/v1/chat/completions';

export class DeepSeekProvider implements LLMProvider {
  name = 'deepseek';

  async analyze(patientData: PatientData, query: string): Promise<LLMResponse> {
    const apiKey = process.env.DEEPSEEK_API_KEY;
    if (!apiKey) {
      throw new Error('[DeepSeek] DEEPSEEK_API_KEY não configurada');
    }

    const alimentosTaco = await buscarAlimentosTACO(patientData.objetivo);

    const systemPrompt = `Você é um assistente de nutrição clínica especializado. 
Analise os dados do paciente e a tabela TACO para gerar sugestões de conduta nutricional.
Responda SEMPRE em português brasileiro.
Seja objetivo, prático e baseado em evidências.

Dados do paciente:
- Nome: ${patientData.nome}
- Idade: ${patientData.idade} anos
- Sexo: ${patientData.sexo}
- Peso: ${patientData.peso_kg} kg
- Altura: ${patientData.altura_cm} cm
- IMC: ${patientData.imc}
- Objetivo: ${patientData.objetivo}
- Restrições: ${patientData.restricoes_alimentares.join(', ') || 'Nenhuma'}
- Patologias: ${patientData.patologias.join(', ') || 'Nenhuma'}
- Medicamentos: ${patientData.medicamentos.join(', ') || 'Nenhum'}

Alimentos TACO relevantes:
${alimentosTaco.map(a => `- ${a.descricao}: ${a.energia_kcal}kcal, P:${a.proteina_g}g, C:${a.carboidrato_g}g, L:${a.lipideos_g}g`).join('\n')}`;

    const response = await fetch(DEEPSEEK_API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: 'deepseek-chat',
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: query },
        ],
        temperature: 0.3,
        max_tokens: 2000,
      }),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      throw new Error(`[DeepSeek] API error ${response.status}: ${errorBody}`);
    }

    const data = await response.json();
    const content = data.choices?.[0]?.message?.content || '';

    return {
      sugestao: content,
      baseado_em: 'DeepSeek V3 + Tabela TACO',
      confianca: 0.85,
      alimentos_taco: alimentosTaco,
    };
  }
}
