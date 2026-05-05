import { Routes } from '@angular/router';
import { Translate } from './features/translate/translate';
import { ArticleParser } from './features/article-parser/article-parser';

export const routes: Routes = [
  {
    path: '',
    redirectTo: 'translate',
    pathMatch: 'full',
  },
  {
    path: 'translate',
    component: Translate,
  },
  {
    path: 'article-parser',
    component: ArticleParser,
  },
];