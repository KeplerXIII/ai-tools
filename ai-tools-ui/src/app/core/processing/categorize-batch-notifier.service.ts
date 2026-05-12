import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { CategorizeBatchStatusResponse, DocumentsApi, TranslateBatchStatusResponse } from '../../features/documents/documents-api';

import {
  AbstractBatchToastNotifierService,
  GlobalToast,
} from './abstract-batch-toast-notifier.service';
import { ProcessingBatchStreamApi } from './processing-batch-stream.service';

export type { GlobalToast };

@Injectable({
  providedIn: 'root',
})
export class CategorizeBatchNotifierService extends AbstractBatchToastNotifierService {
  protected override get storageKey(): string {
    return 'categorize_batch_id';
  }

  protected override get batchKind() {
    return 'categorize' as const;
  }

  constructor(batchStream: ProcessingBatchStreamApi, documentsApi: DocumentsApi) {
    super(batchStream, documentsApi);
  }

  protected override fetchStatus(batchId: string): Observable<TranslateBatchStatusResponse> {
    return this.documentsApi.getCategorizeBatchStatus(batchId) as Observable<TranslateBatchStatusResponse>;
  }

  protected override buildToast(status: CategorizeBatchStatusResponse): GlobalToast {
    const hasErrors = status.failed > 0;
    return {
      kind: hasErrors ? 'error' : 'success',
      text: `Категоризация завершена: готово ${status.completed}, ошибок ${status.failed}, пропущено ${status.skipped}`,
    };
  }
}
