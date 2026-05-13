import { ChangeDetectorRef, Component, DestroyRef, NgZone, OnInit, ViewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { InputTextModule } from 'primeng/inputtext';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { ArticleParserUrlFormComponent } from './ui/article-parser-url-form/article-parser-url-form';
import { ArticleParserStatusComponent } from './ui/article-parser-status/article-parser-status';
import { ArticleParserMetaComponent } from './ui/article-parser-meta/article-parser-meta';
import { ArticleParserCategoriesComponent } from './ui/article-parser-categories/article-parser-categories';
import { ArticleParserEntitiesComponent } from './ui/article-parser-entities/article-parser-entities';
import { ArticleParserOriginalTextComponent } from './ui/article-parser-original-text/article-parser-original-text';
import { ArticleParserTranslationComponent } from './ui/article-parser-translation/article-parser-translation';
import { ArticleParserAnnotationComponent } from './ui/article-parser-annotation/article-parser-annotation';
import { ArticleParserArticleLoadingComponent } from './ui/article-parser-article-loading/article-parser-article-loading';
import {
  ArticleParserApi,
  DocumentTagsResponse,
} from './api/article-parser-api';
import { ArticleParserState } from './model/article-parser-state';
import { scrollToElement } from './lib/scroll-to-element';
import { HttpErrorResponse } from '@angular/common/http';
import { DocumentsApi } from '../documents/documents-api';

@Component({
  selector: 'app-article-parser',
  imports: [
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    InputTextModule,
    ArticleParserUrlFormComponent,
    ArticleParserStatusComponent,
    ArticleParserMetaComponent,
    ArticleParserCategoriesComponent,
    ArticleParserEntitiesComponent,
    ArticleParserOriginalTextComponent,
    ArticleParserTranslationComponent,
    ArticleParserAnnotationComponent,
    ArticleParserArticleLoadingComponent,
  ],
  templateUrl: './article-parser.html',
  styleUrl: './article-parser.scss',
})
export class ArticleParser implements OnInit {
  @ViewChild(ArticleParserOriginalTextComponent)
  originalTextComponent?: ArticleParserOriginalTextComponent;
  @ViewChild(ArticleParserTranslationComponent)
  translationComponent?: ArticleParserTranslationComponent;
  @ViewChild(ArticleParserAnnotationComponent)
  annotationComponent?: ArticleParserAnnotationComponent;
  loadingArticle = false;
  loadingEntitiesSection = false;
  loadingCategories = false;
  loadingTranslation = false;
  loadingSummary = false;
  loadingOriginalTags = false;
  loadingTranslatedTags = false;
  loadingFullPipeline = false;
  fullPipelineMessage = '';
  fullPipelineError = '';
  articleError = '';
  originalTagsError = '';
  translationError = '';
  translatedTagsError = '';
  summaryError = '';

  private buffer = '';
  private lastAutoloadKey = '';

  constructor(
    private api: ArticleParserApi,
    private documentsApi: DocumentsApi,
    public state: ArticleParserState,
    private cdr: ChangeDetectorRef,
    private ngZone: NgZone,
    private route: ActivatedRoute,
    private destroyRef: DestroyRef,
  ) {}

  // =========================
  // ОСНОВНОЕ
  // =========================

  ngOnInit(): void {
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const url = params.get('url')?.trim() || '';
      const autoload = params.get('autoload') === '1';

      if (!url) {
        return;
      }

      this.state.url = url;

      if (!autoload || this.lastAutoloadKey === url) {
        return;
      }

      this.lastAutoloadKey = url;
      this.extractArticle();
    });
  }

  extractArticle(): void {
    const value = this.state.url.trim();
    if (!value) return;

    this.articleError = '';
    this.state.error = '';
    this.originalTagsError = '';
    this.translationError = '';
    this.translatedTagsError = '';
    this.summaryError = '';
    this.fullPipelineMessage = '';
    this.fullPipelineError = '';
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

    scrollToElement(() => this.translationComponent?.translationSkeleton, this.cdr);

    this.api.translateToRussianStream(this.state.article.document_id).subscribe({
      next: (chunk) => {
        this.ngZone.run(() => {
          this.state.translatedText += chunk;
        });
      },
      error: () => {
        this.ngZone.run(() => {
          this.translationError = 'Ошибка при потоковом переводе статьи';
          this.loadingTranslation = false;
        });
      },
      complete: () => {
        this.ngZone.run(() => {
          this.loadingTranslation = false;
        });
      },
    });
  }

  async summarizeArticle(): Promise<void> {
    if (!this.state.article?.document_id || !this.state.translatedText.trim()) return;

    this.loadingSummary = true;
    this.summaryError = '';
    this.state.annotation = '';
    this.buffer = '';

    scrollToElement(() => this.annotationComponent?.annotationSkeleton, this.cdr);

    this.api.summarizeStream(this.state.article.document_id, 'translated').subscribe({
      next: (chunk) => {
        this.ngZone.run(() => {
          this.state.annotation += chunk;
        });
      },
      error: () => {
        this.ngZone.run(() => {
          this.summaryError = 'Ошибка при потоковом формировании аннотации';
          this.loadingSummary = false;
        });
      },
      complete: () => {
        this.ngZone.run(() => {
          this.loadingSummary = false;
        });
      },
    });
  }
  clear(): void {
    this.resetBlockEditors();
    this.state.clear();
    this.articleError = '';
    this.originalTagsError = '';
    this.translationError = '';
    this.translatedTagsError = '';
    this.summaryError = '';
    this.fullPipelineMessage = '';
    this.fullPipelineError = '';
  }

  enqueueFullLlmPipeline(): void {
    const documentId = this.state.article?.document_id;
    if (!documentId) {
      return;
    }
    this.loadingFullPipeline = true;
    this.fullPipelineError = '';
    this.fullPipelineMessage = '';
    this.documentsApi
      .enqueueFullLlmPipeline({ document_ids: [documentId], target_lang: 'ru', max_tags: 12 })
      .subscribe({
        next: (r) => {
          this.loadingFullPipeline = false;
          this.fullPipelineMessage =
            r.enqueued > 0
              ? `В очередь поставлено ${r.enqueued} из ${r.scanned} (фаза A). После перевода запустится фаза B. Correlation: ${r.pipeline_correlation_id.slice(0, 8)}…`
              : `Ничего не поставлено: ${r.scanned} в выборке или уже есть активные джобы.`;
          this.cdr.markForCheck();
        },
        error: (err: unknown) => {
          this.loadingFullPipeline = false;
          const detail =
            err instanceof HttpErrorResponse && typeof err.error?.detail === 'string'
              ? err.error.detail
              : null;
          this.fullPipelineError = detail ?? 'Ошибка постановки полного пайплайна в очередь';
          this.cdr.markForCheck();
        },
      });
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
  // РЕДАКТИРОВАНИЕ (блоки в дочерних компонентах)
  // =========================

  private resetBlockEditors(): void {
    this.originalTextComponent?.resetEdit();
    this.translationComponent?.resetTranslationEdit();
    this.annotationComponent?.resetAnnotationEdit();
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

  get isLoading(): boolean {
    return (
      this.loadingArticle ||
      this.loadingEntitiesSection ||
      this.loadingCategories ||
      this.loadingTranslation ||
      this.loadingSummary ||
      this.loadingOriginalTags ||
      this.loadingTranslatedTags ||
      this.loadingFullPipeline
    );
  }

  get isDisabled(): boolean {
    return this.isLoading;
  }
}
