import { CommonModule } from '@angular/common';
import {
  ChangeDetectorRef,
  Component,
  DestroyRef,
  EventEmitter,
  inject,
  Input,
  OnChanges,
  OnInit,
  Output,
  SimpleChanges,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AccordionModule } from 'primeng/accordion';
import { SourceAccordionHeaderComponent } from '../source-accordion-header/source-accordion-header.component';
import { SourceExpandedDetailsComponent } from '../source-expanded-details/source-expanded-details.component';
import { SourceEditPanelComponent } from '../source-edit-panel/source-edit-panel.component';
import { SourceParsePanelComponent } from '../source-parse-panel/source-parse-panel.component';
import { LanguageCatalogItem, SourceListItem, SourcesApi } from '../../api/sources-api';
import { SourceParseRunService } from '../../services/source-parse-run.service';
import {
  createDefaultSourceParseFormState,
  SourceParseFormState,
} from './source-parse-form.model';

@Component({
  selector: 'app-sources-list-accordion',
  standalone: true,
  imports: [
    CommonModule,
    AccordionModule,
    SourceAccordionHeaderComponent,
    SourceExpandedDetailsComponent,
    SourceEditPanelComponent,
    SourceParsePanelComponent,
  ],
  templateUrl: './sources-list-accordion.component.html',
  styleUrl: './sources-list-accordion.component.scss',
})
export class SourcesListAccordionComponent implements OnInit, OnChanges {
  @Input({ required: true }) displayItems: SourceListItem[] = [];
  @Input({ required: true }) allItems: SourceListItem[] = [];
  @Input() listLoading = false;
  @Input() listError = '';
  @Input() listEmpty = false;
  @Output() readonly sourceUpdated = new EventEmitter<void>();

  expandedSourceId: string | undefined = undefined;
  languagesCatalog: LanguageCatalogItem[] = [];
  languagesLoadError = '';

  private readonly parseForms = new Map<string, SourceParseFormState>();
  private readonly parseRun = inject(SourceParseRunService);
  readonly parseRunState$ = this.parseRun.viewState$;

  private readonly storageExpandedKey = 'ai-tools.sources.expandedSourceId';

  private readonly sourcesApi = inject(SourcesApi);
  private readonly cdr = inject(ChangeDetectorRef);
  private readonly destroyRef = inject(DestroyRef);

  ngOnInit(): void {
    this.loadLanguagesCatalog();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['displayItems']) {
      this.syncExpandedToVisibleItems();
    }
    const allCh = changes['allItems'];
    if (!allCh || !this.allItems.length) {
      return;
    }
    this.applyExpandedFromStorage();
    const knownSourceIds = this.allItems.map((i) => i.source_id);
    this.parseRun.restoreParseUiFromStorage(knownSourceIds);
    this.parseRun.reconcileActiveRuns(this.allItems, this.expandedSourceId);
  }

  getParseForm(sourceId: string): SourceParseFormState {
    let form = this.parseForms.get(sourceId);
    if (!form) {
      form = createDefaultSourceParseFormState();
      this.parseForms.set(sourceId, form);
      this.ensureParsePostTargetLangSelection(form);
    }
    return form;
  }

  runParse(src: SourceListItem): void {
    this.parseRun.runParse(src, this.getParseForm(src.source_id));
  }

  onSourceUpdated(): void {
    this.sourceUpdated.emit();
  }

  onSourcesListAccordionValueChange(value: unknown): void {
    const raw = Array.isArray(value) ? value[0] : value;
    const v =
      raw === null || raw === undefined || raw === ''
        ? undefined
        : typeof raw === 'string'
          ? raw
          : String(raw);
    if (v) {
      sessionStorage.setItem(this.storageExpandedKey, v);
    } else {
      sessionStorage.removeItem(this.storageExpandedKey);
    }
  }

  private syncExpandedToVisibleItems(): void {
    if (!this.expandedSourceId) {
      return;
    }
    if (this.displayItems.some((i) => i.source_id === this.expandedSourceId)) {
      return;
    }
    this.expandedSourceId = undefined;
    sessionStorage.removeItem(this.storageExpandedKey);
  }

  private applyExpandedFromStorage(): void {
    const stored = sessionStorage.getItem(this.storageExpandedKey);
    if (!stored) {
      return;
    }
    if (this.allItems.some((i) => i.source_id === stored)) {
      this.expandedSourceId = stored;
    } else {
      sessionStorage.removeItem(this.storageExpandedKey);
      this.expandedSourceId = undefined;
    }
  }

  private loadLanguagesCatalog(): void {
    this.languagesLoadError = '';
    this.sourcesApi
      .getLanguagesCatalog()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (items) => {
          this.languagesCatalog = items;
          for (const form of this.parseForms.values()) {
            this.ensureParsePostTargetLangSelection(form);
          }
          this.cdr.markForCheck();
        },
        error: () => {
          this.languagesLoadError = 'Не удалось загрузить список языков';
          this.cdr.markForCheck();
        },
      });
  }

  private ensureParsePostTargetLangSelection(form: SourceParseFormState): void {
    if (!this.languagesCatalog.length) {
      return;
    }
    const lower = form.parsePostTargetLang.trim().toLowerCase();
    const match = this.languagesCatalog.find((l) => l.code.toLowerCase() === lower);
    if (match) {
      form.parsePostTargetLang = match.code;
      return;
    }
    const ru = this.languagesCatalog.find((l) => l.code.toLowerCase() === 'ru');
    form.parsePostTargetLang = ru ? ru.code : this.languagesCatalog[0].code;
  }
}
