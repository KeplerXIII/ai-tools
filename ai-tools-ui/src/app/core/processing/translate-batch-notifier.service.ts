import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { DocumentsApi, TranslateBatchStatusResponse } from '../../features/documents/documents-api';

import {
  AbstractBatchToastNotifierService,
  GlobalToast,
} from './abstract-batch-toast-notifier.service';
import { ProcessingBatchStreamApi } from './processing-batch-stream.service';

export type { GlobalToast };

@Injectable({
  providedIn: 'root',
})
export class TranslateBatchNotifierService extends AbstractBatchToastNotifierService {
  protected override get storageKey(): string {
    return 'translate_batch_id';
  }

  protected override get batchKind() {
    return 'translate' as const;
  }

  constructor(batchStream: ProcessingBatchStreamApi, documentsApi: DocumentsApi) {
    super(batchStream, documentsApi);
  }

  protected override fetchStatus(batchId: string): Observable<TranslateBatchStatusResponse> {
    return this.documentsApi.getTranslateBatchStatus(batchId);
  }

  protected override buildToast(status: TranslateBatchStatusResponse): GlobalToast {
    const hasErrors = status.failed > 0;
    return {
      kind: hasErrors ? 'error' : 'success',
      text: `Перевод завершен: переведено ${status.completed}, ошибок ${status.failed}, пропущено ${status.skipped}`,
    };
  }
}
