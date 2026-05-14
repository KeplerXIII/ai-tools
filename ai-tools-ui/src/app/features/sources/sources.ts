import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { SelectModule } from 'primeng/select';
import { OutlineButtonComponent } from '../../shared/ui/outline-button/outline-button.component';
import { SourceListItem, SourcesApi } from './api/sources-api';
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
  templateUrl: './sources.html',
  styleUrl: './sources.scss',
})
export class Sources implements OnInit {
  items: SourceListItem[] = [];
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

  constructor(private readonly sourcesApi: SourcesApi) {}

  ngOnInit(): void {
    this.loadSources();
  }

  loadSources(options?: { silent?: boolean }): void {
    const silent = options?.silent ?? false;
    if (!silent) {
      this.listLoading = true;
    }
    this.listError = '';
    this.sourcesApi.listSources().subscribe({
      next: (response) => {
        this.items = response.items;
        this.canFilterByAllUsers = response.can_filter_by_all_users;
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
    for (const item of this.items) {
      if (!map.has(item.added_by_user_id)) {
        map.set(item.added_by_user_id, item.added_by_username);
      }
    }
    return [...map.entries()]
      .map(([userId, label]) => ({ userId, label }))
      .sort((a, b) => a.label.localeCompare(b.label, 'ru'));
  }

  get filteredAndSortedItems(): SourceListItem[] {
    let list = this.items;
    if (this.selectedUserId) {
      list = list.filter((s) => s.added_by_user_id === this.selectedUserId);
    }
    const out = [...list];
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

  onFiltersChanged(): void {
    /* сортировка и фильтр вычисляются в геттере */
  }

  resetFilters(): void {
    this.selectedUserId = '';
    this.sortMode = 'created_desc';
  }
}
