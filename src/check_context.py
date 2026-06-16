import json, psycopg, os, sys
sys.path.insert(0, '/app/src')
from psycopg.rows import dict_row

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://nutrideby:nutrideby_dev@postgres:5432/nutrideby')

with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.doc_type, d.content_text
            FROM documents d
            WHERE d.patient_id = (
              SELECT id FROM patients
              WHERE display_name ILIKE '%Icaro%'
              AND source_system='dietbox' LIMIT 1
            )
            ORDER BY d.doc_type, d.collected_at DESC
        """)
        rows = cur.fetchall()

for r in rows:
    ct = r['content_text'] or ''
    print(f"\n{'='*60}")
    print(f"DOC TYPE: {r['doc_type']}")
    if ct.startswith('{') and 'text_summary' in ct:
        try:
            data = json.loads(ct)
            summary = data.get('text_summary','')
            print(summary[:800])
        except:
            print(ct[:400])
    else:
        print(ct[:400])
