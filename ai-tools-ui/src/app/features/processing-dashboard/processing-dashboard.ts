import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { firstValueFrom, Subscription, timer } from 'rxjs';

import { DocumentListItem } from '../documents/documents-api';

import { AnnotateBatchNotifierService } from '../../core/processing/annotate-batch-notifier.service';
import { CategorizeBatchNotifierService } from '../../core/processing/categorize-batch-notifier.service';
import { ExtractorBatchNotifierService } from '../../core/processing/extractor-batch-notifier.service';
import { TaggerBatchNotifierService } from '../../core/processing/tagger-batch-notifier.service';
import { TranslateBatchNotifierService } from '../../core/processing/translate-batch-notifier.service';
import { DocumentsApi } from '../documents/documents-api';
import {
  ProcessingCounters,
  ProcessingDashboardApi,
  ProcessingDashboardSnapshot,
  ProcessingJobRow,
} from './processing-dashboard-api';

type CounterKey = keyof ProcessingCounters;
type CounterFlashKind = 'up' | 'down' | 'same';
type JobFlashKind = 'new' | 'changed';
type JobFieldKey = keyof ProcessingJobRow;

const BULK_FEEDBACK_HIDE_MS = 6000;

@Component({
  selector: 'app-processing-dashboard',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './processing-dashboard.html',
  styleUrl: './processing-dashboard.scss',
})
export class ProcessingDashboard implements OnInit, OnDestroy {
  jobs: ProcessingJobRow[] = [];
  counters: ProcessingCounters | null = null;
  snapshotAt = '';
  loading = true;
  error = '';
  purgeLoading = false;
  purgeMessage = '';
  purgeError = '';

  bulkTranslateLoading = false;
  bulkTranslateMessage = '';
  bulkTranslateError = '';
  bulkAnnotateLoading = false;
  bulkAnnotateMessage = '';
  bulkAnnotateError = '';
  bulkCategorizeLoading = false;
  bulkCategorizeMessage = '';
  bulkCategorizeError = '';
  bulkExtractorLoading = false;
  bulkExtractorMessage = '';
  bulkExtractorError = '';
  bulkTagOriginalLoading = false;
  bulkTagOriginalMessage = '';
  bulkTagOriginalError = '';
  bulkTagTranslatedLoading = false;
  bulkTagTranslatedMessage = '';
  bulkTagTranslatedError = '';

  counterFlash: Partial<Record<CounterKey, CounterFlashKind>> = {};
  jobFlash: Record<string, JobFlashKind> = {};
  jobCellFlash: Record<string, true> = {};

  private streamSub: Subscription | null = null;
  private reconnectSub: Subscription | null = null;
  private flashTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private previousJobsById = new Map<string, string>();
  private previousJobFieldsById = new Map<string, ProcessingJobRow>();
  private pendingSnapshot: ProcessingDashboardSnapshot | null = null;
  private applySnapshotTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly bulkFeedbackTimers = new Map<string, ReturnType<typeof setTimeout>>();

  constructor(
    private readonly api: ProcessingDashboardApi,
    private readonly documentsApi: DocumentsApi,
    private readonly translateBatchNotifier: TranslateBatchNotifierService,
    private readonly annotateBatchNotifier: AnnotateBatchNotifierService,
    private readonly categorizeBatchNotifier: CategorizeBatchNotifierService,
    private readonly extractorBatchNotifier: ExtractorBatchNotifierService,
    private readonly taggerBatchNotifier: TaggerBatchNotifierService,
    private readonly cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    this.startStream();
  }

  ngOnDestroy(): void {
    this.streamSub?.unsubscribe();
    this.reconnectSub?.unsubscribe();
    if (this.applySnapshotTimer) {
      clearTimeout(this.applySnapshotTimer);
      this.applySnapshotTimer = null;
    }
    this.flashTimers.forEach((t) => clearTimeout(t));
    this.flashTimers.clear();
    this.bulkFeedbackTimers.forEach((t) => clearTimeout(t));
    this.bulkFeedbackTimers.clear();
  }

  trackJob(_: number, job: ProcessingJobRow): string {
    return job.id;
  }

  private startStream(): void {
    this.reconnectSub?.unsubscribe();
    this.streamSub?.unsubscribe();
    this.loading = true;

    this.streamSub = this.api.streamDashboard().subscribe({
      next: (snapshot) => {
        this.loading = false;
        this.error = '';
        this.queueSnapshot(snapshot);
        this.cdr.detectChanges();
      },
      error: () => {
        this.loading = false;
        this.error = 'Поток обновлений остановлен. Переподключаемся...';
        this.scheduleReconnect();
        this.cdr.detectChanges();
      },
      complete: () => {
        this.error = 'Поток обновлений завершен. Переподключаемся...';
        this.scheduleReconnect();
        this.cdr.detectChanges();
      },
    });
  }

  private scheduleReconnect(): void {
    if (this.reconnectSub) {
      return;
    }
    this.reconnectSub = timer(3000).subscribe(() => {
      this.reconnectSub = null;
      this.startStream();
      this.cdr.detectChanges();
    });
  }

  private applySnapshot(snapshot: ProcessingDashboardSnapshot): void {
    this.snapshotAt = snapshot.snapshot_at;
    this.applyCounterFlash(snapshot.counters);
    this.applyJobs(snapshot.jobs);
    this.counters = snapshot.counters;
    this.cdr.detectChanges();
  }

  private queueSnapshot(snapshot: ProcessingDashboardSnapshot): void {
    this.pendingSnapshot = snapshot;
    if (this.applySnapshotTimer) {
      return;
    }
    this.applySnapshotTimer = setTimeout(() => {
      const pending = this.pendingSnapshot;
      this.pendingSnapshot = null;
      this.applySnapshotTimer = null;
      if (pending) {
        this.applySnapshot(pending);
      }
    }, 350);
  }

  private applyCounterFlash(nextCounters: ProcessingCounters): void {
    if (!this.counters) {
      this.counterFlash = {};
      return;
    }

    const keys = Object.keys(nextCounters) as CounterKey[];
    for (const key of keys) {
      const prev = this.counters[key];
      const next = nextCounters[key];
      const flash: CounterFlashKind = next > prev ? 'up' : next < prev ? 'down' : 'same';
      if (flash !== 'same') {
        this.counterFlash[key] = flash;
        this.resetFlashLater(`counter:${key}`, () => {
          this.counterFlash[key] = 'same';
        });
      }
    }
  }

  private applyJobs(nextJobs: ProcessingJobRow[]): void {
    const nextMap = new Map<string, string>();
    const nextFieldsMap = new Map<string, ProcessingJobRow>();
    const fieldsToWatch: JobFieldKey[] = [
      'id',
      'document_id',
      'job_type',
      'status',
      'model_name',
      'provider',
      'batch_id',
      'queue_name',
      'queue_job_key',
      'started_by_id',
      'started_at',
      'finished_at',
      'duration_ms',
      'error_message',
      'created_at',
    ];
    for (const job of nextJobs) {
      const serialized = JSON.stringify(job);
      nextMap.set(job.id, serialized);
      nextFieldsMap.set(job.id, job);

      const prev = this.previousJobsById.get(job.id);
      if (!prev) {
        this.jobFlash[job.id] = 'new';
        this.resetFlashLater(`job:${job.id}`, () => {
          delete this.jobFlash[job.id];
        });
      } else if (prev !== serialized) {
        this.jobFlash[job.id] = 'changed';
        this.resetFlashLater(`job:${job.id}`, () => {
          delete this.jobFlash[job.id];
        });
        const prevFields = this.previousJobFieldsById.get(job.id);
        if (prevFields) {
          for (const field of fieldsToWatch) {
            if (prevFields[field] !== job[field]) {
              const cellKey = `${job.id}:${field}`;
              this.jobCellFlash[cellKey] = true;
              this.resetFlashLater(`cell:${cellKey}`, () => {
                delete this.jobCellFlash[cellKey];
              });
            }
          }
        }
      }
    }
    this.previousJobsById = nextMap;
    this.previousJobFieldsById = nextFieldsMap;
    this.jobs = nextJobs;
  }

  isCellFlashing(jobId: string, field: JobFieldKey): boolean {
    return Boolean(this.jobCellFlash[`${jobId}:${field}`]);
  }

  private cancelBulkFeedbackHide(key: string): void {
    const t = this.bulkFeedbackTimers.get(key);
    if (t) {
      clearTimeout(t);
      this.bulkFeedbackTimers.delete(key);
    }
  }

  /** Скрывает зелёные/красные строки под схемой, чтобы они не копились на экране. */
  private scheduleBulkFeedbackHide(key: string, clear: () => void): void {
    this.cancelBulkFeedbackHide(key);
    const id = setTimeout(() => {
      clear();
      this.bulkFeedbackTimers.delete(key);
      this.cdr.detectChanges();
    }, BULK_FEEDBACK_HIDE_MS);
    this.bulkFeedbackTimers.set(key, id);
  }

  /** Полный список документов (постранично, до 200 за запрос — лимит API). */
  private async fetchAllDocumentsList(): Promise<DocumentListItem[]> {
    const pageSize = 200;
    let offset = 0;
    const all: DocumentListItem[] = [];
    while (true) {
      const res = await firstValueFrom(
        this.documentsApi.listDocuments({
          usePublishedDate: false,
          limit: pageSize,
          offset,
        }),
      );
      all.push(...res.items);
      if (res.items.length < pageSize) {
        break;
      }
      offset += pageSize;
    }
    return all;
  }

  async enqueueTranslate(): Promise<void> {
    if (this.bulkTranslateLoading) {
      return;
    }
    this.bulkTranslateLoading = true;
    this.cancelBulkFeedbackHide('translate');
    this.bulkTranslateMessage = '';
    this.bulkTranslateError = '';
    try {
      const docs = await this.fetchAllDocumentsList();
      const ids = docs.filter((d) => !d.has_translation).map((d) => d.document_id);
      if (ids.length === 0) {
        this.bulkTranslateMessage =
          'Новых документов без перевода для постановки в очередь не найдено';
        this.scheduleBulkFeedbackHide('translate', () => {
          this.bulkTranslateMessage = '';
          this.bulkTranslateError = '';
        });
        return;
      }
      const response = await firstValueFrom(
        this.documentsApi.enqueueTranslateDocuments({ document_ids: ids, target_lang: 'ru' }),
      );
      if (response.enqueued > 0) {
        this.translateBatchNotifier.trackBatch(response.batch_id);
      }
      this.bulkTranslateMessage =
        response.enqueued > 0
          ? `В очередь поставлено: ${response.enqueued} из ${response.scanned}`
          : 'Все выбранные документы уже в работе (перевод)';
      this.scheduleBulkFeedbackHide('translate', () => {
        this.bulkTranslateMessage = '';
        this.bulkTranslateError = '';
      });
    } catch {
      this.bulkTranslateError = 'Не удалось поставить документы на перевод';
      this.scheduleBulkFeedbackHide('translate', () => {
        this.bulkTranslateMessage = '';
        this.bulkTranslateError = '';
      });
    } finally {
      this.bulkTranslateLoading = false;
      this.cdr.detectChanges();
    }
  }

  async enqueueAnnotate(): Promise<void> {
    if (this.bulkAnnotateLoading) {
      return;
    }
    this.bulkAnnotateLoading = true;
    this.cancelBulkFeedbackHide('annotate');
    this.bulkAnnotateMessage = '';
    this.bulkAnnotateError = '';
    try {
      const docs = await this.fetchAllDocumentsList();
      const ids = docs
        .filter((d) => d.has_translation && !d.has_translated_summary)
        .map((d) => d.document_id);
      if (ids.length === 0) {
        this.bulkAnnotateMessage = 'Новых документов с переводом без аннотации не найдено';
        this.scheduleBulkFeedbackHide('annotate', () => {
          this.bulkAnnotateMessage = '';
          this.bulkAnnotateError = '';
        });
        return;
      }
      const response = await firstValueFrom(
        this.documentsApi.enqueueAnnotateDocuments({ document_ids: ids }),
      );
      if (response.enqueued > 0) {
        this.annotateBatchNotifier.trackBatch(response.batch_id);
      }
      this.bulkAnnotateMessage =
        response.enqueued > 0
          ? `В очередь поставлено на аннотацию: ${response.enqueued} из ${response.scanned}`
          : 'Все выбранные документы уже в работе (аннотация)';
      this.scheduleBulkFeedbackHide('annotate', () => {
        this.bulkAnnotateMessage = '';
        this.bulkAnnotateError = '';
      });
    } catch {
      this.bulkAnnotateError = 'Не удалось поставить документы на аннотацию';
      this.scheduleBulkFeedbackHide('annotate', () => {
        this.bulkAnnotateMessage = '';
        this.bulkAnnotateError = '';
      });
    } finally {
      this.bulkAnnotateLoading = false;
      this.cdr.detectChanges();
    }
  }

  async enqueueCategorize(): Promise<void> {
    if (this.bulkCategorizeLoading) {
      return;
    }
    this.bulkCategorizeLoading = true;
    this.cancelBulkFeedbackHide('categorize');
    this.bulkCategorizeMessage = '';
    this.bulkCategorizeError = '';
    try {
      const docs = await this.fetchAllDocumentsList();
      const ids = docs.filter((d) => d.has_translation && !d.has_categories).map((d) => d.document_id);
      if (ids.length === 0) {
        this.bulkCategorizeMessage = 'Новых документов с переводом без категорий не найдено';
        this.scheduleBulkFeedbackHide('categorize', () => {
          this.bulkCategorizeMessage = '';
          this.bulkCategorizeError = '';
        });
        return;
      }
      const response = await firstValueFrom(
        this.documentsApi.enqueueCategorizeDocuments({ document_ids: ids }),
      );
      if (response.enqueued > 0) {
        this.categorizeBatchNotifier.trackBatch(response.batch_id);
      }
      this.bulkCategorizeMessage =
        response.enqueued > 0
          ? `В очередь поставлено на категоризацию: ${response.enqueued} из ${response.scanned}`
          : 'Все выбранные документы уже в работе (категоризация)';
      this.scheduleBulkFeedbackHide('categorize', () => {
        this.bulkCategorizeMessage = '';
        this.bulkCategorizeError = '';
      });
    } catch {
      this.bulkCategorizeError = 'Не удалось поставить документы на категоризацию';
      this.scheduleBulkFeedbackHide('categorize', () => {
        this.bulkCategorizeMessage = '';
        this.bulkCategorizeError = '';
      });
    } finally {
      this.bulkCategorizeLoading = false;
      this.cdr.detectChanges();
    }
  }

  async enqueueExtractor(): Promise<void> {
    if (this.bulkExtractorLoading) {
      return;
    }
    this.bulkExtractorLoading = true;
    this.cancelBulkFeedbackHide('extractor');
    this.bulkExtractorMessage = '';
    this.bulkExtractorError = '';
    try {
      const docs = await this.fetchAllDocumentsList();
      const ids = docs.filter((d) => d.has_original_content && !d.has_entities).map((d) => d.document_id);
      if (ids.length === 0) {
        this.bulkExtractorMessage =
          'Новых документов с оригинальным текстом без сущностей не найдено';
        this.scheduleBulkFeedbackHide('extractor', () => {
          this.bulkExtractorMessage = '';
          this.bulkExtractorError = '';
        });
        return;
      }
      const response = await firstValueFrom(
        this.documentsApi.enqueueExtractorDocuments({ document_ids: ids }),
      );
      if (response.enqueued > 0) {
        this.extractorBatchNotifier.trackBatch(response.batch_id);
      }
      this.bulkExtractorMessage =
        response.enqueued > 0
          ? `В очередь extractor поставлено: ${response.enqueued} из ${response.scanned}`
          : 'Все выбранные документы уже в работе (сущности)';
      this.scheduleBulkFeedbackHide('extractor', () => {
        this.bulkExtractorMessage = '';
        this.bulkExtractorError = '';
      });
    } catch {
      this.bulkExtractorError = 'Не удалось поставить документы на извлечение сущностей';
      this.scheduleBulkFeedbackHide('extractor', () => {
        this.bulkExtractorMessage = '';
        this.bulkExtractorError = '';
      });
    } finally {
      this.bulkExtractorLoading = false;
      this.cdr.detectChanges();
    }
  }

  async enqueueTaggerOriginal(): Promise<void> {
    if (this.bulkTagOriginalLoading) {
      return;
    }
    this.bulkTagOriginalLoading = true;
    this.cancelBulkFeedbackHide('tagOriginal');
    this.bulkTagOriginalMessage = '';
    this.bulkTagOriginalError = '';
    try {
      const docs = await this.fetchAllDocumentsList();
      const ids = docs
        .filter((d) => d.has_original_content && d.original_tags.length === 0)
        .map((d) => d.document_id);
      if (ids.length === 0) {
        this.bulkTagOriginalMessage =
          'Новых документов с оригиналом без оригинальных тегов не найдено';
        this.scheduleBulkFeedbackHide('tagOriginal', () => {
          this.bulkTagOriginalMessage = '';
          this.bulkTagOriginalError = '';
        });
        return;
      }
      const response = await firstValueFrom(
        this.documentsApi.enqueueTaggerOriginalDocuments({ document_ids: ids }),
      );
      if (response.enqueued > 0) {
        this.taggerBatchNotifier.trackBatch(response.batch_id, 'original');
      }
      this.bulkTagOriginalMessage =
        response.enqueued > 0
          ? `В очередь tagger (оригинал) поставлено: ${response.enqueued} из ${response.scanned}`
          : 'Все выбранные документы уже в работе (теги оригинала)';
      this.scheduleBulkFeedbackHide('tagOriginal', () => {
        this.bulkTagOriginalMessage = '';
        this.bulkTagOriginalError = '';
      });
    } catch {
      this.bulkTagOriginalError = 'Не удалось поставить документы на извлечение оригинальных тегов';
      this.scheduleBulkFeedbackHide('tagOriginal', () => {
        this.bulkTagOriginalMessage = '';
        this.bulkTagOriginalError = '';
      });
    } finally {
      this.bulkTagOriginalLoading = false;
      this.cdr.detectChanges();
    }
  }

  async enqueueTaggerTranslated(): Promise<void> {
    if (this.bulkTagTranslatedLoading) {
      return;
    }
    this.bulkTagTranslatedLoading = true;
    this.cancelBulkFeedbackHide('tagTranslated');
    this.bulkTagTranslatedMessage = '';
    this.bulkTagTranslatedError = '';
    try {
      const docs = await this.fetchAllDocumentsList();
      const ids = docs
        .filter((d) => d.has_translation && d.translated_tags.length === 0)
        .map((d) => d.document_id);
      if (ids.length === 0) {
        this.bulkTagTranslatedMessage =
          'Новых документов с переводом без переводных тегов не найдено';
        this.scheduleBulkFeedbackHide('tagTranslated', () => {
          this.bulkTagTranslatedMessage = '';
          this.bulkTagTranslatedError = '';
        });
        return;
      }
      const response = await firstValueFrom(
        this.documentsApi.enqueueTaggerTranslatedDocuments({ document_ids: ids }),
      );
      if (response.enqueued > 0) {
        this.taggerBatchNotifier.trackBatch(response.batch_id, 'translated');
      }
      this.bulkTagTranslatedMessage =
        response.enqueued > 0
          ? `В очередь tagger (перевод) поставлено: ${response.enqueued} из ${response.scanned}`
          : 'Все выбранные документы уже в работе (теги перевода)';
      this.scheduleBulkFeedbackHide('tagTranslated', () => {
        this.bulkTagTranslatedMessage = '';
        this.bulkTagTranslatedError = '';
      });
    } catch {
      this.bulkTagTranslatedError = 'Не удалось поставить документы на извлечение тегов перевода';
      this.scheduleBulkFeedbackHide('tagTranslated', () => {
        this.bulkTagTranslatedMessage = '';
        this.bulkTagTranslatedError = '';
      });
    } finally {
      this.bulkTagTranslatedLoading = false;
      this.cdr.detectChanges();
    }
  }

  async purgeAllDocuments(): Promise<void> {
    if (this.purgeLoading) {
      return;
    }
    const ok = window.confirm(
      'Удалить ВСЕ документы и связанные данные (теги/сущности/категории/джобы)? Действие необратимо.',
    );
    if (!ok) {
      return;
    }
    this.purgeLoading = true;
    this.purgeMessage = '';
    this.purgeError = '';
    this.cdr.detectChanges();
    try {
      const result = await this.api.purgeAllDocuments();
      this.purgeMessage = `Удалено документов: ${result.deleted_documents}`;
    } catch {
      this.purgeError = 'Не удалось очистить документы';
    } finally {
      this.purgeLoading = false;
      this.cdr.detectChanges();
    }
  }

  private resetFlashLater(key: string, handler: () => void): void {
    const existing = this.flashTimers.get(key);
    if (existing) {
      clearTimeout(existing);
    }
    const timerId = setTimeout(() => {
      handler();
      this.flashTimers.delete(key);
    }, 1200);
    this.flashTimers.set(key, timerId);
  }
}
