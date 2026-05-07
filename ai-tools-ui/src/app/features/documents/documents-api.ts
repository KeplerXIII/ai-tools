import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

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
  source_url: string | null;
  document_type_code: string;
  document_type_name: string;
  created_at: string;
  published_at: string | null;
  annotation: string | null;
  main_image: string | null;
  statuses: DocumentStatusItem[];
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

export interface TranslateMissingDocumentsResponse {
  ok: boolean;
  batch_id: string;
  queue: string;
  scanned: number;
  enqueued: number;
}

export interface TranslateMissingBatchStatusResponse {
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

export interface ListDocumentsFilters {
  statusCode?: string;
  documentTypeCode?: string;
  sourceId?: string;
  dateFrom?: string;
  dateTo?: string;
  usePublishedDate?: boolean;
}

@Injectable({
  providedIn: 'root',
})
export class DocumentsApi {
  constructor(private readonly http: HttpClient) {}

  listDocuments(filters: ListDocumentsFilters): Observable<DocumentListResponse> {
    let params = new HttpParams();
    if (filters.statusCode) {
      params = params.set('status_code', filters.statusCode);
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

  enqueueTranslateMissingDocuments(
    payload: { target_lang?: string; limit?: number } = {},
  ): Observable<TranslateMissingDocumentsResponse> {
    return this.http.post<TranslateMissingDocumentsResponse>(
      '/api/v1/processing/documents/translate-missing',
      payload,
    );
  }

  getTranslateMissingBatchStatus(batchId: string): Observable<TranslateMissingBatchStatusResponse> {
    return this.http.get<TranslateMissingBatchStatusResponse>(
      `/api/v1/processing/documents/translate-missing/${batchId}`,
    );
  }
}
