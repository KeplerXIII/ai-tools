import { Injectable } from '@angular/core';

import {
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

  originalTags: DocumentTagRef[] = [];
  translatedTags: DocumentTagRef[] = [];

  translatedText = '';
  annotation = '';

  editMode = false;

  error = '';

  clear(): void {
    this.url = '';
    this.article = null;
    this.entities = null;
    this.originalTags = [];
    this.translatedTags = [];
    this.translatedText = '';
    this.annotation = '';
    this.editMode = false;
    this.error = '';
  }
}