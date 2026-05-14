const EVOLUTION_API_URL = process.env.EVOLUTION_API_URL || '';
const EVOLUTION_API_KEY = process.env.EVOLUTION_API_KEY || '';

interface SendMessagePayload {
  number: string;
  text: string;
}

interface SendMessageResponse {
  key: {
    remoteJid: string;
    fromMe: boolean;
    id: string;
  };
  message: {
    conversation: string;
  };
  messageTimestamp: string;
  status: string;
}

/**
 * Envia mensagem de texto via Evolution API (WhatsApp).
 * Formata o número para o padrão internacional (55 + DDD + número).
 */
export async function enviarMensagemWhatsApp(
  telefone: string,
  mensagem: string
): Promise<SendMessageResponse> {
  if (!EVOLUTION_API_URL || !EVOLUTION_API_KEY) {
    throw new Error('[WhatsApp] EVOLUTION_API_URL ou EVOLUTION_API_KEY não configuradas');
  }

  const numero = formatarTelefone(telefone);

  const payload: SendMessagePayload = {
    number: numero,
    text: mensagem,
  };

  const response = await fetch(`${EVOLUTION_API_URL}/message/sendText/nutrideby`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      apikey: EVOLUTION_API_KEY,
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`[WhatsApp] Erro ${response.status}: ${errorBody}`);
  }

  return response.json();
}

/**
 * Envia link de videochamada para o paciente via WhatsApp.
 */
export async function enviarLinkVideochamada(
  telefone: string,
  linkVideo: string,
  nomeNutricionista: string
): Promise<SendMessageResponse> {
  const mensagem = `🩺 *NutriDeby - Consulta Online*\n\nOlá! Sua nutricionista ${nomeNutricionista} está iniciando uma videochamada.\n\nAcesse o link abaixo para entrar na consulta:\n${linkVideo}\n\n_Caso tenha dificuldades, responda esta mensagem._`;

  return enviarMensagemWhatsApp(telefone, mensagem);
}

function formatarTelefone(telefone: string): string {
  // Remove tudo que não é dígito
  const digits = telefone.replace(/\D/g, '');

  // Se já tem 55 no início e tem 12-13 dígitos, retorna como está
  if (digits.startsWith('55') && digits.length >= 12) {
    return digits;
  }

  // Se tem 10-11 dígitos (DDD + número), adiciona 55
  if (digits.length >= 10 && digits.length <= 11) {
    return `55${digits}`;
  }

  return digits;
}
