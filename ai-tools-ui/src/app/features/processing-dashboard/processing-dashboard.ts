import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { Subscription, timer } from 'rxjs';

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

  constructor(
    private readonly api: ProcessingDashboardApi,
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
