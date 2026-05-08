import { Routes } from '@angular/router';
import { Translate } from './features/translate/translate';
import { ArticleParser } from './features/article-parser/article-parser';
import { Documents } from './features/documents/documents';
import { Sources } from './features/sources/sources';
import { Login } from './features/login/login';
import { ProcessingDashboard } from './features/processing-dashboard/processing-dashboard';
import { authGuard } from './core/auth/auth.guard';

export const routes: Routes = [
  {
    path: '',
    redirectTo: 'login',
    pathMatch: 'full',
  },
  {
    path: 'login',
    component: Login,
  },
  {
    path: 'translate',
    component: Translate,
    canActivate: [authGuard],
  },
  {
    path: 'article-parser',
    component: ArticleParser,
    canActivate: [authGuard],
  },
  {
    path: 'documents',
    component: Documents,
    canActivate: [authGuard],
  },
  {
    path: 'sources',
    component: Sources,
    canActivate: [authGuard],
  },
  {
    path: 'processing-dashboard',
    component: ProcessingDashboard,
    canActivate: [authGuard],
  },
];
