import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ActivatedRoute, Router } from '@angular/router';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { SelectModule } from 'primeng/select';
import { ArticleParser } from '../article-parser/article-parser';
import { DocumentsApi, DocumentTypeCatalogItem } from '../documents/documents-api';
import { PrimaryButtonComponent } from '../../shared/ui/primary-button/primary-button.component';

export type DocumentCreationMode = 'material' | 'url' | 'template';
export type CreateBodyTextMode = 'plain' | 'markdown';

@Component({
  selector: 'app-document-page',
  standalone: true,
  imports: [CommonModule, FormsModule, ArticleParser, SelectModule, PrimaryButtonComponent],
  templateUrl: './document-page.html',
  styleUrl: './document-page.scss',
})
export class DocumentPage implements OnInit {
  creationMode: DocumentCreationMode = 'material';

  documentTypesCatalog: DocumentTypeCatalogItem[] = [];
  documentTypesLoadError = '';
  formTitle = '';
  formAuthor = '';
  /** Формат YYYY-MM-DD для input type="date". */
  formPublicationDate = '';
  /** Необязательная ссылка на источник (documents.source_url). */
  formSourceUrl = '';
  /** URL главного изображения (documents.extracted_main_image). */
  formMainImageUrl = '';
  rawText = '';
  /** Режим поля тела: обычный текст или Markdown с предпросмотром. */
  bodyTextMode: CreateBodyTextMode = 'plain';
  formDocumentTypeCode = '';
  createSubmitting = false;
  createError = '';

  constructor(
    private readonly route: ActivatedRoute,
    private readonly router: Router,
    private readonly destroyRef: DestroyRef,
    private readonly documentsApi: DocumentsApi,
    private readonly sanitizer: DomSanitizer,
  ) {}

  get createDocumentTypeSelectOptions(): { label: string; value: string }[] {
    return this.documentTypesCatalog.map((dt) => ({
      value: dt.code,
      label: `${dt.name} (${dt.code})`,
    }));
  }

  ngOnInit(): void {
    marked.setOptions({ gfm: true, breaks: true });
    this.loadDocumentTypesCatalog();

    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((q) => {
      const id = q.get('id')?.trim() ?? '';
      const mode = q.get('mode')?.trim().toLowerCase() ?? '';
      const urlParam = q.get('url')?.trim() ?? '';

      if (mode === 'template') {
        this.creationMode = 'template';
        return;
      }
      if (mode === 'url' || urlParam) {
        this.creationMode = 'url';
        return;
      }
      if (mode === 'material' || id) {
        this.creationMode = 'material';
        return;
      }
      this.creationMode = 'material';
    });
  }

  loadDocumentTypesCatalog(): void {
    this.documentTypesLoadError = '';
    this.documentsApi.getDocumentTypesCatalog().subscribe({
      next: (items) => {
        this.documentTypesCatalog = items;
        this.ensureDocumentTypeSelection();
      },
      error: () => {
        this.documentTypesLoadError = 'Не удалось загрузить типы документов';
      },
    });
  }

  setBodyTextMode(mode: CreateBodyTextMode): void {
    this.bodyTextMode = mode;
  }

  markdownPreviewHtml(): SafeHtml {
    const src = this.rawText?.trim() ?? '';
    if (!src) {
      return this.sanitizer.bypassSecurityTrustHtml(
        '<p class="document-page__md-preview-empty">Нет текста для предпросмотра</p>',
      );
    }
    try {
      const rawHtml = marked.parse(src, { async: false }) as string;
      const clean = DOMPurify.sanitize(rawHtml);
      return this.sanitizer.bypassSecurityTrustHtml(clean);
    } catch {
      return this.sanitizer.bypassSecurityTrustHtml(
        '<p class="document-page__md-preview-empty">Не удалось разобрать Markdown</p>',
      );
    }
  }

  private ensureDocumentTypeSelection(): void {
    if (!this.documentTypesCatalog.length) {
      this.formDocumentTypeCode = '';
      return;
    }
    const current = this.formDocumentTypeCode.trim().toLowerCase();
    const ok = this.documentTypesCatalog.some((t) => t.code.toLowerCase() === current);
    if (!ok) {
      this.formDocumentTypeCode = this.documentTypesCatalog[0].code;
    }
  }

  setMode(mode: DocumentCreationMode): void {
    const currentId = this.route.snapshot.queryParamMap.get('id')?.trim() ?? '';

    if (mode === 'template') {
      void this.router.navigate([], {
        relativeTo: this.route,
        queryParams: { id: null, url: null, autoload: null, from: null, mode: 'template' },
        queryParamsHandling: 'merge',
        replaceUrl: true,
      });
      return;
    }

    if (mode === 'url') {
      void this.router.navigate([], {
        relativeTo: this.route,
        queryParams: { id: null, url: null, autoload: null, from: null, mode: 'url' },
        queryParamsHandling: 'merge',
        replaceUrl: true,
      });
      return;
    }

    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {
        mode: 'material',
        url: null,
        autoload: null,
        from: null,
        ...(currentId ? { id: currentId } : { id: null }),
      },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  submitCreateFromRaw(): void {
    const title = this.formTitle.trim();
    if (!title) {
      this.createError = 'Введите заголовок документа';
      return;
    }
    const author = this.formAuthor.trim();
    if (!author) {
      this.createError = 'Укажите автора';
      return;
    }
    const pub = this.formPublicationDate.trim();
    if (!pub) {
      this.createError = 'Укажите дату публикации';
      return;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(pub)) {
      this.createError = 'Дата публикации должна быть в формате ГГГГ-ММ-ДД';
      return;
    }
    const text = this.rawText.trim();
    if (!text) {
      this.createError = 'Введите текст документа';
      return;
    }
    if (!this.documentTypesCatalog.length) {
      this.createError = 'Дождитесь загрузки типов документов или обновите страницу';
      return;
    }
    const docTypeLower = this.formDocumentTypeCode.trim().toLowerCase();
    const docTypeOk = this.documentTypesCatalog.some((t) => t.code.toLowerCase() === docTypeLower);
    if (!docTypeOk) {
      this.createError = 'Выберите тип документа из списка';
      return;
    }

    this.createError = '';
    this.createSubmitting = true;

    this.documentsApi
      .createDocumentFromRaw({
        title,
        author,
        publication_date: pub,
        text: this.rawText,
        document_type_code: docTypeLower,
        ...(this.formSourceUrl.trim() ? { source_url: this.formSourceUrl.trim() } : {}),
        ...(this.formMainImageUrl.trim() ? { main_image: this.formMainImageUrl.trim() } : {}),
      })
      .subscribe({
        next: (res) => {
          const id = res.document_id?.trim();
          if (!id) {
            this.createError = 'Сервер не вернул идентификатор документа';
            this.createSubmitting = false;
            return;
          }
          this.createSubmitting = false;
          void this.router.navigate(['/document'], {
            queryParams: { id, mode: 'material' },
            replaceUrl: true,
          });
        },
        error: (err: HttpErrorResponse) => {
          const detail = err.error?.detail;
          this.createError =
            typeof detail === 'string' ? detail : 'Не удалось создать документ';
          this.createSubmitting = false;
        },
      });
  }
}
