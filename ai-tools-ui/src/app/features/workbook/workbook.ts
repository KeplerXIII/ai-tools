import { CommonModule } from '@angular/common';
import {
  AfterViewInit,
  Component,
  DestroyRef,
  OnInit,
  QueryList,
  ViewChildren,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { OutlineButtonComponent } from '../../shared/ui/outline-button/outline-button.component';
import { PrimaryButtonComponent } from '../../shared/ui/primary-button/primary-button.component';
import { DocumentListItem, DocumentsApi } from '../documents/documents-api';
import {
  WorkbookApi,
  WorkbookDetailResponse,
  WorkbookEntryItem,
  WorkbookListItem,
  WorkbookSourceItem,
} from './api/workbook-api';
import { WbAutosizeTextareaDirective } from './wb-autosize-textarea.directive';

type SourcePickerTarget =
  | { kind: 'new-entry' }
  | { kind: 'entry'; entryId: string };

@Component({
  selector: 'app-workbook',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    OutlineButtonComponent,
    PrimaryButtonComponent,
    WbAutosizeTextareaDirective,
  ],
  templateUrl: './workbook.html',
  styleUrl: './workbook.scss',
})
export class Workbook implements OnInit, AfterViewInit {
  @ViewChildren(WbAutosizeTextareaDirective) private autosizeAreas!: QueryList<WbAutosizeTextareaDirective>;

  workbooks: WorkbookListItem[] = [];
  listLoading = false;
  listError: string | null = null;
  sidebarSearch = '';

  selectedId: string | null = null;
  detail: WorkbookDetailResponse | null = null;
  detailLoading = false;
  detailError: string | null = null;

  editName = '';
  editNotes = '';
  editPrompt = '';
  savingWorkbook = false;
  workbookSaveError: string | null = null;
  lastSavedAt: Date | null = null;

  newEntryText = '';
  newEntrySourceIds = new Set<string>();
  creatingEntry = false;
  entryError: string | null = null;
  entryEdits: Record<string, string> = {};
  savingEntryId: string | null = null;

  sourcePicker: SourcePickerTarget | null = null;
  documentSearch = '';
  pickerDocuments: DocumentListItem[] = [];
  pickerLoading = false;
  pickerError: string | null = null;
  selectedPickerIds = new Set<string>();
  linkingSources = false;

  creatingWorkbook = false;
  newWorkbookName = '';
  showCreateForm = false;

  entriesOpen = false;
  generationOpen = false;

  constructor(
    private readonly workbookApi: WorkbookApi,
    private readonly documentsApi: DocumentsApi,
    private readonly route: ActivatedRoute,
    private readonly router: Router,
    private readonly destroyRef: DestroyRef,
  ) {}

  ngOnInit(): void {
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((q) => {
      const id = q.get('workbook_id')?.trim() || null;
      if (id !== this.selectedId) {
        this.selectedId = id;
        if (id) {
          this.loadDetail(id);
        } else {
          this.detail = null;
          this.detailError = null;
        }
      }
    });
    this.loadWorkbooks();
  }

  ngAfterViewInit(): void {
    this.refreshAutosize();
    this.autosizeAreas.changes.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
      this.refreshAutosize();
    });
  }

  filteredWorkbooks(): WorkbookListItem[] {
    const q = this.sidebarSearch.trim().toLowerCase();
    if (!q) return this.workbooks;
    return this.workbooks.filter((wb) => wb.name.toLowerCase().includes(q));
  }

  loadWorkbooks(): void {
    this.listLoading = true;
    this.listError = null;
    this.workbookApi.listWorkbooks().subscribe({
      next: (res) => {
        this.workbooks = res.items;
        this.listLoading = false;
      },
      error: (err) => {
        this.listLoading = false;
        this.listError = err?.error?.detail ?? 'Не удалось загрузить тетради';
      },
    });
  }

  loadDetail(workbookId: string): void {
    this.detailLoading = true;
    this.detailError = null;
    this.workbookApi.getWorkbook(workbookId).subscribe({
      next: (detail) => {
        this.applyDetail(detail);
        this.detailLoading = false;
      },
      error: (err) => {
        this.detailLoading = false;
        this.detailError = err?.error?.detail ?? 'Не удалось загрузить тетрадь';
        this.detail = null;
      },
    });
  }

  private applyDetail(detail: WorkbookDetailResponse): void {
    this.detail = detail;
    this.editName = detail.name;
    this.editNotes = detail.notes ?? '';
    this.editPrompt = detail.generation_prompt ?? '';
    this.syncEntryEdits(detail.entries ?? []);
    this.lastSavedAt = new Date(detail.updated_at);
    this.workbookSaveError = null;
    this.entryError = null;
    this.refreshAutosize();
  }

  selectWorkbook(workbookId: string): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { workbook_id: workbookId },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  clearSelection(): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { workbook_id: null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  toggleCreateForm(): void {
    this.showCreateForm = !this.showCreateForm;
    this.newWorkbookName = '';
  }

  createWorkbook(): void {
    const name = this.newWorkbookName.trim();
    if (!name || this.creatingWorkbook) return;
    this.creatingWorkbook = true;
    this.workbookApi.createWorkbook(name).subscribe({
      next: (detail) => {
        this.creatingWorkbook = false;
        this.showCreateForm = false;
        this.loadWorkbooks();
        this.selectWorkbook(detail.workbook_id);
      },
      error: (err) => {
        this.creatingWorkbook = false;
        this.listError = err?.error?.detail ?? 'Не удалось создать тетрадь';
      },
    });
  }

  workbookIsDirty(): boolean {
    if (!this.detail) return false;
    return (
      this.editName.trim() !== this.detail.name ||
      (this.editNotes ?? '') !== (this.detail.notes ?? '') ||
      (this.editPrompt ?? '') !== (this.detail.generation_prompt ?? '')
    );
  }

  saveWorkbook(): void {
    if (!this.detail || this.savingWorkbook) return;
    const name = this.editName.trim();
    if (!name) {
      this.workbookSaveError = 'Укажите название тетради';
      return;
    }
    this.savingWorkbook = true;
    this.workbookSaveError = null;
    this.workbookApi
      .updateWorkbook(this.detail.workbook_id, {
        name,
        notes: this.editNotes,
        generation_prompt: this.editPrompt,
      })
      .subscribe({
        next: (detail) => {
          this.savingWorkbook = false;
          this.applyDetail(detail);
          this.loadWorkbooks();
        },
        error: (err) => {
          this.savingWorkbook = false;
          this.workbookSaveError = err?.error?.detail ?? 'Не удалось сохранить';
        },
      });
  }

  deleteWorkbook(): void {
    if (!this.detail) return;
    if (!confirm(`Удалить тетрадь «${this.detail.name}»? Все тезисы будут потеряны.`)) return;
    this.workbookApi.deleteWorkbook(this.detail.workbook_id).subscribe({
      next: () => {
        this.clearSelection();
        this.loadWorkbooks();
      },
      error: (err) => {
        this.detailError = err?.error?.detail ?? 'Не удалось удалить тетрадь';
      },
    });
  }

  openSourcePicker(target: SourcePickerTarget): void {
    this.sourcePicker = target;
    this.documentSearch = '';
    this.pickerError = null;
    if (target.kind === 'new-entry') {
      this.selectedPickerIds = new Set(this.newEntrySourceIds);
    } else {
      const entry = this.detail?.entries.find((e) => e.entry_id === target.entryId);
      this.selectedPickerIds = new Set(entry?.sources.map((s) => s.document_id) ?? []);
    }
    this.loadPickerDocuments();
  }

  closeSourcePicker(): void {
    this.sourcePicker = null;
    this.selectedPickerIds = new Set();
  }

  loadPickerDocuments(): void {
    this.pickerLoading = true;
    this.pickerError = null;
    this.documentsApi.listDocuments({ limit: 150, offset: 0 }).subscribe({
      next: (res) => {
        this.pickerDocuments = res.items;
        this.pickerLoading = false;
      },
      error: (err) => {
        this.pickerLoading = false;
        this.pickerError = err?.error?.detail ?? 'Не удалось загрузить документы';
      },
    });
  }

  filteredPickerDocuments(): DocumentListItem[] {
    const q = this.documentSearch.trim().toLowerCase();
    return this.pickerDocuments.filter((doc) => {
      if (!q) return true;
      const title = (doc.translated_title || doc.title || '').toLowerCase();
      return title.includes(q) || doc.document_id.toLowerCase().includes(q);
    });
  }

  togglePickerDocument(documentId: string): void {
    const next = new Set(this.selectedPickerIds);
    if (next.has(documentId)) {
      next.delete(documentId);
    } else {
      next.add(documentId);
    }
    this.selectedPickerIds = next;
  }

  isPickerSelected(documentId: string): boolean {
    return this.selectedPickerIds.has(documentId);
  }

  confirmSourcePicker(): void {
    if (!this.sourcePicker) return;
    if (this.sourcePicker.kind === 'new-entry') {
      this.newEntrySourceIds = new Set(this.selectedPickerIds);
      this.closeSourcePicker();
      return;
    }
    if (!this.detail || this.linkingSources) return;
    this.linkingSources = true;
    this.pickerError = null;
    const entryId = this.sourcePicker.entryId;
    const ids = [...this.selectedPickerIds];
    this.workbookApi.updateEntry(this.detail.workbook_id, entryId, { document_ids: ids }).subscribe({
      next: (updated) => {
        this.linkingSources = false;
        this.patchEntry(updated);
        this.closeSourcePicker();
        this.loadWorkbooks();
      },
      error: (err) => {
        this.linkingSources = false;
        this.pickerError = err?.error?.detail ?? 'Не удалось обновить источники';
      },
    });
  }

  removeEntrySource(entry: WorkbookEntryItem, source: WorkbookSourceItem): void {
    if (!this.detail) return;
    this.workbookApi
      .removeEntrySource(this.detail.workbook_id, entry.entry_id, source.document_id)
      .subscribe({
        next: () => {
          this.patchEntry({
            ...entry,
            sources: entry.sources.filter((s) => s.document_id !== source.document_id),
          });
          this.loadWorkbooks();
        },
        error: (err) => {
          this.entryError = err?.error?.detail ?? 'Не удалось отвязать источник';
        },
      });
  }

  private patchEntry(updated: WorkbookEntryItem): void {
    if (!this.detail) return;
    this.detail = {
      ...this.detail,
      entries: this.detail.entries.map((e) => (e.entry_id === updated.entry_id ? updated : e)),
    };
    this.entryEdits[updated.entry_id] = updated.content;
  }

  addEntry(): void {
    if (!this.detail || this.creatingEntry) return;
    const content = this.newEntryText.trim();
    if (!content) {
      this.entryError = 'Напишите текст тезиса';
      return;
    }
    this.creatingEntry = true;
    this.entryError = null;
    this.workbookApi
      .createEntry(this.detail.workbook_id, {
        content,
        document_ids: [...this.newEntrySourceIds],
      })
      .subscribe({
        next: (entry) => {
          this.creatingEntry = false;
          this.newEntryText = '';
          this.newEntrySourceIds = new Set();
          if (this.detail) {
            this.detail = { ...this.detail, entries: [...this.detail.entries, entry] };
            this.entryEdits[entry.entry_id] = entry.content;
          }
          this.loadWorkbooks();
          this.refreshAutosize();
        },
        error: (err) => {
          this.creatingEntry = false;
          this.entryError = err?.error?.detail ?? 'Не удалось добавить тезис';
        },
      });
  }

  saveEntry(entry: WorkbookEntryItem): void {
    if (!this.detail || this.savingEntryId) return;
    const content = (this.entryEdits[entry.entry_id] ?? '').trim();
    if (!content) {
      this.entryError = 'Текст тезиса не может быть пустым';
      return;
    }
    this.savingEntryId = entry.entry_id;
    this.entryError = null;
    this.workbookApi.updateEntry(this.detail.workbook_id, entry.entry_id, { content }).subscribe({
      next: (updated) => {
        this.savingEntryId = null;
        this.patchEntry(updated);
        this.loadWorkbooks();
      },
      error: (err) => {
        this.savingEntryId = null;
        this.entryError = err?.error?.detail ?? 'Не удалось сохранить тезис';
      },
    });
  }

  deleteEntry(entry: WorkbookEntryItem): void {
    if (!this.detail) return;
    const preview = entry.content.trim().slice(0, 60);
    if (!confirm(`Удалить тезис «${preview}${entry.content.length > 60 ? '…' : ''}»?`)) return;
    this.workbookApi.deleteEntry(this.detail.workbook_id, entry.entry_id).subscribe({
      next: () => {
        if (this.detail) {
          this.detail = {
            ...this.detail,
            entries: this.detail.entries.filter((e) => e.entry_id !== entry.entry_id),
          };
          delete this.entryEdits[entry.entry_id];
        }
        this.loadWorkbooks();
      },
      error: (err) => {
        this.entryError = err?.error?.detail ?? 'Не удалось удалить тезис';
      },
    });
  }

  entryIsDirty(entry: WorkbookEntryItem): boolean {
    return (this.entryEdits[entry.entry_id] ?? '').trim() !== entry.content.trim();
  }

  sourcePickerTitle(): string {
    if (!this.sourcePicker) return '';
    return this.sourcePicker.kind === 'new-entry'
      ? 'Источники для нового тезиса'
      : 'Источники тезиса';
  }

  onEntriesToggle(event: Event): void {
    const el = event.target as HTMLDetailsElement;
    this.entriesOpen = el.open;
    if (el.open) {
      this.refreshAutosize();
    }
  }

  thesesCountLabel(count: number): string {
    const n = Math.abs(count);
    const mod10 = n % 10;
    const mod100 = n % 100;
    if (mod100 >= 11 && mod100 <= 14) return 'тезисов';
    if (mod10 === 1) return 'тезис';
    if (mod10 >= 2 && mod10 <= 4) return 'тезиса';
    return 'тезисов';
  }

  documentTitle(doc: { title: string; translated_title?: string | null }): string {
    return (doc.translated_title || doc.title || 'Без названия').trim() || 'Без названия';
  }

  formatDate(iso: string): string {
    try {
      return new Date(iso).toLocaleString('ru-RU', {
        day: 'numeric',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return '';
    }
  }

  newEntrySourceLabels(): string[] {
    if (!this.detail) return [];
    const ids = this.newEntrySourceIds;
    const fromEntries = this.detail.entries.flatMap((e) => e.sources);
    const fromPicker = this.pickerDocuments;
    return [...ids].map((id) => {
      const s = fromEntries.find((x) => x.document_id === id);
      if (s) return this.documentTitle(s);
      const d = fromPicker.find((x) => x.document_id === id);
      return d ? this.documentTitle(d) : id.slice(0, 8);
    });
  }

  private syncEntryEdits(entries: WorkbookEntryItem[]): void {
    this.entryEdits = Object.fromEntries(entries.map((e) => [e.entry_id, e.content]));
  }

  private refreshAutosize(): void {
    queueMicrotask(() => {
      requestAnimationFrame(() => {
        this.autosizeAreas?.forEach((area) => area.resize());
      });
    });
  }
}
