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
import { ChipModule } from 'primeng/chip';
import { SkeletonModule } from 'primeng/skeleton';
import {
  ArticleParserApi,
  DocumentCategoryRef,
  DocumentEntityRef,
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
  categoryPickerCatalogItems: DocumentEntityRef[] = [];
  loadingCategoryPickerCatalog = false;

  isEditingCategoriesBlock = false;

  categoryTreeNodes: TreeNode<DocumentEntityRef>[] = [];
  selectedCategoryNodes: Record<string, boolean> = {};

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
    if (!this.isEditingCategoriesBlock) {
      this.closeCategoryPicker();
    }
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
      next: (items: DocumentEntityRef[]) => {
        this.categoryPickerCatalogItems = items;
        this.categoryTreeNodes = [...this.mapCategoriesToTreeNodes(items)];
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

  private mapCategoriesToTreeNodes(items: DocumentEntityRef[]): TreeNode<DocumentEntityRef>[] {
    return items.map((item) => ({
      key: String(item.id),
      label: item.name,
      data: item,
      leaf: true,
    }));
  }

  onCategoryTreeSelectChange(value: Record<string, boolean>): void {
    const selectedId = Object.keys(value || {}).find((key) => value[key]);

    if (!selectedId) {
      return;
    }

    const selectedItem = this.categoryPickerCatalogItems.find(
      (item) => String(item.id) === selectedId,
    );

    if (!selectedItem) {
      return;
    }

    this.onCategoryPickerSelect(selectedItem);
    this.selectedCategoryNodes = {};
  }

  get filteredCategoryPickerItems(): DocumentEntityRef[] {
    const q = this.categoryPickerSearch.trim().toLowerCase();
    if (!q) {
      return this.categoryPickerCatalogItems;
    }
    return this.categoryPickerCatalogItems.filter((item) => item.name.toLowerCase().includes(q));
  }

  onCategoryPickerSelect(item: DocumentEntityRef): void {
    const docId = this.article?.document_id;
    if (!docId || this.loadingDocumentCategoriesMutation) {
      return;
    }

    this.loadingDocumentCategoriesMutation = true;
    this.categoriesError = '';

    this.api.assignDocumentCategory(docId, item.id).subscribe({
      next: () => {
        this.selectedCategoryNodes = {};
        this.refreshDocumentCategoriesFromServer(docId);
      },
      error: () => {
        this.categoriesError = 'Не удалось добавить категорию';
        this.loadingDocumentCategoriesMutation = false;
      },
    });
  }

  private refreshDocumentCategoriesFromServer(documentId: string): void {
    this.api.getDocumentCategories(documentId).subscribe({
      next: (res) => {
        this.state.categories = res.categories || [];
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
    this.selectedCategoryNodes = {};
    this.loadingCategoryPickerCatalog = false;
  }

  categoryKnobValue(cat: DocumentCategoryRef): number {
    if (typeof cat.confidence !== 'number' || Number.isNaN(cat.confidence)) {
      return 0;
    }

    return Math.round(cat.confidence * 100);
  }

  valueTemplate = (v: number): string => `${v}%`;
}
