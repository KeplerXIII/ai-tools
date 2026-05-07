import { ChangeDetectorRef, Component, ElementRef, ViewChild } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { FloatLabelModule } from 'primeng/floatlabel';
import { InputTextModule } from 'primeng/inputtext';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { SkeletonModule } from 'primeng/skeleton';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { TextareaModule } from 'primeng/textarea';
import { ArticleParserUrlFormComponent } from './ui/article-parser-url-form/article-parser-url-form';
import { ArticleParserStatusComponent } from './ui/article-parser-status/article-parser-status';
import { ArticleParserMetaComponent } from './ui/article-parser-meta/article-parser-meta';
import { ArticleParserCategoriesComponent } from './ui/article-parser-categories/article-parser-categories';
import { ArticleParserEntitiesComponent } from './ui/article-parser-entities/article-parser-entities';
import {
  ArticleParserApi,
  DocumentTagsResponse,
} from './api/article-parser-api';
import { ArticleParserState } from './model/article-parser-state';
import {
  ButtonVariant,
  OutlineButtonComponent,
} from '../../shared/ui/outline-button/outline-button.component';
import { buildHighlightedArticleTextByGroups } from './lib/article-highlighter';
import { scrollToElement } from './lib/scroll-to-element';

export type ArticleParserBlock =
  | 'original'
  | 'translation'
  | 'annotation';

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
    ArticleParserStatusComponent,
    ArticleParserMetaComponent,
    ArticleParserCategoriesComponent,
    ArticleParserEntitiesComponent,
    SkeletonModule,
    TextareaModule,
  ],
  templateUrl: './article-parser.html',
  styleUrl: './article-parser.scss',
})
export class ArticleParser {
  @ViewChild('translationSkeleton') translationSkeleton?: ElementRef;
  @ViewChild('annotationSkeleton') annotationSkeleton?: ElementRef;
  @ViewChild('originalTextPreview') originalTextPreview?: ElementRef<HTMLElement>;
  @ViewChild('originalTextEditor') originalTextEditor?: ElementRef<HTMLElement>;
  readonly ButtonVariant = ButtonVariant;
  loadingArticle = false;
  loadingEntitiesSection = false;
  loadingCategories = false;
  loadingTranslation = false;
  loadingSummary = false;
  loadingOriginalTags = false;
  loadingTranslatedTags = false;
  articleError = '';
  originalTagsError = '';
  translationError = '';
  translatedTagsError = '';
  summaryError = '';

  isEditingOriginalBlock = false;
  isEditingTranslationBlock = false;
  isEditingAnnotationBlock = false;

  private buffer = '';
  private originalTextViewportScroll = 0;
  private lastAutoloadKey = '';

  constructor(
    private api: ArticleParserApi,
    public state: ArticleParserState,
    private cdr: ChangeDetectorRef,
    private route: ActivatedRoute,
  ) {}

  // =========================
  // ОСНОВНОЕ
  // =========================

  extractArticle(): void {
    const value = this.state.url.trim();
    if (!value) return;

    this.articleError = '';
    this.state.error = '';
    this.originalTagsError = '';
    this.translationError = '';
    this.loadingCategories = false;
    this.state.article = null;
    this.state.entities = null;
    this.state.categories = null;
    this.state.translatedText = '';
    this.state.annotation = '';
    this.state.originalTags = [];
    this.state.translatedTags = [];
    this.resetBlockEditors();

    this.loadingArticle = true;

    this.api.extractByUrl(value).subscribe({
      next: (response) => {
        this.state.article = response;
        this.state.translatedText = response.translated_content?.trim() || '';
        this.state.annotation = (
          response.translated_summary ||
          response.original_summary ||
          ''
        ).trim();
        this.state.originalTags = response.original_tags || [];
        this.state.translatedTags = response.translated_tags || [];
        this.state.entities = {
          military_equipment: response.entities_military_equipment || [],
          manufacturers: response.entities_manufacturers || [],
          contracts: response.entities_contracts || [],
        };
        this.state.categories = response.categories ?? [];
        this.loadingArticle = false;
      },
      error: () => {
        this.articleError = 'Ошибка при извлечении статьи';
        this.loadingArticle = false;
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

    scrollToElement(() => this.translationSkeleton, this.cdr);

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

    scrollToElement(() => this.annotationSkeleton, this.cdr);

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

  // =========================
  // РЕДАКТИРОВАНИЕ
  // =========================

  toggleBlockEdit(block: ArticleParserBlock): void {
    switch (block) {
      case 'original':
        if (!this.isEditingOriginalBlock) {
          const docId = this.state.article?.document_id;
          if (docId) {
            this.state.error = '';
            this.api.lockDocument(docId).subscribe({
              error: () => {
                this.state.error = 'Не удалось заблокировать документ для редактирования';
                this.cdr.detectChanges();
              },
            });
          }
        }
        if (!this.isEditingOriginalBlock) {
          this.originalTextViewportScroll = this.originalTextPreview?.nativeElement?.scrollTop ?? 0;
        } else {
          const ta = this.getOriginalTextTextarea();
          this.originalTextViewportScroll = ta?.scrollTop ?? 0;
        }
        this.isEditingOriginalBlock = !this.isEditingOriginalBlock;
        this.scheduleRestoreOriginalTextScroll();
        if (!this.isEditingOriginalBlock) {
          const docId = this.state.article?.document_id;
          if (docId && this.state.article) {
            this.state.error = '';
            this.api
              .saveDocument(docId, {
                original_content: this.state.article.text ?? '',
              })
              .subscribe({
                error: () => {
                  this.state.error = 'Не удалось сохранить исходный текст';
                  this.cdr.detectChanges();
                },
              });
          }
        }
        break;
      case 'translation':
        if (!this.isEditingTranslationBlock) {
          const docId = this.state.article?.document_id;
          if (docId) {
            this.state.error = '';
            this.api.lockDocument(docId).subscribe({
              error: () => {
                this.state.error = 'Не удалось заблокировать документ для редактирования';
                this.cdr.detectChanges();
              },
            });
          }
        }
        this.isEditingTranslationBlock = !this.isEditingTranslationBlock;
        if (!this.isEditingTranslationBlock) {
          const docId = this.state.article?.document_id;
          if (docId) {
            this.state.error = '';
            this.api
              .saveDocument(docId, {
                translated_content: this.state.translatedText ?? '',
              })
              .subscribe({
                error: () => {
                  this.state.error = 'Не удалось сохранить перевод';
                  this.cdr.detectChanges();
                },
              });
          }
        }
        break;
      case 'annotation':
        if (!this.isEditingAnnotationBlock) {
          const docId = this.state.article?.document_id;
          if (docId) {
            this.state.error = '';
            this.api.lockDocument(docId).subscribe({
              error: () => {
                this.state.error = 'Не удалось заблокировать документ для редактирования';
                this.cdr.detectChanges();
              },
            });
          }
        }
        this.isEditingAnnotationBlock = !this.isEditingAnnotationBlock;
        if (!this.isEditingAnnotationBlock) {
          const docId = this.state.article?.document_id;
          if (docId) {
            const hasTranslation = !!this.state.translatedText?.trim();
            this.state.error = '';
            this.api
              .saveDocument(
                docId,
                hasTranslation
                  ? { translated_summary: this.state.annotation ?? '' }
                  : { original_summary: this.state.annotation ?? '' },
              )
              .subscribe({
                error: () => {
                  this.state.error = 'Не удалось сохранить аннотацию';
                  this.cdr.detectChanges();
                },
              });
          }
        }
        break;
    }
  }

  private resetBlockEditors(): void {
    this.isEditingOriginalBlock = false;
    this.isEditingTranslationBlock = false;
    this.isEditingAnnotationBlock = false;
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
        // Tags are rendered in the dedicated entities component.
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

  autoResize(event: Event): void {
    const textarea = event.target as HTMLTextAreaElement;

    textarea.style.height = 'auto';
    textarea.style.height = `${textarea.scrollHeight}px`;
  }

  get isLoading(): boolean {
    return (
      this.loadingArticle ||
      this.loadingEntitiesSection ||
      this.loadingCategories ||
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

    return buildHighlightedArticleTextByGroups(text, [
      { className: 'highlighted-entity-military', entities: military },
      { className: 'highlighted-entity-manufacturer', entities: manufacturers },
      { className: 'highlighted-entity-contract', entities: contracts },
    ]);
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
