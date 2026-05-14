import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import type { ExtractResponse } from '../article-parser/api/article-parser-api';

export interface DocumentStatusItem {
  code: string;
  name_ru: string;
  description: string | null;
  assigned_at: string;
  assigned_by_id: string | null;
}

export interface DocumentCategoryItem {
  category_id: string;
  code: string;
  name: string;
  name_ru?: string | null;
  level: number;
  parent_id?: string | null;
  parent_code?: string | null;
  parent_name?: string | null;
  parent_name_ru?: string | null;
  confidence: number;
  prediction_source_code: string;
  text_source?: 'original' | 'translated' | null;
}

export interface DocumentEntityItem {
  id: string;
  name: string;
  entity_type_code: 'military_equipment' | 'manufacturer' | 'contract' | string;
}

export interface DocumentTagItem {
  id: string;
  name: string;
}

export interface DocumentListItem {
  document_id: string;
  title: string;
  translated_title?: string | null;
  source_url: string | null;
  document_type_code: string;
  document_type_name: string;
  created_at: string;
  published_at: string | null;
  annotation: string | null;
  main_image: string | null;
  statuses: DocumentStatusItem[];
  has_translation: boolean;
  has_annotation: boolean;
  has_translated_summary: boolean;
  has_original_content: boolean;
  has_categories: boolean;
  has_entities: boolean;
  has_tags: boolean;
  categories: DocumentCategoryItem[];
  entities: DocumentEntityItem[];
  original_tags: DocumentTagItem[];
  translated_tags: DocumentTagItem[];
}

export interface DocumentListResponse {
  total: number;
  items: DocumentListItem[];
}

export interface DocumentStatusCatalogItem {
  code: string;
  name_ru: string;
  description: string | null;
}

export interface DocumentTypeCatalogItem {
  code: string;
  name: string;
  description: string | null;
}

export interface EnqueueTranslateResponse {
  ok: boolean;
  batch_id: string;
  queue: string;
  scanned: number;
  enqueued: number;
}

export interface TranslateBatchStatusResponse {
  ok: boolean;
  batch_id: string;
  scanned: number;
  enqueued: number;
  completed: number;
  failed: number;
  skipped: number;
  pending: number;
  done: boolean;
}

export interface EnqueueAnnotateResponse {
  ok: boolean;
  batch_id: string;
  queue: string;
  scanned: number;
  enqueued: number;
}

export interface AnnotateBatchStatusResponse {
  ok: boolean;
  batch_id: string;
  scanned: number;
  enqueued: number;
  completed: number;
  failed: number;
  skipped: number;
  pending: number;
  done: boolean;
}

export interface EnqueueCategorizeResponse {
  ok: boolean;
  batch_id: string;
  queue: string;
  scanned: number;
  enqueued: number;
}

export interface CategorizeBatchStatusResponse {
  ok: boolean;
  batch_id: string;
  scanned: number;
  enqueued: number;
  completed: number;
  failed: number;
  skipped: number;
  pending: number;
  done: boolean;
}

export interface EnqueueExtractorResponse {
  ok: boolean;
  batch_id: string;
  queue: string;
  scanned: number;
  enqueued: number;
}

export interface ExtractorBatchStatusResponse {
  ok: boolean;
  batch_id: string;
  scanned: number;
  enqueued: number;
  completed: number;
  failed: number;
  skipped: number;
  pending: number;
  done: boolean;
}

export interface EnqueueTaggerResponse {
  ok: boolean;
  batch_id: string;
  queue: string;
  scanned: number;
  enqueued: number;
  text_source: 'original' | 'translated';
}

export interface TaggerBatchStatusResponse {
  ok: boolean;
  batch_id: string;
  scanned: number;
  enqueued: number;
  completed: number;
  failed: number;
  skipped: number;
  pending: number;
  done: boolean;
}

export interface EnqueueFullLlmPipelineResponse {
  ok: boolean;
  pipeline_correlation_id: string;
  translate_batch_id: string;
  tagger_original_batch_id: string;
  extractor_batch_id: string;
  scanned: number;
  enqueued: number;
  skipped_blocked: number;
  skipped_already_complete: number;
}

export interface ListDocumentsFilters {
  /** Несколько кодов объединяются на сервере по ИЛИ (материал подходит, если есть любой из статусов). */
  statusCodes?: string[];
  /** Один материал по id (ответ как у списка). */
  documentId?: string;
  documentTypeCode?: string;
  sourceId?: string;
  dateFrom?: string;
  dateTo?: string;
  usePublishedDate?: boolean;
  limit?: number;
  offset?: number;
}

@Injectable({
  providedIn: 'root',
})
export class DocumentsApi {
  constructor(private readonly http: HttpClient) {}

  listDocuments(filters: ListDocumentsFilters): Observable<DocumentListResponse> {
    let params = new HttpParams();
    for (const code of filters.statusCodes ?? []) {
      const c = code?.trim();
      if (c) {
        params = params.append('status_code', c);
      }
    }
    if (filters.documentId?.trim()) {
      params = params.set('document_id', filters.documentId.trim());
    }
    if (filters.documentTypeCode) {
      params = params.set('document_type_code', filters.documentTypeCode);
    }
    if (filters.sourceId) {
      params = params.set('source_id', filters.sourceId);
    }
    if (filters.dateFrom) {
      params = params.set('date_from', `${filters.dateFrom}T00:00:00`);
    }
    if (filters.dateTo) {
      params = params.set('date_to', `${filters.dateTo}T23:59:59`);
    }
    params = params.set('use_published_date', filters.usePublishedDate ? 'true' : 'false');
    if (filters.limit != null) {
      params = params.set('limit', String(filters.limit));
    }
    if (filters.offset != null) {
      params = params.set('offset', String(filters.offset));
    }

    return this.http.get<DocumentListResponse>('/api/v1/documents', { params });
  }

  getStatusesCatalog(): Observable<DocumentStatusCatalogItem[]> {
    return this.http.get<DocumentStatusCatalogItem[]>('/api/v1/documents/statuses/catalog');
  }

  getDocumentTypesCatalog(): Observable<DocumentTypeCatalogItem[]> {
    return this.http.get<DocumentTypeCatalogItem[]>('/api/v1/documents/types/catalog');
  }

  deleteDocument(documentId: string): Observable<{ ok: boolean; document_id: string }> {
    return this.http.delete<{ ok: boolean; document_id: string }>(`/api/v1/documents/${documentId}`);
  }

  /** Создание документа из сырого текста (те же статусы, что после extract-url). */
  createDocumentFromRaw(payload: {
    title: string;
    author: string;
    publication_date: string;
    text: string;
    document_type_code: string;
    source_url?: string;
    main_image?: string;
  }): Observable<ExtractResponse> {
    return this.http.post<ExtractResponse>('/api/v1/documents/from-raw', payload);
  }

  enqueueTranslateDocuments(payload: {
    document_ids: string[];
    target_lang?: string;
  }): Observable<EnqueueTranslateResponse> {
    return this.http.post<EnqueueTranslateResponse>('/api/v1/processing/documents/translate', payload);
  }

  getTranslateBatchStatus(batchId: string): Observable<TranslateBatchStatusResponse> {
    return this.http.get<TranslateBatchStatusResponse>(
      `/api/v1/processing/documents/translate/${batchId}`,
    );
  }

  enqueueAnnotateDocuments(payload: { document_ids: string[] }): Observable<EnqueueAnnotateResponse> {
    return this.http.post<EnqueueAnnotateResponse>('/api/v1/processing/documents/annotate', payload);
  }

  getAnnotateBatchStatus(batchId: string): Observable<AnnotateBatchStatusResponse> {
    return this.http.get<AnnotateBatchStatusResponse>(
      `/api/v1/processing/documents/annotate/${batchId}`,
    );
  }

  enqueueCategorizeDocuments(payload: { document_ids: string[] }): Observable<EnqueueCategorizeResponse> {
    return this.http.post<EnqueueCategorizeResponse>('/api/v1/processing/documents/categorize', payload);
  }

  getCategorizeBatchStatus(batchId: string): Observable<CategorizeBatchStatusResponse> {
    return this.http.get<CategorizeBatchStatusResponse>(
      `/api/v1/processing/documents/categorize/${batchId}`,
    );
  }

  enqueueExtractorDocuments(payload: { document_ids: string[] }): Observable<EnqueueExtractorResponse> {
    return this.http.post<EnqueueExtractorResponse>('/api/v1/processing/documents/extractor', payload);
  }

  getExtractorBatchStatus(batchId: string): Observable<ExtractorBatchStatusResponse> {
    return this.http.get<ExtractorBatchStatusResponse>(
      `/api/v1/processing/documents/extractor/${batchId}`,
    );
  }

  enqueueTaggerOriginalDocuments(payload: {
    document_ids: string[];
    max_tags?: number;
  }): Observable<EnqueueTaggerResponse> {
    return this.http.post<EnqueueTaggerResponse>(
      '/api/v1/processing/documents/tagger-original',
      payload,
    );
  }

  enqueueTaggerTranslatedDocuments(payload: {
    document_ids: string[];
    max_tags?: number;
  }): Observable<EnqueueTaggerResponse> {
    return this.http.post<EnqueueTaggerResponse>(
      '/api/v1/processing/documents/tagger-translated',
      payload,
    );
  }

  getTaggerBatchStatus(batchId: string): Observable<TaggerBatchStatusResponse> {
    return this.http.get<TaggerBatchStatusResponse>(`/api/v1/processing/documents/tagger/${batchId}`);
  }

  enqueueFullLlmPipeline(payload: {
    document_ids: string[];
    target_lang?: string;
    max_tags?: number;
  }): Observable<EnqueueFullLlmPipelineResponse> {
    return this.http.post<EnqueueFullLlmPipelineResponse>(
      '/api/v1/processing/documents/full-llm-pipeline',
      payload,
    );
  }
}
