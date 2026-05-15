import { CommonModule } from '@angular/common';
import { Component, DestroyRef, inject, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { SelectModule } from 'primeng/select';
import { OutlineButtonComponent } from '../../shared/ui/outline-button/outline-button.component';
import { SourceListItem, SourcesApi } from './api/sources-api';
import { SourceParseRunService } from './services/source-parse-run.service';
import { SourcesCreateSectionComponent } from './ui/sources-create-section/sources-create-section.component';
import { SourcesListAccordionComponent } from './ui/sources-list-accordion/sources-list-accordion.component';

type SortMode = 'created_desc' | 'created_asc' | 'user_asc';

@Component({
  selector: 'app-sources',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    SelectModule,
    OutlineButtonComponent,
    SourcesCreateSectionComponent,
    SourcesListAccordionComponent,
  ],
  providers: [SourceParseRunService],
  templateUrl: './sources.html',
  styleUrl: './sources.scss',
})
export class Sources implements OnInit {
  items: SourceListItem[] = [];
  /** Полный список для выпадающего фильтра по пользователю (без серверного фильтра). */
  contributorItems: SourceListItem[] = [];
  canFilterByAllUsers = false;
  listLoading = false;
  listError = '';

  selectedUserId = '';
  sortMode: SortMode = 'created_desc';
  sortSelectOptions: { label: string; value: SortMode }[] = [
    { label: 'По дате добавления (сначала новые)', value: 'created_desc' },
    { label: 'По дате добавления (сначала старые)', value: 'created_asc' },
    { label: 'По пользователю (А–Я)', value: 'user_asc' },
  ];

  private readonly sourcesApi = inject(SourcesApi);
  private readonly destroyRef = inject(DestroyRef);
  private readonly parseRun = inject(SourceParseRunService);

  ngOnInit(): void {
    this.parseRun.sourcesReloadRequested$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((options) => this.loadSources(options));
    this.loadSources();
  }

  loadSources(options?: { silent?: boolean }): void {
    const silent = options?.silent ?? false;
    const addedByUserId = this.selectedUserId || undefined;
    if (!silent) {
      this.listLoading = true;
    }
    this.listError = '';
    this.sourcesApi
      .listSources(addedByUserId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (response) => {
          this.items = response.items;
          this.canFilterByAllUsers = response.can_filter_by_all_users;
          if (!addedByUserId || !this.canFilterByAllUsers) {
            this.contributorItems = response.items;
          }
          this.listLoading = false;
        },
        error: () => {
          this.listError = 'Не удалось загрузить список источников';
          this.listLoading = false;
        },
      });
  }

  get userFilterSelectOptions(): { label: string; value: string }[] {
    return [
      { label: 'Все', value: '' },
      ...this.contributorOptions.map((o) => ({ label: o.label, value: o.userId })),
    ];
  }

  get contributorOptions(): { userId: string; label: string }[] {
    const map = new Map<string, string>();
    const source = this.canFilterByAllUsers ? this.contributorItems : this.items;
    for (const item of source) {
      if (!map.has(item.added_by_user_id)) {
        map.set(item.added_by_user_id, item.added_by_username);
      }
    }
    return [...map.entries()]
      .map(([userId, label]) => ({ userId, label }))
      .sort((a, b) => a.label.localeCompare(b.label, 'ru'));
  }

  get sortedItems(): SourceListItem[] {
    const out = [...this.items];
    if (this.sortMode === 'created_desc') {
      out.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
    } else if (this.sortMode === 'created_asc') {
      out.sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
    } else {
      out.sort(
        (a, b) =>
          a.added_by_username.localeCompare(b.added_by_username, 'ru') ||
          Date.parse(b.created_at) - Date.parse(a.created_at),
      );
    }
    return out;
  }

  get listEmpty(): boolean {
    return !this.listLoading && !this.listError && this.sortedItems.length === 0;
  }

  onUserFilterChange(): void {
    this.loadSources();
  }

  resetFilters(): void {
    this.selectedUserId = '';
    this.sortMode = 'created_desc';
    this.loadSources();
  }
}
