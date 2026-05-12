import { Component } from '@angular/core';
import { SkeletonModule } from 'primeng/skeleton';

@Component({
  selector: 'app-article-parser-article-loading',
  standalone: true,
  imports: [SkeletonModule],
  templateUrl: './article-parser-article-loading.html',
  styleUrl: './article-parser-article-loading.scss',
})
export class ArticleParserArticleLoadingComponent {}
