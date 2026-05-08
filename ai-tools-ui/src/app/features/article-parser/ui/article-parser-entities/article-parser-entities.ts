import { Component, EventEmitter, Input, Output, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ChipModule } from 'primeng/chip';
import { SkeletonModule } from 'primeng/skeleton';
import { SelectModule } from 'primeng/select';
import { Select } from 'primeng/select';
import {
  ArticleParserApi,
  DocumentEntityRef,
  DocumentTagRef,
  DocumentTagsResponse,
  EntitiesResponse,
  ExtractResponse,
} from '../../api/article-parser-api';
import { ArticleParserState } from '../../model/article-parser-state';
import {
  ButtonVariant,
  OutlineButtonComponent,
} from '../../../../shared/ui/outline-button/outline-button.component';

type EntitySection = 'military_equipment' | 'manufacturers' | 'contracts';
type TagScope = 'original' | 'translated';

@Component({
  selector: 'app-article-parser-entities',
  standalone: true,
  imports: [FormsModule, ChipModule, SkeletonModule, OutlineButtonComponent, SelectModule],
  templateUrl: './article-parser-entities.html',
  styleUrl: './article-parser-entities.scss',
})
export class ArticleParserEntitiesComponent {
  @Input({ required: true }) article!: ExtractResponse;
  @Input({ required: true }) buttonsDisabled!: boolean;
  @Input() loadingOriginalTags = false;
  @Input() loadingTranslatedTags = false;
  @Output() entitiesLoadingChange = new EventEmitter<boolean>();
  @ViewChild('entityPickerSelect') entityPickerSelect?: Select;

  readonly ButtonVariant = ButtonVariant;

  loadingEntities = false;
  entitiesError = '';

  entityPickerOpen: EntitySection | null = null;
  entityPickerSearch = '';
  entityPickerCatalogItems: DocumentEntityRef[] = [];
  selectedEntityPickerItem: DocumentEntityRef | null = null;
  loadingEntityPickerCatalog = false;
  loadingDocumentEntitiesMutation = false;

  tagPickerOpen: TagScope | null = null;
  tagPickerSearch = '';
  tagPickerCatalogItems: DocumentTagRef[] = [];
  selectedTagPickerItem: DocumentTagRef | null = null;
  loadingTagPickerCatalog = false;
  loadingDocumentTagsMutation = false;

  isEditingEntitiesBlock = false;

  constructor(
    private api: ArticleParserApi,
    public state: ArticleParserState,
  ) {}

  requestEntities(): void {
    if (!this.state.article?.text || !this.state.article.document_id) return;

    this.loadingEntities = true;
    this.entitiesLoadingChange.emit(true);
    this.entitiesError = '';
    this.state.entities = null;

    this.api.extractEntities(this.state.article.document_id).subscribe({
      next: (response) => {
        this.state.entities = {
          military_equipment: response.military_equipment || [],
          manufacturers: response.manufacturers || [],
          contracts: response.contracts || [],
        };
        this.loadingEntities = false;
        this.entitiesLoadingChange.emit(false);
      },
      error: () => {
        this.entitiesError = 'Ошибка при извлечении сущностей';
        this.loadingEntities = false;
        this.entitiesLoadingChange.emit(false);
      },
    });
  }

  toggleBlockEdit(): void {
    this.isEditingEntitiesBlock = !this.isEditingEntitiesBlock;
    if (!this.isEditingEntitiesBlock) {
      this.closeEntityPicker();
      this.closeTagPicker();
    }
  }

  get hasEmptyEntitiesResult(): boolean {
    return (
      !!this.state.entities &&
      !this.loadingEntities &&
      !this.state.entities.military_equipment?.length &&
      !this.state.entities.manufacturers?.length &&
      !this.state.entities.contracts?.length
    );
  }

  entityTypeCodeForSection(section: EntitySection): string {
    if (section === 'manufacturers') {
      return 'manufacturer';
    }
    if (section === 'contracts') {
      return 'contract';
    }
    return 'military_equipment';
  }

  toggleEntityPicker(section: EntitySection): void {
    if (!this.isEditingEntitiesBlock || !this.state.article?.document_id) {
      return;
    }

    if (this.entityPickerOpen === section) {
      this.closeEntityPicker();
      return;
    }

    this.entityPickerOpen = section;
    this.entityPickerSearch = '';
    this.entityPickerCatalogItems = [];
    this.selectedEntityPickerItem = null;
    const docId = this.state.article.document_id;
    const typeCode = this.entityTypeCodeForSection(section);
    this.loadingEntityPickerCatalog = true;

    this.api.getEntityCatalog(docId, typeCode).subscribe({
      next: (items: DocumentEntityRef[]) => {
        this.entityPickerCatalogItems = items;
        this.loadingEntityPickerCatalog = false;
        setTimeout(() => this.entityPickerSelect?.show(true));
      },
      error: () => {
        this.entitiesError = 'Не удалось загрузить список сущностей';
        this.loadingEntityPickerCatalog = false;
        this.closeEntityPicker();
      },
    });
  }

  get filteredEntityPickerItems(): DocumentEntityRef[] {
    const q = this.entityPickerSearch.trim().toLowerCase();
    if (!q) {
      return this.entityPickerCatalogItems;
    }
    return this.entityPickerCatalogItems.filter((item) => item.name.toLowerCase().includes(q));
  }

  onEntityPickerSelect(item: DocumentEntityRef): void {
    const docId = this.state.article?.document_id;
    if (!docId || this.loadingDocumentEntitiesMutation || !item?.id) {
      return;
    }

    this.loadingDocumentEntitiesMutation = true;
    this.entitiesError = '';

    this.api.assignDocumentEntity(docId, item.id).subscribe({
      next: () => {
        this.closeEntityPicker();
        this.refreshDocumentEntitiesFromServer(docId);
      },
      error: () => {
        this.entitiesError = 'Не удалось добавить сущность';
        this.loadingDocumentEntitiesMutation = false;
      },
    });
  }

  removeEntityItem(item: DocumentEntityRef): void {
    const docId = this.state.article?.document_id;
    if (!docId || this.loadingDocumentEntitiesMutation) {
      return;
    }

    this.loadingDocumentEntitiesMutation = true;
    this.entitiesError = '';

    this.api.removeDocumentEntity(docId, item.id).subscribe({
      next: () => {
        this.refreshDocumentEntitiesFromServer(docId);
      },
      error: () => {
        this.entitiesError = 'Не удалось удалить сущность';
        this.loadingDocumentEntitiesMutation = false;
      },
    });
  }

  toggleTagPicker(scope: TagScope): void {
    if (!this.isEditingEntitiesBlock || !this.state.article?.document_id) {
      return;
    }

    if (this.tagPickerOpen === scope) {
      this.closeTagPicker();
      return;
    }

    this.tagPickerOpen = scope;
    this.tagPickerSearch = '';
    this.tagPickerCatalogItems = [];
    this.selectedTagPickerItem = null;
    const docId = this.state.article.document_id;
    this.loadingTagPickerCatalog = true;

    this.api.getTagCatalog(docId, scope).subscribe({
      next: (items: DocumentTagRef[]) => {
        this.tagPickerCatalogItems = items;
        this.loadingTagPickerCatalog = false;
      },
      error: () => {
        this.loadingTagPickerCatalog = false;
        this.closeTagPicker();
      },
    });
  }

  get filteredTagPickerItems(): DocumentTagRef[] {
    const q = this.tagPickerSearch.trim().toLowerCase();
    if (!q) {
      return this.tagPickerCatalogItems;
    }
    return this.tagPickerCatalogItems.filter((item) => item.name.toLowerCase().includes(q));
  }

  onTagPickerSelect(item: DocumentTagRef): void {
    const docId = this.state.article?.document_id;
    if (!docId || this.loadingDocumentTagsMutation || !item?.id) {
      return;
    }

    this.loadingDocumentTagsMutation = true;
    this.api.assignDocumentTag(docId, item.id).subscribe({
      next: () => {
        this.closeTagPicker();
        this.refreshDocumentTagsFromServer(docId);
      },
      error: () => {
        this.loadingDocumentTagsMutation = false;
      },
    });
  }

  removeOriginalTag(tag: DocumentTagRef): void {
    const docId = this.state.article?.document_id;
    if (!docId || this.loadingDocumentTagsMutation) {
      return;
    }

    this.loadingDocumentTagsMutation = true;
    this.api.removeDocumentTag(docId, tag.id).subscribe({
      next: () => {
        this.refreshDocumentTagsFromServer(docId);
      },
      error: () => {
        this.loadingDocumentTagsMutation = false;
      },
    });
  }

  removeTranslatedTag(tag: DocumentTagRef): void {
    const docId = this.state.article?.document_id;
    if (!docId || this.loadingDocumentTagsMutation) {
      return;
    }

    this.loadingDocumentTagsMutation = true;
    this.api.removeDocumentTag(docId, tag.id).subscribe({
      next: () => {
        this.refreshDocumentTagsFromServer(docId);
      },
      error: () => {
        this.loadingDocumentTagsMutation = false;
      },
    });
  }

  private refreshDocumentEntitiesFromServer(documentId: string): void {
    this.api.getDocumentEntities(documentId).subscribe({
      next: (res: EntitiesResponse) => {
        this.state.entities = {
          military_equipment: res.military_equipment || [],
          manufacturers: res.manufacturers || [],
          contracts: res.contracts || [],
        };
        this.loadingDocumentEntitiesMutation = false;
      },
      error: () => {
        this.entitiesError = 'Не удалось обновить список сущностей';
        this.loadingDocumentEntitiesMutation = false;
      },
    });
  }

  private refreshDocumentTagsFromServer(documentId: string): void {
    this.api.getDocumentTags(documentId).subscribe({
      next: (res: DocumentTagsResponse) => {
        this.state.originalTags = res.original_tags || [];
        this.state.translatedTags = res.translated_tags || [];
        this.loadingDocumentTagsMutation = false;
      },
      error: () => {
        this.loadingDocumentTagsMutation = false;
      },
    });
  }

  private closeTagPicker(): void {
    this.tagPickerOpen = null;
    this.tagPickerSearch = '';
    this.tagPickerCatalogItems = [];
    this.selectedTagPickerItem = null;
    this.loadingTagPickerCatalog = false;
  }

  private closeEntityPicker(): void {
    this.entityPickerOpen = null;
    this.entityPickerSearch = '';
    this.entityPickerCatalogItems = [];
    this.selectedEntityPickerItem = null;
    this.loadingEntityPickerCatalog = false;
  }
}
