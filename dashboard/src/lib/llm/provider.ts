import type { PatientData, LLMResponse } from '@/types/patient';

export interface LLMProvider {
  name: string;
  analyze(patientData: PatientData, query: string): Promise<LLMResponse>;
}

export function getLLMProvider(): LLMProvider {
  const providerName = process.env.LLM_PROVIDER || 'deepseek';

  switch (providerName.toLowerCase()) {
    case 'groq':
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const { GroqProvider } = require('./groq');
      return new GroqProvider();
    case 'deepseek':
    default:
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const { DeepSeekProvider } = require('./deepseek');
      return new DeepSeekProvider();
  }
}
