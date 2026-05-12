import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { finalize, switchMap, tap } from 'rxjs/operators';
import { Subscription } from 'rxjs';
import { DocumentTypeCatalogItem, DocumentsApi } from '../documents/documents-api';
import {
  CountryCatalogItem,
  LanguageCatalogItem,
  ParseSourceRunResponse,
  ParseSourceRunSnapshotPayload,
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
export class Sources implements OnInit, OnDestroy {
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
  private parseStreamSub: Subscription | null = null;
  /** Текущий открытый SSE по ``parse_run_id`` (чтобы не дублировать подписку после ``loadSources``). */
  private attachedParseRunId: string | null = null;

  /** Чтобы после возврата на страницу снова показывались блок статистики и итог разбора. */
  private readonly storageExpandedKey = 'ai-tools.sources.expandedSourceId';
  private readonly storageParseUiKey = 'ai-tools.sources.lastParseUi';

  constructor(
    private readonly sourcesApi: SourcesApi,
    private readonly documentsApi: DocumentsApi,
    private readonly cdr: ChangeDetectorRef,
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

  ngOnDestroy(): void {
    this.parseStreamSub?.unsubscribe();
    this.parseStreamSub = null;
    this.attachedParseRunId = null;
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

  loadSources(options?: { silent?: boolean }): void {
    const silent = options?.silent ?? false;
    if (!silent) {
      this.listLoading = true;
    }
    this.listError = '';
    this.sourcesApi.listSources().subscribe({
      next: (response) => {
        this.items = response.items;
        this.canFilterByAllUsers = response.can_filter_by_all_users;
        this.applyExpandedFromStorage();
        this.applyParseUiFromStorage();
        this.reconcileActiveParseStreamsAfterListLoad();
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

  private applyExpandedFromStorage(): void {
    const stored = sessionStorage.getItem(this.storageExpandedKey);
    if (!stored) {
      return;
    }
    if (this.items.some((i) => i.source_id === stored)) {
      this.expandedSourceId = stored;
    } else {
      sessionStorage.removeItem(this.storageExpandedKey);
    }
  }

  private applyParseUiFromStorage(): void {
    const raw = sessionStorage.getItem(this.storageParseUiKey);
    if (!raw) {
      return;
    }
    try {
      const o = JSON.parse(raw) as {
        sourceId: string;
        feedback: string;
        error: string;
        status: string;
      };
      if (o.status !== 'completed' && o.status !== 'failed') {
        return;
      }
      if (!this.items.some((i) => i.source_id === o.sourceId)) {
        return;
      }
      this.lastParsedSourceId = o.sourceId;
      this.parseFeedback = o.feedback ?? '';
      this.parseError = o.error ?? '';
    } catch {
      sessionStorage.removeItem(this.storageParseUiKey);
    }
  }

  private persistParseUiSnapshot(sourceId: string, status: string): void {
    if (status !== 'completed' && status !== 'failed') {
      return;
    }
    sessionStorage.setItem(
      this.storageParseUiKey,
      JSON.stringify({
        sourceId,
        feedback: this.parseFeedback,
        error: this.parseError,
        status,
      }),
    );
  }

  private formatParseProgress(
    snap: Pick<ParseSourceRunSnapshotPayload, 'status' | 'phase' | 'found_total' | 'created_total'>,
  ): string {
    if (snap.status === 'failed') {
      return 'Ошибка разбора';
    }
    if (snap.status === 'completed') {
      return `Готово: ссылок ${snap.found_total ?? 0}, новых документов ${snap.created_total ?? 0}`;
    }
    const ph = snap.phase || '';
    const found = snap.found_total;
    const phaseLabels: Record<string, string> = {
      queued: 'В очереди на воркер…',
      discovery: 'Поиск страниц и RSS…',
      extract:
        found != null
          ? `Загрузка и извлечение текста (найдено ссылок: ${found})…`
          : 'Загрузка и извлечение текста…',
      save: 'Сохранение документов в базу…',
      complete: 'Завершение…',
    };
    return phaseLabels[ph] || `Статус: ${snap.status}`;
  }

  private applySnapToParseUi(sourceId: string, snap: ParseSourceRunResponse | ParseSourceRunSnapshotPayload): void {
    this.lastParsedSourceId = sourceId;
    this.parseFeedback = this.formatParseProgress(snap);
    if (snap.status === 'failed') {
      this.parseError = snap.error_message || 'Разбор завершился с ошибкой';
    } else {
      this.parseError = '';
    }
  }

  private handleParseStreamSnapshot(sourceId: string, snap: ParseSourceRunSnapshotPayload): void {
    this.applySnapToParseUi(sourceId, snap);
    if (snap.status === 'completed' || snap.status === 'failed') {
      this.attachedParseRunId = null;
      this.persistParseUiSnapshot(sourceId, snap.status);
    }
  }

  private onParseStreamFinalize(sourceId: string): void {
    this.parsingSourceId = null;
    this.lastParsedSourceId = sourceId;
    this.loadSources({ silent: true });
    this.cdr.markForCheck();
  }

  private onParseStreamError(err: unknown): void {
    this.parseError =
      err instanceof HttpErrorResponse ? this.formatParseError(err) : 'Поток разбора прерван';
    this.parseFeedback = '';
  }

  /** После загрузки списка: подтянуть из БД незавершённые разборы и снова открыть SSE. */
  private reconcileActiveParseStreamsAfterListLoad(): void {
    this.sourcesApi.listActiveSourceParseRuns().subscribe({
      next: (resp) => {
        const visible = resp.items.filter((row) => this.items.some((s) => s.source_id === row.source_id));
        if (!visible.length) {
          return;
        }
        const expanded = this.expandedSourceId;
        const pick =
          (expanded ? visible.find((i) => i.source_id === expanded) : undefined) ?? visible[0];
        this.subscribeParseRunStreamIfNeeded(pick.source_id, pick.parse_run);
      },
      error: () => {
        /* не блокируем список источников */
      },
    });
  }

  /**
   * Подписка на SSE по данным с сервера (без sessionStorage).
   * Если снимок уже терминальный — только обновляем UI.
   */
  private subscribeParseRunStreamIfNeeded(sourceId: string, initial: ParseSourceRunResponse): void {
    const parseRunId = String(initial.parse_run_id);
    if (
      this.attachedParseRunId === parseRunId &&
      this.parseStreamSub !== null &&
      !this.parseStreamSub.closed
    ) {
      return;
    }
    this.parseStreamSub?.unsubscribe();
    this.parseStreamSub = null;

    if (initial.status === 'completed' || initial.status === 'failed') {
      this.applySnapToParseUi(sourceId, initial);
      this.persistParseUiSnapshot(sourceId, initial.status);
      this.parsingSourceId = null;
      this.lastParsedSourceId = sourceId;
      this.attachedParseRunId = null;
      this.loadSources({ silent: true });
      this.cdr.markForCheck();
      return;
    }

    this.applySnapToParseUi(sourceId, initial);
    this.parsingSourceId = sourceId;
    this.attachedParseRunId = parseRunId;

    this.parseStreamSub = this.sourcesApi.streamParseRun(parseRunId).pipe(
      finalize(() => {
        this.attachedParseRunId = null;
        this.onParseStreamFinalize(sourceId);
      }),
    ).subscribe({
      next: (snap) => {
        this.handleParseStreamSnapshot(sourceId, snap);
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.attachedParseRunId = null;
        this.onParseStreamError(err);
        this.cdr.markForCheck();
      },
    });
  }

  runParse(src: SourceListItem): void {
    if (!src.is_active) {
      return;
    }
    this.parseStreamSub?.unsubscribe();
    this.parseStreamSub = null;
    this.attachedParseRunId = null;
    this.parseError = '';
    this.parseFeedback = '';
    this.lastParsedSourceId = null;
    sessionStorage.removeItem(this.storageParseUiKey);
    const days = Math.min(30, Math.max(1, Math.floor(Number(this.parseDays)) || 3));
    this.parseDays = days;
    this.parsingSourceId = src.source_id;
    this.parseStreamSub = this.sourcesApi
      .parseSource({
        source_id: src.source_id,
        days,
        skip_undated: this.parseSkipUndated,
      })
      .pipe(
        tap((enq) => {
          this.attachedParseRunId = enq.parse_run_id;
        }),
        switchMap((enq) =>
          this.sourcesApi.streamParseRun(enq.parse_run_id).pipe(
            finalize(() => this.onParseStreamFinalize(src.source_id)),
          ),
        ),
        finalize(() => {
          this.parsingSourceId = null;
          this.cdr.markForCheck();
        }),
      )
      .subscribe({
        next: (snap) => {
          this.handleParseStreamSnapshot(src.source_id, snap);
          this.cdr.markForCheck();
        },
        error: (err: unknown) => {
          this.attachedParseRunId = null;
          this.onParseStreamError(err);
          this.cdr.markForCheck();
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
    if (this.expandedSourceId) {
      sessionStorage.setItem(this.storageExpandedKey, this.expandedSourceId);
    } else {
      sessionStorage.removeItem(this.storageExpandedKey);
    }
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
