"""Поведение parse_source_job при «зависшем» running (падение воркера, повтор SAQ)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from app.services.processing.jobs import JobStatus
from app.services.processing.saq_tasks import parse_source_job


class _FakeSession:
    def __init__(self, run: SimpleNamespace, pj: SimpleNamespace | None) -> None:
        self._run = run
        self._pj = pj
        self.commits = 0

    async def get(self, model, item_id):  # noqa: ANN001
        if item_id == self._run.id:
            return self._run
        if self._pj is not None and item_id == self._pj.id:
            return self._pj
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass


class TestParseSourceJobStaleRunning(IsolatedAsyncioTestCase):
    async def test_stale_running_marks_run_and_job_failed(self) -> None:
        run_id = uuid.uuid4()
        pj_id = uuid.uuid4()
        old = datetime.now(UTC) - timedelta(hours=5)
        run = SimpleNamespace(
            id=run_id,
            status="running",
            started_at=old,
            processing_job_id=pj_id,
            source_id=uuid.uuid4(),
            days=7,
            skip_undated=False,
            created_by_id=None,
        )
        pj = SimpleNamespace(
            id=pj_id,
            status=JobStatus.RUNNING,
        )
        fake = _FakeSession(run, pj)

        @asynccontextmanager
        async def _cm():
            yield fake

        with patch("app.services.processing.saq_tasks.AsyncSessionLocal", return_value=_cm()):
            out = await parse_source_job({}, parse_run_id=str(run_id))

        self.assertEqual(out["status"], "failed")
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.phase, "failed")
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(pj.status, JobStatus.FAILED)
        self.assertEqual(fake.commits, 1)

    async def test_running_recent_still_skipped(self) -> None:
        run_id = uuid.uuid4()
        recent = datetime.now(UTC) - timedelta(minutes=1)
        run = SimpleNamespace(
            id=run_id,
            status="running",
            started_at=recent,
            processing_job_id=None,
            source_id=uuid.uuid4(),
            days=7,
            skip_undated=False,
            created_by_id=None,
        )
        fake = _FakeSession(run, None)

        @asynccontextmanager
        async def _cm():
            yield fake

        with patch("app.services.processing.saq_tasks.AsyncSessionLocal", return_value=_cm()):
            out = await parse_source_job({}, parse_run_id=str(run_id))

        self.assertEqual(out["status"], "skipped")
        self.assertEqual(run.status, "running")
