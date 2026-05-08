import { Component } from '@angular/core';
import { AsyncPipe } from '@angular/common';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { MatSidenavModule } from '@angular/material/sidenav';
import { MatListModule } from '@angular/material/list';
import { MatToolbarModule } from '@angular/material/toolbar';
import { HeaderComponent } from './shared/ui/header/header.component';
import { SidebarComponent } from './shared/ui/sidebar/sidebar-component';
import { AnnotateBatchNotifierService } from './core/processing/annotate-batch-notifier.service';
import { CategorizeBatchNotifierService } from './core/processing/categorize-batch-notifier.service';
import { ExtractorBatchNotifierService } from './core/processing/extractor-batch-notifier.service';
import { TaggerBatchNotifierService } from './core/processing/tagger-batch-notifier.service';
import { AuthService } from './core/auth/auth.service';
import { TranslateBatchNotifierService } from './core/processing/translate-batch-notifier.service';

@Component({
  selector: 'app-root',
  imports: [
    AsyncPipe,
    RouterOutlet,
    MatSidenavModule,
    MatListModule,
    MatToolbarModule,
    HeaderComponent,
    SidebarComponent,
  ],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  constructor(
    private readonly router: Router,
    private readonly authService: AuthService,
    readonly translateBatchNotifier: TranslateBatchNotifierService,
    readonly annotateBatchNotifier: AnnotateBatchNotifierService,
    readonly categorizeBatchNotifier: CategorizeBatchNotifierService,
    readonly extractorBatchNotifier: ExtractorBatchNotifierService,
    readonly taggerBatchNotifier: TaggerBatchNotifierService,
  ) {
    this.translateBatchNotifier.initFromStorage();
    this.annotateBatchNotifier.initFromStorage();
    this.categorizeBatchNotifier.initFromStorage();
    this.extractorBatchNotifier.initFromStorage();
    this.taggerBatchNotifier.initFromStorage();
  }

  get showAppShell(): boolean {
    return this.authService.isAuthenticated() && !this.router.url.startsWith('/login');
  }
}