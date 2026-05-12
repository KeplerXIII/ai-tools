import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { DocumentsApi, ExtractorBatchStatusResponse, TranslateBatchStatusResponse } from '../../features/documents/documents-api';

import {
  AbstractBatchToastNotifierService,
  GlobalToast,
} from './abstract-batch-toast-notifier.service';
import { ProcessingBatchStreamApi } from './processing-batch-stream.service';

export type { GlobalToast };

@Injectable({
  providedIn: 'root',
})
export class ExtractorBatchNotifierService extends AbstractBatchToastNotifierService {
  protected override get storageKey(): string {
    return 'extractor_batch_id';
  }

  protected override get batchKind() {
    return 'extractor' as const;
  }

  constructor(batchStream: ProcessingBatchStreamApi, documentsApi: DocumentsApi) {
    super(batchStream, documentsApi);
  }

  protected override fetchStatus(batchId: string): Observable<TranslateBatchStatusResponse> {
    return this.documentsApi.getExtractorBatchStatus(batchId) as Observable<TranslateBatchStatusResponse>;
  }

  protected override buildToast(status: ExtractorBatchStatusResponse): GlobalToast {
    const hasErrors = status.failed > 0;
    return {
      kind: hasErrors ? 'error' : 'success',
      text: `Извлечение сущностей завершено: готово ${status.completed}, ошибок ${status.failed}, пропущено ${status.skipped}`,
    };
  }
}
