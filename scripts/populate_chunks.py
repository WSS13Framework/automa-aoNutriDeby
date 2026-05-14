import os
import sys
import uuid
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

# Adicionar src ao PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from nutrideby.config import Settings
from nutrideby.workers.chunk_documents import chunk_patient_documents
from nutrideby.workers.embed_chunks import embed_patient_chunks

def main():
    load_dotenv()
    settings = Settings()
    
    if not settings.openai_api_key:
        print("ERRO: OPENAI_API_KEY não definida no .env")
        sys.exit(1)
        
    print(f"Conectando ao banco de dados: {settings.database_url}")
    
    try:
        with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                # Buscar todos os pacientes que têm documentos
                cur.execute("""
                    SELECT DISTINCT p.id 
                    FROM patients p
                    JOIN documents d ON d.patient_id = p.id
                """)
                patients = cur.fetchall()
                
                print(f"Encontrados {len(patients)} pacientes com documentos.")
                
                for p in patients:
                    patient_id = p['id']
                    print(f"\nProcessando paciente: {patient_id}")
                    
                    # 1. Gerar chunks
                    print("  -> Gerando chunks...")
                    try:
                        chunk_patient_documents(conn, patient_id=patient_id)
                        conn.commit()
                    except Exception as e:
                        print(f"  -> Erro ao gerar chunks: {e}")
                        conn.rollback()
                        continue
                        
                    # 2. Gerar embeddings
                    print("  -> Gerando embeddings...")
                    try:
                        embed_patient_chunks(
                            conn, 
                            patient_id=patient_id,
                            api_base=settings.openai_api_base,
                            api_key=settings.openai_api_key,
                            model=settings.openai_embedding_model
                        )
                        conn.commit()
                    except Exception as e:
                        print(f"  -> Erro ao gerar embeddings: {e}")
                        conn.rollback()
                        
        print("\nProcessamento concluído com sucesso!")
        
    except Exception as e:
        print(f"Erro fatal: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
