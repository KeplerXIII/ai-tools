import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, OnDestroy } from '@angular/core';
import { BehaviorSubject, Observable, Subscription } from 'rxjs';

import { DocumentsApi, TranslateBatchStatusResponse } from '../../features/documents/documents-api';

import {
  ProcessingBatchKind,
  ProcessingBatchStreamApi,
  ProcessingBatchStreamSnapshot,
} from './processing-batch-stream.service';

type ToastKind = 'success' | 'error';

export interface GlobalToast {
  kind: ToastKind;
  text: string;
}

const RECONNECT_MS = 3000;
const TOAST_HIDE_MS = 9000;

/**
 * Тост по завершении массового батча: SSE + ``batch_id`` в localStorage.
 * При обрыве соединения — один GET и при необходимости переподключение.
 */
@Injectable()
export abstract class AbstractBatchToastNotifierService implements OnDestroy {
  private streamSub: Subscription | null = null;
  private httpFallbackSub: Subscription | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private trackedBatchId: string | null = null;
  private hideTimer: ReturnType<typeof setTimeout> | null = null;

  private readonly _toast = new BehaviorSubject<GlobalToast | null>(null);
  readonly toast$ = this._toast.asObservable();

  protected constructor(
    private readonly batchStream: ProcessingBatchStreamApi,
    protected readonly documentsApi: DocumentsApi,
  ) {}

  protected abstract get storageKey(): string;
  protected abstract get batchKind(): ProcessingBatchKind;
  protected abstract fetchStatus(batchId: string): Observable<TranslateBatchStatusResponse>;
  protected abstract buildToast(status: TranslateBatchStatusResponse): GlobalToast;

  ngOnDestroy(): void {
    this.clearReconnectTimer();
    this.streamSub?.unsubscribe();
    this.streamSub = null;
    this.httpFallbackSub?.unsubscribe();
    this.httpFallbackSub = null;
    if (this.hideTimer) {
      clearTimeout(this.hideTimer);
      this.hideTimer = null;
    }
  }

  initFromStorage(): void {
    const batchId = localStorage.getItem(this.storageKey);
    if (batchId) {
      this.startStream(batchId);
    }
  }

  trackBatch(batchId: string): void {
    localStorage.setItem(this.storageKey, batchId);
    this.startStream(batchId);
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

  protected stopTracking(): void {
    this.clearReconnectTimer();
    this.streamSub?.unsubscribe();
    this.streamSub = null;
    this.httpFallbackSub?.unsubscribe();
    this.httpFallbackSub = null;
    this.trackedBatchId = null;
    localStorage.removeItem(this.storageKey);
  }

  private startStream(batchId: string): void {
    this.clearReconnectTimer();
    this.httpFallbackSub?.unsubscribe();
    this.httpFallbackSub = null;
    this.streamSub?.unsubscribe();
    this.streamSub = null;
    this.trackedBatchId = batchId;
    this.streamSub = this.batchStream.stream(batchId, this.batchKind).subscribe({
      next: (snap) => this.onSnapshot(snap),
      error: () => this.onTransportError(),
      complete: () => this.onStreamComplete(),
    });
  }

  private onSnapshot(snap: ProcessingBatchStreamSnapshot): void {
    const { snapshot_at: _sa, kind: _k, ...rest } = snap;
    this.applyIfDone(rest as TranslateBatchStatusResponse);
  }

  private onStreamComplete(): void {
    const id = localStorage.getItem(this.storageKey);
    if (!id) {
      return;
    }
    this.httpFallbackSub?.unsubscribe();
    this.httpFallbackSub = this.fetchStatus(id).subscribe({
      next: (s) => this.applyIfDone(s),
      error: (e: HttpErrorResponse) => {
        if (e.status === 404) {
          this.stopTracking();
        }
      },
    });
  }

  private applyIfDone(status: TranslateBatchStatusResponse): void {
    if (!status.done) {
      return;
    }
    this._toast.next(this.buildToast(status));
    this.stopTracking();
    if (this.hideTimer) {
      clearTimeout(this.hideTimer);
    }
    this.hideTimer = setTimeout(() => {
      this._toast.next(null);
      this.hideTimer = null;
    }, TOAST_HIDE_MS);
  }

  private onTransportError(): void {
    const id = this.trackedBatchId ?? localStorage.getItem(this.storageKey);
    if (!id) {
      return;
    }
    this.streamSub?.unsubscribe();
    this.streamSub = null;
    this.httpFallbackSub?.unsubscribe();
    this.httpFallbackSub = this.fetchStatus(id).subscribe({
      next: (s) => {
        if (s.done) {
          this.applyIfDone(s);
        } else {
          this.scheduleReconnect(id);
        }
      },
      error: (e: HttpErrorResponse) => {
        if (e.status === 404) {
          this.stopTracking();
        } else {
          this.scheduleReconnect(id);
        }
      },
    });
  }

  private scheduleReconnect(batchId: string): void {
    this.clearReconnectTimer();
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (localStorage.getItem(this.storageKey) === batchId) {
        this.startStream(batchId);
      }
    }, RECONNECT_MS);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}
