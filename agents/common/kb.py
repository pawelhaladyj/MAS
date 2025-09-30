import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

DSN = os.getenv("MAS_DB_DSN", "postgresql://mas_user:pass2835@127.0.0.1:5432/mas")

@contextmanager
def get_conn():
    conn = psycopg2.connect(DSN)
    try:
        yield conn
    finally:
        conn.close()

def put_fact(conversation_id: str, slot: str, value: dict):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO facts (conversation_id, slot, value) VALUES (%s, %s, %s)",
            (conversation_id, slot, psycopg2.extras.Json(value)),
        )
        conn.commit()

def get_fact(conversation_id: str, slot: str):
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(
            "SELECT value FROM facts WHERE conversation_id=%s AND slot=%s "
            "ORDER BY created_at DESC LIMIT 1",
            (conversation_id, slot),
        )
        row = cur.fetchone()
        return dict(row["value"]) if row else None

def query_offers(conversation_id: str):
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(
            "SELECT provider, offer, score FROM offers WHERE conversation_id=%s "
            "ORDER BY score DESC NULLS LAST",
            (conversation_id,),
        )
        return [
            {"provider": r["provider"], "offer": dict(r["offer"]), "score": r["score"]}
            for r in cur.fetchall()
        ]
        
def list_facts(conversation_id: str):
    """Zwróć listę (slot, value, created_at) dla danej sesji."""
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(
            "SELECT slot, value, created_at FROM facts WHERE conversation_id=%s ORDER BY created_at",
            (conversation_id,),
        )
        return [dict(r) for r in cur.fetchall()]
    
def add_offer(conversation_id: str, provider: str, offer: dict, score: float | None = None):
    """Dodaj ofertę do tabeli offers."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO offers (conversation_id, provider, offer, score) VALUES (%s, %s, %s, %s)",
            (conversation_id, provider, psycopg2.extras.Json(offer), score),
        )
        conn.commit()
