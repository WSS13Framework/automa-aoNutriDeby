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

// ── Sprint unificação: stats, PATCH, reactivation, notes, timeline ──

export interface PatientStats {
  total: number;
  active: number;
  trial: number;
  inactive: number;
  expired: number;
  reactivation_responded: number;
  reactivation_scheduled: number;
  reactivation_reactivated: number;
}

export type ReactivationStage = "responded" | "scheduled" | "reactivated";

export interface PatientUpdateResult {
  id: string;
  display_name: string | null;
  email: string | null;
  subscription_status: string | null;
  reactivation_stage: string | null;
  updated_at: string | null;
}

export interface PatientNote {
  id: string;
  author: string | null;
  note: string;
  created_at: string | null;
}

export interface TimelineEvent {
  ts: string | null;
  kind: string;
  summary: string | null;
}

export function getPatientStats() {
  return apiFetch<PatientStats>({ path: `/v1/patients/stats`, revalidate: 10 });
}

export function updatePatient(id: string, data: Record<string, unknown>) {
  return apiFetch<PatientUpdateResult>({
    path: `/v1/patients/${id}`,
    method: "PATCH",
    body: data,
    revalidate: 0,
  });
}

export function updateReactivationStage(
  id: string,
  stage: ReactivationStage,
  notes?: string,
) {
  return apiFetch<{ status: string; patient_id: string; stage: string; stage_at: string | null }>({
    path: `/v1/patients/${id}/reactivation-stage`,
    method: "PATCH",
    body: { stage, notes },
    revalidate: 0,
  });
}

export function addPatientNote(id: string, note: string, author?: string) {
  return apiFetch<PatientNote>({
    path: `/v1/patients/${id}/notes`,
    method: "POST",
    body: { note, author },
    revalidate: 0,
  });
}

export function getPatientNotes(id: string, limit = 50) {
  return apiFetch<PatientNote[]>({
    path: `/v1/patients/${id}/notes?limit=${limit}`,
    revalidate: 0,
  });
}

export function getPatientTimeline(id: string, limit = 100) {
  return apiFetch<TimelineEvent[]>({
    path: `/v1/patients/${id}/timeline?limit=${limit}`,
    revalidate: 0,
  });
}

// ── Evolução do Paciente ──────────────────────────────────────────────────────

export interface WeeklyCalories {
  week: string;
  days_logged: number;
  avg_calories: number;
  avg_protein: number;
}

export interface BodyScanSummary {
  id: string;
  created_at: string;
  body_fat_pct: number | null;
  muscle_mass_pct: number | null;
  lean_mass_kg: number | null;
  analysis_notes: string | null;
}

export interface MedidaSummary {
  descricao: string | null;
  data: string | null;
  peso_kg: number | null;
  imc: number | null;
}

export interface PatientEvolution {
  patient_id: string;
  display_name: string | null;
  streak: number;
  longest_streak: number;
  deby_level: number;
  deby_xp: number;
  calories_target: number | null;
  protein_target: number | null;
  weekly_calories: WeeklyCalories[];
  body_scans: BodyScanSummary[];
  medidas: MedidaSummary[];
  total_food_logs_30d: number;
}

export function getPatientEvolution(id: string, days = 90) {
  return apiFetch<PatientEvolution>({
    path: `/v1/patients/${id}/evolution?days=${days}`,
    revalidate: 0,
  });
}

export function askPatient(id: string, question: string) {
  return apiFetch<{ answer: string }>({
    path: `/v1/patients/${id}/ask`,
    method: "POST",
    body: { question },
    revalidate: 0,
  });
}
