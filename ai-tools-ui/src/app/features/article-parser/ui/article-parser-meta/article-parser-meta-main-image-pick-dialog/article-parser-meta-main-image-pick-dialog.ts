import { ApplicationRef, ChangeDetectorRef, Component, Input } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DialogModule } from 'primeng/dialog';
import { RadioButtonModule } from 'primeng/radiobutton';
import { ArticleParserApi, ExtractResponse } from '../../../api/article-parser-api';
import { ArticleParserState } from '../../../model/article-parser-state';
import { ArticleMetaGalleriaItem } from '../../article-parser-meta-galleria/article-parser-meta-galleria';

interface ArticleMetaMainPickRow {
  url: string;
  title: string;
  alt: string;
  isMain: boolean;
}

@Component({
  selector: 'app-article-parser-meta-main-image-pick-dialog',
  standalone: true,
  imports: [FormsModule, DialogModule, RadioButtonModule],
  templateUrl: './article-parser-meta-main-image-pick-dialog.html',
  styleUrl: './article-parser-meta-main-image-pick-dialog.scss',
})
export class ArticleParserMetaMainImagePickDialogComponent {
  @Input({ required: true }) article!: ExtractResponse;

  @Input({ required: true }) galleriaItems: ArticleMetaGalleriaItem[] = [];

  dialogVisible = false;

  rows: ArticleMetaMainPickRow[] = [];

  selectedUrl: string | null = null;

  saveLoading = false;

  constructor(
    private api: ArticleParserApi,
    private state: ArticleParserState,
    private cdr: ChangeDetectorRef,
    private appRef: ApplicationRef,
  ) {}

  open(): void {
    const mainUrl = (this.article.main_image || '').trim();
    this.rows = this.galleriaItems.map((it, idx) => ({
      url: it.itemImageSrc,
      title: (it.title || '').trim(),
      alt: (it.alt || '').trim(),
      isMain: idx === 0 && !!mainUrl && it.itemImageSrc === mainUrl,
    }));
    const urls = this.rows.map((r) => r.url);
    const curMain = (this.article.main_image || '').trim();
    this.selectedUrl =
      curMain && urls.includes(curMain) ? curMain : (this.rows[0]?.url ?? null);
    this.dialogVisible = true;
  }

  get canPersist(): boolean {
    return !!this.article?.document_id?.trim();
  }

  get applyDisabled(): boolean {
    const url = (this.selectedUrl || '').trim();
    if (!url || !this.canPersist || this.saveLoading) {
      return true;
    }
    const cur = (this.article?.main_image || '').trim();
    return url === cur;
  }

  close(): void {
    this.dialogVisible = false;
    this.onDialogHide();
  }

  onDialogHide(): void {
    this.rows = [];
    this.selectedUrl = null;
    this.saveLoading = false;
  }

  apply(): void {
    const docId = this.article?.document_id?.trim();
    if (!docId) {
      this.state.error = 'Нельзя сохранить главное изображение: документ ещё не сохранён на сервере';
      this.cdr.detectChanges();
      return;
    }
    const url = (this.selectedUrl || '').trim();
    if (!url) {
      return;
    }

    this.state.error = '';
    this.saveLoading = true;
    this.cdr.detectChanges();

    this.api.updateDocumentMetadata(docId, { main_image: url }).subscribe({
      next: () => {
        const art = this.state.article;
        if (art) {
          this.state.article = { ...art, main_image: url };
        }
        this.saveLoading = false;
        this.dialogVisible = false;
        this.rows = [];
        this.selectedUrl = null;
        this.appRef.tick();
      },
      error: () => {
        this.saveLoading = false;
        this.state.error = 'Не удалось назначить главное изображение';
        this.cdr.detectChanges();
      },
    });
  }
}
