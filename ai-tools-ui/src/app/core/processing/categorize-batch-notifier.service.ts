import { Injectable } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { BehaviorSubject, Subscription, timer } from 'rxjs';

import { DocumentsApi } from '../../features/documents/documents-api';

type ToastKind = 'success' | 'error';

export interface GlobalToast {
  kind: ToastKind;
  text: string;
}

@Injectable({
  providedIn: 'root',
})
export class CategorizeBatchNotifierService {
  private readonly storageKey = 'categorize_batch_id';
  private pollSub: Subscription | null = null;
  private hideTimer: ReturnType<typeof setTimeout> | null = null;

  private readonly _toast = new BehaviorSubject<GlobalToast | null>(null);
  readonly toast$ = this._toast.asObservable();

  constructor(private readonly documentsApi: DocumentsApi) {}

  initFromStorage(): void {
    const batchId = localStorage.getItem(this.storageKey);
    if (batchId) {
      this.startPolling(batchId);
    }
  }

  trackBatch(batchId: string): void {
    localStorage.setItem(this.storageKey, batchId);
    this.startPolling(batchId);
  }

  stopTrackingByBatchId(batchId: string): boolean {
    const normalized = batchId.trim();
    if (!normalized) {
      return false;
    }
    const current = localStorage.getItem(this.storageKey);
    if (current !== normalized) {
      return false;
    }
    this.stopTracking();
    return true;
  }

  dismissToast(): void {
    this._toast.next(null);
    if (this.hideTimer) {
      clearTimeout(this.hideTimer);
      this.hideTimer = null;
    }
  }

  private startPolling(batchId: string): void {
    this.pollSub?.unsubscribe();
    this.pollSub = timer(0, 5000).subscribe(() => {
      this.documentsApi.getCategorizeBatchStatus(batchId).subscribe({
        next: (status) => this.handleStatus(status),
        error: (err: HttpErrorResponse) => {
          if (err.status === 404) {
            this.stopTracking();
          }
        },
      });
    });
  }

  private handleStatus(status: {
    done: boolean;
    completed: number;
    failed: number;
    skipped: number;
  }): void {
    if (!status.done) {
      return;
    }

    const hasErrors = status.failed > 0;
    this._toast.next({
      kind: hasErrors ? 'error' : 'success',
      text: `Категоризация завершена: готово ${status.completed}, ошибок ${status.failed}, пропущено ${status.skipped}`,
    });
    this.stopTracking();

    if (this.hideTimer) {
      clearTimeout(this.hideTimer);
    }
    this.hideTimer = setTimeout(() => {
      this._toast.next(null);
      this.hideTimer = null;
    }, 9000);
  }

  private stopTracking(): void {
    this.pollSub?.unsubscribe();
    this.pollSub = null;
    localStorage.removeItem(this.storageKey);
  }
}
