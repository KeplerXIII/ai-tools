import { Routes } from '@angular/router';
import { Tools } from './features/tools/tools';
import { DocumentPage } from './features/document-page/document-page';
import { Documents } from './features/documents/documents';
import { Sources } from './features/sources/sources';
import { Login } from './features/login/login';
import { ProcessingDashboard } from './features/processing-dashboard/processing-dashboard';
import { RagQa } from './features/rag-qa/rag-qa';
import { authGuard } from './core/auth/auth.guard';

export const routes: Routes = [
  {
    path: '',
    redirectTo: 'documents',
    pathMatch: 'full',
  },
  {
    path: 'login',
    component: Login,
  },
  {
    path: 'tools',
    component: Tools,
    canActivate: [authGuard],
  },
  {
    path: 'translate',
    component: Tools,
    canActivate: [authGuard],
  },
  {
    path: 'document',
    component: DocumentPage,
    canActivate: [authGuard],
  },
  {
    path: 'article-parser',
    component: DocumentPage,
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
  {
    path: 'rag',
    component: RagQa,
    canActivate: [authGuard],
  },
];
