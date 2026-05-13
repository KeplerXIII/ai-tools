import { NgTemplateOutlet } from '@angular/common';
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
  imports: [GalleriaModule, NgTemplateOutlet],
  templateUrl: './article-parser-meta-galleria.html',
  styleUrl: './article-parser-meta-galleria.scss',
})
export class ArticleParserMetaGalleriaComponent implements OnChanges {
  @Input({ required: true }) items: ArticleMetaGalleriaItem[] = [];

  /** Синхронизация с p-galleria: иначе кастомный item-шаблон иногда не обновляет большой кадр при смене слайда. */
  galleriaActiveIndex = 0;

  /** Полноэкранный просмотр (второй p-galleria с [fullScreen]="true"). */
  lightboxVisible = false;

  readonly containerStyle: Record<string, string> = { maxWidth: '640px' };

  readonly lightboxContainerStyle: Record<string, string> = {
    width: 'min(96vw, 1400px)',
    maxWidth: '96vw',
  };

  readonly responsiveOptions: GalleriaResponsiveOptions[] = [
    { breakpoint: '991px', numVisible: 4 },
    { breakpoint: '767px', numVisible: 3 },
    { breakpoint: '575px', numVisible: 1 },
  ];

  readonly responsiveLightboxOptions: GalleriaResponsiveOptions[] = [
    { breakpoint: '1200px', numVisible: 6 },
    { breakpoint: '991px', numVisible: 5 },
    { breakpoint: '767px', numVisible: 4 },
    { breakpoint: '575px', numVisible: 3 },
  ];

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['items']) {
      this.galleriaActiveIndex = 0;
      this.lightboxVisible = false;
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

  onItemImageError(event: Event): void {
    console.warn('Ошибка загрузки изображения в галерее', event);
  }

  openLightbox(_event?: Event): void {
    if (this.lightboxVisible || !(this.items?.length)) {
      return;
    }
    this.lightboxVisible = true;
  }

  openLightboxFromThumbnail(item: ArticleMetaGalleriaItem, event: Event): void {
    const list = this.items ?? [];
    if (!list.length) {
      return;
    }
    const i = list.findIndex((x) => x.itemImageSrc === item.itemImageSrc || x === item);
    if (i >= 0) {
      this.galleriaActiveIndex = i;
    }
    event.stopPropagation();
    this.lightboxVisible = true;
  }
}
