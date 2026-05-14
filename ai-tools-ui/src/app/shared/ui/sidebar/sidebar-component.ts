import { ChangeDetectorRef, Component } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive } from '@angular/router';
import { filter } from 'rxjs/operators';

@Component({
  selector: 'app-sidebar-component',
  standalone: true,
  imports: [RouterLink, RouterLinkActive],
  templateUrl: './sidebar-component.html',
  styleUrl: './sidebar-component.scss',
})
export class SidebarComponent {
  isExpanded = false;

  constructor(
    private readonly router: Router,
    private readonly cdr: ChangeDetectorRef,
  ) {
    this.router.events.pipe(filter((e) => e instanceof NavigationEnd)).subscribe(() => {
      this.cdr.markForCheck();
    });
  }

  toggle() {
    this.isExpanded = !this.isExpanded;
  }

  /** Подсветка «Документ» и для старого пути `/article-parser` (закладки). */
  documentSectionActive(): boolean {
    const path = this.router.url.split('?')[0] ?? '';
    return path === '/document' || path === '/article-parser';
  }

  /** Раздел «Инструменты» и закладка `/translate`. */
  toolsSectionActive(): boolean {
    const path = this.router.url.split('?')[0] ?? '';
    return path === '/tools' || path === '/translate';
  }
}
