import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, EventEmitter, OnInit, Output } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { PrimeTemplate } from 'primeng/api';
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
  SourceCreateRequestBody,
  SourcesApi,
} from '../../api/sources-api';

@Component({
  selector: 'app-sources-create-form',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    PrimeTemplate,
    SelectModule,
    InputGroupModule,
    InputGroupAddonModule,
    InputTextModule,
    OutlineButtonComponent,
    PrimaryButtonComponent,
  ],
  templateUrl: './sources-create-form.component.html',
  styleUrl: './sources-create-form.component.scss',
})
export class SourcesCreateFormComponent implements OnInit {
  readonly ButtonVariant = ButtonVariant;

  @Output() readonly sourceCreated = new EventEmitter<void>();

  formUrl = '';
  formName = '';
  formLanguageCode = 'en';
  formCountryCode = '';
  /** По одному URL RSS на строку */
  formRssUrls = '';
  /** По одному пути на строку, от корня сайта: /news */
  formDiscoveryPaths = '';
  formDocumentTypeCode = 'news';
  languagesCatalog: LanguageCatalogItem[] = [];
  languagesLoadError = '';
  countriesCatalog: CountryCatalogItem[] = [];
  countriesLoadError = '';
  documentTypesCatalog: DocumentTypeCatalogItem[] = [];
  documentTypesLoadError = '';
  createSubmitting = false;
  createError = '';
  createSuccess = '';

  constructor(
    private readonly sourcesApi: SourcesApi,
    private readonly documentsApi: DocumentsApi,
    private readonly destroyRef: DestroyRef,
  ) {}

  ngOnInit(): void {
    this.loadLanguagesCatalog();
    this.loadCountriesCatalog();
    this.loadDocumentTypesCatalog();
  }

  get createLanguageSelectOptions(): { label: string; value: string }[] {
    return this.languagesCatalog.map((l) => ({
      value: l.code,
      label: `${l.name} (${l.code})`,
    }));
  }

  get createCountrySelectOptions(): { label: string; value: string }[] {
    return this.countriesCatalog.map((c) => ({
      value: c.code,
      label: `${c.name} (${c.code})`,
    }));
  }

  get createDocumentTypeSelectOptions(): { label: string; value: string }[] {
    return this.documentTypesCatalog.map((dt) => ({
      value: dt.code,
      label: `${dt.name} (${dt.code})`,
    }));
  }

  onFormCountryCodeChange(value: string | null | undefined): void {
    this.formCountryCode = value == null ? '' : value;
  }

  countryFlagUrl(code: string | null | undefined): string {
    const c = (code ?? '').trim().toLowerCase();
    if (!c) {
      return '';
    }
    return `https://flagcdn.com/w20/${c}.png`;
  }

  loadDocumentTypesCatalog(): void {
    this.documentTypesLoadError = '';
    this.documentsApi
      .getDocumentTypesCatalog()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
      next: (items) => {
        this.documentTypesCatalog = items;
        this.ensureDocumentTypeSelection();
      },
      error: () => {
        this.documentTypesLoadError = 'Не удалось загрузить типы документов';
      },
    });
  }

  loadLanguagesCatalog(): void {
    this.languagesLoadError = '';
    this.sourcesApi
      .getLanguagesCatalog()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
      next: (items) => {
        this.languagesCatalog = items;
        this.ensureLanguageSelection();
      },
      error: () => {
        this.languagesLoadError = 'Не удалось загрузить список языков';
      },
    });
  }

  loadCountriesCatalog(): void {
    this.countriesLoadError = '';
    this.sourcesApi
      .getCountriesCatalog()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
      next: (items) => {
        this.countriesCatalog = items;
        this.ensureCountrySelection();
      },
      error: () => {
        this.countriesLoadError = 'Не удалось загрузить список стран';
      },
    });
  }

  submitCreate(): void {
    const url = this.formUrl.trim();
    if (!url) {
      this.createError = 'Укажите URL сайта источника';
      return;
    }

    this.createError = '';
    this.createSuccess = '';
    this.createSubmitting = true;

    if (!this.languagesCatalog.length) {
      this.createError = 'Дождитесь загрузки списка языков или обновите страницу';
      this.createSubmitting = false;
      return;
    }

    const languageCode = this.formLanguageCode.trim().toLowerCase();
    const langOk = this.languagesCatalog.some((l) => l.code.toLowerCase() === languageCode);
    if (!langOk) {
      this.createError = 'Выберите язык из списка';
      this.createSubmitting = false;
      return;
    }

    if (!this.documentTypesCatalog.length) {
      this.createError = 'Дождитесь загрузки типов документов или обновите страницу';
      this.createSubmitting = false;
      return;
    }
    const docTypeLower = this.formDocumentTypeCode.trim().toLowerCase();
    const docTypeOk = this.documentTypesCatalog.some((t) => t.code.toLowerCase() === docTypeLower);
    if (!docTypeOk) {
      this.createError = 'Выберите тип документа из списка';
      this.createSubmitting = false;
      return;
    }

    const body: SourceCreateRequestBody = {
      url,
      language_code: languageCode,
      document_type_code: docTypeLower,
    };
    const name = this.formName.trim();
    if (name) {
      body.name = name.slice(0, 255);
    }
    const countryRaw = this.formCountryCode.trim();
    if (countryRaw) {
      if (!this.countriesCatalog.length) {
        this.createError = 'Дождитесь загрузки списка стран или сбросьте выбор страны';
        this.createSubmitting = false;
        return;
      }
      const countryUpper = countryRaw.toUpperCase();
      const countryOk = this.countriesCatalog.some((c) => c.code.toUpperCase() === countryUpper);
      if (!countryOk) {
        this.createError = 'Выберите страну из списка';
        this.createSubmitting = false;
        return;
      }
      body.country_code = countryUpper.slice(0, 8);
    }
    const rssUrls = this.parseLineListInput(this.formRssUrls);
    if (rssUrls.length) {
      body.rss_urls = rssUrls;
    }
    const discoveryPaths = this.parseLineListInput(this.formDiscoveryPaths);
    if (discoveryPaths.length) {
      body.discovery_paths = discoveryPaths;
    }

    this.sourcesApi
      .createSource(body)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
      next: () => {
        this.createSubmitting = false;
        this.createSuccess = 'Источник добавлен';
        this.resetCreateForm(false);
        this.sourceCreated.emit();
      },
      error: (err: HttpErrorResponse) => {
        this.createSubmitting = false;
        this.createError = this.formatApiError(err);
      },
    });
  }

  resetCreateForm(clearMessages = true): void {
    this.formUrl = '';
    this.formName = '';
    this.formLanguageCode = 'en';
    this.formCountryCode = '';
    this.formRssUrls = '';
    this.formDiscoveryPaths = '';
    this.formDocumentTypeCode = 'news';
    this.ensureLanguageSelection();
    this.ensureCountrySelection();
    this.ensureDocumentTypeSelection();
    if (clearMessages) {
      this.createError = '';
      this.createSuccess = '';
    }
  }

  private ensureDocumentTypeSelection(): void {
    if (!this.documentTypesCatalog.length) {
      return;
    }
    const lower = this.formDocumentTypeCode.trim().toLowerCase();
    const match = this.documentTypesCatalog.find((t) => t.code.toLowerCase() === lower);
    if (match) {
      this.formDocumentTypeCode = match.code;
      return;
    }
    const news = this.documentTypesCatalog.find((t) => t.code.toLowerCase() === 'news');
    this.formDocumentTypeCode = news ? news.code : this.documentTypesCatalog[0].code;
  }

  private ensureCountrySelection(): void {
    const raw = this.formCountryCode == null ? '' : String(this.formCountryCode);
    if (!raw.trim()) {
      this.formCountryCode = '';
      return;
    }
    const upper = raw.trim().toUpperCase();
    const match = this.countriesCatalog.find((c) => c.code.toUpperCase() === upper);
    if (match) {
      this.formCountryCode = match.code;
      return;
    }
    this.formCountryCode = '';
  }

  private ensureLanguageSelection(): void {
    if (!this.languagesCatalog.length) {
      return;
    }
    const lower = this.formLanguageCode.trim().toLowerCase();
    const match = this.languagesCatalog.find((l) => l.code.toLowerCase() === lower);
    if (match) {
      this.formLanguageCode = match.code;
      return;
    }
    const en = this.languagesCatalog.find((l) => l.code.toLowerCase() === 'en');
    this.formLanguageCode = en ? en.code : this.languagesCatalog[0].code;
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
    if (Array.isArray(detail)) {
      return detail
        .map((row: { msg?: string; loc?: string[] }) => row.msg || '')
        .filter(Boolean)
        .join('; ');
    }
    if (err.status === 409) {
      return 'Источник с таким URL уже существует для вашего пользователя';
    }
    return 'Не удалось создать источник';
  }
}
