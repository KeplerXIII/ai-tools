import { ApplicationRef, ChangeDetectorRef, Component, Input, OnChanges, SimpleChanges } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FloatLabelModule } from 'primeng/floatlabel';
import { InputTextModule } from 'primeng/inputtext';
import { ChipModule } from 'primeng/chip';
import { ImageModule } from 'primeng/image';
import { DialogModule } from 'primeng/dialog';
import { RadioButtonModule } from 'primeng/radiobutton';
import { ArticleParserApi, ExtractResponse } from '../../api/article-parser-api';
import { ArticleParserState } from '../../model/article-parser-state';
import {
  ArticleMetaGalleriaItem,
  ArticleParserMetaGalleriaComponent,
} from '../article-parser-meta-galleria/article-parser-meta-galleria';
import { ArticleParserMetaImagesDeleteDialogComponent } from './article-parser-meta-images-delete-dialog/article-parser-meta-images-delete-dialog';

/** Строка в модальном окне выбора главного изображения (без множественного выбора). */
interface ArticleMetaMainPickRow {
  url: string;
  title: string;
  alt: string;
  /** Главное на момент открытия диалога (подпись в списке). */
  isMain: boolean;
}

@Component({
  selector: 'app-article-parser-meta',
  standalone: true,
  imports: [
    FormsModule,
    FloatLabelModule,
    InputTextModule,
    ChipModule,
    ImageModule,
    DialogModule,
    RadioButtonModule,
    ArticleParserMetaGalleriaComponent,
    ArticleParserMetaImagesDeleteDialogComponent,
  ],
  templateUrl: './article-parser-meta.html',
  styleUrl: './article-parser-meta.scss',
})
export class ArticleParserMetaComponent implements OnChanges {
  @Input({ required: true }) article!: ExtractResponse;

  isEditingMetaBlock = false;

  galleriaItems: ArticleMetaGalleriaItem[] = [];

  mainImagePickDialogVisible = false;

  mainPickRows: ArticleMetaMainPickRow[] = [];

  /** URL выбранного снимка для назначения main_image (один на группу). */
  mainPickerSelectedUrl: string | null = null;

  mainImagePickLoading = false;

  constructor(
    private api: ArticleParserApi,
    private state: ArticleParserState,
    private cdr: ChangeDetectorRef,
    private appRef: ApplicationRef,
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

  get canPersistMainImageChanges(): boolean {
    return !!this.article?.document_id?.trim();
  }

  get mainPickApplyDisabled(): boolean {
    const url = (this.mainPickerSelectedUrl || '').trim();
    if (!url || !this.canPersistMainImageChanges || this.mainImagePickLoading) {
      return true;
    }
    const cur = (this.article?.main_image || '').trim();
    return url === cur;
  }

  openMainImagePickDialog(): void {
    const mainUrl = (this.article.main_image || '').trim();
    this.mainPickRows = this.galleriaItems.map((it, idx) => ({
      url: it.itemImageSrc,
      title: (it.title || '').trim(),
      alt: (it.alt || '').trim(),
      isMain: idx === 0 && !!mainUrl && it.itemImageSrc === mainUrl,
    }));
    const urls = this.mainPickRows.map((r) => r.url);
    const curMain = (this.article.main_image || '').trim();
    this.mainPickerSelectedUrl =
      curMain && urls.includes(curMain) ? curMain : (this.mainPickRows[0]?.url ?? null);
    this.mainImagePickDialogVisible = true;
  }

  closeMainImagePickDialog(): void {
    this.mainImagePickDialogVisible = false;
    this.onMainImagePickDialogHide();
  }

  onMainImagePickDialogHide(): void {
    this.mainPickRows = [];
    this.mainPickerSelectedUrl = null;
    this.mainImagePickLoading = false;
  }

  applyMainImagePick(): void {
    const docId = this.article?.document_id?.trim();
    if (!docId) {
      this.state.error = 'Нельзя сохранить главное изображение: документ ещё не сохранён на сервере';
      this.cdr.detectChanges();
      return;
    }
    const url = (this.mainPickerSelectedUrl || '').trim();
    if (!url) {
      return;
    }

    this.state.error = '';
    this.mainImagePickLoading = true;
    this.cdr.detectChanges();

    this.api.updateDocumentMetadata(docId, { main_image: url }).subscribe({
      next: () => {
        const art = this.state.article;
        if (art) {
          this.state.article = { ...art, main_image: url };
        }
        this.mainImagePickLoading = false;
        this.mainImagePickDialogVisible = false;
        this.mainPickRows = [];
        this.mainPickerSelectedUrl = null;
        this.appRef.tick();
      },
      error: () => {
        this.mainImagePickLoading = false;
        this.state.error = 'Не удалось назначить главное изображение';
        this.cdr.detectChanges();
      },
    });
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
