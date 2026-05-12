import { ChangeDetectorRef, Component, ElementRef, Input, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FloatLabelModule } from 'primeng/floatlabel';
import { SkeletonModule } from 'primeng/skeleton';
import { TextareaModule } from 'primeng/textarea';
import { ArticleParserApi } from '../../api/article-parser-api';
import { ArticleParserState } from '../../model/article-parser-state';

@Component({
  selector: 'app-article-parser-annotation',
  standalone: true,
  imports: [FormsModule, FloatLabelModule, SkeletonModule, TextareaModule],
  templateUrl: './article-parser-annotation.html',
  styleUrl: './article-parser-annotation.scss',
})
export class ArticleParserAnnotationComponent {
  @Input({ required: true }) loadingSummary = false;

  @ViewChild('annotationSkeleton') annotationSkeleton?: ElementRef<HTMLElement>;

  isEditingAnnotationBlock = false;

  constructor(
    public state: ArticleParserState,
    private api: ArticleParserApi,
    private cdr: ChangeDetectorRef,
  ) {}

  toggleAnnotationEdit(): void {
    if (!this.isEditingAnnotationBlock) {
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
    this.isEditingAnnotationBlock = !this.isEditingAnnotationBlock;
    if (!this.isEditingAnnotationBlock) {
      const docId = this.state.article?.document_id;
      if (docId) {
        const hasTranslation = !!this.state.translatedText?.trim();
        this.state.error = '';
        this.api
          .saveDocument(
            docId,
            hasTranslation
              ? { translated_summary: this.state.annotation ?? '' }
              : { original_summary: this.state.annotation ?? '' },
          )
          .subscribe({
            error: () => {
              this.state.error = 'Не удалось сохранить аннотацию';
              this.cdr.detectChanges();
            },
          });
      }
    }
  }

  resetAnnotationEdit(): void {
    this.isEditingAnnotationBlock = false;
  }
}
