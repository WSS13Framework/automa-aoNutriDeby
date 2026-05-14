/**
 * Cliente HTTP para a API NutriDeby (FastAPI).
 * Roda server-side (Next.js RSC / Route Handlers).
 * Lê NUTRIDEBY_API_URL e NUTRIDEBY_API_KEY do process.env.
 */

const API_URL = process.env.NUTRIDEBY_API_URL || "http://localhost:8081";
const API_KEY = process.env.NUTRIDEBY_API_KEY || "";

interface FetchOptions {
  path: string;
  method?: string;
  body?: unknown;
  revalidate?: number;
}

export async function apiFetch<T>(opts: FetchOptions): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (API_KEY) {
    headers["X-API-Key"] = API_KEY;
  }

  const res = await fetch(`${API_URL}${opts.path}`, {
    method: opts.method || "GET",
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    next: { revalidate: opts.revalidate ?? 30 },
  });

  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// ── Tipos ────────────────────────────────────────────────────

export interface Patient {
  id: string;
  source_system: string;
  external_id: string;
  display_name: string | null;
  updated_at: string;
}

export interface PatientDetail extends Patient {
  metadata: Record<string, unknown>;
  documents_count: number;
}

export interface Document {
  id: string;
  doc_type: string;
  collected_at: string;
  content_preview: string;
}

export interface RagCoverage {
  patient_id: string;
  source_system: string;
  external_id: string;
  display_name: string | null;
  chunks_total: number;
  chunks_embedded: number;
  chunks_missing_embedding: number;
  placeholder_prontuario_embedded: number;
  usable_embedded_chunks: number;
}

export interface RetrieveHit {
  chunk_id: string;
  document_id: string | null;
  chunk_index: number;
  distance: number;
  score: number;
  text: string;
}

export interface RetrieveResponse {
  query: string;
  embedding_model: string;
  hits: RetrieveHit[];
  embedding_cache_hit: boolean;
}

// ── Funções ──────────────────────────────────────────────────

export function listPatients(limit = 50, offset = 0) {
  return apiFetch<Patient[]>({ path: `/v1/patients?limit=${limit}&offset=${offset}` });
}

export function getPatient(id: string) {
  return apiFetch<PatientDetail>({ path: `/v1/patients/${id}` });
}

export function getPatientDocuments(id: string) {
  return apiFetch<Document[]>({ path: `/v1/patients/${id}/documents` });
}

export function getRagCoverage(limit = 200) {
  return apiFetch<RagCoverage[]>({ path: `/v1/patients/rag-coverage?limit=${limit}` });
}

export function retrievePatient(patientId: string, query: string, k = 5) {
  return apiFetch<RetrieveResponse>({
    path: `/v1/patients/${patientId}/retrieve`,
    method: "POST",
    body: { query, k },
    revalidate: 0,
  });
}
