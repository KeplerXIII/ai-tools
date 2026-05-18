from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.infrastructure.db.models import User, Workbook
from app.infrastructure.db.session import get_db
from app.schemas.workbooks import (
    WorkbookCreateRequest,
    WorkbookDetailResponse,
    WorkbookDocumentsAddRequest,
    WorkbookDocumentsAddResponse,
    WorkbookEntryCreateRequest,
    WorkbookEntryItem,
    WorkbookEntrySourcesAddRequest,
    WorkbookEntryUpdateRequest,
    WorkbookListResponse,
    WorkbookSourceItem,
    WorkbookUpdateRequest,
)
from app.services.workbooks.workbook_service import (
    add_entry_sources,
    add_workbook_documents,
    assert_workbook_write_access,
    create_workbook_entry,
    delete_workbook_entry,
    get_workbook_detail,
    get_workbook_entry_or_404,
    get_workbook_or_404,
    list_workbooks,
    remove_entry_source,
    remove_workbook_document,
    _entry_to_item,
    set_entry_sources,
    update_workbook_entry,
)

router = APIRouter(prefix="/workbooks", tags=["workbooks"])


@router.get("", response_model=WorkbookListResponse)
async def list_user_workbooks(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkbookListResponse:
    return await list_workbooks(db, user)


@router.post("", response_model=WorkbookDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_workbook(
    payload: WorkbookCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkbookDetailResponse:
    workbook = Workbook(user_id=user.id, name=payload.name.strip())
    db.add(workbook)
    await db.commit()
    await db.refresh(workbook)
    return await get_workbook_detail(db, workbook)


@router.get("/{workbook_id}", response_model=WorkbookDetailResponse)
async def get_workbook(
    workbook_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkbookDetailResponse:
    workbook = await get_workbook_or_404(db, workbook_id)
    assert_workbook_write_access(workbook, user)
    return await get_workbook_detail(db, workbook)


@router.patch("/{workbook_id}", response_model=WorkbookDetailResponse)
async def update_workbook(
    workbook_id: UUID,
    payload: WorkbookUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkbookDetailResponse:
    workbook = await get_workbook_or_404(db, workbook_id)
    assert_workbook_write_access(workbook, user)
    if payload.name is not None:
        workbook.name = payload.name.strip()
    if payload.notes is not None:
        workbook.notes = payload.notes.strip() or None
    if payload.generation_prompt is not None:
        workbook.generation_prompt = payload.generation_prompt.strip() or None
    await db.commit()
    await db.refresh(workbook)
    return await get_workbook_detail(db, workbook)


@router.delete("/{workbook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workbook(
    workbook_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    workbook = await get_workbook_or_404(db, workbook_id)
    assert_workbook_write_access(workbook, user)
    await db.delete(workbook)
    await db.commit()


@router.post("/{workbook_id}/documents", response_model=WorkbookDocumentsAddResponse)
async def add_documents_to_workbook(
    workbook_id: UUID,
    payload: WorkbookDocumentsAddRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkbookDocumentsAddResponse:
    workbook = await get_workbook_or_404(db, workbook_id)
    assert_workbook_write_access(workbook, user)
    response = await add_workbook_documents(db, workbook, payload.document_ids)
    await db.commit()
    return response


@router.delete("/{workbook_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document_from_workbook(
    workbook_id: UUID,
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    workbook = await get_workbook_or_404(db, workbook_id)
    assert_workbook_write_access(workbook, user)
    await remove_workbook_document(db, workbook, document_id)
    await db.commit()


@router.post(
    "/{workbook_id}/entries",
    response_model=WorkbookEntryItem,
    status_code=status.HTTP_201_CREATED,
)
async def create_workbook_entry_endpoint(
    workbook_id: UUID,
    payload: WorkbookEntryCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkbookEntryItem:
    workbook = await get_workbook_or_404(db, workbook_id)
    assert_workbook_write_access(workbook, user)
    item = await create_workbook_entry(
        db,
        workbook,
        payload.content,
        payload.document_ids,
        payload.excerpts,
    )
    await db.commit()
    return item


@router.patch("/{workbook_id}/entries/{entry_id}", response_model=WorkbookEntryItem)
async def update_workbook_entry_endpoint(
    workbook_id: UUID,
    entry_id: UUID,
    payload: WorkbookEntryUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkbookEntryItem:
    workbook = await get_workbook_or_404(db, workbook_id)
    assert_workbook_write_access(workbook, user)
    entry = await get_workbook_entry_or_404(db, workbook_id, entry_id)
    item = await update_workbook_entry(db, workbook, entry, payload.content, payload.document_ids)
    await db.commit()
    return item


@router.delete("/{workbook_id}/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workbook_entry_endpoint(
    workbook_id: UUID,
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    workbook = await get_workbook_or_404(db, workbook_id)
    assert_workbook_write_access(workbook, user)
    entry = await get_workbook_entry_or_404(db, workbook_id, entry_id)
    await delete_workbook_entry(db, workbook, entry)
    await db.commit()


@router.post(
    "/{workbook_id}/entries/{entry_id}/sources",
    response_model=WorkbookEntryItem,
)
async def add_sources_to_entry(
    workbook_id: UUID,
    entry_id: UUID,
    payload: WorkbookEntrySourcesAddRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkbookEntryItem:
    workbook = await get_workbook_or_404(db, workbook_id)
    assert_workbook_write_access(workbook, user)
    entry = await get_workbook_entry_or_404(db, workbook_id, entry_id)
    await add_entry_sources(db, workbook, entry, payload.document_ids, payload.excerpts)
    await db.commit()
    await db.refresh(entry)
    return await _entry_to_item(db, entry)


@router.put(
    "/{workbook_id}/entries/{entry_id}/sources",
    response_model=WorkbookEntryItem,
)
async def replace_entry_sources(
    workbook_id: UUID,
    entry_id: UUID,
    payload: WorkbookEntrySourcesAddRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkbookEntryItem:
    workbook = await get_workbook_or_404(db, workbook_id)
    assert_workbook_write_access(workbook, user)
    entry = await get_workbook_entry_or_404(db, workbook_id, entry_id)
    await set_entry_sources(db, workbook, entry, payload.document_ids, payload.excerpts)
    await db.commit()
    await db.refresh(entry)
    return await _entry_to_item(db, entry)


@router.delete(
    "/{workbook_id}/entries/{entry_id}/sources/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_source_from_entry(
    workbook_id: UUID,
    entry_id: UUID,
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    workbook = await get_workbook_or_404(db, workbook_id)
    assert_workbook_write_access(workbook, user)
    entry = await get_workbook_entry_or_404(db, workbook_id, entry_id)
    await remove_entry_source(db, workbook, entry, document_id)
    await db.commit()
