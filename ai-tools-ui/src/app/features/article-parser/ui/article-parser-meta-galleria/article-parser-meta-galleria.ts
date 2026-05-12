import { Component, Input, OnChanges, SimpleChanges } from '@angular/core';
import { GalleriaModule } from 'primeng/galleria';
import type { GalleriaResponsiveOptions } from 'primeng/types/galleria';

/** Слайды для p-galleria (формат как в демо PrimeNG). */
export interface ArticleMetaGalleriaItem {
  itemImageSrc: string;
  thumbnailImageSrc: string;
  title: string;
  alt: string;
}

@Component({
  selector: 'app-article-parser-meta-galleria',
  standalone: true,
  imports: [GalleriaModule],
  templateUrl: './article-parser-meta-galleria.html',
  styleUrl: './article-parser-meta-galleria.scss',
})
export class ArticleParserMetaGalleriaComponent implements OnChanges {
  @Input({ required: true }) items: ArticleMetaGalleriaItem[] = [];

  /** Синхронизация с p-galleria: иначе кастомный item-шаблон иногда не обновляет большой кадр при смене слайда. */
  galleriaActiveIndex = 0;

  readonly containerStyle: Record<string, string> = { maxWidth: '640px' };

  readonly responsiveOptions: GalleriaResponsiveOptions[] = [
    { breakpoint: '991px', numVisible: 4 },
    { breakpoint: '767px', numVisible: 3 },
    { breakpoint: '575px', numVisible: 1 },
  ];

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['items']) {
      this.galleriaActiveIndex = 0;
    }
  }

  get activeSlide(): ArticleMetaGalleriaItem | null {
    const list = this.items;
    if (!list?.length) {
      return null;
    }
    const i = Math.max(0, Math.min(this.galleriaActiveIndex, list.length - 1));
    return list[i] ?? null;
  }

  /** Есть ли у слайда текст для подписи (не пустой и не только пробелы). */
  slideHasCaption(item: ArticleMetaGalleriaItem): boolean {
    return (item.title || '').trim().length > 0 || (item.alt || '').trim().length > 0;
  }

  /** Подключаем pTemplate caption только если есть что показывать — иначе блок caption не создаётся. */
  get hasAnyCaptionContent(): boolean {
    return (this.items ?? []).some((item) => this.slideHasCaption(item));
  }

  /**
   * PrimeNG всё равно рисует пустой `.p-galleria-caption`, если caption-шаблон есть, но у активного
   * слайда нет title/alt — скрываем полосу через класс на корне (см. SCSS).
   */
  get showCaptionForActiveSlide(): boolean {
    const s = this.activeSlide;
    return !!s && this.slideHasCaption(s);
  }

  onItemImageError(event: Event): void {
    console.warn('Ошибка загрузки изображения в галерее', event);
  }
}
