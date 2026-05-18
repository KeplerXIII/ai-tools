import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

export interface WorkbookListItem {
  workbook_id: string;
  name: string;
  sources_count: number;
  entries_count: number;
  created_at: string;
  updated_at: string;
}

export interface WorkbookListResponse {
  total: number;
  items: WorkbookListItem[];
}

export interface WorkbookSourceItem {
  document_id: string;
  title: string;
  translated_title?: string | null;
  source_url?: string | null;
  document_type_code: string;
  document_type_name: string;
  excerpt?: string | null;
  added_at: string;
}

export interface WorkbookEntryItem {
  entry_id: string;
  content: string;
  sources: WorkbookSourceItem[];
  created_at: string;
  updated_at: string;
}

export interface WorkbookDetailResponse {
  workbook_id: string;
  name: string;
  notes?: string | null;
  generation_prompt?: string | null;
  entries: WorkbookEntryItem[];
  created_at: string;
  updated_at: string;
}

@Injectable({ providedIn: 'root' })
export class WorkbookApi {
  private readonly base = '/api/v1/workbooks';

  constructor(private readonly http: HttpClient) {}

  listWorkbooks(): Observable<WorkbookListResponse> {
    return this.http.get<WorkbookListResponse>(this.base);
  }

  createWorkbook(name: string): Observable<WorkbookDetailResponse> {
    return this.http.post<WorkbookDetailResponse>(this.base, { name });
  }

  getWorkbook(workbookId: string): Observable<WorkbookDetailResponse> {
    return this.http.get<WorkbookDetailResponse>(`${this.base}/${workbookId}`);
  }

  updateWorkbook(
    workbookId: string,
    body: { name?: string; notes?: string | null; generation_prompt?: string | null },
  ): Observable<WorkbookDetailResponse> {
    return this.http.patch<WorkbookDetailResponse>(`${this.base}/${workbookId}`, body);
  }

  deleteWorkbook(workbookId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${workbookId}`);
  }

  createEntry(
    workbookId: string,
    body: {
      content: string;
      document_ids?: string[];
      excerpts?: Record<string, string>;
    },
  ): Observable<WorkbookEntryItem> {
    return this.http.post<WorkbookEntryItem>(`${this.base}/${workbookId}/entries`, body);
  }

  updateEntry(
    workbookId: string,
    entryId: string,
    body: { content?: string; document_ids?: string[] },
  ): Observable<WorkbookEntryItem> {
    return this.http.patch<WorkbookEntryItem>(`${this.base}/${workbookId}/entries/${entryId}`, body);
  }

  deleteEntry(workbookId: string, entryId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${workbookId}/entries/${entryId}`);
  }

  addEntrySources(
    workbookId: string,
    entryId: string,
    documentIds: string[],
  ): Observable<WorkbookEntryItem> {
    return this.http.post<WorkbookEntryItem>(
      `${this.base}/${workbookId}/entries/${entryId}/sources`,
      { document_ids: documentIds },
    );
  }

  removeEntrySource(workbookId: string, entryId: string, documentId: string): Observable<void> {
    return this.http.delete<void>(
      `${this.base}/${workbookId}/entries/${entryId}/sources/${documentId}`,
    );
  }
}
