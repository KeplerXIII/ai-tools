import { Injectable } from '@angular/core';

import {
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

  originalTags: string[] = [];
  translatedTags: string[] = [];

  originalTagsText = '';
  translatedTagsText = '';

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
    this.originalTagsText = '';
    this.translatedTagsText = '';
    this.translatedText = '';
    this.annotation = '';
    this.editMode = false;
    this.error = '';
  }
}