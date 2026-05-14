import { CommonModule } from '@angular/common';
import { Component, DestroyRef, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { Translate } from '../translate/translate';

export type ToolsTab = 'translate' | 'translation_analysis' | 'orthopunct';

@Component({
  selector: 'app-tools',
  standalone: true,
  imports: [CommonModule, Translate],
  templateUrl: './tools.html',
  styleUrl: './tools.scss',
})
export class Tools implements OnInit {
  activeTab: ToolsTab = 'translate';

  constructor(
    private readonly route: ActivatedRoute,
    private readonly router: Router,
    private readonly destroyRef: DestroyRef,
  ) {}

  ngOnInit(): void {
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((q) => {
      const tool = q.get('tool')?.trim().toLowerCase() ?? '';
      if (tool === 'translation_analysis' || tool === 'analysis') {
        this.activeTab = 'translation_analysis';
        return;
      }
      if (tool === 'orthopunct') {
        this.activeTab = 'orthopunct';
        return;
      }
      this.activeTab = 'translate';
    });
  }

  setTab(tab: ToolsTab): void {
    const tool =
      tab === 'translate'
        ? null
        : tab === 'translation_analysis'
          ? 'translation_analysis'
          : 'orthopunct';
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { tool },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }
}
