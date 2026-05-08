import {
  ChangeDetectorRef,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  Output,
  SimpleChanges,
  ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';
import { ChipModule } from 'primeng/chip';
import { SkeletonModule } from 'primeng/skeleton';
import {
  ArticleParserApi,
  DocumentCategoryCatalogRef,
  DocumentCategoryRef,
  ExtractResponse,
} from '../../api/article-parser-api';
import { ArticleParserState } from '../../model/article-parser-state';
import {
  ButtonVariant,
  OutlineButtonComponent,
} from '../../../../shared/ui/outline-button/outline-button.component';
import { scrollToElement } from '../../lib/scroll-to-element';
import { KnobModule } from 'primeng/knob';
import { TreeSelectModule } from 'primeng/treeselect';
import { TreeNode } from 'primeng/api';

@Component({
  selector: 'app-article-parser-categories',
  standalone: true,
  imports: [
    FormsModule,
    ChipModule,
    SkeletonModule,
    OutlineButtonComponent,
    KnobModule,
    TreeSelectModule,
  ],
  templateUrl: './article-parser-categories.html',
  styleUrl: './article-parser-categories.scss',
})
export class ArticleParserCategoriesComponent implements OnChanges, OnDestroy {
  @Input({ required: true }) article!: ExtractResponse;
  @Input({ required: true }) buttonsDisabled!: boolean;
  @Output() categorizationLoadingChange = new EventEmitter<boolean>();

  @ViewChild('categoriesBlock') categoriesBlock?: ElementRef;

  readonly ButtonVariant = ButtonVariant;

  categoriesError = '';
  loadingCategories = false;
  loadingDocumentCategoriesMutation = false;

  categoryPickerOpen = false;
  categoryPickerSearch = '';
  categoryPickerCatalogItems: DocumentCategoryCatalogRef[] = [];
  loadingCategoryPickerCatalog = false;

  isEditingCategoriesBlock = false;

  categoryTreeNodes: TreeNode<DocumentCategoryCatalogRef>[] = [];
  selectedCategoryNodes: TreeNode<DocumentCategoryCatalogRef>[] = [];

  constructor(
    private api: ArticleParserApi,
    public state: ArticleParserState,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['article']) {
      this.isEditingCategoriesBlock = false;
      this.categoriesError = '';
      this.closeCategoryPicker();
      this.categorizationLoadingChange.emit(false);
      this.syncSelectedNodesFromAssignedCategories();
    }
  }

  ngOnDestroy(): void {
    this.categorizationLoadingChange.emit(false);
  }

  requestCategorize(): void {
    if (!this.article?.document_id) return;

    this.loadingCategories = true;
    this.categorizationLoadingChange.emit(true);
    this.categoriesError = '';
    this.state.categories = null;

    this.api.categorizeDocument(this.article.document_id).subscribe({
      next: (response) => {
        this.state.categories = response.categories || [];
        this.loadingCategories = false;
        this.categorizationLoadingChange.emit(false);
        scrollToElement(() => this.categoriesBlock, this.cdr);
      },
      error: () => {
        this.categoriesError = 'Ошибка при классификации категорий';
        this.loadingCategories = false;
        this.categorizationLoadingChange.emit(false);
      },
    });
  }

  toggleBlockEdit(): void {
    this.isEditingCategoriesBlock = !this.isEditingCategoriesBlock;

    if (this.isEditingCategoriesBlock) {
      this.loadCategoryCatalog();
      return;
    }

    this.closeCategoryPicker();
  }

  get hasEmptyCategoriesResult(): boolean {
    return (
      !!this.article &&
      this.state.categories !== null &&
      !this.loadingCategories &&
      (this.state.categories?.length ?? 0) === 0
    );
  }

  get rankedCategories(): DocumentCategoryRef[] {
    const list = this.state.categories || [];
    return [...list].sort((a, b) => {
      const ac = typeof a.confidence === 'number' && !Number.isNaN(a.confidence) ? a.confidence : 0;
      const bc = typeof b.confidence === 'number' && !Number.isNaN(b.confidence) ? b.confidence : 0;
      if (bc !== ac) return bc - ac;
      return (a.name_ru || a.name || a.code).localeCompare(b.name_ru || b.name || b.code);
    });
  }

  categoryChipLabel(cat: DocumentCategoryRef): string {
    const title = (cat.name_ru || cat.name || cat.code).trim();
    const confPct =
      typeof cat.confidence === 'number' && !Number.isNaN(cat.confidence)
        ? `${Math.round(cat.confidence * 100)}%`
        : '—';
    return `${title} (${confPct})`;
  }

  loadCategoryCatalog(): void {
    if (!this.isEditingCategoriesBlock || !this.article?.document_id) {
      return;
    }

    if (this.categoryTreeNodes.length || this.loadingCategoryPickerCatalog) {
      return;
    }

    this.loadingCategoryPickerCatalog = true;
    this.categoriesError = '';

    this.api.getCategoryCatalog(this.article.document_id).subscribe({
      next: (items: DocumentCategoryCatalogRef[]) => {
        this.categoryPickerCatalogItems = items;
        this.categoryTreeNodes = [...this.mapCategoriesToTreeNodes(items)];
        this.syncSelectedNodesFromAssignedCategories();
        this.loadingCategoryPickerCatalog = false;

        this.cdr.detectChanges();
      },
      error: () => {
        this.categoriesError = 'Не удалось загрузить каталог категорий';
        this.loadingCategoryPickerCatalog = false;

        this.cdr.detectChanges();
      },
    });
  }

  private mapCategoriesToTreeNodes(
    items: DocumentCategoryCatalogRef[],
  ): TreeNode<DocumentCategoryCatalogRef>[] {
    const byId = new Map<string, TreeNode<DocumentCategoryCatalogRef>>();
    const roots: TreeNode<DocumentCategoryCatalogRef>[] = [];

    for (const item of items) {
      const categoryId = String(item.category_id);
      byId.set(categoryId, {
        key: categoryId,
        label: item.name_ru || item.name || item.code,
        data: item,
        children: [],
      });
    }

    for (const item of items) {
      const node = byId.get(String(item.category_id));
      if (!node) {
        continue;
      }

      const parentId = item.parent_id ? String(item.parent_id) : '';
      if (parentId && byId.has(parentId)) {
        byId.get(parentId)!.children!.push(node);
      } else {
        roots.push(node);
      }
    }

    const sortTree = (nodes: TreeNode<DocumentCategoryCatalogRef>[]): void => {
      nodes.sort((a, b) => String(a.label || '').localeCompare(String(b.label || '')));
      for (const node of nodes) {
        if (node.children?.length) {
          sortTree(node.children);
        }
        node.leaf = !node.children?.length;
      }
    };

    sortTree(roots);
    return roots;
  }

  onCategoryTreeSelectChange(
    value: TreeNode<DocumentCategoryCatalogRef>[] | null,
  ): void {
    this.selectedCategoryNodes = value ?? [];
  }

  onCategoryTreeHide(): void {
    const docId = this.article?.document_id;
    if (!docId || this.loadingDocumentCategoriesMutation) {
      return;
    }

    const selectedIds = new Set(
      (this.selectedCategoryNodes || [])
        .map((node) => String(node?.key || node?.data?.category_id || ''))
        .filter(Boolean),
    );
    const existingIds = new Set((this.state.categories || []).map((cat) => String(cat.category_id)));

    const idsToAdd = [...selectedIds].filter((id) => !existingIds.has(id));
    if (!idsToAdd.length) {
      return;
    }

    this.loadingDocumentCategoriesMutation = true;
    this.categoriesError = '';

    forkJoin(idsToAdd.map((id) => this.api.assignDocumentCategory(docId, id))).subscribe({
      next: () => {
        this.refreshDocumentCategoriesFromServer(docId, true);
      },
      error: () => {
        this.categoriesError = 'Не удалось добавить категории';
        this.loadingDocumentCategoriesMutation = false;
      },
    });
  }

  get filteredCategoryPickerItems(): DocumentCategoryCatalogRef[] {
    const q = this.categoryPickerSearch.trim().toLowerCase();
    if (!q) {
      return this.categoryPickerCatalogItems;
    }
    return this.categoryPickerCatalogItems.filter((item) =>
      (item.name_ru || item.name || item.code).toLowerCase().includes(q),
    );
  }

  onCategoryPickerSelect(item: DocumentCategoryCatalogRef): void {
    const docId = this.article?.document_id;
    if (!docId || this.loadingDocumentCategoriesMutation) {
      return;
    }

    this.loadingDocumentCategoriesMutation = true;
    this.categoriesError = '';

    this.api.assignDocumentCategory(docId, item.category_id).subscribe({
      next: () => {
        this.selectedCategoryNodes = [];
        this.refreshDocumentCategoriesFromServer(docId);
      },
      error: () => {
        this.categoriesError = 'Не удалось добавить категорию';
        this.loadingDocumentCategoriesMutation = false;
      },
    });
  }

  private refreshDocumentCategoriesFromServer(documentId: string, resetTreeSelect = false): void {
    this.api.getDocumentCategories(documentId).subscribe({
      next: (res) => {
        this.state.categories = res.categories || [];
        if (resetTreeSelect) {
          this.selectedCategoryNodes = [];
        } else {
          this.syncSelectedNodesFromAssignedCategories();
        }
        this.loadingDocumentCategoriesMutation = false;
      },
      error: () => {
        this.categoriesError = 'Не удалось обновить список категорий';
        this.loadingDocumentCategoriesMutation = false;
      },
    });
  }

  removeCategoryChip(cat: DocumentCategoryRef): void {
    const docId = this.article?.document_id;
    if (!docId || this.loadingDocumentCategoriesMutation) {
      return;
    }

    this.loadingDocumentCategoriesMutation = true;
    this.categoriesError = '';

    this.api.removeDocumentCategory(docId, cat.category_id).subscribe({
      next: () => {
        this.refreshDocumentCategoriesFromServer(docId);
      },
      error: () => {
        this.categoriesError = 'Не удалось удалить категорию';
        this.loadingDocumentCategoriesMutation = false;
      },
    });
  }

  private closeCategoryPicker(): void {
    this.categoryPickerOpen = false;
    this.categoryPickerSearch = '';
    this.categoryPickerCatalogItems = [];
    this.categoryTreeNodes = [];
    this.selectedCategoryNodes = [];
    this.loadingCategoryPickerCatalog = false;
  }

  private syncSelectedNodesFromAssignedCategories(): void {
    const selectedIds = new Set((this.state.categories || []).map((cat) => String(cat.category_id)));
    this.selectedCategoryNodes = this.categoryTreeNodes.filter((node) =>
      selectedIds.has(String(node.key || node.data?.category_id)),
    );
  }

  categoryKnobValue(cat: DocumentCategoryRef): number {
    if (typeof cat.confidence !== 'number' || Number.isNaN(cat.confidence)) {
      return 0;
    }

    return Math.round(cat.confidence * 100);
  }

  categoryKnobColor(cat: DocumentCategoryRef): string {
    const value = this.categoryKnobValue(cat);
    if (value <= 30) {
      return '#ef4444';
    }
    if (value <= 60) {
      return '#f97316';
    }
    if (value <= 90) {
      return '#eab308';
    }
    return '#22c55e';
  }

  valueTemplate = (v: number): string => `${v}%`;
}
