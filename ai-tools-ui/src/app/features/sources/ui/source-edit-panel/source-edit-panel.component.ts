import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  SimpleChanges,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { InputGroupAddonModule } from 'primeng/inputgroupaddon';
import { InputGroupModule } from 'primeng/inputgroup';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import {
  ButtonVariant,
  OutlineButtonComponent,
} from '../../../../shared/ui/outline-button/outline-button.component';
import { PrimaryButtonComponent } from '../../../../shared/ui/primary-button/primary-button.component';
import { DocumentTypeCatalogItem, DocumentsApi } from '../../../documents/documents-api';
import {
  CountryCatalogItem,
  LanguageCatalogItem,
  SourceListItem,
  SourceUpdateRequestBody,
  SourcesApi,
} from '../../api/sources-api';

@Component({
  selector: 'app-source-edit-panel',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    SelectModule,
    InputGroupModule,
    InputGroupAddonModule,
    InputTextModule,
    OutlineButtonComponent,
    PrimaryButtonComponent,
  ],
  templateUrl: './source-edit-panel.component.html',
  styleUrl: './source-edit-panel.component.scss',
})
export class SourceEditPanelComponent implements OnChanges {
  readonly ButtonVariant = ButtonVariant;

  @Input({ required: true }) src!: SourceListItem;
  @Output() readonly sourceUpdated = new EventEmitter<void>();

  editing = false;
  formUrl = '';
  formName = '';
  formLanguageCode = 'en';
  formCountryCode = '';
  formRssUrls = '';
  formDiscoveryPaths = '';
  formDocumentTypeCode = 'news';

  languagesCatalog: LanguageCatalogItem[] = [];
  languagesLoadError = '';
  countriesCatalog: CountryCatalogItem[] = [];
  countriesLoadError = '';
  documentTypesCatalog: DocumentTypeCatalogItem[] = [];
  documentTypesLoadError = '';

  saveSubmitting = false;
  saveError = '';
  saveSuccess = '';

  constructor(
    private readonly sourcesApi: SourcesApi,
    private readonly documentsApi: DocumentsApi,
    private readonly destroyRef: DestroyRef,
  ) {
    this.loadLanguagesCatalog();
    this.loadCountriesCatalog();
    this.loadDocumentTypesCatalog();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['src'] && !this.editing) {
      this.resetFormFromSource();
    }
  }

  get languageSelectOptions(): { label: string; value: string }[] {
    return this.languagesCatalog.map((l) => ({
      value: l.code,
      label: `${l.name} (${l.code})`,
    }));
  }

  get countrySelectOptions(): { label: string; value: string }[] {
    return this.countriesCatalog.map((c) => ({
      value: c.code,
      label: `${c.name} (${c.code})`,
    }));
  }

  get documentTypeSelectOptions(): { label: string; value: string }[] {
    return this.documentTypesCatalog.map((dt) => ({
      value: dt.code,
      label: `${dt.name} (${dt.code})`,
    }));
  }

  startEdit(): void {
    this.resetFormFromSource();
    this.editing = true;
    this.saveError = '';
    this.saveSuccess = '';
  }

  cancelEdit(): void {
    this.editing = false;
    this.resetFormFromSource();
    this.saveError = '';
    this.saveSuccess = '';
  }

  submitSave(): void {
    const url = this.formUrl.trim();
    if (!url) {
      this.saveError = 'Укажите URL сайта источника';
      return;
    }

    this.saveError = '';
    this.saveSuccess = '';
    this.saveSubmitting = true;

    const languageCode = this.formLanguageCode.trim().toLowerCase();
    if (!this.languagesCatalog.some((l) => l.code.toLowerCase() === languageCode)) {
      this.saveError = 'Выберите язык из списка';
      this.saveSubmitting = false;
      return;
    }

    const docTypeLower = this.formDocumentTypeCode.trim().toLowerCase();
    if (!this.documentTypesCatalog.some((t) => t.code.toLowerCase() === docTypeLower)) {
      this.saveError = 'Выберите тип документа из списка';
      this.saveSubmitting = false;
      return;
    }

    const body: SourceUpdateRequestBody = {
      url,
      language_code: languageCode,
      document_type_code: docTypeLower,
      discovery_paths: this.parseLineListInput(this.formDiscoveryPaths),
    };

    const name = this.formName.trim();
    body.name = name ? name.slice(0, 255) : null;

    const countryRaw = this.formCountryCode.trim();
    if (countryRaw) {
      const countryUpper = countryRaw.toUpperCase();
      if (!this.countriesCatalog.some((c) => c.code.toUpperCase() === countryUpper)) {
        this.saveError = 'Выберите страну из списка';
        this.saveSubmitting = false;
        return;
      }
      body.country_code = countryUpper.slice(0, 8);
    } else {
      body.country_code = null;
    }

    body.rss_urls = this.parseLineListInput(this.formRssUrls);

    this.sourcesApi
      .updateSource(this.src.source_id, body)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.saveSubmitting = false;
          this.saveSuccess = 'Изменения сохранены';
          this.editing = false;
          this.sourceUpdated.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.saveSubmitting = false;
          this.saveError = this.formatApiError(err);
        },
      });
  }

  private resetFormFromSource(): void {
    this.formUrl = this.src.url;
    this.formName = this.src.name ?? '';
    this.formLanguageCode = this.src.language_code;
    this.formCountryCode = this.src.country_code ?? '';
    const feeds = this.src.rss_urls?.length
      ? this.src.rss_urls
      : this.src.rss_url
        ? [this.src.rss_url]
        : [];
    this.formRssUrls = feeds.join('\n');
    this.formDiscoveryPaths = (this.src.discovery_paths ?? []).join('\n');
    this.formDocumentTypeCode = this.src.document_type_code;
  }

  private loadLanguagesCatalog(): void {
    this.sourcesApi
      .getLanguagesCatalog()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (items) => {
          this.languagesCatalog = items;
        },
        error: () => {
          this.languagesLoadError = 'Не удалось загрузить список языков';
        },
      });
  }

  private loadCountriesCatalog(): void {
    this.sourcesApi
      .getCountriesCatalog()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (items) => {
          this.countriesCatalog = items;
        },
        error: () => {
          this.countriesLoadError = 'Не удалось загрузить список стран';
        },
      });
  }

  private loadDocumentTypesCatalog(): void {
    this.documentsApi
      .getDocumentTypesCatalog()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (items) => {
          this.documentTypesCatalog = items;
        },
        error: () => {
          this.documentTypesLoadError = 'Не удалось загрузить типы документов';
        },
      });
  }

  private parseLineListInput(raw: string): string[] {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const part of raw.split(/[\n,]+/)) {
      const p = part.trim();
      if (!p || seen.has(p)) {
        continue;
      }
      seen.add(p);
      out.push(p);
    }
    return out;
  }

  private formatApiError(err: HttpErrorResponse): string {
    const detail = err.error?.detail;
    if (typeof detail === 'string') {
      return detail;
    }
    if (err.status === 409) {
      return 'Источник с таким URL уже существует для вашего пользователя';
    }
    return 'Не удалось сохранить изменения';
  }
}
