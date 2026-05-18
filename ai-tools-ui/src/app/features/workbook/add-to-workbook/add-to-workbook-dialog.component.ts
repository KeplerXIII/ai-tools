import { CommonModule } from '@angular/common';
import { Component, DestroyRef, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { DocumentListItem, DocumentsApi } from '../../documents/documents-api';
import { WorkbookApi, WorkbookListItem } from '../api/workbook-api';
import { AddToWorkbookOpenPayload, AddToWorkbookService } from './add-to-workbook.service';

@Component({
  selector: 'app-add-to-workbook-dialog',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './add-to-workbook-dialog.component.html',
  styleUrl: './add-to-workbook-dialog.component.scss',
})
export class AddToWorkbookDialogComponent implements OnInit {
  visible = false;

  workbooks: WorkbookListItem[] = [];
  workbooksLoading = false;
  workbooksError: string | null = null;
  selectedWorkbookId = '';

  entryText = '';
  attachSource = false;
  documentId = '';
  documentTitle = '';

  showDocumentPicker = false;
  documentSearch = '';
  pickerDocuments: DocumentListItem[] = [];
  pickerLoading = false;
  pickerError: string | null = null;

  submitting = false;
  submitError: string | null = null;
  successMessage: string | null = null;

  constructor(
    private readonly addToWorkbook: AddToWorkbookService,
    private readonly workbookApi: WorkbookApi,
    private readonly documentsApi: DocumentsApi,
    private readonly router: Router,
    private readonly destroyRef: DestroyRef,
  ) {}

  ngOnInit(): void {
    this.addToWorkbook.open$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((payload) => {
      this.openWith(payload);
    });
  }

  private openWith(payload: AddToWorkbookOpenPayload): void {
    this.visible = true;
    this.entryText = payload.initialText;
    this.documentId = payload.documentId ?? '';
    this.documentTitle = payload.documentTitle ?? '';
    this.attachSource = Boolean(payload.documentId);
    this.submitError = null;
    this.successMessage = null;
    this.showDocumentPicker = false;
    if (this.documentId && !this.documentTitle) {
      this.resolveDocumentTitle(this.documentId);
    }
    this.loadWorkbooks();
  }

  private resolveDocumentTitle(documentId: string): void {
    this.documentsApi.listDocuments({ documentId, limit: 1, offset: 0 }).subscribe({
      next: (res) => {
        const doc = res.items[0];
        if (doc?.document_id === documentId) {
          this.documentTitle = this.docTitle(doc);
        }
      },
    });
  }

  close(): void {
    this.visible = false;
  }

  loadWorkbooks(): void {
    this.workbooksLoading = true;
    this.workbooksError = null;
    this.workbookApi.listWorkbooks().subscribe({
      next: (res) => {
        this.workbooks = res.items;
        this.workbooksLoading = false;
        if (!this.selectedWorkbookId && res.items.length > 0) {
          this.selectedWorkbookId = res.items[0].workbook_id;
        }
        if (
          this.selectedWorkbookId &&
          !res.items.some((w) => w.workbook_id === this.selectedWorkbookId)
        ) {
          this.selectedWorkbookId = res.items[0]?.workbook_id ?? '';
        }
      },
      error: (err) => {
        this.workbooksLoading = false;
        this.workbooksError = err?.error?.detail ?? 'Не удалось загрузить тетради';
      },
    });
  }

  openDocumentPicker(): void {
    this.showDocumentPicker = true;
    this.documentSearch = '';
    this.pickerLoading = true;
    this.pickerError = null;
    this.documentsApi.listDocuments({ limit: 150, offset: 0 }).subscribe({
      next: (res) => {
        this.pickerDocuments = res.items;
        this.pickerLoading = false;
      },
      error: (err) => {
        this.pickerLoading = false;
        this.pickerError = err?.error?.detail ?? 'Не удалось загрузить документы';
      },
    });
  }

  filteredPickerDocuments(): DocumentListItem[] {
    const q = this.documentSearch.trim().toLowerCase();
    if (!q) return this.pickerDocuments;
    return this.pickerDocuments.filter((doc) => {
      const title = (doc.translated_title || doc.title || '').toLowerCase();
      return title.includes(q) || doc.document_id.toLowerCase().includes(q);
    });
  }

  pickDocument(doc: DocumentListItem): void {
    this.documentId = doc.document_id;
    this.documentTitle = this.docTitle(doc);
    this.attachSource = true;
    this.showDocumentPicker = false;
  }

  clearSource(): void {
    this.documentId = '';
    this.documentTitle = '';
    this.attachSource = false;
  }

  submit(): void {
    const content = this.entryText.trim();
    if (!content) {
      this.submitError = 'Введите текст тезиса';
      return;
    }
    if (!this.selectedWorkbookId) {
      this.submitError = 'Выберите тетрадь';
      return;
    }
    const documentIds = this.attachSource && this.documentId ? [this.documentId] : [];

    this.submitting = true;
    this.submitError = null;
    this.workbookApi
      .createEntry(this.selectedWorkbookId, {
        content,
        document_ids: documentIds,
      })
      .subscribe({
        next: () => {
          this.submitting = false;
          const wb = this.workbooks.find((w) => w.workbook_id === this.selectedWorkbookId);
          this.successMessage = wb ? `Тезис добавлен в «${wb.name}»` : 'Тезис добавлен';
        },
        error: (err) => {
          this.submitting = false;
          this.submitError = err?.error?.detail ?? 'Не удалось добавить тезис';
        },
      });
  }

  openWorkbookInTools(): void {
    if (!this.selectedWorkbookId) return;
    void this.router.navigate(['/tools'], {
      queryParams: { workbook_id: this.selectedWorkbookId },
    });
    this.close();
  }

  docTitle(doc: { title: string; translated_title?: string | null }): string {
    return (doc.translated_title || doc.title || 'Без названия').trim() || 'Без названия';
  }

  get hasSelectionPrefill(): boolean {
    return Boolean(this.entryText.trim());
  }
}
