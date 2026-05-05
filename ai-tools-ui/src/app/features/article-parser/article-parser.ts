import { ChangeDetectorRef, Component, ElementRef, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FloatLabelModule } from 'primeng/floatlabel';
import { InputTextModule } from 'primeng/inputtext';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { SkeletonModule } from 'primeng/skeleton';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { ChipModule } from 'primeng/chip';
import { ImageModule } from 'primeng/image';
import { ArticleParserApi } from './article-parser-api';
import { ArticleParserState } from './article-parser-state';
import {
  ButtonVariant,
  OutlineButtonComponent,
} from '../../shared/ui/outline-button/outline-button.component';
import { ArticleParserUrlFormComponent } from './article-parser-url-form/article-parser-url-form';

@Component({
  selector: 'app-article-parser',
  imports: [
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressSpinnerModule,
    FloatLabelModule,
    InputTextModule,
    OutlineButtonComponent,
    ArticleParserUrlFormComponent,
    ChipModule,
    ImageModule,
    SkeletonModule,
  ],
  templateUrl: './article-parser.html',
  styleUrl: './article-parser.scss',
})
export class ArticleParser {
  @ViewChild('translationSkeleton') translationSkeleton?: ElementRef;
  @ViewChild('annotationSkeleton') annotationSkeleton?: ElementRef;
  @ViewChild('entitiesBlock') entitiesBlock?: ElementRef;
  readonly ButtonVariant = ButtonVariant;
  loadingArticle = false;
  loadingEntities = false;
  loadingTranslation = false;
  loadingSummary = false;
  loadingOriginalTags = false;
  loadingTranslatedTags = false;
  entitiesError = '';
  articleError = '';
  originalTagsError = '';
  translationError = '';
  translatedTagsError = '';
  summaryError = '';
  imagePreview: string | null = null;
  availableDocumentStatuses: { code: string; name_ru: string; description: string | null }[] = [];
  documentStatusTags: { code: string; label: string }[] = [];
  loadingDocumentStatuses = false;
  documentStatusError = '';
  isStatusPickerOpen = false;

  private buffer = '';

  constructor(
    private api: ArticleParserApi,
    public state: ArticleParserState,
    private cdr: ChangeDetectorRef,
  ) {}

  openImage(url: string): void {
    this.imagePreview = url;
  }

  closeImage(): void {
    this.imagePreview = null;
  }

  // =========================
  // ОСНОВНОЕ
  // =========================

  extractArticle(): void {
    const value = this.state.url.trim();
    if (!value) return;

    this.articleError = '';
    this.state.error = '';
    this.entitiesError = '';
    this.originalTagsError = '';
    this.translationError = '';
    this.state.article = null;
    this.state.entities = null;
    this.state.translatedText = '';
    this.state.annotation = '';
    this.state.originalTags = [];
    this.state.translatedTags = [];
    this.state.originalTagsText = '';
    this.state.translatedTagsText = '';
    this.state.editMode = false;

    this.loadingArticle = true;

    this.api.extractByUrl(value).subscribe({
      next: (response) => {
        this.state.article = response;
        this.syncDocumentStatusTagsFromArticle();
        this.loadAvailableDocumentStatuses();
        this.state.translatedText = response.translated_content?.trim() || '';
        this.state.annotation = (response.translated_summary || response.original_summary || '').trim();
        this.state.originalTags = response.original_tags || [];
        this.state.translatedTags = response.translated_tags || [];
        this.syncTagsToText();
        this.state.entities = {
          military_equipment: response.entities_military_equipment || [],
          manufacturers: response.entities_manufacturers || [],
          contracts: response.entities_contracts || [],
        };
        this.loadingArticle = false;
      },
      error: () => {
        this.articleError = 'Ошибка при извлечении статьи';
        this.loadingArticle = false;
      },
    });
  }

  requestEntities(): void {
    if (!this.state.article?.text) return;

    this.loadingEntities = true;
    this.entitiesError = '';
    this.state.entities = null;

    this.api.extractEntities(this.state.article.text).subscribe({
      next: (response) => {
        this.state.entities = response;
        this.loadingEntities = false;
      },
      error: () => {
        this.entitiesError = 'Ошибка при извлечении сущностей';
        this.loadingEntities = false;
      },
    });
  }

  async translateArticle(): Promise<void> {
    if (!this.state.article?.document_id) return;

    this.loadingTranslation = true;
    this.translationError = '';
    this.state.error = '';
    this.state.translatedText = '';
    this.state.annotation = '';
    this.state.translatedTags = [];
    this.state.translatedTagsText = '';

    this.scrollToElement(() => this.translationSkeleton);

    this.api.translateToRussianStream(this.state.article.document_id).subscribe({
      next: (chunk) => {
        this.state.translatedText += chunk;
        this.cdr.detectChanges();
      },
      error: () => {
        this.translationError = 'Ошибка при потоковом переводе статьи';
        this.loadingTranslation = false;
      },
      complete: () => {
        this.loadingTranslation = false;
      },
    });
  }

  async summarizeArticle(): Promise<void> {
    if (!this.state.article?.document_id || !this.state.translatedText.trim()) return;

    this.loadingSummary = true;
    this.summaryError = '';
    this.state.annotation = '';
    this.buffer = '';

    this.scrollToElement(() => this.annotationSkeleton);

    this.api.summarizeStream(this.state.article.document_id, 'translated').subscribe({
      next: (chunk) => {
        this.state.annotation += chunk;
        this.cdr.detectChanges();
      },
      error: () => {
        this.summaryError = 'Ошибка при потоковом формировании аннотации';
        this.loadingSummary = false;
        this.cdr.detectChanges();
      },
      complete: () => {
        this.loadingSummary = false;
        this.cdr.detectChanges();
      },
    });
  }
  clear(): void {
    this.state.clear();
    this.documentStatusTags = [];
    this.loadingDocumentStatuses = false;
    this.documentStatusError = '';
    this.isStatusPickerOpen = false;
    this.entitiesError = '';
    this.articleError = '';
    this.originalTagsError = '';
    this.translationError = '';
    this.translationError = '';
    this.translatedTagsError = '';
    this.summaryError = '';
  }

  // =========================
  // ТЕГИ
  // =========================

  tagOriginal(): void {
    if (!this.state.article?.document_id) return;

    this.loadingOriginalTags = true;
    this.originalTagsError = '';

    this.api.tagText(this.state.article.document_id, 12, false).subscribe({
      next: () => {
        this.reloadTagsFromServer('original');
      },
      error: () => {
        this.originalTagsError = 'Ошибка тегирования оригинала';
        this.loadingOriginalTags = false;
      },
    });
  }

  tagTranslated(): void {
    if (!this.state.article?.document_id) return;

    this.loadingTranslatedTags = true;
    this.translatedTagsError = '';

    this.api.tagText(this.state.article.document_id, 12, true).subscribe({
      next: () => {
        this.reloadTagsFromServer('translated');
      },
      error: () => {
        this.translatedTagsError = 'Ошибка при тегировании перевода';
        this.loadingTranslatedTags = false;
      },
    });
  }

  // =========================
  // ПОДСВЕТКА СУЩНОСТЕЙ
  // =========================

  private escapeRegExp(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  // =========================
  // РЕДАКТИРОВАНИЕ
  // =========================

  toggleEditMode(): void {
    this.state.editMode = !this.state.editMode;

    if (this.state.editMode) {
      this.syncTagsToText();
      return;
    }

    this.applyEditedTags();
  }

  applyEditedTags(): void {
    this.state.originalTags = this.textToTags(this.state.originalTagsText);
    this.state.translatedTags = this.textToTags(this.state.translatedTagsText);
  }

  private syncTagsToText(): void {
    this.state.originalTagsText = this.state.originalTags.join('\n');
    this.state.translatedTagsText = this.state.translatedTags.join('\n');
  }

  private textToTags(value: string): string[] {
    return value
      .split('\n')
      .map((x) => x.trim())
      .filter(Boolean)
      .filter((x, i, arr) => arr.indexOf(x) === i);
  }

  private reloadTagsFromServer(kind: 'original' | 'translated'): void {
    const url = this.state.url.trim();
    if (!url) {
      if (kind === 'original') {
        this.loadingOriginalTags = false;
      } else {
        this.loadingTranslatedTags = false;
      }
      return;
    }

    this.api.extractByUrl(url).subscribe({
      next: (response) => {
        this.state.article = response;
        this.syncDocumentStatusTagsFromArticle();
        this.state.originalTags = response.original_tags || [];
        this.state.translatedTags = response.translated_tags || [];
        this.syncTagsToText();
        this.loadingOriginalTags = false;
        this.loadingTranslatedTags = false;
        this.cdr.detectChanges();
        this.scrollToElement(() => this.entitiesBlock);
      },
      error: () => {
        if (kind === 'original') {
          this.originalTagsError = 'Теги сохранены, но не удалось обновить список';
          this.loadingOriginalTags = false;
        } else {
          this.translatedTagsError = 'Теги сохранены, но не удалось обновить список';
          this.loadingTranslatedTags = false;
        }
      },
    });
  }

  // =========================
  // СУЩНОСТИ
  // =========================

  updateEntityList(
    field: 'military_equipment' | 'manufacturers' | 'contracts',
    value: string,
  ): void {
    if (!this.state.entities) {
      this.state.entities = {
        military_equipment: [],
        manufacturers: [],
        contracts: [],
      };
    }

    this.state.entities[field] = value
      .split('\n')
      .map((x) => x.trim())
      .filter(Boolean);
  }

  // =========================
  // ЗАГЛУШКИ
  // =========================

  sendToMax(): void {
    console.log('sendToMax', {
      article: this.state.article,
      text: this.state.translatedText,
      tags: this.state.translatedTags,
      annotation: this.state.annotation,
    });
  }

  saveToDb(): void {
    console.log('saveToDb', {
      article: this.state.article,
      text: this.state.translatedText,
      tags: this.state.translatedTags,
      annotation: this.state.annotation,
    });
  }

  removeOriginalTag(tag: string): void {
    this.state.originalTags = this.state.originalTags.filter((item) => item !== tag);
    this.syncTagsToText();
  }

  removeTranslatedTag(tag: string): void {
    this.state.translatedTags = this.state.translatedTags.filter((item) => item !== tag);
    this.syncTagsToText();
  }

  addDocumentStatus(): void {
    const documentId = this.state.article?.document_id;
    const code = this.pendingStatusCode.trim();
    if (!documentId || !code) return;

    this.loadingDocumentStatuses = true;
    this.documentStatusError = '';

    this.api.assignDocumentStatus(documentId, code).subscribe({
      next: () => {
        this.pendingStatusCode = '';
        this.isStatusPickerOpen = false;
        this.refreshDocumentStatuses(documentId);
      },
      error: () => {
        this.documentStatusError = 'Не удалось добавить статус';
        this.loadingDocumentStatuses = false;
      },
    });
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
    const documentId = this.state.article?.document_id;
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

  autoResize(event: Event): void {
    const textarea = event.target as HTMLTextAreaElement;

    textarea.style.height = 'auto';
    textarea.style.height = `${textarea.scrollHeight}px`;
  }

  private escapeHtml(value: string): string {
    return value
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  get mainImageUrl(): string {
    return this.state.article?.main_image?.trim() || '';
  }

  private syncDocumentStatusTagsFromArticle(): void {
    if (!this.state.article) {
      this.documentStatusTags = [];
      return;
    }

    const statusItems = this.state.article.statuses || [];
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
        if (this.state.article) {
          this.state.article.statuses = response.statuses;
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

  pendingStatusCode = '';

  toggleStatusPicker(): void {
    if (!this.state.editMode || this.loadingDocumentStatuses || !this.unassignedDocumentStatuses.length) {
      return;
    }

    this.isStatusPickerOpen = !this.isStatusPickerOpen;
  }

  get unassignedDocumentStatuses(): { code: string; name_ru: string; description: string | null }[] {
    const assigned = new Set(this.documentStatusTags.map((status) => status.code));
    return this.availableDocumentStatuses.filter((status) => !assigned.has(status.code));
  }

  onImageLoad(): void {
    console.log('Картинка загрузилась:', this.mainImageUrl);
  }

  onImageError(event: Event): void {
    console.log('Ошибка загрузки картинки:', this.mainImageUrl, event);
  }

  get hasEmptyEntitiesResult(): boolean {
    return (
      !!this.state.entities &&
      !this.loadingEntities &&
      !this.state.entities.military_equipment?.length &&
      !this.state.entities.manufacturers?.length &&
      !this.state.entities.contracts?.length
    );
  }

  get hasEntitiesBlock(): boolean {
    return (
      this.loadingEntities ||
      this.loadingOriginalTags ||
      this.loadingTranslatedTags ||
      !!this.state.entities ||
      this.state.originalTags.length > 0 ||
      this.state.translatedTags.length > 0
    );
  }

  get isLoading(): boolean {
    return (
      this.loadingArticle ||
      this.loadingEntities ||
      this.loadingTranslation ||
      this.loadingSummary ||
      this.loadingOriginalTags ||
      this.loadingTranslatedTags
    );
  }

  get isDisabled(): boolean {
    return this.isLoading || this.state.editMode;
  }

  get highlightedArticleText(): string {
    const text = this.state.article?.text || '';

    const entities = [
      ...(this.state.entities?.military_equipment || []),
      ...(this.state.entities?.manufacturers || []),
      ...(this.state.entities?.contracts || []),
    ]
      .filter(Boolean)
      .sort((a, b) => b.length - a.length);

    if (!entities.length) {
      return this.escapeHtml(text).replace(/\n/g, '<br>');
    }

    let result = this.escapeHtml(text);

    entities.forEach((entity) => {
      const escapedEntity = this.escapeHtml(entity.trim());

      const pattern = this.createFlexibleEntityPattern(escapedEntity);

      result = result.replace(pattern, (match) => {
        if (match.includes('highlighted-entity')) {
          return match;
        }

        return `<span class="highlighted-entity">${match}</span>`;
      });
    });

    return result.replace(/\n/g, '<br>');
  }

  private createFlexibleEntityPattern(value: string): RegExp {
    const escaped = value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

    const flexible = escaped.replace(/\\ /g, '\\s+').replace(/-/g, '[-–—-]?');

    return new RegExp(flexible, 'gi');
  }

  private scrollToElement(getElement: () => ElementRef | undefined): void {
    setTimeout(() => {
      this.cdr.detectChanges();

      getElement()?.nativeElement.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      });
    }, 0);
  }
}
