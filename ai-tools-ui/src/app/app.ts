import { Component } from '@angular/core';
import { AsyncPipe } from '@angular/common';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { MatSidenavModule } from '@angular/material/sidenav';
import { MatListModule } from '@angular/material/list';
import { MatToolbarModule } from '@angular/material/toolbar';
import { HeaderComponent } from './shared/ui/header/header.component';
import { SidebarComponent } from './shared/ui/sidebar/sidebar-component';
import { AuthService } from './core/auth/auth.service';
import { TranslateBatchNotifierService } from './core/processing/translate-batch-notifier.service';

@Component({
  selector: 'app-root',
  imports: [
    AsyncPipe,
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
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
  ) {
    this.translateBatchNotifier.initFromStorage();
  }

  get showAppShell(): boolean {
    return this.authService.isAuthenticated() && !this.router.url.startsWith('/login');
  }
}