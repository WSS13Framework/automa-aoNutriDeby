export interface PatientData {
  id: string;
  nome: string;
  email: string;
  telefone: string;
  foto_url?: string;
  data_nascimento: string;
  idade: number;
  sexo: 'M' | 'F';
  altura_cm: number;
  peso_kg: number;
  imc: number;
  objetivo: string;
  restricoes_alimentares: string[];
  patologias: string[];
  medicamentos: string[];
  created_at: string;
  updated_at: string;
}

export interface MetaNutricional {
  id: string;
  paciente_id: string;
  descricao: string;
  valor_atual: number;
  valor_meta: number;
  unidade: string;
  progresso: number; // 0-100
}

export interface EngagementData {
  dia: string;
  mensagens: number;
  respostas: number;
}

export interface AlertaClinico {
  id: string;
  paciente_id: string;
  tipo: 'sem_resposta' | 'exame_alterado' | 'meta_atrasada' | 'peso_critico';
  mensagem: string;
  severidade: 'baixa' | 'media' | 'alta';
  created_at: string;
  lido: boolean;
}

export interface SugestaoConduta {
  id: string;
  paciente_id: string;
  texto: string;
  baseado_em: string;
  gerado_em: string;
  aprovado: boolean;
  editado: boolean;
}

export interface MensagemWhatsApp {
  id: string;
  paciente_id: string;
  direcao: 'entrada' | 'saida';
  conteudo: string;
  timestamp: string;
}

export interface ConsultaVideo {
  id: string;
  paciente_id: string;
  link: string;
  provider: 'google_meet' | 'zoom';
  status: 'agendada' | 'em_andamento' | 'finalizada';
  inicio: string;
  fim?: string;
}

export interface LLMResponse {
  sugestao: string;
  baseado_em: string;
  confianca: number;
  alimentos_taco: TacoAlimento[];
}

export interface TacoAlimento {
  id: number;
  descricao: string;
  energia_kcal: number;
  proteina_g: number;
  lipideos_g: number;
  carboidrato_g: number;
  fibra_g: number;
}

export interface UserSession {
  id: string;
  email: string;
  nome: string;
  role: 'nutricionista' | 'admin';
}
