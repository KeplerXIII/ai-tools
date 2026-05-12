import { ChangeDetectorRef, Component, ElementRef, EventEmitter, Input, Output, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TextareaModule } from 'primeng/textarea';
import { ArticleParserApi } from '../../api/article-parser-api';
import { ArticleParserState } from '../../model/article-parser-state';
import {
  ButtonVariant,
  OutlineButtonComponent,
} from '../../../../shared/ui/outline-button/outline-button.component';
import { buildHighlightedArticleTextByGroups } from '../../lib/article-highlighter';

@Component({
  selector: 'app-article-parser-original-text',
  standalone: true,
  imports: [FormsModule, OutlineButtonComponent, TextareaModule],
  templateUrl: './article-parser-original-text.html',
  styleUrl: './article-parser-original-text.scss',
})
export class ArticleParserOriginalTextComponent {
  @Input({ required: true }) isDisabled = false;
  @Input() originalTagsError = '';
  @Input() translationError = '';

  @Output() tagOriginal = new EventEmitter<void>();
  @Output() translateArticle = new EventEmitter<void>();

  @ViewChild('originalTextPreview') originalTextPreview?: ElementRef<HTMLElement>;
  @ViewChild('originalTextEditor') originalTextEditor?: ElementRef<HTMLElement>;

  readonly ButtonVariant = ButtonVariant;

  isEditingOriginalBlock = false;
  private originalTextViewportScroll = 0;

  constructor(
    public state: ArticleParserState,
    private api: ArticleParserApi,
    private cdr: ChangeDetectorRef,
  ) {}

  get highlightedArticleText(): string {
    const text = this.state.article?.text || '';
    const ent = this.state.entities;

    const sortDesc = (a: string, b: string) => b.length - a.length;
    const military = [...(ent?.military_equipment || [])]
      .map((e) => e.name)
      .filter(Boolean)
      .sort(sortDesc);
    const manufacturers = [...(ent?.manufacturers || [])]
      .map((e) => e.name)
      .filter(Boolean)
      .sort(sortDesc);
    const contracts = [...(ent?.contracts || [])]
      .map((e) => e.name)
      .filter(Boolean)
      .sort(sortDesc);

    return buildHighlightedArticleTextByGroups(text, [
      { className: 'highlighted-entity-military', entities: military },
      { className: 'highlighted-entity-manufacturer', entities: manufacturers },
      { className: 'highlighted-entity-contract', entities: contracts },
    ]);
  }

  toggleOriginalEdit(): void {
    if (!this.isEditingOriginalBlock) {
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
    if (!this.isEditingOriginalBlock) {
      this.originalTextViewportScroll = this.originalTextPreview?.nativeElement?.scrollTop ?? 0;
    } else {
      const ta = this.getOriginalTextTextarea();
      this.originalTextViewportScroll = ta?.scrollTop ?? 0;
    }
    this.isEditingOriginalBlock = !this.isEditingOriginalBlock;
    this.scheduleRestoreOriginalTextScroll();
    if (!this.isEditingOriginalBlock) {
      const docId = this.state.article?.document_id;
      if (docId && this.state.article) {
        this.state.error = '';
        this.api
          .saveDocument(docId, {
            original_content: this.state.article.text ?? '',
          })
          .subscribe({
            error: () => {
              this.state.error = 'Не удалось сохранить исходный текст';
              this.cdr.detectChanges();
            },
          });
      }
    }
  }

  resetEdit(): void {
    this.isEditingOriginalBlock = false;
  }

  private getOriginalTextTextarea(): HTMLTextAreaElement | null {
    const host = this.originalTextEditor?.nativeElement;
    if (!host) {
      return null;
    }
    return host.querySelector('textarea');
  }

  private scheduleRestoreOriginalTextScroll(): void {
    const savedInnerScroll = this.originalTextViewportScroll;
    const savedWinX = window.scrollX;
    const savedWinY = window.scrollY;

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        window.scrollTo(savedWinX, savedWinY);

        const textarea = this.getOriginalTextTextarea();
        const preview = this.originalTextPreview?.nativeElement;
        if (this.isEditingOriginalBlock && textarea) {
          textarea.scrollTop = savedInnerScroll;
          textarea.focus({ preventScroll: true });
        } else if (!this.isEditingOriginalBlock && preview) {
          preview.scrollTop = savedInnerScroll;
        }
      });
    });
  }
}
