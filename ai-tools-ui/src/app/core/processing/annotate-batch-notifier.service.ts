import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { AnnotateBatchStatusResponse, DocumentsApi, TranslateBatchStatusResponse } from '../../features/documents/documents-api';

import {
  AbstractBatchToastNotifierService,
  GlobalToast,
} from './abstract-batch-toast-notifier.service';
import { ProcessingBatchStreamApi } from './processing-batch-stream.service';

export type { GlobalToast };

@Injectable({
  providedIn: 'root',
})
export class AnnotateBatchNotifierService extends AbstractBatchToastNotifierService {
  protected override get storageKey(): string {
    return 'annotate_batch_id';
  }

  protected override get batchKind() {
    return 'annotate' as const;
  }

  constructor(batchStream: ProcessingBatchStreamApi, documentsApi: DocumentsApi) {
    super(batchStream, documentsApi);
  }

  protected override fetchStatus(batchId: string): Observable<TranslateBatchStatusResponse> {
    return this.documentsApi.getAnnotateBatchStatus(batchId) as Observable<TranslateBatchStatusResponse>;
  }

  protected override buildToast(status: AnnotateBatchStatusResponse): GlobalToast {
    const hasErrors = status.failed > 0;
    return {
      kind: hasErrors ? 'error' : 'success',
      text: `Аннотация завершена: готово ${status.completed}, ошибок ${status.failed}, пропущено ${status.skipped}`,
    };
  }
}
