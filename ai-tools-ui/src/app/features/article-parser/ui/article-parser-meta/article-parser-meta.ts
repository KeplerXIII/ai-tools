import { ChangeDetectorRef, Component, Input, OnChanges, SimpleChanges } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FloatLabelModule } from 'primeng/floatlabel';
import { InputTextModule } from 'primeng/inputtext';
import { ChipModule } from 'primeng/chip';
import { ImageModule } from 'primeng/image';
import { ArticleParserApi, ExtractResponse } from '../../api/article-parser-api';
import { ArticleParserState } from '../../model/article-parser-state';
import {
  ArticleMetaGalleriaItem,
  ArticleParserMetaGalleriaComponent,
} from '../article-parser-meta-galleria/article-parser-meta-galleria';
import { ArticleParserMetaImagesDeleteDialogComponent } from './article-parser-meta-images-delete-dialog/article-parser-meta-images-delete-dialog';
import { ArticleParserMetaMainImagePickDialogComponent } from './article-parser-meta-main-image-pick-dialog/article-parser-meta-main-image-pick-dialog';

@Component({
  selector: 'app-article-parser-meta',
  standalone: true,
  imports: [
    FormsModule,
    FloatLabelModule,
    InputTextModule,
    ChipModule,
    ImageModule,
    ArticleParserMetaGalleriaComponent,
    ArticleParserMetaImagesDeleteDialogComponent,
    ArticleParserMetaMainImagePickDialogComponent,
  ],
  templateUrl: './article-parser-meta.html',
  styleUrl: './article-parser-meta.scss',
})
export class ArticleParserMetaComponent implements OnChanges {
  @Input({ required: true }) article!: ExtractResponse;

  isEditingMetaBlock = false;

  galleriaItems: ArticleMetaGalleriaItem[] = [];

  constructor(
    private api: ArticleParserApi,
    private state: ArticleParserState,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['article']) {
      this.isEditingMetaBlock = false;
      this.rebuildGalleriaItems();
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

  hasGalleryImages(): boolean {
    return (this.article?.images?.length ?? 0) > 0;
  }

  get mainImageUrl(): string {
    return this.article?.main_image?.trim() || '';
  }

  showImagePreview(): boolean {
    if (this.hasGalleryImages()) {
      return this.galleriaItems.length > 0;
    }
    return !!this.mainImageUrl;
  }

  onImageError(event: Event): void {
    console.log('Ошибка загрузки картинки:', this.mainImageUrl, event);
  }

  private rebuildGalleriaItems(): void {
    if (!this.article || !this.hasGalleryImages()) {
      this.galleriaItems = [];
      return;
    }

    const seen = new Set<string>();
    const items: ArticleMetaGalleriaItem[] = [];
    const main = this.article.main_image?.trim();
    if (main) {
      seen.add(main);
      items.push({
        itemImageSrc: main,
        thumbnailImageSrc: main,
        title: 'Главное изображение',
        alt: 'Главное изображение статьи',
      });
    }

    for (const img of this.article.images ?? []) {
      const url = img.url?.trim();
      if (!url || seen.has(url)) {
        continue;
      }
      seen.add(url);
      items.push({
        itemImageSrc: url,
        thumbnailImageSrc: url,
        title: img.title?.trim() || '',
        alt: img.alt?.trim() || '',
      });
    }

    this.galleriaItems = items;
  }
}
