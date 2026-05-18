import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ChipModule } from 'primeng/chip';
import { MultiSelectModule } from 'primeng/multiselect';
import { SourceListItem, SourcesApi } from '../sources/api/sources-api';
import {
  DocumentCategoryItem,
  DocumentEntityItem,
  DocumentsApi,
  DocumentListItem,
  DocumentStatusCatalogItem,
  DocumentTypeCatalogItem,
} from './documents-api';
@Component({
  selector: 'app-documents',
  standalone: true,
  imports: [CommonModule, FormsModule, ChipModule, MultiSelectModule],
  templateUrl: './documents.html',
  styleUrl: './documents.scss',
})
export class Documents implements OnInit {
  documents: DocumentListItem[] = [];
  statuses: DocumentStatusCatalogItem[] = [];
  documentTypes: DocumentTypeCatalogItem[] = [];
  sources: SourceListItem[] = [];
  loading = false;
  error = '';

  /** Пусто — без фильтра по статусу (все материалы). */
  selectedStatusCodes: string[] = [];
  selectedDocumentTypeCode = '';
  selectedSourceId = '';
  dateFrom = '';
  dateTo = '';
  usePublishedDate = false;
  /** Сортировка списка после загрузки: по дате загрузки или по «дате в полоске» (публикация / загрузка). */
  dateSortOption: 'uploaded-desc' | 'uploaded-asc' | 'card-desc' | 'card-asc' = 'uploaded-desc';
  expandedDocumentId: string | null = null;

  /** Материал, для которого открыто подтверждение удаления. */
  deleteConfirmDocument: DocumentListItem | null = null;
  deleteSubmitting = false;
  deleteError = '';

  constructor(
    private readonly documentsApi: DocumentsApi,
    private readonly sourcesApi: SourcesApi,
    private readonly router: Router,
  ) {}

  ngOnInit(): void {
    this.loadFilters();
    this.loadDocuments();
  }

  loadFilters(): void {
    this.documentsApi.getStatusesCatalog().subscribe({
      next: (items) => {
        this.statuses = items;
      },
    });

    this.documentsApi.getDocumentTypesCatalog().subscribe({
      next: (items) => {
        this.documentTypes = items;
      },
    });

    this.sourcesApi.listSources().subscribe({
      next: (response) => {
        this.sources = response.items;
      },
    });
  }

  loadDocuments(): void {
    this.loading = true;
    this.error = '';

    this.documentsApi
      .listDocuments({
        statusCodes: this.selectedStatusCodes.length ? [...this.selectedStatusCodes] : undefined,
        documentTypeCode: this.selectedDocumentTypeCode || undefined,
        sourceId: this.selectedSourceId || undefined,
        dateFrom: this.dateFrom || undefined,
        dateTo: this.dateTo || undefined,
        usePublishedDate: this.usePublishedDate,
      })
      .subscribe({
        next: (response) => {
          this.documents = this.sortDocumentsByDate(response.items);
          this.loading = false;
        },
        error: () => {
          this.error = 'Не удалось загрузить список материалов';
          this.loading = false;
        },
      });
  }

  onFiltersChanged(): void {
    this.loadDocuments();
  }

  onDateSortChanged(): void {
    this.documents = this.sortDocumentsByDate(this.documents);
  }

  resetFilters(): void {
    this.selectedStatusCodes = [];
    this.selectedDocumentTypeCode = '';
    this.selectedSourceId = '';
    this.dateFrom = '';
    this.dateTo = '';
    this.usePublishedDate = false;
    this.dateSortOption = 'uploaded-desc';
    this.loadDocuments();
  }

  sourceFilterLabel(src: SourceListItem): string {
    const name = src.name?.trim();
    if (name) {
      return name;
    }
    try {
      return new URL(src.url).hostname;
    } catch {
      return src.url;
    }
  }

  /** Заголовок для списка: перевод, иначе оригинал. */
  documentListTitle(doc: DocumentListItem): string {
    const tr = doc.translated_title?.trim();
    if (tr) {
      return tr;
    }
    return (doc.title ?? '').trim() || doc.title;
  }

  toggleExpand(documentId: string): void {
    this.expandedDocumentId = this.expandedDocumentId === documentId ? null : documentId;
  }

  isExpanded(documentId: string): boolean {
    return this.expandedDocumentId === documentId;
  }

  /** Открыть материал в экране «Документ» (редактор / разбор). */
  openDocumentInEditor(doc: DocumentListItem): void {
    void this.router.navigate(['/document'], {
      queryParams: { id: doc.document_id, mode: 'material' },
    });
  }

  private sortDocumentsByDate(items: DocumentListItem[]): DocumentListItem[] {
    const desc = this.dateSortOption.endsWith('desc');
    const byCard = this.dateSortOption.startsWith('card');
    const time = (doc: DocumentListItem): number => {
      const iso = byCard ? this.documentStripPrimaryIso(doc) : doc.created_at;
      const t = new Date(iso).getTime();
      return Number.isNaN(t) ? 0 : t;
    };
    return [...items].sort((a, b) => {
      const diff = time(a) - time(b);
      return desc ? -diff : diff;
    });
  }

  /** ISO для атрибута datetime: дата публикации или дата создания в системе. */
  documentStripPrimaryIso(doc: DocumentListItem): string {
    const pub = doc.published_at?.trim();
    if (pub) {
      return pub;
    }
    return doc.created_at;
  }

  /** Дата в полоске (дд.мм.гггг); источник см. во всплывающей подсказке. */
  documentStripDateLabel(doc: DocumentListItem): string {
    return this.formatRuDateShort(this.documentStripPrimaryIso(doc));
  }

  /** Подсказка: обе даты, если есть. */
  documentStripDateTitle(doc: DocumentListItem): string {
    const lines: string[] = [];
    if (doc.published_at?.trim()) {
      lines.push(`Публикация: ${this.formatRuDateTime(doc.published_at)}`);
    }
    lines.push(`Загружен в систему: ${this.formatRuDateTime(doc.created_at)}`);
    return lines.join('\n');
  }

  private formatRuDateShort(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) {
      return iso.slice(0, 10);
    }
    return d.toLocaleDateString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  }

  private formatRuDateTime(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) {
      return iso;
    }
    return d.toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  categoryChipLabel(item: DocumentCategoryItem): string {
    const parentTitle = (item.parent_name_ru || item.parent_name || item.parent_code || '').trim();
    const title = (item.name_ru || item.name || item.code).trim();
    const conf = Number.isFinite(item.confidence) ? `${Math.round(item.confidence * 100)}%` : '—';
    const label = parentTitle ? `${parentTitle} / ${title}` : title;
    return `${label} (${conf})`;
  }

  entityChipLabel(item: DocumentEntityItem): string {
    return item.name;
  }

  entityChipClass(item: DocumentEntityItem): string {
    if (item.entity_type_code === 'manufacturer') {
      return 'entity-chip-manufacturer chip-compact';
    }
    if (item.entity_type_code === 'contract') {
      return 'entity-chip-contract chip-compact';
    }
    return 'entity-chip-military chip-compact';
  }

  entityItemsByType(
    doc: DocumentListItem,
    entityTypeCode: 'military_equipment' | 'manufacturer' | 'contract',
  ): DocumentEntityItem[] {
    return doc.entities.filter((item) => item.entity_type_code === entityTypeCode);
  }

  openDeleteConfirm(doc: DocumentListItem, event: Event): void {
    event.stopPropagation();
    event.preventDefault();
    this.deleteConfirmDocument = doc;
    this.deleteError = '';
  }

  closeDeleteConfirm(): void {
    if (this.deleteSubmitting) {
      return;
    }
    this.deleteConfirmDocument = null;
    this.deleteError = '';
  }

  onDeleteModalBackdropClick(event: MouseEvent): void {
    if (event.target === event.currentTarget) {
      this.closeDeleteConfirm();
    }
  }

  confirmDeleteDocument(): void {
    const doc = this.deleteConfirmDocument;
    if (!doc || this.deleteSubmitting) {
      return;
    }
    this.deleteSubmitting = true;
    this.deleteError = '';
    this.documentsApi.deleteDocument(doc.document_id).subscribe({
      next: () => {
        this.deleteSubmitting = false;
        this.deleteConfirmDocument = null;
        if (this.expandedDocumentId === doc.document_id) {
          this.expandedDocumentId = null;
        }
        this.documents = this.documents.filter((d) => d.document_id !== doc.document_id);
      },
      error: (err: HttpErrorResponse) => {
        this.deleteSubmitting = false;
        const detail = err.error?.detail;
        this.deleteError =
          typeof detail === 'string'
            ? detail
            : err.status === 403
              ? 'Нет права удалить этот материал'
              : 'Не удалось удалить материал';
      },
    });
  }
}
