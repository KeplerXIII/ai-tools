import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { DocumentsApi, DocumentListItem, DocumentStatusCatalogItem, DocumentTypeCatalogItem } from './documents-api';

@Component({
  selector: 'app-documents',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './documents.html',
  styleUrl: './documents.scss',
})
export class Documents implements OnInit {
  documents: DocumentListItem[] = [];
  statuses: DocumentStatusCatalogItem[] = [];
  documentTypes: DocumentTypeCatalogItem[] = [];
  loading = false;
  error = '';

  selectedStatusCode = '';
  selectedDocumentTypeCode = '';
  dateFrom = '';
  dateTo = '';
  usePublishedDate = false;
  expandedDocumentId: string | null = null;

  constructor(
    private readonly documentsApi: DocumentsApi,
    private readonly router: Router,
  ) {}

  ngOnInit(): void {
    this.loadFilters();
    this.loadDocuments();
  }

  loadFilters(): void {
    this.documentsApi.getStatusesCatalog().subscribe({
      next: (items) => {
        this.statuses = items;
      },
    });

    this.documentsApi.getDocumentTypesCatalog().subscribe({
      next: (items) => {
        this.documentTypes = items;
      },
    });
  }

  loadDocuments(): void {
    this.loading = true;
    this.error = '';

    this.documentsApi
      .listDocuments({
        statusCode: this.selectedStatusCode || undefined,
        documentTypeCode: this.selectedDocumentTypeCode || undefined,
        dateFrom: this.dateFrom || undefined,
        dateTo: this.dateTo || undefined,
        usePublishedDate: this.usePublishedDate,
      })
      .subscribe({
        next: (response) => {
          this.documents = response.items;
          this.loading = false;
        },
        error: () => {
          this.error = 'Не удалось загрузить список документов';
          this.loading = false;
        },
      });
  }

  onFiltersChanged(): void {
    this.loadDocuments();
  }

  resetFilters(): void {
    this.selectedStatusCode = '';
    this.selectedDocumentTypeCode = '';
    this.dateFrom = '';
    this.dateTo = '';
    this.usePublishedDate = false;
    this.loadDocuments();
  }

  toggleExpand(documentId: string): void {
    this.expandedDocumentId = this.expandedDocumentId === documentId ? null : documentId;
  }

  isExpanded(documentId: string): boolean {
    return this.expandedDocumentId === documentId;
  }

  openInArticleParser(doc: DocumentListItem): void {
    if (!doc.source_url?.trim()) {
      return;
    }

    void this.router.navigate(['/article-parser'], {
      queryParams: {
        url: doc.source_url,
        autoload: '1',
      },
    });
  }
}
