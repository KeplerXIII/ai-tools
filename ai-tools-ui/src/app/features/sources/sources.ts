import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DocumentTypeCatalogItem, DocumentsApi } from '../documents/documents-api';
import {
  CountryCatalogItem,
  LanguageCatalogItem,
  SourceCreateRequestBody,
  SourceListItem,
  SourcesApi,
} from './sources-api';

type SortMode = 'created_desc' | 'created_asc' | 'user_asc';

@Component({
  selector: 'app-sources',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './sources.html',
  styleUrl: './sources.scss',
})
export class Sources implements OnInit {
  items: SourceListItem[] = [];
  canFilterByAllUsers = false;
  listLoading = false;
  listError = '';

  formUrl = '';
  formName = '';
  formLanguageCode = 'en';
  formCountryCode = '';
  formRssUrl = '';
  formDocumentTypeCode = 'news';
  languagesCatalog: LanguageCatalogItem[] = [];
  languagesLoadError = '';
  countriesCatalog: CountryCatalogItem[] = [];
  countriesLoadError = '';
  documentTypesCatalog: DocumentTypeCatalogItem[] = [];
  documentTypesLoadError = '';
  createSubmitting = false;
  createError = '';
  createSuccess = '';
  /** Панель «Новый источник» по умолчанию свёрнута, чтобы не занимать место. */
  createSectionOpen = false;

  selectedUserId = '';
  sortMode: SortMode = 'created_desc';
  expandedSourceId: string | null = null;

  parseDays = 3;
  /** Соответствует skip_undated в API: после извлечения не сохранять материалы без итоговой даты. */
  parseSkipUndated = true;
  parsingSourceId: string | null = null;
  lastParsedSourceId: string | null = null;
  parseFeedback = '';
  parseError = '';

  constructor(
    private readonly sourcesApi: SourcesApi,
    private readonly documentsApi: DocumentsApi,
  ) {}

  toggleCreateSection(): void {
    this.createSectionOpen = !this.createSectionOpen;
  }

  ngOnInit(): void {
    this.loadLanguagesCatalog();
    this.loadCountriesCatalog();
    this.loadDocumentTypesCatalog();
    this.loadSources();
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

  private ensureDocumentTypeSelection(): void {
    if (!this.documentTypesCatalog.length) {
      return;
    }
    const lower = this.formDocumentTypeCode.trim().toLowerCase();
    const match = this.documentTypesCatalog.find((t) => t.code.toLowerCase() === lower);
    if (match) {
      this.formDocumentTypeCode = match.code;
      return;
    }
    const news = this.documentTypesCatalog.find((t) => t.code.toLowerCase() === 'news');
    this.formDocumentTypeCode = news ? news.code : this.documentTypesCatalog[0].code;
  }

  loadLanguagesCatalog(): void {
    this.languagesLoadError = '';
    this.sourcesApi.getLanguagesCatalog().subscribe({
      next: (items) => {
        this.languagesCatalog = items;
        this.ensureLanguageSelection();
      },
      error: () => {
        this.languagesLoadError = 'Не удалось загрузить список языков';
      },
    });
  }

  loadCountriesCatalog(): void {
    this.countriesLoadError = '';
    this.sourcesApi.getCountriesCatalog().subscribe({
      next: (items) => {
        this.countriesCatalog = items;
        this.ensureCountrySelection();
      },
      error: () => {
        this.countriesLoadError = 'Не удалось загрузить список стран';
      },
    });
  }

  private ensureCountrySelection(): void {
    if (!this.formCountryCode.trim()) {
      return;
    }
    const upper = this.formCountryCode.trim().toUpperCase();
    const match = this.countriesCatalog.find((c) => c.code.toUpperCase() === upper);
    if (match) {
      this.formCountryCode = match.code;
      return;
    }
    this.formCountryCode = '';
  }

  private ensureLanguageSelection(): void {
    if (!this.languagesCatalog.length) {
      return;
    }
    const lower = this.formLanguageCode.trim().toLowerCase();
    const match = this.languagesCatalog.find((l) => l.code.toLowerCase() === lower);
    if (match) {
      this.formLanguageCode = match.code;
      return;
    }
    const en = this.languagesCatalog.find((l) => l.code.toLowerCase() === 'en');
    this.formLanguageCode = en ? en.code : this.languagesCatalog[0].code;
  }

  loadSources(): void {
    this.listLoading = true;
    this.listError = '';
    this.sourcesApi.listSources().subscribe({
      next: (response) => {
        this.items = response.items;
        this.canFilterByAllUsers = response.can_filter_by_all_users;
        this.listLoading = false;
      },
      error: () => {
        this.listError = 'Не удалось загрузить список источников';
        this.listLoading = false;
      },
    });
  }

  submitCreate(): void {
    const url = this.formUrl.trim();
    if (!url) {
      this.createError = 'Укажите URL сайта источника';
      return;
    }

    this.createError = '';
    this.createSuccess = '';
    this.createSubmitting = true;

    if (!this.languagesCatalog.length) {
      this.createError = 'Дождитесь загрузки списка языков или обновите страницу';
      this.createSubmitting = false;
      return;
    }

    const languageCode = this.formLanguageCode.trim().toLowerCase();
    const langOk = this.languagesCatalog.some((l) => l.code.toLowerCase() === languageCode);
    if (!langOk) {
      this.createError = 'Выберите язык из списка';
      this.createSubmitting = false;
      return;
    }

    if (!this.documentTypesCatalog.length) {
      this.createError = 'Дождитесь загрузки типов документов или обновите страницу';
      this.createSubmitting = false;
      return;
    }
    const docTypeLower = this.formDocumentTypeCode.trim().toLowerCase();
    const docTypeOk = this.documentTypesCatalog.some((t) => t.code.toLowerCase() === docTypeLower);
    if (!docTypeOk) {
      this.createError = 'Выберите тип документа из списка';
      this.createSubmitting = false;
      return;
    }

    const body: SourceCreateRequestBody = {
      url,
      language_code: languageCode,
      document_type_code: docTypeLower,
    };
    const name = this.formName.trim();
    if (name) {
      body.name = name.slice(0, 255);
    }
    const countryRaw = this.formCountryCode.trim();
    if (countryRaw) {
      if (!this.countriesCatalog.length) {
        this.createError = 'Дождитесь загрузки списка стран или сбросьте выбор страны';
        this.createSubmitting = false;
        return;
      }
      const countryUpper = countryRaw.toUpperCase();
      const countryOk = this.countriesCatalog.some((c) => c.code.toUpperCase() === countryUpper);
      if (!countryOk) {
        this.createError = 'Выберите страну из списка';
        this.createSubmitting = false;
        return;
      }
      body.country_code = countryUpper.slice(0, 8);
    }
    const rss = this.formRssUrl.trim();
    if (rss) {
      body.rss_url = rss;
    }

    this.sourcesApi.createSource(body).subscribe({
      next: () => {
        this.createSubmitting = false;
        this.createSuccess = 'Источник добавлен';
        this.resetCreateForm(false);
        this.loadSources();
      },
      error: (err: HttpErrorResponse) => {
        this.createSubmitting = false;
        this.createError = this.formatApiError(err);
      },
    });
  }

  resetCreateForm(clearMessages = true): void {
    this.formUrl = '';
    this.formName = '';
    this.formLanguageCode = 'en';
    this.formCountryCode = '';
    this.formRssUrl = '';
    this.formDocumentTypeCode = 'news';
    this.ensureLanguageSelection();
    this.ensureCountrySelection();
    this.ensureDocumentTypeSelection();
    if (clearMessages) {
      this.createError = '';
      this.createSuccess = '';
    }
  }

  private formatApiError(err: HttpErrorResponse): string {
    const detail = err.error?.detail;
    if (typeof detail === 'string') {
      return detail;
    }
    if (Array.isArray(detail)) {
      return detail
        .map((row: { msg?: string; loc?: string[] }) => row.msg || '')
        .filter(Boolean)
        .join('; ');
    }
    if (err.status === 409) {
      return 'Источник с таким URL уже существует для вашего пользователя';
    }
    return 'Не удалось создать источник';
  }

  runParse(src: SourceListItem): void {
    if (!src.is_active) {
      return;
    }
    this.parseError = '';
    this.parseFeedback = '';
    this.lastParsedSourceId = null;
    const days = Math.min(30, Math.max(1, Math.floor(Number(this.parseDays)) || 3));
    this.parseDays = days;
    this.parsingSourceId = src.source_id;
    this.sourcesApi
      .parseSource({
        source_id: src.source_id,
        days,
        skip_undated: this.parseSkipUndated,
      })
      .subscribe({
        next: (res) => {
          this.parsingSourceId = null;
          this.lastParsedSourceId = src.source_id;
          this.parseError = '';
          this.parseFeedback = `Обработано ссылок: ${res.found_total}, создано документов: ${res.created_total}`;
          this.loadSources();
        },
        error: (err: HttpErrorResponse) => {
          this.parsingSourceId = null;
          this.lastParsedSourceId = src.source_id;
          this.parseError = this.formatParseError(err);
        },
      });
  }

  private formatParseError(err: HttpErrorResponse): string {
    const detail = err.error?.detail;
    if (typeof detail === 'string') {
      return detail;
    }
    return 'Не удалось запустить разбор источника';
  }

  get contributorOptions(): { userId: string; label: string }[] {
    const map = new Map<string, string>();
    for (const item of this.items) {
      if (!map.has(item.added_by_user_id)) {
        map.set(item.added_by_user_id, item.added_by_username);
      }
    }
    return [...map.entries()]
      .map(([userId, label]) => ({ userId, label }))
      .sort((a, b) => a.label.localeCompare(b.label, 'ru'));
  }

  get filteredAndSortedItems(): SourceListItem[] {
    let list = this.items;
    if (this.selectedUserId) {
      list = list.filter((s) => s.added_by_user_id === this.selectedUserId);
    }
    const out = [...list];
    if (this.sortMode === 'created_desc') {
      out.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
    } else if (this.sortMode === 'created_asc') {
      out.sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
    } else {
      out.sort((a, b) =>
        a.added_by_username.localeCompare(b.added_by_username, 'ru') ||
        Date.parse(b.created_at) - Date.parse(a.created_at),
      );
    }
    return out;
  }

  onFiltersChanged(): void {
    /* сортировка и фильтр вычисляются в геттере */
  }

  resetFilters(): void {
    this.selectedUserId = '';
    this.sortMode = 'created_desc';
  }

  toggleExpand(sourceId: string): void {
    this.expandedSourceId = this.expandedSourceId === sourceId ? null : sourceId;
  }

  isExpanded(sourceId: string): boolean {
    return this.expandedSourceId === sourceId;
  }

  displayTitle(item: SourceListItem): string {
    const name = item.name?.trim();
    if (name) {
      return name;
    }
    try {
      return new URL(item.url).hostname;
    } catch {
      return item.url;
    }
  }

  formatDate(iso: string): string {
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
}
