import { ChangeDetectorRef, Component, Input, OnChanges, SimpleChanges } from '@angular/core';
import { MenuItem } from 'primeng/api';
import { ChipModule } from 'primeng/chip';
import { SpeedDialModule } from 'primeng/speeddial';
import { ArticleParserApi, ExtractResponse } from '../../api/article-parser-api';

@Component({
  selector: 'app-article-parser-status',
  standalone: true,
  imports: [ChipModule, SpeedDialModule],
  templateUrl: './article-parser-status.html',
  styleUrl: './article-parser-status.scss',
})
export class ArticleParserStatusComponent implements OnChanges {
  @Input() article: ExtractResponse | null = null;

  availableDocumentStatuses: { code: string; name_ru: string; description: string | null }[] = [];
  documentStatusTags: { code: string; label: string }[] = [];
  /** Стабильная ссылка для p-speeddial: геттер давал новый массив на каждом CD и ломал привязку пунктов. */
  statusSpeedDialItems: MenuItem[] = [];
  loadingDocumentStatuses = false;
  documentStatusError = '';
  isEditingStatusBlock = false;
  pendingStatusCode = '';

  constructor(
    private api: ArticleParserApi,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnChanges(changes: SimpleChanges): void {
    if (!changes['article']) {
      return;
    }

    if (!this.article) {
      this.documentStatusTags = [];
      this.availableDocumentStatuses = [];
      this.statusSpeedDialItems = [];
      this.documentStatusError = '';
      this.loadingDocumentStatuses = false;
      this.isEditingStatusBlock = false;
      this.pendingStatusCode = '';
      return;
    }

    this.syncDocumentStatusTagsFromArticle();
    this.loadAvailableDocumentStatuses();
  }

  toggleEdit(): void {
    this.isEditingStatusBlock = !this.isEditingStatusBlock;
  }

  /**
   * Закрывает SpeedDial (через toggleCallback → hide) и добавляет статус по id пункта,
   * не полагаясь только на item.command (document click / смена model на CD).
   */
  onStatusSpeedDialItemClick(
    event: MouseEvent,
    menuItem: MenuItem,
    toggleCallback: (e: Event, item: MenuItem) => void,
  ): void {
    event.stopPropagation();
    const code = typeof menuItem.id === 'string' ? menuItem.id.trim() : '';
    if (code) {
      this.onDocumentStatusSelected(code);
    }
    toggleCallback(event, { ...menuItem, command: undefined });
  }

  onDocumentStatusSelected(code: string | null | undefined): void {
    if (!code || this.loadingDocumentStatuses) {
      return;
    }

    const alreadyAssigned = this.documentStatusTags.some((status) => status.code === code);
    if (alreadyAssigned) {
      this.pendingStatusCode = '';
      return;
    }

    this.pendingStatusCode = code;
    this.addDocumentStatus();
  }

  removeDocumentStatusTag(code: string): void {
    const documentId = this.article?.document_id;
    if (!documentId) return;

    this.loadingDocumentStatuses = true;
    this.documentStatusError = '';

    this.api.removeDocumentStatus(documentId, code).subscribe({
      next: () => {
        this.refreshDocumentStatuses(documentId);
      },
      error: () => {
        this.documentStatusError = 'Не удалось удалить статус';
        this.loadingDocumentStatuses = false;
        this.cdr.detectChanges();
      },
    });
  }

  get unassignedDocumentStatuses(): {
    code: string;
    name_ru: string;
    description: string | null;
  }[] {
    const assigned = new Set(this.documentStatusTags.map((status) => status.code));
    return this.availableDocumentStatuses.filter((status) => !assigned.has(status.code));
  }

  private rebuildStatusSpeedDialItems(): void {
    this.statusSpeedDialItems = this.unassignedDocumentStatuses.map((status) => ({
      id: status.code,
      label: status.name_ru,
      command: () => this.onDocumentStatusSelected(status.code),
    }));
  }

  private addDocumentStatus(): void {
    const documentId = this.article?.document_id;
    const code = this.pendingStatusCode.trim();
    if (!documentId || !code) return;

    this.loadingDocumentStatuses = true;
    this.documentStatusError = '';

    this.api.assignDocumentStatus(documentId, code).subscribe({
      next: () => {
        this.pendingStatusCode = '';
        this.refreshDocumentStatuses(documentId);
      },
      error: () => {
        this.documentStatusError = 'Не удалось добавить статус';
        this.loadingDocumentStatuses = false;
        this.cdr.detectChanges();
      },
    });
  }

  private syncDocumentStatusTagsFromArticle(): void {
    if (!this.article) {
      this.documentStatusTags = [];
      this.statusSpeedDialItems = [];
      return;
    }

    const statusItems = this.article.statuses || [];
    this.documentStatusTags = statusItems
      .map((status) => ({
        code: status.code,
        label: status.name_ru || status.code,
      }))
      .filter((status) => !!status.code);
    this.rebuildStatusSpeedDialItems();
  }

  private loadAvailableDocumentStatuses(): void {
    this.api.getAvailableDocumentStatuses().subscribe({
      next: (statuses) => {
        this.availableDocumentStatuses = statuses;
        this.rebuildStatusSpeedDialItems();
        this.cdr.detectChanges();
      },
      error: () => {
        this.documentStatusError = 'Не удалось загрузить справочник статусов';
        this.cdr.detectChanges();
      },
    });
  }

  private refreshDocumentStatuses(documentId: string): void {
    this.api.getDocumentStatuses(documentId).subscribe({
      next: (response) => {
        if (this.article) {
          this.article.statuses = response.statuses;
        }
        this.syncDocumentStatusTagsFromArticle();
        this.loadingDocumentStatuses = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.documentStatusError = 'Статусы обновлены, но не удалось получить актуальный список';
        this.loadingDocumentStatuses = false;
        this.cdr.detectChanges();
      },
    });
  }
}
