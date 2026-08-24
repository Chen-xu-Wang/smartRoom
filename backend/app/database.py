"""SQLite database for work orders and maintenance records."""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from .config import DB_PATH

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS work_orders (
            id TEXT PRIMARY KEY,
            house_id TEXT NOT NULL,
            location TEXT,
            fault_type TEXT,
            user_description TEXT,
            related_equipment TEXT,
            ai_analysis TEXT,
            suggested_trade TEXT,
            urgency TEXT,
            status TEXT DEFAULT 'pending_review',
            confidence INTEGER DEFAULT 0,
            created_at TEXT,
            reviewed_by TEXT,
            reviewed_at TEXT,
            review_notes TEXT,
            assigned_to TEXT,
            completed_at TEXT,
            actual_fault TEXT,
            actual_action TEXT,
            used_parts TEXT,
            repair_person TEXT,
            result TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_records (
            id TEXT PRIMARY KEY,
            house_id TEXT NOT NULL,
            work_order_id TEXT,
            date TEXT,
            location TEXT,
            fault TEXT,
            cause TEXT,
            action TEXT,
            repair_person TEXT,
            result TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            house_id TEXT NOT NULL,
            messages TEXT,
            extracted_info TEXT,
            agent_state TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    conn.commit()
    conn.close()

def execute_query(query, params=(), fetchone=False, fetchall=False, commit=False):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(query, params)
    result = None
    if fetchone:
        result = dict(cursor.fetchone()) if cursor.fetchone() else None
    elif fetchall:
        rows = cursor.fetchall()
        result = [dict(r) for r in rows]
    if commit:
        conn.commit()
    conn.close()
    return result
