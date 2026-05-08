import { Component, Input, OnChanges, SimpleChanges } from '@angular/core';
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
  loadingDocumentStatuses = false;
  documentStatusError = '';
  isEditingStatusBlock = false;
  pendingStatusCode = '';

  constructor(private api: ArticleParserApi) {}

  ngOnChanges(changes: SimpleChanges): void {
    if (!changes['article']) {
      return;
    }

    if (!this.article) {
      this.documentStatusTags = [];
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

  get statusSpeedDialItems(): MenuItem[] {
    return this.unassignedDocumentStatuses.map((status) => ({
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
      },
    });
  }

  private syncDocumentStatusTagsFromArticle(): void {
    if (!this.article) {
      this.documentStatusTags = [];
      return;
    }

    const statusItems = this.article.statuses || [];
    this.documentStatusTags = statusItems
      .map((status) => ({
        code: status.code,
        label: status.name_ru || status.code,
      }))
      .filter((status) => !!status.code);
  }

  private loadAvailableDocumentStatuses(): void {
    this.api.getAvailableDocumentStatuses().subscribe({
      next: (statuses) => {
        this.availableDocumentStatuses = statuses;
      },
      error: () => {
        this.documentStatusError = 'Не удалось загрузить справочник статусов';
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
      },
      error: () => {
        this.documentStatusError = 'Статусы обновлены, но не удалось получить актуальный список';
        this.loadingDocumentStatuses = false;
      },
    });
  }
}
