import { ApplicationRef, ChangeDetectorRef, Component, HostListener, Input } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { ArticleParserApi, ExtractResponse, ImageInfo } from '../../../api/article-parser-api';
import { ArticleParserState } from '../../../model/article-parser-state';
import { ArticleMetaGalleriaItem } from '../../article-parser-meta-galleria/article-parser-meta-galleria';

interface ArticleMetaImageDeleteRow {
  url: string;
  title: string;
  alt: string;
  selected: boolean;
}

@Component({
  selector: 'app-article-parser-meta-images-delete-dialog',
  standalone: true,
  imports: [FormsModule, DialogModule, CheckboxModule],
  templateUrl: './article-parser-meta-images-delete-dialog.html',
  styleUrl: './article-parser-meta-images-delete-dialog.scss',
})
export class ArticleParserMetaImagesDeleteDialogComponent {
  @Input({ required: true }) article!: ExtractResponse;

  @Input({ required: true }) galleriaItems: ArticleMetaGalleriaItem[] = [];

  dialogVisible = false;

  rows: ArticleMetaImageDeleteRow[] = [];

  deleteLoading = false;

  constructor(
    private api: ArticleParserApi,
    private state: ArticleParserState,
    private cdr: ChangeDetectorRef,
    private appRef: ApplicationRef,
  ) {}

  @HostListener('document:keydown', ['$event'])
  onDocumentKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || !this.dialogVisible) {
      return;
    }
    this.close();
  }

  open(): void {
    this.rows = this.galleriaItems.map((it) => ({
      url: it.itemImageSrc,
      title: (it.title || '').trim(),
      alt: (it.alt || '').trim(),
      selected: false,
    }));
    this.dialogVisible = true;
  }

  get hasSelectedForDelete(): boolean {
    return this.rows.some((r) => r.selected);
  }

  get canPersist(): boolean {
    return !!this.article?.document_id?.trim();
  }

  close(): void {
    this.dialogVisible = false;
    this.onDialogHide();
  }

  onDialogHide(): void {
    this.rows = [];
    this.deleteLoading = false;
  }

  deleteSelected(): void {
    const docId = this.article?.document_id?.trim();
    if (!docId) {
      this.state.error = 'Нельзя удалить изображения: документ ещё не сохранён на сервере';
      this.cdr.detectChanges();
      return;
    }

    const selectedUrls = new Set(this.rows.filter((r) => r.selected).map((r) => r.url));
    if (selectedUrls.size === 0) {
      return;
    }

    const mainUrl = (this.article.main_image || '').trim();
    const mainAffected = !!mainUrl && selectedUrls.has(mainUrl);

    const newImages: ImageInfo[] = (this.article.images ?? [])
      .filter((img) => {
        const u = (img.url || '').trim();
        return u && !selectedUrls.has(u);
      })
      .map((img) => ({
        url: img.url!.trim(),
        alt: img.alt ?? null,
        title: img.title ?? null,
      }));

    const payload: { images: ImageInfo[]; main_image?: string | null } = { images: newImages };
    if (mainAffected) {
      payload.main_image = null;
    }

    this.state.error = '';
    this.deleteLoading = true;
    this.cdr.detectChanges();

    this.api.updateDocumentMetadata(docId, payload).subscribe({
      next: () => {
        const art = this.state.article;
        if (art) {
          this.state.article = {
            ...art,
            images: newImages,
            main_image: mainAffected ? null : art.main_image,
          };
        }
        this.deleteLoading = false;
        this.dialogVisible = false;
        this.rows = [];
        this.appRef.tick();
      },
      error: () => {
        this.deleteLoading = false;
        this.state.error = 'Не удалось удалить выбранные изображения';
        this.cdr.detectChanges();
      },
    });
  }
}
