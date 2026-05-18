import { Component } from '@angular/core';
import { Router } from '@angular/router';

import { AuthService } from '../../../core/auth/auth.service';
import { AddToWorkbookService } from './add-to-workbook.service';

@Component({
  selector: 'app-add-to-workbook-fab',
  standalone: true,
  template: `
    @if (visible) {
      <button
        type="button"
        class="wb-fab"
        title="Тезис в рабочую тетрадь"
        aria-label="Тезис в рабочую тетрадь"
        (click)="onClick()"
      >
        <i class="pi pi-pencil" aria-hidden="true"></i>
      </button>
    }
  `,
  styles: [
    `
      .wb-fab {
        position: fixed;
        top: 50%;
        right: 20px;
        z-index: 1300;
        width: 52px;
        height: 52px;
        border: 1px solid rgb(255 255 255 / 45%);
        border-radius: 50%;
        background: var(--bg-gradient-base);
        color: var(--light-text-color, #fff);
        font-size: 20px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transform: translateY(-50%);
        box-shadow:
          0 4px 12px rgba(0, 0, 0, 0.12),
          0 2px 6px rgba(0, 0, 0, 0.08);
        transition:
          background 0.15s,
          transform 0.15s,
          box-shadow 0.15s,
          border-color 0.15s;
      }
      .wb-fab:hover {
        background: var(--bg-gradient-base-light);
        border-color: rgb(255 255 255 / 65%);
        transform: translateY(-50%) scale(1.06);
        box-shadow:
          0 6px 16px rgba(0, 0, 0, 0.16),
          0 3px 8px rgba(0, 0, 0, 0.1);
      }
      .wb-fab:active {
        transform: translateY(-50%) scale(0.98);
      }
      .wb-fab:focus-visible {
        outline: 2px solid rgb(255 255 255 / 85%);
        outline-offset: 3px;
      }
      @media (max-width: 640px) {
        .wb-fab {
          right: 12px;
          width: 48px;
          height: 48px;
          font-size: 18px;
        }
      }
    `,
  ],
})
export class AddToWorkbookFabComponent {
  constructor(
    private readonly addToWorkbook: AddToWorkbookService,
    private readonly authService: AuthService,
    private readonly router: Router,
  ) {}

  get visible(): boolean {
    return this.authService.isAuthenticated() && !this.router.url.startsWith('/login');
  }

  onClick(): void {
    this.addToWorkbook.openFromPage();
  }
}
