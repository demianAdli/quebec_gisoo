"""
QuebecGISOO project
batch_jobs module
Persistent SQLite job queue and execution locks for FSA batches.
Project Designer and Developer: Alireza Adli
alireza.adli@mail.concordia.ca
alireza.adli4@gmail.com
www.demianadli.com
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone


JOB_STORE_PATH_ENV = 'JUG_GIS_CITIES_JOB_STORE_PATH'
DEFAULT_JOB_STORE_PATH = os.path.abspath(
    os.path.join(tempfile.gettempdir(), 'jug_gis_cities_jobs.sqlite3'))

QUEUED = 'queued'
RUNNING = 'running'
SUCCEEDED = 'succeeded'
FAILED = 'failed'
TERMINAL_STATUSES = (SUCCEEDED, FAILED)
_STORES_BY_PATH = {}


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _json_dump(value):
    return json.dumps(value, separators=(',', ':'))


def _json_load(value, default=None):
    if value is None:
        return default
    return json.loads(value)


@dataclass(frozen=True)
class BatchJob:
    """Persisted FSA batch job configuration and progress."""

    batch_id: str
    component_name: str
    mode: str
    requested_fsas: tuple[str, ...] | None
    all_fsas: bool
    max_workers: int
    non_null_required_fields: tuple[str, ...] | None
    cleanup_outputs: bool
    keep_outputs: tuple[str, ...] | None
    status: str
    resolved_fsas: tuple[str, ...] | None
    results: tuple[dict, ...]
    error: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    worker_id: str | None

    @property
    def total_count(self):
        fsas = self.resolved_fsas or self.requested_fsas or ()
        return len(fsas)

    @property
    def completed_count(self):
        return len(self.results)

    @property
    def succeeded_count(self):
        return sum(1 for result in self.results if result.get('succeeded'))

    @property
    def failed_count(self):
        return sum(1 for result in self.results
                   if not result.get('succeeded'))

    def to_response(self):
        return {
            'batch_id': self.batch_id,
            'component_name': self.component_name,
            'mode': self.mode,
            'status': self.status,
            'all_fsas': self.all_fsas,
            'fsas': (list(self.resolved_fsas)
                     if self.resolved_fsas is not None else
                     (list(self.requested_fsas)
                      if self.requested_fsas is not None else None)),
            'max_workers': self.max_workers,
            'cleanup_outputs': self.cleanup_outputs,
            'keep_outputs': (list(self.keep_outputs)
                             if self.keep_outputs is not None else None),
            'total_count': self.total_count,
            'completed_count': self.completed_count,
            'succeeded_count': self.succeeded_count,
            'failed_count': self.failed_count,
            'results': list(self.results),
            'error': self.error,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'started_at': self.started_at,
            'finished_at': self.finished_at,
        }


class SqliteBatchJobStore:
    """Small persistent queue suitable for one Docker batch worker."""

    def __init__(self, path=None):
        self.path = os.path.abspath(
            path or os.getenv(JOB_STORE_PATH_ENV, DEFAULT_JOB_STORE_PATH))
        parent_dir = os.path.dirname(self.path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA busy_timeout = 30000')
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self):
        with self._connect() as connection:
            connection.execute('PRAGMA journal_mode = WAL')
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS batch_jobs (
                    batch_id TEXT PRIMARY KEY,
                    component_name TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    requested_fsas_json TEXT,
                    all_fsas INTEGER NOT NULL,
                    max_workers INTEGER NOT NULL,
                    non_null_fields_json TEXT,
                    cleanup_outputs INTEGER NOT NULL,
                    keep_outputs_json TEXT,
                    status TEXT NOT NULL,
                    resolved_fsas_json TEXT,
                    results_json TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    worker_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_batch_jobs_status_created
                    ON batch_jobs(status, created_at);
                CREATE TABLE IF NOT EXISTS fsa_execution_locks (
                    component_name TEXT NOT NULL,
                    fsa TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    PRIMARY KEY(component_name, fsa)
                );
                """)

    @staticmethod
    def _row_to_job(row):
        if row is None:
            return None
        requested_fsas = _json_load(row['requested_fsas_json'])
        resolved_fsas = _json_load(row['resolved_fsas_json'])
        non_null_fields = _json_load(row['non_null_fields_json'])
        keep_outputs = _json_load(row['keep_outputs_json'])
        return BatchJob(
            batch_id=row['batch_id'],
            component_name=row['component_name'],
            mode=row['mode'],
            requested_fsas=(tuple(requested_fsas)
                            if requested_fsas is not None else None),
            all_fsas=bool(row['all_fsas']),
            max_workers=row['max_workers'],
            non_null_required_fields=(
                tuple(non_null_fields)
                if non_null_fields is not None else None),
            cleanup_outputs=bool(row['cleanup_outputs']),
            keep_outputs=(tuple(keep_outputs)
                          if keep_outputs is not None else None),
            status=row['status'],
            resolved_fsas=(tuple(resolved_fsas)
                           if resolved_fsas is not None else None),
            results=tuple(_json_load(row['results_json'], [])),
            error=row['error'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            started_at=row['started_at'],
            finished_at=row['finished_at'],
            worker_id=row['worker_id'])

    def create_job(
            self,
            component_name,
            mode,
            requested_fsas,
            all_fsas,
            max_workers,
            non_null_required_fields=None,
            cleanup_outputs=False,
            keep_outputs=None):
        batch_id = uuid.uuid4().hex
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO batch_jobs (
                    batch_id, component_name, mode, requested_fsas_json,
                    all_fsas, max_workers, non_null_fields_json,
                    cleanup_outputs, keep_outputs_json, status,
                    results_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    component_name,
                    mode,
                    (_json_dump(list(requested_fsas))
                     if requested_fsas is not None else None),
                    int(all_fsas),
                    max_workers,
                    (_json_dump(list(non_null_required_fields))
                     if non_null_required_fields is not None else None),
                    int(cleanup_outputs),
                    (_json_dump(list(keep_outputs))
                     if keep_outputs is not None else None),
                    QUEUED,
                    '[]',
                    now,
                    now,
                ))
        return self.get_job(batch_id)

    def get_job(self, batch_id, component_name=None):
        query = 'SELECT * FROM batch_jobs WHERE batch_id = ?'
        params = [batch_id]
        if component_name is not None:
            query += ' AND component_name = ?'
            params.append(component_name)
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return self._row_to_job(row)

    def claim_next_job(self, worker_id):
        now = _utc_now()
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute(
                """
                SELECT * FROM batch_jobs
                WHERE status = ?
                ORDER BY created_at, batch_id
                LIMIT 1
                """,
                (QUEUED,)).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE batch_jobs
                SET status = ?, worker_id = ?, started_at = ?,
                    updated_at = ?, error = NULL
                WHERE batch_id = ? AND status = ?
                """,
                (RUNNING, worker_id, now, now, row['batch_id'], QUEUED))
            connection.commit()
        return self.get_job(row['batch_id'])

    def set_resolved_fsas(self, batch_id, fsas):
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE batch_jobs
                SET resolved_fsas_json = ?, updated_at = ?
                WHERE batch_id = ?
                """,
                (_json_dump(list(fsas)), now, batch_id))

    def record_result(self, batch_id, result):
        result_data = dict(result)
        now = _utc_now()
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute(
                """
                SELECT results_json, resolved_fsas_json
                FROM batch_jobs WHERE batch_id = ?
                """,
                (batch_id,)).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(f'Batch job not found: {batch_id}')
            results = _json_load(row['results_json'], [])
            results.append(result_data)
            resolved_fsas = _json_load(row['resolved_fsas_json'], [])
            fsa_order = {
                fsa: index for index, fsa in enumerate(resolved_fsas)
            }
            results.sort(key=lambda item: fsa_order.get(
                item.get('fsa'),
                len(fsa_order)))
            connection.execute(
                """
                UPDATE batch_jobs
                SET results_json = ?, updated_at = ?
                WHERE batch_id = ?
                """,
                (_json_dump(results), now, batch_id))
            connection.commit()

    def set_results(self, batch_id, results):
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE batch_jobs
                SET results_json = ?, updated_at = ?
                WHERE batch_id = ?
                """,
                (_json_dump(list(results)), now, batch_id))

    def complete_job(self, batch_id, succeeded):
        now = _utc_now()
        status = SUCCEEDED if succeeded else FAILED
        error = None if succeeded else 'One or more FSA runs failed.'
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE batch_jobs
                SET status = ?, error = ?, updated_at = ?, finished_at = ?
                WHERE batch_id = ?
                """,
                (status, error, now, now, batch_id))

    def fail_job(self, batch_id, error):
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE batch_jobs
                SET status = ?, error = ?, updated_at = ?, finished_at = ?
                WHERE batch_id = ?
                """,
                (FAILED, str(error), now, now, batch_id))

    def requeue_job(self, batch_id, error=None):
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE batch_jobs
                SET status = ?, worker_id = NULL, started_at = NULL,
                    updated_at = ?, error = ?
                WHERE batch_id = ?
                """,
                (QUEUED, now, error, batch_id))

    def acquire_fsa_locks(self, owner_id, component_name, fsas):
        normalized_fsas = tuple(fsas)
        now = _utc_now()
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            placeholders = ','.join('?' for _ in normalized_fsas)
            if normalized_fsas:
                conflict = connection.execute(
                    f"""
                    SELECT fsa, owner_id FROM fsa_execution_locks
                    WHERE component_name = ?
                      AND fsa IN ({placeholders})
                      AND owner_id != ?
                    LIMIT 1
                    """,
                    (component_name, *normalized_fsas, owner_id)).fetchone()
                if conflict is not None:
                    connection.rollback()
                    return False
            for fsa in normalized_fsas:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO fsa_execution_locks (
                        component_name, fsa, owner_id, acquired_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (component_name, fsa, owner_id, now))
            connection.commit()
        return True

    def release_fsa_locks(self, owner_id):
        with self._connect() as connection:
            connection.execute(
                'DELETE FROM fsa_execution_locks WHERE owner_id = ?',
                (owner_id,))

    def recover_running_jobs(self):
        now = _utc_now()
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            rows = connection.execute(
                'SELECT batch_id FROM batch_jobs WHERE status = ?',
                (RUNNING,)).fetchall()
            batch_ids = [row['batch_id'] for row in rows]
            for batch_id in batch_ids:
                connection.execute(
                    'DELETE FROM fsa_execution_locks WHERE owner_id = ?',
                    (batch_id,))
            connection.execute(
                """
                UPDATE batch_jobs
                SET status = ?, worker_id = NULL, started_at = NULL,
                    updated_at = ?, error = ?, results_json = '[]'
                WHERE status = ?
                """,
                (QUEUED, now, 'Recovered after worker restart.', RUNNING))
            connection.commit()
        return len(batch_ids)


def get_batch_job_store():
    """Return a store using the currently configured persistent path."""
    path = os.path.abspath(
        os.getenv(JOB_STORE_PATH_ENV, DEFAULT_JOB_STORE_PATH))
    store = _STORES_BY_PATH.get(path)
    if store is None:
        store = SqliteBatchJobStore(path)
        _STORES_BY_PATH[path] = store
    return store


__all__ = [
    'BatchJob',
    'FAILED',
    'QUEUED',
    'RUNNING',
    'SUCCEEDED',
    'SqliteBatchJobStore',
    'get_batch_job_store',
]
