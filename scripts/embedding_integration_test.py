#!/usr/bin/env python3
"""Интеграционная проверка сценариев векторизации и invalidate (API + БД)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.infrastructure.db.models import (
    Document,
    DocumentCategory,
    DocumentChunk,
    DocumentEmbedding,
    DocumentEntity,
    DocumentTag,
    SourceParseRun,
    Tag,
    User,
)
from app.infrastructure.db.session import AsyncSessionLocal
from app.services.documents.document_embedding import content_fingerprint

API_BASE = "http://127.0.0.1:8000/api/v1"
PARSE_SOURCE_ID = uuid.UUID("ffbc3490-6460-4972-93af-dcb5cfec8f67")  # Минобр Германии
PARSE_DAYS = 2
POLL_SEC = 3
PARSE_TIMEOUT_SEC = 600


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class RunReport:
    checks: list[CheckResult] = field(default_factory=list)

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(CheckResult(name, ok, detail))
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks)


report = RunReport()


async def get_admin_token(session: AsyncSession) -> str:
    uid = await session.scalar(select(User.id).where(User.username == "admin"))
    if uid is None:
        uid = await session.scalar(select(User.id).limit(1))
    if uid is None:
        raise RuntimeError("Нет пользователя для JWT")
    return create_access_token(subject=str(uid))


async def wipe_documents(session: AsyncSession) -> int:
    before = await session.scalar(select(func.count()).select_from(Document)) or 0
    await session.execute(delete(Document))
    await session.commit()
    after = await session.scalar(select(func.count()).select_from(Document)) or 0
    return int(before), int(after)


async def fetch_doc_state(session: AsyncSession, doc_id: uuid.UUID) -> dict[str, Any]:
    doc = await session.get(Document, doc_id)
    if doc is None:
        return {"exists": False}

    chunks = (
        await session.execute(
            select(DocumentChunk.chunk_type, func.count())
            .where(DocumentChunk.document_id == doc_id)
            .group_by(DocumentChunk.chunk_type),
        )
    ).all()
    chunk_map = {row[0]: int(row[1]) for row in chunks}

    emb_count = int(
        await session.scalar(
            select(func.count())
            .select_from(DocumentEmbedding)
            .join(DocumentChunk, DocumentChunk.id == DocumentEmbedding.chunk_id)
            .where(DocumentChunk.document_id == doc_id),
        )
        or 0,
    )

    orig_fp_match = doc.embedding_original_fp == content_fingerprint(doc.original_content or "")
    trans_text = (doc.translated_content or "").strip()
    trans_fp_match = bool(
        trans_text
        and doc.embedding_translated_fp
        and doc.embedding_translated_fp == content_fingerprint(trans_text),
    )

    auto_tags_orig = await _auto_tag_count(session, doc_id, doc.original_language_id)
    auto_tags_trans = 0
    if doc.translated_language_id:
        auto_tags_trans = await _auto_tag_count(session, doc_id, doc.translated_language_id)

    auto_entities = int(
        await session.scalar(
            select(func.count()).select_from(DocumentEntity).where(DocumentEntity.document_id == doc_id),
        )
        or 0,
    )
    auto_categories = int(
        await session.scalar(
            select(func.count()).select_from(DocumentCategory).where(DocumentCategory.document_id == doc_id),
        )
        or 0,
    )

    return {
        "exists": True,
        "title": doc.title,
        "translated_summary": (doc.translated_summary or "")[:80],
        "chunks": chunk_map,
        "embeddings": emb_count,
        "embedding_original_fp": doc.embedding_original_fp,
        "embedding_translated_fp": doc.embedding_translated_fp,
        "embedding_annotation_fp": doc.embedding_annotation_fp,
        "orig_fp_match": orig_fp_match,
        "trans_fp_match": trans_fp_match,
        "original_summary_stale": doc.original_summary_stale,
        "translated_summary_stale": doc.translated_summary_stale,
        "has_translated_summary": bool((doc.translated_summary or "").strip()),
        "auto_tags_orig": auto_tags_orig,
        "auto_tags_trans": auto_tags_trans,
        "auto_entities": auto_entities,
        "auto_categories": auto_categories,
    }


async def _auto_tag_count(session: AsyncSession, doc_id: uuid.UUID, language_id: uuid.UUID) -> int:
    from app.services.documents.db_refs import prediction_source_id

    manual_id = await prediction_source_id(session, "manual")
    return int(
        await session.scalar(
            select(func.count())
            .select_from(DocumentTag)
            .join(Tag, Tag.id == DocumentTag.tag_id)
            .where(
                DocumentTag.document_id == doc_id,
                Tag.language_id == language_id,
                (DocumentTag.prediction_source_id.is_(None) | (DocumentTag.prediction_source_id != manual_id)),
            ),
        )
        or 0,
    )


def _chunks_ok(state: dict[str, Any], *types: str, min_each: int = 1) -> bool:
    for t in types:
        if state["chunks"].get(t, 0) < min_each:
            return False
    return state["embeddings"] >= sum(state["chunks"].get(t, 0) for t in types)


async def wait_parse(
    client: httpx.AsyncClient,
    parse_run_id: uuid.UUID,
    headers: dict[str, str],
) -> dict[str, Any]:
    deadline = time.time() + PARSE_TIMEOUT_SEC
    while time.time() < deadline:
        r = await client.get(
            f"{API_BASE}/parsing/sources/parse-runs/{parse_run_id}",
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
        st = data.get("status")
        if st in ("completed", "failed"):
            return data
        await asyncio.sleep(POLL_SEC)
    raise TimeoutError(f"parse run {parse_run_id} не завершился за {PARSE_TIMEOUT_SEC}s")


async def main() -> int:
    print("=== 0. Подготовка ===")
    async with AsyncSessionLocal() as session:
        token = await get_admin_token(session)
        before, after = await wipe_documents(session)
        print(f"  Удалено документов: {before} → {after}")

    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
        print("\n=== 1. Парсинг источника ===")
        r = await client.post(
            f"{API_BASE}/parsing/sources/parse",
            headers=headers,
            json={
                "source_id": str(PARSE_SOURCE_ID),
                "days": PARSE_DAYS,
                "skip_undated": True,
                "post_parse": None,
            },
        )
        if r.status_code != 202:
            print(r.text)
            r.raise_for_status()
        parse_run_id = uuid.UUID(r.json()["parse_run_id"])
        print(f"  parse_run_id={parse_run_id}")
        outcome = await wait_parse(client, parse_run_id, headers)
        created = outcome.get("created_total") or 0
        print(f"  status={outcome.get('status')} created_total={created}")
        report.record("parse завершился", outcome.get("status") == "completed", str(outcome.get("error_message", "")))

        async with AsyncSessionLocal() as session:
            doc_id = await session.scalar(select(Document.id).order_by(Document.created_at.desc()).limit(1))
        report.record("есть хотя бы 1 документ", doc_id is not None)
        if doc_id is None:
            return 1

        async with AsyncSessionLocal() as session:
            st = await fetch_doc_state(session, doc_id)
        report.record(
            "после parse: original chunks + fp",
            _chunks_ok(st, "original") and st["orig_fp_match"],
            json.dumps(st["chunks"], ensure_ascii=False),
        )

        print(f"\n  Тестовый документ: {doc_id} ({st.get('title', '')[:60]})")

        print("\n=== 2. Теги + сущности + категории (для проверки invalidate) ===")
        for path, key, body in [
            (f"/documents/{doc_id}/tags", "tag", {"max_tags": 5, "use_translation": False}),
            (f"/documents/{doc_id}/entities", "entity", {}),
            (f"/documents/{doc_id}/categorize", "categorize", {}),
        ]:
            try:
                pr = await client.post(f"{API_BASE}{path}", headers=headers, json=body)
                ok = pr.status_code in (200, 201)
                report.record(f"POST {key}", ok, pr.text[:200] if not ok else "")
            except Exception as exc:
                report.record(f"POST {key}", False, str(exc)[:200])

        async with AsyncSessionLocal() as session:
            st = await fetch_doc_state(session, doc_id)
        report.record(
            "производные созданы",
            st["auto_tags_orig"] > 0 or st["auto_entities"] > 0 or st["auto_categories"] > 0,
            f"tags_o={st['auto_tags_orig']} ent={st['auto_entities']} cat={st['auto_categories']}",
        )
        baseline_tags_orig = st["auto_tags_orig"]
        baseline_entities = st["auto_entities"]
        baseline_categories = st["auto_categories"]

        print("\n=== 3. Перевод ===")
        tr = await client.post(
            f"{API_BASE}/documents/{doc_id}/translate",
            headers=headers,
            json={"target_lang": "ru"},
        )
        report.record("POST translate", tr.status_code == 200, tr.text[:200] if tr.status_code != 200 else "")
        async with AsyncSessionLocal() as session:
            st = await fetch_doc_state(session, doc_id)
        report.record(
            "после translate: translated chunks + fp",
            _chunks_ok(st, "translated") and st["trans_fp_match"],
            json.dumps(st["chunks"], ensure_ascii=False),
        )
        report.record(
            "translate: summary stale, текст summary на месте",
            st["translated_summary_stale"] is True,
            f"has_summary={st['has_translated_summary']}",
        )
        report.record(
            "translate: сброс только тегов перевода (сущности на месте)",
            st["auto_tags_trans"] == 0 and st["auto_entities"] == baseline_entities,
            f"tags_trans={st['auto_tags_trans']} entities={st['auto_entities']}",
        )

        print("\n=== 4. Аннотация ===")
        sm = await client.post(
            f"{API_BASE}/documents/{doc_id}/summary",
            headers=headers,
            json={"source": "translated"},
        )
        report.record("POST summary", sm.status_code == 200, sm.text[:200] if sm.status_code != 200 else "")
        async with AsyncSessionLocal() as session:
            st = await fetch_doc_state(session, doc_id)
        report.record(
            "после summary: annotation chunks",
            _chunks_ok(st, "annotation") or st["chunks"].get("annotation", 0) >= 1,
            json.dumps(st["chunks"], ensure_ascii=False),
        )
        report.record("summary: translated_summary_stale=false", st["translated_summary_stale"] is False, "")

        print("\n=== 5. Refine ===")
        rf = await client.post(
            f"{API_BASE}/documents/{doc_id}/summary/refine",
            headers=headers,
            json={
                "source": "translated",
                "user_instruction": "Сделай на 20% короче.",
                "mode": "shorten",
            },
        )
        report.record("POST summary/refine", rf.status_code == 200, rf.text[:200] if rf.status_code != 200 else "")
        async with AsyncSessionLocal() as session:
            st_after_refine = await fetch_doc_state(session, doc_id)
        report.record(
            "после refine: annotation chunks",
            st_after_refine["chunks"].get("annotation", 0) >= 1,
            json.dumps(st_after_refine["chunks"], ensure_ascii=False),
        )

        print("\n=== 6. Ручное сохранение (lock + PUT) ===")
        async with AsyncSessionLocal() as session:
            doc = await session.get(Document, doc_id)
            orig_before = doc.original_content if doc else ""
            trans_before = doc.translated_content or ""

        lk = await client.post(f"{API_BASE}/documents/{doc_id}/lock", headers=headers)
        report.record("POST lock", lk.status_code == 200, lk.text[:120] if lk.status_code != 200 else "")

        # 6a только title
        put_title = await client.put(
            f"{API_BASE}/documents/{doc_id}",
            headers=headers,
            json={"title": (st_after_refine.get("title") or "test") + " [t]"},
        )
        report.record("PUT только title", put_title.status_code == 200, "")
        async with AsyncSessionLocal() as session:
            st_t = await fetch_doc_state(session, doc_id)
        report.record(
            "title: чанки без изменений",
            st_t["chunks"] == st_after_refine["chunks"],
            json.dumps(st_t["chunks"], ensure_ascii=False),
        )

        # re-tag translated for invalidate test
        await client.post(
            f"{API_BASE}/documents/{doc_id}/tags",
            headers=headers,
            json={"max_tags": 5, "use_translation": True},
        )
        async with AsyncSessionLocal() as session:
            st = await fetch_doc_state(session, doc_id)
        tags_trans_before_save = st["auto_tags_trans"]

        lk2 = await client.post(f"{API_BASE}/documents/{doc_id}/lock", headers=headers)
        if lk2.status_code != 200:
            report.record("POST lock (2)", False, lk2.text[:120])
        else:
            put_trans = await client.put(
                f"{API_BASE}/documents/{doc_id}",
                headers=headers,
                json={"translated_content": (trans_before or "test") + " [edit]"},
            )
            report.record("PUT translated", put_trans.status_code == 200, put_trans.text[:200] if put_trans.status_code != 200 else "")
            async with AsyncSessionLocal() as session:
                st_pt = await fetch_doc_state(session, doc_id)
            report.record(
                "save translated: пересчёт translated chunks",
                _chunks_ok(st_pt, "translated") and st_pt["trans_fp_match"],
                json.dumps(st_pt["chunks"], ensure_ascii=False),
            )
            report.record(
                "save translated: теги перевода сброшены",
                st_pt["auto_tags_trans"] < tags_trans_before_save or tags_trans_before_save == 0,
                f"was={tags_trans_before_save} now={st_pt['auto_tags_trans']}",
            )
            report.record(
                "save translated: original chunks на месте",
                st_pt["chunks"].get("original", 0) >= 1,
                json.dumps(st_pt["chunks"], ensure_ascii=False),
            )

        # tag original again + save original
        await client.post(
            f"{API_BASE}/documents/{doc_id}/tags",
            headers=headers,
            json={"max_tags": 5, "use_translation": False},
        )
        lk3 = await client.post(f"{API_BASE}/documents/{doc_id}/lock", headers=headers)
        put_orig = await client.put(
            f"{API_BASE}/documents/{doc_id}",
            headers=headers,
            json={"original_content": orig_before + " [edit]"},
        )
        report.record("PUT original", put_orig.status_code == 200, put_orig.text[:200] if put_orig.status_code != 200 else "")
        async with AsyncSessionLocal() as session:
            st_po = await fetch_doc_state(session, doc_id)
        report.record(
            "save original: original chunks + fp",
            _chunks_ok(st_po, "original") and st_po["orig_fp_match"],
            json.dumps(st_po["chunks"], ensure_ascii=False),
        )
        report.record(
            "save original: entities/categories сброшены",
            st_po["auto_entities"] == 0 and st_po["auto_categories"] == 0,
            f"ent={st_po['auto_entities']} cat={st_po['auto_categories']}",
        )

        # summary only
        async with AsyncSessionLocal() as session:
            doc = await session.get(Document, doc_id)
            summ = (doc.translated_summary or "Краткое резюме.") if doc else "Краткое резюме."
        lk4 = await client.post(f"{API_BASE}/documents/{doc_id}/lock", headers=headers)
        put_sum = await client.put(
            f"{API_BASE}/documents/{doc_id}",
            headers=headers,
            json={"translated_summary": summ + " [summary-edit]"},
        )
        report.record("PUT summary only", put_sum.status_code == 200, put_sum.text[:200] if put_sum.status_code != 200 else "")
        async with AsyncSessionLocal() as session:
            st_ps = await fetch_doc_state(session, doc_id)
        report.record(
            "save summary: annotation пересчитана",
            st_ps["chunks"].get("annotation", 0) >= 1 and st_ps.get("embedding_annotation_fp"),
            json.dumps(st_ps["chunks"], ensure_ascii=False),
        )

        print("\n=== 7. Счётчики embedding (как в dashboard) ===")
        from app.services.documents.document_embedding import collect_embedding_counters

        async with AsyncSessionLocal() as session:
            emb = await collect_embedding_counters(session)
        report.record(
            "embedding counters: original >= 1",
            emb.get("embedded_originals", 0) >= 1,
            json.dumps(emb),
        )

    print("\n=== ИТОГ ===")
    failed = [c for c in report.checks if not c.ok]
    print(f"Пройдено: {len(report.checks) - len(failed)}/{len(report.checks)}")
    if failed:
        print("Провалы:")
        for c in failed:
            print(f"  - {c.name}: {c.detail}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
