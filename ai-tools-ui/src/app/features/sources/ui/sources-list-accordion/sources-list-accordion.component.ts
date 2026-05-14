import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectorRef,
  Component,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  Output,
  SimpleChanges,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AccordionModule } from 'primeng/accordion';
import { ChipModule } from 'primeng/chip';
import { KnobModule } from 'primeng/knob';
import { TooltipModule } from 'primeng/tooltip';
import { finalize, switchMap, tap } from 'rxjs/operators';
import { Subscription } from 'rxjs';
import {
  ParseSourceRunResponse,
  ParseSourceRunSnapshotPayload,
  PostParseProcessingOptions,
  SourceListItem,
  SourcesApi,
} from '../../api/sources-api';

@Component({
  selector: 'app-sources-list-accordion',
  standalone: true,
  imports: [CommonModule, FormsModule, AccordionModule, ChipModule, KnobModule, TooltipModule],
  templateUrl: './sources-list-accordion.component.html',
  styleUrl: './sources-list-accordion.component.scss',
})
export class SourcesListAccordionComponent implements OnChanges, OnDestroy {
  /** Цвет дуги для p-knob без числового значения (центр «—»). */
  readonly sourceStatsKnobNullStroke = '#94a3b8';

  @Input({ required: true }) displayItems: SourceListItem[] = [];
  @Input({ required: true }) allItems: SourceListItem[] = [];
  @Output() readonly reloadSources = new EventEmitter<{ silent?: boolean }>();

  expandedSourceId: string | undefined = undefined;

  parseDays = 3;
  /** Соответствует skip_undated в API: после извлечения не сохранять материалы без итоговой даты. */
  parseSkipUndated = true;

  parsePostFullPipeline = false;
  parsePostLlmTagOriginal = false;
  parsePostLlmTranslate = false;
  parsePostLlmExtractor = false;
  parsePostLlmTagTranslated = false;
  parsePostLlmAnnotate = false;
  parsePostLlmCategorize = false;
  parsePostTargetLang = 'ru';
  parsePostMaxTags = 12;

  parsingSourceId: string | null = null;
  lastParsedSourceId: string | null = null;
  parseFeedback = '';
  parseError = '';
  private parseStreamSub: Subscription | null = null;
  private attachedParseRunId: string | null = null;

  private readonly storageExpandedKey = 'ai-tools.sources.expandedSourceId';
  private readonly storageParseUiKey = 'ai-tools.sources.lastParseUi';

  constructor(
    private readonly sourcesApi: SourcesApi,
    private readonly cdr: ChangeDetectorRef,
  ) {}

  ngOnChanges(changes: SimpleChanges): void {
    const allCh = changes['allItems'];
    if (!allCh || !this.allItems.length) {
      return;
    }
    this.applyExpandedFromStorage();
    this.applyParseUiFromStorage();
    this.reconcileActiveParseStreamsAfterListLoad();
  }

  ngOnDestroy(): void {
    this.parseStreamSub?.unsubscribe();
    this.parseStreamSub = null;
    this.attachedParseRunId = null;
  }

  private applyExpandedFromStorage(): void {
    const stored = sessionStorage.getItem(this.storageExpandedKey);
    if (!stored) {
      return;
    }
    if (this.allItems.some((i) => i.source_id === stored)) {
      this.expandedSourceId = stored;
    } else {
      sessionStorage.removeItem(this.storageExpandedKey);
      this.expandedSourceId = undefined;
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
      if (!this.allItems.some((i) => i.source_id === o.sourceId)) {
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

  parsePostHasAnyGranular(): boolean {
    return (
      this.parsePostLlmTagOriginal ||
      this.parsePostLlmTranslate ||
      this.parsePostLlmExtractor ||
      this.parsePostLlmTagTranslated ||
      this.parsePostLlmAnnotate ||
      this.parsePostLlmCategorize
    );
  }

  parsePostShowLangAndMaxTags(): boolean {
    return this.parsePostFullPipeline || this.parsePostHasAnyGranular();
  }

  parsePostDependsOnTranslateDisabled(srcActive: boolean, parsing: boolean): boolean {
    return !srcActive || parsing || this.parsePostFullPipeline || !this.parsePostLlmTranslate;
  }

  parsePostOnTranslateToggled(enabled: boolean): void {
    if (!enabled) {
      this.parsePostLlmTagTranslated = false;
      this.parsePostLlmAnnotate = false;
    }
  }

  private buildPostParsePayload(): PostParseProcessingOptions | undefined {
    const target_lang = (this.parsePostTargetLang || 'ru').trim().slice(0, 8) || 'ru';
    const max_tags = Math.min(100, Math.max(1, Math.floor(Number(this.parsePostMaxTags)) || 12));
    if (this.parsePostFullPipeline) {
      return { full_llm_pipeline: true, target_lang, max_tags };
    }
    if (!this.parsePostHasAnyGranular()) {
      return undefined;
    }
    return {
      full_llm_pipeline: false,
      llm_tag_original: this.parsePostLlmTagOriginal || undefined,
      llm_translate: this.parsePostLlmTranslate || undefined,
      llm_extractor: this.parsePostLlmExtractor || undefined,
      llm_tag_translated: this.parsePostLlmTagTranslated || undefined,
      llm_annotate: this.parsePostLlmAnnotate || undefined,
      llm_categorize: this.parsePostLlmCategorize || undefined,
      target_lang,
      max_tags,
    };
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

  private applySnapToParseUi(
    sourceId: string,
    snap: ParseSourceRunResponse | ParseSourceRunSnapshotPayload,
  ): void {
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
    this.reloadSources.emit({ silent: true });
    this.cdr.markForCheck();
  }

  private onParseStreamError(err: unknown): void {
    this.parseError =
      err instanceof HttpErrorResponse ? this.formatParseError(err) : 'Поток разбора прерван';
    this.parseFeedback = '';
  }

  private reconcileActiveParseStreamsAfterListLoad(): void {
    this.sourcesApi.listActiveSourceParseRuns().subscribe({
      next: (resp) => {
        const visible = resp.items.filter((row) =>
          this.allItems.some((s) => s.source_id === row.source_id),
        );
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
      this.reloadSources.emit({ silent: true });
      this.cdr.markForCheck();
      return;
    }

    this.applySnapToParseUi(sourceId, initial);
    this.parsingSourceId = sourceId;
    this.attachedParseRunId = parseRunId;

    this.parseStreamSub = this.sourcesApi
      .streamParseRun(parseRunId)
      .pipe(
        finalize(() => {
          this.attachedParseRunId = null;
          this.onParseStreamFinalize(sourceId);
        }),
      )
      .subscribe({
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
        post_parse: this.buildPostParsePayload(),
      })
      .pipe(
        tap((enq) => {
          this.attachedParseRunId = enq.parse_run_id;
        }),
        switchMap((enq) =>
          this.sourcesApi
            .streamParseRun(enq.parse_run_id)
            .pipe(finalize(() => this.onParseStreamFinalize(src.source_id))),
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

  onSourcesListAccordionValueChange(value: unknown): void {
    const raw = Array.isArray(value) ? value[0] : value;
    const v =
      raw === null || raw === undefined || raw === ''
        ? undefined
        : typeof raw === 'string'
          ? raw
          : String(raw);
    if (v) {
      sessionStorage.setItem(this.storageExpandedKey, v);
    } else {
      sessionStorage.removeItem(this.storageExpandedKey);
    }
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

  /**
   * Общий max для трёх счётчиков в блоке статистики источника — дуги наглядно сопоставимы.
   */
  sourceStatsKnobMax(src: SourceListItem): number {
    const total = this.sourceStatsCoalesceCount(src.documents_total);
    const unprocessed = this.sourceStatsCoalesceCount(src.documents_unprocessed);
    const last = this.sourceStatsCoalesceCount(src.last_parse_created_total);
    const peak = Math.max(total, unprocessed, last, 1);
    return Math.max(100, peak);
  }

  /** Есть число для статистики (null/undefined/NaN — нет). */
  hasSourceStatNumber(value: unknown): boolean {
    if (value === null || value === undefined) {
      return false;
    }
    const n = Number(value);
    return !Number.isNaN(n);
  }

  private sourceStatsCoalesceCount(value: unknown): number {
    if (value === null || value === undefined) {
      return 0;
    }
    const n = Number(value);
    if (Number.isNaN(n)) {
      return 0;
    }
    return Math.max(0, Math.floor(n));
  }

  /** Цвет дуги по доле value/max (как шкала уверенности в категориях). */
  sourceStatsKnobColor(value: number | null | undefined, max: number): string {
    const v = Math.max(0, Number(value) || 0);
    const m = Math.max(1, max);
    const pct = Math.round((v / m) * 100);
    if (pct <= 10) {
      return '#ef4444';
    }
    if (pct <= 30) {
      return '#f97316';
    }
    if (pct <= 50) {
      return '#eab308';
    }
    if (pct <= 80) {
      return '#AEEB9D';
    }
    return '#22c55e';
  }

  lastParseAtTooltip(src: SourceListItem): string {
    if (!src.last_parse_at) {
      return '';
    }
    return `Последний разбор: ${this.formatDate(src.last_parse_at)}`;
  }
}
