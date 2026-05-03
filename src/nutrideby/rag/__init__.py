"""RAG por paciente (pgvector + embeddings OpenAI-compatible)."""

from nutrideby.rag.clinical_analyst_prompts import build_system_prompt
from nutrideby.rag.exam_hit_preprocess import extract_and_compare_exams
from nutrideby.rag.patient_retrieve import patient_retrieve

__all__ = ["patient_retrieve", "build_system_prompt", "extract_and_compare_exams"]
