import { ChangeDetectorRef, Component, ElementRef, EventEmitter, Input, Output, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FloatLabelModule } from 'primeng/floatlabel';
import { SkeletonModule } from 'primeng/skeleton';
import { TextareaModule } from 'primeng/textarea';
import { ArticleParserApi } from '../../api/article-parser-api';
import { ArticleParserState } from '../../model/article-parser-state';
import {
  ButtonVariant,
  OutlineButtonComponent,
} from '../../../../shared/ui/outline-button/outline-button.component';

@Component({
  selector: 'app-article-parser-translation',
  standalone: true,
  imports: [FormsModule, FloatLabelModule, OutlineButtonComponent, SkeletonModule, TextareaModule],
  templateUrl: './article-parser-translation.html',
  styleUrl: './article-parser-translation.scss',
})
export class ArticleParserTranslationComponent {
  @Input({ required: true }) isDisabled = false;
  @Input() loadingTranslation = false;
  @Input() translatedTagsError = '';
  @Input() summaryError = '';

  @Output() tagTranslated = new EventEmitter<void>();
  @Output() summarizeArticle = new EventEmitter<void>();

  @ViewChild('translationSkeleton') translationSkeleton?: ElementRef<HTMLElement>;

  readonly ButtonVariant = ButtonVariant;

  isEditingTranslationBlock = false;

  constructor(
    public state: ArticleParserState,
    private api: ArticleParserApi,
    private cdr: ChangeDetectorRef,
  ) {}

  toggleTranslationEdit(): void {
    if (!this.isEditingTranslationBlock) {
      const docId = this.state.article?.document_id;
      if (docId) {
        this.state.error = '';
        this.api.lockDocument(docId).subscribe({
          error: () => {
            this.state.error = 'Не удалось заблокировать документ для редактирования';
            this.cdr.detectChanges();
          },
        });
      }
    }
    this.isEditingTranslationBlock = !this.isEditingTranslationBlock;
    if (!this.isEditingTranslationBlock) {
      const docId = this.state.article?.document_id;
      if (docId) {
        this.state.error = '';
        this.api
          .saveDocument(docId, {
            translated_content: this.state.translatedText ?? '',
          })
          .subscribe({
            error: () => {
              this.state.error = 'Не удалось сохранить перевод';
              this.cdr.detectChanges();
            },
          });
      }
    }
  }

  resetTranslationEdit(): void {
    this.isEditingTranslationBlock = false;
  }
}
