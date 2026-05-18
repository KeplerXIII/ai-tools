from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import (
    Document,
    DocumentType,
    User,
    Workbook,
    WorkbookDocument,
    WorkbookEntry,
    WorkbookEntryDocument,
)
from app.schemas.workbooks import (
    WorkbookDetailResponse,
    WorkbookDocumentItem,
    WorkbookDocumentsAddResponse,
    WorkbookEntryItem,
    WorkbookListItem,
    WorkbookListResponse,
    WorkbookSourceItem,
)


def assert_workbook_write_access(workbook: Workbook, user: User) -> None:
    if not getattr(user, "is_admin", False) and workbook.user_id != user.id:
        raise HTTPException(status_code=403, detail="Нет доступа к рабочей тетради")


async def get_workbook_or_404(db: AsyncSession, workbook_id: UUID) -> Workbook:
    workbook = await db.get(Workbook, workbook_id)
    if workbook is None:
        raise HTTPException(status_code=404, detail="Рабочая тетрадь не найдена")
    return workbook


async def get_workbook_entry_or_404(
    db: AsyncSession,
    workbook_id: UUID,
    entry_id: UUID,
) -> WorkbookEntry:
    entry = await db.get(WorkbookEntry, entry_id)
    if entry is None or entry.workbook_id != workbook_id:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return entry


async def touch_workbook_updated_at(workbook: Workbook) -> None:
    workbook.updated_at = datetime.now(UTC)


async def _ensure_documents_exist(db: AsyncSession, document_ids: list[UUID]) -> None:
    if not document_ids:
        return
    found_ids = set(await db.scalars(select(Document.id).where(Document.id.in_(document_ids))))
    if len(found_ids) != len(document_ids):
        raise HTTPException(status_code=404, detail="Один или несколько документов не найдены")


async def _sync_workbook_document_pool(
    db: AsyncSession,
    workbook: Workbook,
    document_ids: list[UUID],
) -> None:
    if not document_ids:
        return
    existing = set(
        await db.scalars(
            select(WorkbookDocument.document_id).where(WorkbookDocument.workbook_id == workbook.id),
        ),
    )
    for doc_id in document_ids:
        if doc_id not in existing:
            db.add(WorkbookDocument(workbook_id=workbook.id, document_id=doc_id))
            existing.add(doc_id)


def _excerpt_for(document_id: UUID, excerpts: dict[str, str]) -> str | None:
    raw = excerpts.get(str(document_id))
    if raw is None:
        return None
    text = raw.strip()
    return text or None


async def list_entry_sources(db: AsyncSession, entry_id: UUID) -> list[WorkbookSourceItem]:
    stmt = (
        select(
            Document.id,
            Document.title,
            Document.translated_title,
            Document.source_url,
            DocumentType.code,
            DocumentType.name,
            WorkbookEntryDocument.excerpt,
            WorkbookEntryDocument.added_at,
        )
        .join(WorkbookEntryDocument, WorkbookEntryDocument.document_id == Document.id)
        .join(DocumentType, DocumentType.id == Document.document_type_id)
        .where(WorkbookEntryDocument.entry_id == entry_id)
        .order_by(WorkbookEntryDocument.added_at.asc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        WorkbookSourceItem(
            document_id=row[0],
            title=row[1],
            translated_title=row[2],
            source_url=row[3],
            document_type_code=row[4],
            document_type_name=row[5],
            excerpt=row[6],
            added_at=row[7],
        )
        for row in rows
    ]


async def _entry_to_item(db: AsyncSession, entry: WorkbookEntry) -> WorkbookEntryItem:
    sources = await list_entry_sources(db, entry.id)
    return WorkbookEntryItem(
        entry_id=entry.id,
        content=entry.content,
        sources=sources,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


async def set_entry_sources(
    db: AsyncSession,
    workbook: Workbook,
    entry: WorkbookEntry,
    document_ids: list[UUID],
    excerpts: dict[str, str] | None = None,
) -> list[WorkbookSourceItem]:
    excerpts = excerpts or {}
    await _ensure_documents_exist(db, document_ids)
    await db.execute(delete(WorkbookEntryDocument).where(WorkbookEntryDocument.entry_id == entry.id))
    for doc_id in document_ids:
        db.add(
            WorkbookEntryDocument(
                entry_id=entry.id,
                document_id=doc_id,
                excerpt=_excerpt_for(doc_id, excerpts),
            ),
        )
    await _sync_workbook_document_pool(db, workbook, document_ids)
    await touch_workbook_updated_at(workbook)
    await db.flush()
    return await list_entry_sources(db, entry.id)


async def add_entry_sources(
    db: AsyncSession,
    workbook: Workbook,
    entry: WorkbookEntry,
    document_ids: list[UUID],
    excerpts: dict[str, str] | None = None,
) -> list[WorkbookSourceItem]:
    excerpts = excerpts or {}
    await _ensure_documents_exist(db, document_ids)
    existing = set(
        await db.scalars(
            select(WorkbookEntryDocument.document_id).where(WorkbookEntryDocument.entry_id == entry.id),
        ),
    )
    added_any = False
    for doc_id in document_ids:
        if doc_id in existing:
            continue
        db.add(
            WorkbookEntryDocument(
                entry_id=entry.id,
                document_id=doc_id,
                excerpt=_excerpt_for(doc_id, excerpts),
            ),
        )
        existing.add(doc_id)
        added_any = True
    if added_any:
        await _sync_workbook_document_pool(db, workbook, document_ids)
        await touch_workbook_updated_at(workbook)
        await db.flush()
    return await list_entry_sources(db, entry.id)


async def remove_entry_source(
    db: AsyncSession,
    workbook: Workbook,
    entry: WorkbookEntry,
    document_id: UUID,
) -> None:
    result = await db.execute(
        delete(WorkbookEntryDocument).where(
            WorkbookEntryDocument.entry_id == entry.id,
            WorkbookEntryDocument.document_id == document_id,
        ),
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Источник не привязан к записи")
    await touch_workbook_updated_at(workbook)


async def list_workbook_entries(db: AsyncSession, workbook_id: UUID) -> list[WorkbookEntryItem]:
    entries = (
        await db.execute(
            select(WorkbookEntry)
            .where(WorkbookEntry.workbook_id == workbook_id)
            .order_by(WorkbookEntry.created_at.asc()),
        )
    ).scalars().all()
    return [await _entry_to_item(db, entry) for entry in entries]


async def count_workbook_sources(db: AsyncSession, workbook_id: UUID) -> int:
    stmt = (
        select(func.count(func.distinct(WorkbookEntryDocument.document_id)))
        .select_from(WorkbookEntryDocument)
        .join(WorkbookEntry, WorkbookEntry.id == WorkbookEntryDocument.entry_id)
        .where(WorkbookEntry.workbook_id == workbook_id)
    )
    return int((await db.scalar(stmt)) or 0)


async def list_workbooks(db: AsyncSession, user: User) -> WorkbookListResponse:
    entries_count_sq = (
        select(func.count())
        .select_from(WorkbookEntry)
        .where(WorkbookEntry.workbook_id == Workbook.id)
        .scalar_subquery()
    )
    sources_count_sq = (
        select(func.count(func.distinct(WorkbookEntryDocument.document_id)))
        .select_from(WorkbookEntryDocument)
        .join(WorkbookEntry, WorkbookEntry.id == WorkbookEntryDocument.entry_id)
        .where(WorkbookEntry.workbook_id == Workbook.id)
        .scalar_subquery()
    )
    stmt = (
        select(Workbook, entries_count_sq, sources_count_sq)
        .where(Workbook.user_id == user.id)
        .order_by(Workbook.updated_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    items = [
        WorkbookListItem(
            workbook_id=wb.id,
            name=wb.name,
            sources_count=int(sources_count or 0),
            entries_count=int(entries_count or 0),
            created_at=wb.created_at,
            updated_at=wb.updated_at,
        )
        for wb, entries_count, sources_count in rows
    ]
    return WorkbookListResponse(total=len(items), items=items)


async def get_workbook_detail(db: AsyncSession, workbook: Workbook) -> WorkbookDetailResponse:
    entries = await list_workbook_entries(db, workbook.id)
    return WorkbookDetailResponse(
        workbook_id=workbook.id,
        name=workbook.name,
        notes=workbook.notes,
        generation_prompt=workbook.generation_prompt,
        entries=entries,
        created_at=workbook.created_at,
        updated_at=workbook.updated_at,
    )


async def create_workbook_entry(
    db: AsyncSession,
    workbook: Workbook,
    content: str,
    document_ids: list[UUID] | None = None,
    excerpts: dict[str, str] | None = None,
) -> WorkbookEntryItem:
    entry = WorkbookEntry(workbook_id=workbook.id, content=content.strip())
    db.add(entry)
    await db.flush()
    if document_ids:
        await set_entry_sources(db, workbook, entry, document_ids, excerpts)
    else:
        await touch_workbook_updated_at(workbook)
        await db.flush()
    await db.refresh(entry)
    return await _entry_to_item(db, entry)


async def update_workbook_entry(
    db: AsyncSession,
    workbook: Workbook,
    entry: WorkbookEntry,
    content: str | None = None,
    document_ids: list[UUID] | None = None,
) -> WorkbookEntryItem:
    if content is not None:
        entry.content = content.strip()
    if document_ids is not None:
        await set_entry_sources(db, workbook, entry, document_ids)
    elif content is not None:
        await touch_workbook_updated_at(workbook)
        await db.flush()
    await db.refresh(entry)
    return await _entry_to_item(db, entry)


async def delete_workbook_entry(db: AsyncSession, workbook: Workbook, entry: WorkbookEntry) -> None:
    await db.delete(entry)
    await touch_workbook_updated_at(workbook)


# --- legacy workbook-level documents (API compat) ---

async def list_workbook_documents(db: AsyncSession, workbook_id: UUID) -> list[WorkbookDocumentItem]:
    stmt = (
        select(
            Document.id,
            Document.title,
            Document.translated_title,
            Document.source_url,
            DocumentType.code,
            DocumentType.name,
            WorkbookDocument.added_at,
        )
        .join(WorkbookDocument, WorkbookDocument.document_id == Document.id)
        .join(DocumentType, DocumentType.id == Document.document_type_id)
        .where(WorkbookDocument.workbook_id == workbook_id)
        .order_by(WorkbookDocument.added_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        WorkbookDocumentItem(
            document_id=row[0],
            title=row[1],
            translated_title=row[2],
            source_url=row[3],
            document_type_code=row[4],
            document_type_name=row[5],
            excerpt=None,
            added_at=row[6],
        )
        for row in rows
    ]


async def add_workbook_documents(
    db: AsyncSession,
    workbook: Workbook,
    document_ids: list[UUID],
) -> WorkbookDocumentsAddResponse:
    await _ensure_documents_exist(db, document_ids)
    existing_ids = set(
        await db.scalars(
            select(WorkbookDocument.document_id).where(WorkbookDocument.workbook_id == workbook.id),
        ),
    )
    added = 0
    skipped = 0
    for doc_id in document_ids:
        if doc_id in existing_ids:
            skipped += 1
            continue
        db.add(WorkbookDocument(workbook_id=workbook.id, document_id=doc_id))
        existing_ids.add(doc_id)
        added += 1
    if added:
        await touch_workbook_updated_at(workbook)
        await db.flush()
    documents = await list_workbook_documents(db, workbook.id)
    return WorkbookDocumentsAddResponse(added=added, skipped=skipped, documents=documents)


async def remove_workbook_document(db: AsyncSession, workbook: Workbook, document_id: UUID) -> None:
    result = await db.execute(
        delete(WorkbookDocument).where(
            WorkbookDocument.workbook_id == workbook.id,
            WorkbookDocument.document_id == document_id,
        ),
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Документ не привязан к тетради")
    await touch_workbook_updated_at(workbook)
