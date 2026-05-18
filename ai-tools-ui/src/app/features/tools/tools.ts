import { CommonModule } from '@angular/common';
import { Component, DestroyRef, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { Translate } from '../translate/translate';
import { Workbook } from '../workbook/workbook';

export type ToolsTab = 'workbook' | 'translate' | 'translation_analysis' | 'orthopunct';

const TOOL_QUERY_PARAM: Record<ToolsTab, string | null> = {
  workbook: null,
  translate: 'translate',
  translation_analysis: 'translation_analysis',
  orthopunct: 'orthopunct',
};

@Component({
  selector: 'app-tools',
  standalone: true,
  imports: [CommonModule, Translate, Workbook],
  templateUrl: './tools.html',
  styleUrl: './tools.scss',
})
export class Tools implements OnInit {
  activeTab: ToolsTab = 'workbook';

  constructor(
    private readonly route: ActivatedRoute,
    private readonly router: Router,
    private readonly destroyRef: DestroyRef,
  ) {}

  ngOnInit(): void {
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((q) => {
      const tool = q.get('tool')?.trim().toLowerCase() ?? '';
      if (tool === 'workbook' || tool === 'notebook') {
        this.activeTab = 'workbook';
        return;
      }
      if (tool === 'translate' || tool === 'translation') {
        this.activeTab = 'translate';
        return;
      }
      if (tool === 'translation_analysis' || tool === 'analysis') {
        this.activeTab = 'translation_analysis';
        return;
      }
      if (tool === 'orthopunct') {
        this.activeTab = 'orthopunct';
        return;
      }
      const path = this.router.url.split('?')[0] ?? '';
      this.activeTab = path === '/translate' ? 'translate' : 'workbook';
    });
  }

  setTab(tab: ToolsTab): void {
    const tool = TOOL_QUERY_PARAM[tab];
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { tool },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }
}
