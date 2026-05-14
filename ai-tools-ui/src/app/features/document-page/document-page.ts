import { CommonModule } from '@angular/common';
import { Component, DestroyRef, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { ArticleParser } from '../article-parser/article-parser';

export type DocumentCreationMode = 'material' | 'url' | 'template';

@Component({
  selector: 'app-document-page',
  standalone: true,
  imports: [CommonModule, ArticleParser],
  templateUrl: './document-page.html',
  styleUrl: './document-page.scss',
})
export class DocumentPage implements OnInit {
  creationMode: DocumentCreationMode = 'url';

  constructor(
    private readonly route: ActivatedRoute,
    private readonly router: Router,
    private readonly destroyRef: DestroyRef,
  ) {}

  ngOnInit(): void {
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((q) => {
      const id = q.get('id')?.trim() ?? '';
      const mode = q.get('mode')?.trim().toLowerCase() ?? '';

      if (mode === 'template') {
        this.creationMode = 'template';
        return;
      }
      if (mode === 'url') {
        this.creationMode = 'url';
        return;
      }
      if (mode === 'material' || id) {
        this.creationMode = 'material';
        return;
      }
      this.creationMode = 'url';
    });
  }

  setMode(mode: DocumentCreationMode): void {
    const currentId = this.route.snapshot.queryParamMap.get('id')?.trim() ?? '';

    if (mode === 'template') {
      void this.router.navigate([], {
        relativeTo: this.route,
        queryParams: { id: null, url: null, autoload: null, mode: 'template' },
        queryParamsHandling: 'merge',
        replaceUrl: true,
      });
      return;
    }

    if (mode === 'url') {
      void this.router.navigate([], {
        relativeTo: this.route,
        queryParams: { id: null, url: null, autoload: null, mode: 'url' },
        queryParamsHandling: 'merge',
        replaceUrl: true,
      });
      return;
    }

    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {
        mode: 'material',
        url: null,
        autoload: null,
        ...(currentId ? { id: currentId } : { id: null }),
      },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }
}
