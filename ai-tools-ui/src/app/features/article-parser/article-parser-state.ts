import { Injectable } from '@angular/core';

import {
  DocumentCategoryRef,
  DocumentTagRef,
  EntitiesResponse,
  ExtractResponse,
} from './article-parser-api';

@Injectable({
  providedIn: 'root',
})
export class ArticleParserState {
  url = '';

  article: ExtractResponse | null = null;
  entities: EntitiesResponse | null = null;
  categories: DocumentCategoryRef[] | null = null;

  originalTags: DocumentTagRef[] = [];
  translatedTags: DocumentTagRef[] = [];

  translatedText = '';
  annotation = '';

  error = '';

  clear(): void {
    this.url = '';
    this.article = null;
    this.entities = null;
    this.categories = null;
    this.originalTags = [];
    this.translatedTags = [];
    this.translatedText = '';
    this.annotation = '';
    this.error = '';
  }
}