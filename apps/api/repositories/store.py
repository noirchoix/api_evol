from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import settings


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class AssuranceStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path=Path(db_path or settings.db_path)
        self.db_path.parent.mkdir(parents=True,exist_ok=True)
        self._lock=threading.RLock()
        self._init()

    def connect(self) -> sqlite3.Connection:
        conn=sqlite3.connect(self.db_path,timeout=30,check_same_thread=False)
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        return conn

    def _init(self) -> None:
        with self._lock,self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS contracts(
              id TEXT PRIMARY KEY, source_name TEXT NOT NULL, canonical_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS repositories(
              id TEXT PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL, root_path TEXT NOT NULL,
              index_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analyses(
              id TEXT PRIMARY KEY, request_json TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            ''')

    def put_contract(self,contract_id:str,source_name:str,canonical:dict[str,Any]) -> None:
        with self._lock,self.connect() as c:
            c.execute('INSERT OR REPLACE INTO contracts(id,source_name,canonical_json,created_at) VALUES (?,?,?,?)',(contract_id,source_name,json.dumps(canonical),utcnow()))

    def get_contract(self,contract_id:str) -> dict[str,Any] | None:
        with self.connect() as c: row=c.execute('SELECT canonical_json FROM contracts WHERE id=?',(contract_id,)).fetchone()
        return json.loads(row['canonical_json']) if row else None

    def put_repository(self,repo_id:str,filename:str,sha256:str,root_path:str,index:dict[str,Any]) -> None:
        with self._lock,self.connect() as c:
            c.execute('INSERT OR REPLACE INTO repositories(id,filename,sha256,root_path,index_json,created_at) VALUES (?,?,?,?,?,?)',(repo_id,filename,sha256,root_path,json.dumps(index),utcnow()))

    def get_repository(self,repo_id:str) -> dict[str,Any] | None:
        with self.connect() as c: row=c.execute('SELECT * FROM repositories WHERE id=?',(repo_id,)).fetchone()
        if not row: return None
        d=dict(row); d['index']=json.loads(d.pop('index_json')); return d

    def put_analysis(self,analysis_id:str,request:dict[str,Any],response:dict[str,Any]) -> None:
        with self._lock,self.connect() as c:
            c.execute('INSERT INTO analyses(id,request_json,response_json,created_at) VALUES (?,?,?,?)',(analysis_id,json.dumps(request),json.dumps(response),response['created_at']))

    def get_analysis(self,analysis_id:str) -> dict[str,Any] | None:
        with self.connect() as c: row=c.execute('SELECT response_json FROM analyses WHERE id=?',(analysis_id,)).fetchone()
        return json.loads(row['response_json']) if row else None

    def counts(self) -> tuple[int,int]:
        with self.connect() as c:
            analyses=int(c.execute('SELECT COUNT(*) FROM analyses').fetchone()[0]); repos=int(c.execute('SELECT COUNT(*) FROM repositories').fetchone()[0])
        return analyses,repos
