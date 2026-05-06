import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

export interface SourceListItem {
  source_id: string;
  name: string | null;
  url: string;
  rss_url: string | null;
  language_code: string;
  country_code: string | null;
  document_type_code: string;
  document_type_name: string;
  is_active: boolean;
  created_at: string;
  added_by_user_id: string;
  added_by_username: string;
  documents_total: number;
  documents_unprocessed: number;
  last_parse_created_total: number | null;
  last_parse_at: string | null;
}

export interface SourceListResponse {
  total: number;
  items: SourceListItem[];
  can_filter_by_all_users: boolean;
}

/** Тело POST /parsing/sources — совпадает с ``SourceCreateRequest`` на бэкенде. */
export interface SourceCreateRequestBody {
  url: string;
  name?: string | null;
  language_code?: string;
  country_code?: string | null;
  rss_url?: string | null;
  document_type_code: string;
}

export interface SourceCreateResponse {
  source_id: string;
  url: string;
  name: string | null;
  language_code: string;
  country_code: string | null;
  rss_url: string | null;
  is_active: boolean;
  document_type_code: string;
  document_type_name: string;
}

export interface ParseSourceRequestBody {
  source_id: string;
  days?: number;
}

export interface ParseSourceDocumentItem {
  document_id: string;
  title: string;
  source_url: string | null;
  published_at: string | null;
  created_at: string;
}

export interface ParseSourceResponse {
  source_id: string;
  found_total: number;
  created_total: number;
  existing_unprocessed_by_source: ParseSourceDocumentItem[];
  new_unprocessed_by_source: ParseSourceDocumentItem[];
}

export interface LanguageCatalogItem {
  code: string;
  name: string;
}

export interface CountryCatalogItem {
  code: string;
  name: string;
}

@Injectable({
  providedIn: 'root',
})
export class SourcesApi {
  constructor(private readonly http: HttpClient) {}

  getLanguagesCatalog(): Observable<LanguageCatalogItem[]> {
    return this.http.get<LanguageCatalogItem[]>('/api/v1/parsing/languages/catalog');
  }

  getCountriesCatalog(): Observable<CountryCatalogItem[]> {
    return this.http.get<CountryCatalogItem[]>('/api/v1/parsing/countries/catalog');
  }

  createSource(body: SourceCreateRequestBody): Observable<SourceCreateResponse> {
    return this.http.post<SourceCreateResponse>('/api/v1/parsing/sources', body);
  }

  parseSource(body: ParseSourceRequestBody): Observable<ParseSourceResponse> {
    return this.http.post<ParseSourceResponse>('/api/v1/parsing/sources/parse', body);
  }

  listSources(addedByUserId?: string): Observable<SourceListResponse> {
    let params = new HttpParams();
    if (addedByUserId) {
      params = params.set('added_by_user_id', addedByUserId);
    }
    return this.http.get<SourceListResponse>('/api/v1/parsing/sources', { params });
  }
}
