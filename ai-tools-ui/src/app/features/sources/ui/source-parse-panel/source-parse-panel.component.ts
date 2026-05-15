import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CheckboxModule } from 'primeng/checkbox';
import { InputNumberModule } from 'primeng/inputnumber';
import { SelectModule } from 'primeng/select';
import { PrimaryButtonComponent } from '../../../../shared/ui/primary-button/primary-button.component';
import { LanguageCatalogItem, SourceListItem } from '../../api/sources-api';
import {
  clampBoundedInteger,
  onBoundedIntegerKeyDown,
} from '../sources-list-accordion/bounded-integer-input.util';
import {
  parsePostHasAnyGranular,
  parsePostShowLangAndMaxTags,
  SourceParseFormState,
} from '../sources-list-accordion/source-parse-form.model';

@Component({
  selector: 'app-source-parse-panel',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    CheckboxModule,
    InputNumberModule,
    SelectModule,
    PrimaryButtonComponent,
  ],
  templateUrl: './source-parse-panel.component.html',
  styleUrl: './source-parse-panel.component.scss',
})
export class SourceParsePanelComponent {
  private static readonly parseDaysMin = 1;
  private static readonly parseDaysMax = 30;
  private static readonly parseMaxTagsMin = 1;
  private static readonly parseMaxTagsMax = 12;

  @Input({ required: true }) src!: SourceListItem;
  @Input({ required: true }) form!: SourceParseFormState;
  @Input() parsingSourceId: string | null = null;
  @Input() languagesCatalog: LanguageCatalogItem[] = [];
  @Input() parseError = '';
  @Input() parseFeedback = '';
  @Input() lastParsedSourceId: string | null = null;

  @Output() readonly parseRequested = new EventEmitter<void>();

  constructor(private readonly cdr: ChangeDetectorRef) {}

  get targetLangSelectOptions(): { label: string; value: string }[] {
    return this.languagesCatalog.map((l) => ({
      value: l.code,
      label: `${l.name} (${l.code})`,
    }));
  }

  get isParsingThisSource(): boolean {
    return this.parsingSourceId === this.src.source_id;
  }

  get fieldsDisabled(): boolean {
    return !this.src.is_active || this.isParsingThisSource;
  }

  showLangAndMaxTags(): boolean {
    return parsePostShowLangAndMaxTags(this.form);
  }

  hasAnyGranular(): boolean {
    return parsePostHasAnyGranular(this.form);
  }

  dependsOnTranslateDisabled(): boolean {
    return (
      !this.src.is_active ||
      this.isParsingThisSource ||
      this.form.parsePostFullPipeline ||
      !this.form.parsePostLlmTranslate
    );
  }

  clampParseDays(): void {
    this.form.parseDays = clampBoundedInteger(
      this.form.parseDays,
      SourceParsePanelComponent.parseDaysMin,
      SourceParsePanelComponent.parseDaysMax,
      3,
    );
  }

  onParseDaysKeyDown(event: KeyboardEvent): void {
    onBoundedIntegerKeyDown(
      event,
      SourceParsePanelComponent.parseDaysMin,
      SourceParsePanelComponent.parseDaysMax,
    );
  }

  clampParseMaxTags(): void {
    this.form.parsePostMaxTags = clampBoundedInteger(
      this.form.parsePostMaxTags,
      SourceParsePanelComponent.parseMaxTagsMin,
      SourceParsePanelComponent.parseMaxTagsMax,
      12,
    );
  }

  onParseMaxTagsKeyDown(event: KeyboardEvent): void {
    onBoundedIntegerKeyDown(
      event,
      SourceParsePanelComponent.parseMaxTagsMin,
      SourceParsePanelComponent.parseMaxTagsMax,
    );
  }

  onTranslateToggled(enabled: boolean): void {
    if (!enabled) {
      this.form.parsePostLlmTagTranslated = false;
      this.form.parsePostLlmAnnotate = false;
    }
  }

  onFullPipelineChange(checked: boolean): void {
    if (checked) {
      return;
    }
    this.cdr.markForCheck();
    window.setTimeout(() => {
      const top = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
      window.scrollTo({ top, behavior: 'smooth' });
    }, 320);
  }

  onParseClick(): void {
    this.parseRequested.emit();
  }
}
