import { ChangeDetectorRef, Component, Input, OnChanges, SimpleChanges } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FloatLabelModule } from 'primeng/floatlabel';
import { InputTextModule } from 'primeng/inputtext';
import { ChipModule } from 'primeng/chip';
import { ImageModule } from 'primeng/image';
import { ArticleParserApi, ExtractResponse } from '../../api/article-parser-api';
import { ArticleParserState } from '../../model/article-parser-state';

@Component({
  selector: 'app-article-parser-meta',
  standalone: true,
  imports: [FormsModule, FloatLabelModule, InputTextModule, ChipModule, ImageModule],
  templateUrl: './article-parser-meta.html',
  styleUrl: './article-parser-meta.scss',
})
export class ArticleParserMetaComponent implements OnChanges {
  @Input({ required: true }) article!: ExtractResponse;

  isEditingMetaBlock = false;

  constructor(
    private api: ArticleParserApi,
    private state: ArticleParserState,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['article']) {
      this.isEditingMetaBlock = false;
    }
  }

  toggleEdit(): void {
    if (!this.isEditingMetaBlock) {
      const docId = this.article?.document_id;
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

    this.isEditingMetaBlock = !this.isEditingMetaBlock;

    if (!this.isEditingMetaBlock) {
      const doc = this.article;
      const docId = doc?.document_id;
      if (docId && doc) {
        const sourceUrl = (doc.url || '').trim();
        this.state.error = '';
        this.api
          .updateDocumentMetadata(docId, {
            title: doc.title ?? '',
            author: doc.author ?? '',
            date: doc.date ?? '',
            main_image: doc.main_image ?? '',
            images: doc.images ?? [],
            ...(sourceUrl ? { source_url: sourceUrl } : {}),
          })
          .subscribe({
            error: () => {
              this.state.error = 'Не удалось сохранить метаданные';
              this.cdr.detectChanges();
            },
          });
      }
    }
  }

  get mainImageUrl(): string {
    return this.article?.main_image?.trim() || '';
  }

  onImageError(event: Event): void {
    console.log('Ошибка загрузки картинки:', this.mainImageUrl, event);
  }
}
