import sqlite3
import json
import os
from datetime import datetime
from threading import Lock
from pathlib import Path

# Use absolute path to ensure DB is found
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "../../data")
DB_PATH = os.getenv("DATABASE_PATH", str(Path(__file__).parent.parent.parent / "data" / "deployments.db"))

class Database:
    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(Database, cls).__new__(cls)
                    cls._instance._init_db()
        return cls._instance

    def _get_connection(self):
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row  
        return conn

    def _init_db(self):
        db_dir = Path(DB_PATH).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        
        with self._get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS deployments (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    scenario TEXT,
                    status TEXT,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP,
                    outputs TEXT,
                    error TEXT
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_hash TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TIMESTAMP,
                    last_used_at TIMESTAMP,
                    revoked INTEGER NOT NULL DEFAULT 0
                )
            ''')
            conn.commit()

    def create_deployment(self, deployment_id, user_id, scenario):
        with self._get_connection() as conn:
            conn.execute('''
                INSERT INTO deployments (id, user_id, scenario, status, created_at, updated_at, outputs)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (deployment_id, user_id, scenario, 'pending', datetime.now(), datetime.now(), '{}'))
            conn.commit()
        return deployment_id

    def update_deployment(self, deployment_id, status=None, outputs=None, error=None):
        updates = ["updated_at = ?"]
        params = [datetime.now()]

        if status:
            updates.append("status = ?")
            params.append(status)
        if outputs is not None:
            updates.append("outputs = ?")
            params.append(json.dumps(outputs))
        if error is not None:
            updates.append("error = ?")
            params.append(error)

        params.append(deployment_id)
        # The dynamic part is a fixed allowlist of column assignments above;
        # every value goes through a ? placeholder — no injection surface.
        query = f"UPDATE deployments SET {', '.join(updates)} WHERE id = ?"  # nosec B608

        with self._get_connection() as conn:
            conn.execute(query, params)
            conn.commit()

    def get_deployment(self, deployment_id):
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM deployments WHERE id = ?", (deployment_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def list_deployments(self):
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM deployments ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def delete_deployment(self, deployment_id):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM deployments WHERE id = ?", (deployment_id,))
            conn.commit()

    # --- API keys (ADR-0002) -------------------------------------------------
    # Only SHA-256 digests are stored; plaintext keys never touch the DB.

    def create_api_key(self, key_hash, name, role):
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO api_keys (key_hash, name, role, created_at) "
                "VALUES (?, ?, ?, ?)",
                (key_hash, name, role, datetime.now()),
            )
            conn.commit()

    def get_api_key(self, key_hash):
        """Return the active (non-revoked) key record, updating last_used_at."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM api_keys WHERE key_hash = ? AND revoked = 0",
                (key_hash,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?",
                (datetime.now(), key_hash),
            )
            conn.commit()
            return dict(row)

    def count_api_keys(self):
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) AS n FROM api_keys WHERE revoked = 0"
            )
            return cursor.fetchone()["n"]

    def revoke_api_keys_by_name(self, name):
        """Revoke (not delete: keep the audit trail) all keys with this name."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE api_keys SET revoked = 1 WHERE name = ? AND revoked = 0",
                (name,),
            )
            conn.commit()
            return cursor.rowcount