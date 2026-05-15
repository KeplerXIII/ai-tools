import { HttpErrorResponse } from '@angular/common/http';
import { DestroyRef, Injectable } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { BehaviorSubject, Observable, Subject, Subscription } from 'rxjs';
import { finalize, switchMap, tap } from 'rxjs/operators';
import {
  ParseSourceRunResponse,
  ParseSourceRunSnapshotPayload,
  SourceListItem,
  SourcesApi,
} from '../api/sources-api';
import { clampBoundedInteger } from '../ui/sources-list-accordion/bounded-integer-input.util';
import {
  buildPostParsePayload,
  SourceParseFormState,
} from '../ui/sources-list-accordion/source-parse-form.model';

export interface SourceParseRunViewState {
  parsingSourceId: string | null;
  lastParsedSourceId: string | null;
  parseFeedback: string;
  parseError: string;
}

const initialViewState: SourceParseRunViewState = {
  parsingSourceId: null,
  lastParsedSourceId: null,
  parseFeedback: '',
  parseError: '',
};

@Injectable()
export class SourceParseRunService {
  private readonly storageParseUiKey = 'ai-tools.sources.lastParseUi';

  private readonly viewStateSubject = new BehaviorSubject<SourceParseRunViewState>(initialViewState);
  readonly viewState$: Observable<SourceParseRunViewState> = this.viewStateSubject.asObservable();

  private readonly sourcesReloadSubject = new Subject<{ silent?: boolean }>();
  /** Запрос на обновление списка источников после завершения разбора. */
  readonly sourcesReloadRequested$: Observable<{ silent?: boolean }> =
    this.sourcesReloadSubject.asObservable();

  private parseStreamSub: Subscription | null = null;
  private reconcileSub: Subscription | null = null;
  private attachedParseRunId: string | null = null;

  constructor(
    private readonly sourcesApi: SourcesApi,
    private readonly destroyRef: DestroyRef,
  ) {}

  get viewState(): SourceParseRunViewState {
    return this.viewStateSubject.value;
  }

  restoreParseUiFromStorage(knownSourceIds: string[]): void {
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
      if (!knownSourceIds.includes(o.sourceId)) {
        return;
      }
      this.patchViewState({
        lastParsedSourceId: o.sourceId,
        parseFeedback: o.feedback ?? '',
        parseError: o.error ?? '',
      });
    } catch {
      sessionStorage.removeItem(this.storageParseUiKey);
    }
  }

  reconcileActiveRuns(allItems: SourceListItem[], expandedSourceId: string | undefined): void {
    const knownIds = allItems.map((s) => s.source_id);
    this.reconcileSub?.unsubscribe();
    this.reconcileSub = this.sourcesApi
      .listActiveSourceParseRuns()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          const visible = resp.items.filter((row) => knownIds.includes(row.source_id));
          if (!visible.length) {
            return;
          }
          const pick =
            (expandedSourceId
              ? visible.find((i) => i.source_id === expandedSourceId)
              : undefined) ?? visible[0];
          this.attachParseRunStreamIfNeeded(pick.source_id, pick.parse_run);
        },
        error: () => {
          /* не блокируем список источников */
        },
      });
  }

  runParse(src: SourceListItem, form: SourceParseFormState): void {
    if (!src.is_active) {
      return;
    }
    this.detachParseStream();
    this.patchViewState({
      parseError: '',
      parseFeedback: '',
      lastParsedSourceId: null,
    });
    sessionStorage.removeItem(this.storageParseUiKey);

    form.parseDays = clampBoundedInteger(form.parseDays, 1, 30, 3);
    form.parsePostMaxTags = clampBoundedInteger(form.parsePostMaxTags, 1, 12, 12);

    this.patchViewState({ parsingSourceId: src.source_id });
    this.parseStreamSub = this.sourcesApi
      .parseSource({
        source_id: src.source_id,
        days: form.parseDays,
        skip_undated: form.parseSkipUndated,
        post_parse: buildPostParsePayload(form),
      })
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        tap((enq) => {
          this.attachedParseRunId = enq.parse_run_id;
        }),
        switchMap((enq) =>
          this.sourcesApi.streamParseRun(enq.parse_run_id).pipe(
            takeUntilDestroyed(this.destroyRef),
            finalize(() => this.onParseStreamFinalize(src.source_id)),
          ),
        ),
        finalize(() => {
          this.patchViewState({ parsingSourceId: null });
        }),
      )
      .subscribe({
        next: (snap) => this.handleParseStreamSnapshot(src.source_id, snap),
        error: (err: unknown) => {
          this.attachedParseRunId = null;
          this.onParseStreamError(err);
        },
      });
  }

  private attachParseRunStreamIfNeeded(sourceId: string, initial: ParseSourceRunResponse): void {
    const parseRunId = String(initial.parse_run_id);
    if (
      this.attachedParseRunId === parseRunId &&
      this.parseStreamSub !== null &&
      !this.parseStreamSub.closed
    ) {
      return;
    }
    this.detachParseStream();

    if (initial.status === 'completed' || initial.status === 'failed') {
      this.applySnapToParseUi(sourceId, initial);
      this.persistParseUiSnapshot(sourceId, initial.status);
      this.patchViewState({ parsingSourceId: null });
      this.attachedParseRunId = null;
      this.requestSourcesReload({ silent: true });
      return;
    }

    this.applySnapToParseUi(sourceId, initial);
    this.patchViewState({ parsingSourceId: sourceId });
    this.attachedParseRunId = parseRunId;

    this.parseStreamSub = this.sourcesApi
      .streamParseRun(parseRunId)
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => {
          this.attachedParseRunId = null;
          this.onParseStreamFinalize(sourceId);
        }),
      )
      .subscribe({
        next: (snap) => this.handleParseStreamSnapshot(sourceId, snap),
        error: (err) => {
          this.attachedParseRunId = null;
          this.onParseStreamError(err);
        },
      });
  }

  private detachParseStream(): void {
    this.parseStreamSub?.unsubscribe();
    this.parseStreamSub = null;
    this.attachedParseRunId = null;
  }

  private handleParseStreamSnapshot(sourceId: string, snap: ParseSourceRunSnapshotPayload): void {
    this.applySnapToParseUi(sourceId, snap);
    if (snap.status === 'completed' || snap.status === 'failed') {
      this.attachedParseRunId = null;
      this.persistParseUiSnapshot(sourceId, snap.status);
    }
  }

  private onParseStreamFinalize(sourceId: string): void {
    this.patchViewState({
      parsingSourceId: null,
      lastParsedSourceId: sourceId,
    });
    this.requestSourcesReload({ silent: true });
  }

  private onParseStreamError(err: unknown): void {
    this.patchViewState({
      parseError:
        err instanceof HttpErrorResponse ? this.formatParseError(err) : 'Поток разбора прерван',
      parseFeedback: '',
    });
  }

  private applySnapToParseUi(
    sourceId: string,
    snap: ParseSourceRunResponse | ParseSourceRunSnapshotPayload,
  ): void {
    const parseError =
      snap.status === 'failed'
        ? snap.error_message || 'Разбор завершился с ошибкой'
        : '';
    this.patchViewState({
      lastParsedSourceId: sourceId,
      parseFeedback: this.formatParseProgress(snap),
      parseError,
    });
  }

  private persistParseUiSnapshot(sourceId: string, status: string): void {
    if (status !== 'completed' && status !== 'failed') {
      return;
    }
    const { parseFeedback, parseError } = this.viewState;
    sessionStorage.setItem(
      this.storageParseUiKey,
      JSON.stringify({
        sourceId,
        feedback: parseFeedback,
        error: parseError,
        status,
      }),
    );
  }

  private requestSourcesReload(options?: { silent?: boolean }): void {
    this.sourcesReloadSubject.next(options ?? {});
  }

  private patchViewState(patch: Partial<SourceParseRunViewState>): void {
    this.viewStateSubject.next({ ...this.viewStateSubject.value, ...patch });
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

  private formatParseError(err: HttpErrorResponse): string {
    const detail = err.error?.detail;
    if (typeof detail === 'string') {
      return detail;
    }
    return 'Не удалось запустить разбор источника';
  }
}
