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
import { TextareaModule } from 'primeng/textarea';
import {
  ArticleParserApi,
  DocumentEntityRef,
  DocumentTagRef,
  DocumentTagsResponse,
  EntitiesResponse,
} from './article-parser-api';
import { ArticleParserState } from './article-parser-state';
import {
  ButtonVariant,
  OutlineButtonComponent,
} from '../../shared/ui/outline-button/outline-button.component';
import { ArticleParserUrlFormComponent } from './article-parser-url-form/article-parser-url-form';

export type ArticleParserBlock =
  | 'status'
  | 'meta'
  | 'entities'
  | 'original'
  | 'translation'
  | 'annotation';

export type EntitySection = 'military_equipment' | 'manufacturers' | 'contracts';

export type TagScope = 'original' | 'translated';

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
    TextareaModule,
  ],
  templateUrl: './article-parser.html',
  styleUrl: './article-parser.scss',
})
export class ArticleParser {
  @ViewChild('translationSkeleton') translationSkeleton?: ElementRef;
  @ViewChild('annotationSkeleton') annotationSkeleton?: ElementRef;
  @ViewChild('entitiesBlock') entitiesBlock?: ElementRef;
  @ViewChild('originalTextPreview') originalTextPreview?: ElementRef<HTMLElement>;
  @ViewChild('originalTextEditor') originalTextEditor?: ElementRef<HTMLElement>;
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

  entityPickerOpen: EntitySection | null = null;
  entityPickerSearch = '';
  entityPickerCatalogItems: DocumentEntityRef[] = [];
  loadingEntityPickerCatalog = false;
  loadingDocumentEntitiesMutation = false;

  tagPickerOpen: TagScope | null = null;
  tagPickerSearch = '';
  tagPickerCatalogItems: DocumentTagRef[] = [];
  loadingTagPickerCatalog = false;
  loadingDocumentTagsMutation = false;

  isEditingStatusBlock = false;
  isEditingMetaBlock = false;
  isEditingEntitiesBlock = false;
  isEditingOriginalBlock = false;
  isEditingTranslationBlock = false;
  isEditingAnnotationBlock = false;

  private buffer = '';
  private originalTextViewportScroll = 0;

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
    this.resetBlockEditors();

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
    if (!this.state.article?.text || !this.state.article.document_id) return;

    this.loadingEntities = true;
    this.entitiesError = '';
    this.state.entities = null;

    this.api.extractEntities(this.state.article.document_id).subscribe({
      next: (response) => {
        this.state.entities = {
          military_equipment: response.military_equipment || [],
          manufacturers: response.manufacturers || [],
          contracts: response.contracts || [],
        };
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
    this.resetBlockEditors();
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

  toggleBlockEdit(block: ArticleParserBlock): void {
    switch (block) {
      case 'status':
        this.isEditingStatusBlock = !this.isEditingStatusBlock;
        if (!this.isEditingStatusBlock) {
          this.isStatusPickerOpen = false;
        }
        break;
      case 'meta':
        this.isEditingMetaBlock = !this.isEditingMetaBlock;
        break;
      case 'entities':
        this.isEditingEntitiesBlock = !this.isEditingEntitiesBlock;
        if (!this.isEditingEntitiesBlock) {
          this.closeEntityPicker();
          this.closeTagPicker();
        }
        break;
      case 'original':
        if (!this.isEditingOriginalBlock) {
          this.originalTextViewportScroll =
            this.originalTextPreview?.nativeElement?.scrollTop ?? 0;
        } else {
          const ta = this.getOriginalTextTextarea();
          this.originalTextViewportScroll = ta?.scrollTop ?? 0;
        }
        this.isEditingOriginalBlock = !this.isEditingOriginalBlock;
        this.scheduleRestoreOriginalTextScroll();
        break;
      case 'translation':
        this.isEditingTranslationBlock = !this.isEditingTranslationBlock;
        break;
      case 'annotation':
        this.isEditingAnnotationBlock = !this.isEditingAnnotationBlock;
        break;
    }
  }

  private resetBlockEditors(): void {
    this.isEditingStatusBlock = false;
    this.isEditingMetaBlock = false;
    this.isEditingEntitiesBlock = false;
    this.isEditingOriginalBlock = false;
    this.isEditingTranslationBlock = false;
    this.isEditingAnnotationBlock = false;
    this.isStatusPickerOpen = false;
    this.closeEntityPicker();
    this.closeTagPicker();
  }

  private closeTagPicker(): void {
    this.tagPickerOpen = null;
    this.tagPickerSearch = '';
    this.tagPickerCatalogItems = [];
    this.loadingTagPickerCatalog = false;
  }

  private closeEntityPicker(): void {
    this.entityPickerOpen = null;
    this.entityPickerSearch = '';
    this.entityPickerCatalogItems = [];
    this.loadingEntityPickerCatalog = false;
  }

  entityTypeCodeForSection(section: EntitySection): string {
    if (section === 'manufacturers') {
      return 'manufacturer';
    }
    if (section === 'contracts') {
      return 'contract';
    }
    return 'military_equipment';
  }

  toggleEntityPicker(section: EntitySection): void {
    if (!this.isEditingEntitiesBlock || !this.state.article?.document_id) {
      return;
    }

    if (this.entityPickerOpen === section) {
      this.closeEntityPicker();
      return;
    }

    this.entityPickerOpen = section;
    this.entityPickerSearch = '';
    this.entityPickerCatalogItems = [];
    const docId = this.state.article.document_id;
    const typeCode = this.entityTypeCodeForSection(section);
    this.loadingEntityPickerCatalog = true;

    this.api.getEntityCatalog(docId, typeCode).subscribe({
      next: (items: DocumentEntityRef[]) => {
        this.entityPickerCatalogItems = items;
        this.loadingEntityPickerCatalog = false;
      },
      error: () => {
        this.entitiesError = 'Не удалось загрузить список сущностей';
        this.loadingEntityPickerCatalog = false;
        this.closeEntityPicker();
      },
    });
  }

  get filteredEntityPickerItems(): DocumentEntityRef[] {
    const q = this.entityPickerSearch.trim().toLowerCase();
    if (!q) {
      return this.entityPickerCatalogItems;
    }
    return this.entityPickerCatalogItems.filter((item) => item.name.toLowerCase().includes(q));
  }

  onEntityPickerSelect(item: DocumentEntityRef): void {
    const docId = this.state.article?.document_id;
    if (!docId || this.loadingDocumentEntitiesMutation) {
      return;
    }

    this.loadingDocumentEntitiesMutation = true;
    this.entitiesError = '';

    this.api.assignDocumentEntity(docId, item.id).subscribe({
      next: () => {
        this.closeEntityPicker();
        this.refreshDocumentEntitiesFromServer(docId);
      },
      error: () => {
        this.entitiesError = 'Не удалось добавить сущность';
        this.loadingDocumentEntitiesMutation = false;
      },
    });
  }

  private refreshDocumentEntitiesFromServer(documentId: string): void {
    this.api.getDocumentEntities(documentId).subscribe({
      next: (res: EntitiesResponse) => {
        this.state.entities = {
          military_equipment: res.military_equipment || [],
          manufacturers: res.manufacturers || [],
          contracts: res.contracts || [],
        };
        this.loadingDocumentEntitiesMutation = false;
      },
      error: () => {
        this.entitiesError = 'Не удалось обновить список сущностей';
        this.loadingDocumentEntitiesMutation = false;
      },
    });
  }

  toggleTagPicker(scope: TagScope): void {
    if (!this.isEditingEntitiesBlock || !this.state.article?.document_id) {
      return;
    }

    if (this.tagPickerOpen === scope) {
      this.closeTagPicker();
      return;
    }

    this.tagPickerOpen = scope;
    this.tagPickerSearch = '';
    this.tagPickerCatalogItems = [];
    const docId = this.state.article.document_id;
    this.loadingTagPickerCatalog = true;

    this.api.getTagCatalog(docId, scope).subscribe({
      next: (items: DocumentTagRef[]) => {
        this.tagPickerCatalogItems = items;
        this.loadingTagPickerCatalog = false;
      },
      error: () => {
        if (scope === 'original') {
          this.originalTagsError = 'Не удалось загрузить каталог тегов';
        } else {
          this.translatedTagsError = 'Не удалось загрузить каталог тегов';
        }
        this.loadingTagPickerCatalog = false;
        this.closeTagPicker();
      },
    });
  }

  get filteredTagPickerItems(): DocumentTagRef[] {
    const q = this.tagPickerSearch.trim().toLowerCase();
    if (!q) {
      return this.tagPickerCatalogItems;
    }
    return this.tagPickerCatalogItems.filter((item) => item.name.toLowerCase().includes(q));
  }

  onTagPickerSelect(item: DocumentTagRef): void {
    const docId = this.state.article?.document_id;
    if (!docId || this.loadingDocumentTagsMutation) {
      return;
    }

    this.loadingDocumentTagsMutation = true;
    this.originalTagsError = '';
    this.translatedTagsError = '';

    this.api.assignDocumentTag(docId, item.id).subscribe({
      next: () => {
        this.closeTagPicker();
        this.refreshDocumentTagsFromServer(docId);
      },
      error: () => {
        const scope = this.tagPickerOpen;
        if (scope === 'translated') {
          this.translatedTagsError = 'Не удалось добавить тег';
        } else {
          this.originalTagsError = 'Не удалось добавить тег';
        }
        this.loadingDocumentTagsMutation = false;
      },
    });
  }

  private refreshDocumentTagsFromServer(documentId: string): void {
    this.api.getDocumentTags(documentId).subscribe({
      next: (res: DocumentTagsResponse) => {
        this.state.originalTags = res.original_tags || [];
        this.state.translatedTags = res.translated_tags || [];
        this.loadingDocumentTagsMutation = false;
      },
      error: () => {
        this.originalTagsError = 'Не удалось обновить список тегов';
        this.translatedTagsError = 'Не удалось обновить список тегов';
        this.loadingDocumentTagsMutation = false;
      },
    });
  }

  private reloadTagsFromServer(kind: 'original' | 'translated'): void {
    const documentId = this.state.article?.document_id;
    if (!documentId) {
      if (kind === 'original') {
        this.loadingOriginalTags = false;
      } else {
        this.loadingTranslatedTags = false;
      }
      return;
    }

    this.api.getDocumentTags(documentId).subscribe({
      next: (res: DocumentTagsResponse) => {
        this.state.originalTags = res.original_tags || [];
        this.state.translatedTags = res.translated_tags || [];
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

  removeEntityItem(item: DocumentEntityRef): void {
    const docId = this.state.article?.document_id;
    if (!docId || this.loadingDocumentEntitiesMutation) {
      return;
    }

    this.loadingDocumentEntitiesMutation = true;
    this.entitiesError = '';

    this.api.removeDocumentEntity(docId, item.id).subscribe({
      next: () => {
        this.refreshDocumentEntitiesFromServer(docId);
      },
      error: () => {
        this.entitiesError = 'Не удалось удалить сущность';
        this.loadingDocumentEntitiesMutation = false;
      },
    });
  }

  removeOriginalTag(tag: DocumentTagRef): void {
    const docId = this.state.article?.document_id;
    if (!docId || this.loadingDocumentTagsMutation) {
      return;
    }

    this.loadingDocumentTagsMutation = true;
    this.originalTagsError = '';

    this.api.removeDocumentTag(docId, tag.id).subscribe({
      next: () => {
        this.refreshDocumentTagsFromServer(docId);
      },
      error: () => {
        this.originalTagsError = 'Не удалось удалить тег';
        this.loadingDocumentTagsMutation = false;
      },
    });
  }

  removeTranslatedTag(tag: DocumentTagRef): void {
    const docId = this.state.article?.document_id;
    if (!docId || this.loadingDocumentTagsMutation) {
      return;
    }

    this.loadingDocumentTagsMutation = true;
    this.translatedTagsError = '';

    this.api.removeDocumentTag(docId, tag.id).subscribe({
      next: () => {
        this.refreshDocumentTagsFromServer(docId);
      },
      error: () => {
        this.translatedTagsError = 'Не удалось удалить тег';
        this.loadingDocumentTagsMutation = false;
      },
    });
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
    if (
      !this.isEditingStatusBlock ||
      this.loadingDocumentStatuses ||
      !this.unassignedDocumentStatuses.length
    ) {
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
    return this.isLoading;
  }

  get highlightedArticleText(): string {
    const text = this.state.article?.text || '';
    const ent = this.state.entities;

    const sortDesc = (a: string, b: string) => b.length - a.length;
    const military = [...(ent?.military_equipment || [])]
      .map((e) => e.name)
      .filter(Boolean)
      .sort(sortDesc);
    const manufacturers = [...(ent?.manufacturers || [])]
      .map((e) => e.name)
      .filter(Boolean)
      .sort(sortDesc);
    const contracts = [...(ent?.contracts || [])]
      .map((e) => e.name)
      .filter(Boolean)
      .sort(sortDesc);

    if (!military.length && !manufacturers.length && !contracts.length) {
      return this.escapeHtml(text).replace(/\n/g, '<br>');
    }

    let result = this.escapeHtml(text);
    result = this.applyEntityHighlights(result, military, 'highlighted-entity-military');
    result = this.applyEntityHighlights(result, manufacturers, 'highlighted-entity-manufacturer');
    result = this.applyEntityHighlights(result, contracts, 'highlighted-entity-contract');

    return result.replace(/\n/g, '<br>');
  }

  private applyEntityHighlights(
    html: string,
    entities: string[],
    className: string,
  ): string {
    let result = html;

    for (const entity of entities) {
      const escapedEntity = this.escapeHtml(entity.trim());
      const pattern = this.createFlexibleEntityPattern(escapedEntity);

      result = result.replace(pattern, (match) => {
        if (match.includes('highlighted-entity')) {
          return match;
        }

        return `<span class="${className}">${match}</span>`;
      });
    }

    return result;
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

  private getOriginalTextTextarea(): HTMLTextAreaElement | null {
    const host = this.originalTextEditor?.nativeElement;
    if (!host) {
      return null;
    }
    return host.querySelector('textarea');
  }

  /** Keep viewport and in-block scroll when swapping preview ↔ textarea */
  private scheduleRestoreOriginalTextScroll(): void {
    const savedInnerScroll = this.originalTextViewportScroll;
    const savedWinX = window.scrollX;
    const savedWinY = window.scrollY;

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        window.scrollTo(savedWinX, savedWinY);

        const textarea = this.getOriginalTextTextarea();
        const preview = this.originalTextPreview?.nativeElement;
        if (this.isEditingOriginalBlock && textarea) {
          textarea.scrollTop = savedInnerScroll;
          textarea.focus({ preventScroll: true });
        } else if (!this.isEditingOriginalBlock && preview) {
          preview.scrollTop = savedInnerScroll;
        }
      });
    });
  }
}
