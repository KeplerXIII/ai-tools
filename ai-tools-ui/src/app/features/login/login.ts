import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { finalize } from 'rxjs';
import { AuthService } from '../../core/auth/auth.service';
import { PrimaryButtonComponent } from '../../shared/ui/primary-button/primary-button.component';

/** Автозакрытие оверлея (~⅔ длины цикла гифки). */
const POST_LOGIN_CELEBRATION_MS = Math.round((2240 * 2) / 3);

@Component({
  selector: 'app-login',
  imports: [FormsModule, PrimaryButtonComponent],
  templateUrl: './login.html',
  styleUrl: './login.scss',
})
export class Login implements OnInit, OnDestroy {
  username = '';
  password = '';
  loading = false;
  error = '';
  celebrationVisible = false;
  celebrationGifSrc = '';

  private celebrationTimeoutId: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly authService: AuthService,
    private readonly router: Router,
  ) {}

  ngOnInit(): void {
    if (this.authService.isAuthenticated()) {
      this.router.navigate(['/translate']);
    }
  }

  ngOnDestroy(): void {
    this.clearCelebrationTimer();
  }

  submit(): void {
    if (!this.username.trim() || !this.password.trim() || this.loading) {
      return;
    }

    this.loading = true;
    this.error = '';

    this.authService
      .login(this.username.trim(), this.password)
      .pipe(
        finalize(() => {
          this.loading = false;
        }),
      )
      .subscribe({
        next: () => {
          this.startPostLoginCelebration();
        },
        error: () => {
          this.error = 'Неверный логин или пароль';
        },
      });
  }

  dismissCelebration(): void {
    this.clearCelebrationTimer();
    this.celebrationVisible = false;
    void this.router.navigate(['/translate']);
  }

  logoutDuringCelebration(): void {
    this.clearCelebrationTimer();
    this.celebrationVisible = false;
    this.authService.logout();
  }

  private startPostLoginCelebration(): void {
    this.celebrationGifSrc = `assets/login-celebration.gif?t=${Date.now()}`;
    this.celebrationVisible = true;
    this.clearCelebrationTimer();
    this.celebrationTimeoutId = setTimeout(() => this.dismissCelebration(), POST_LOGIN_CELEBRATION_MS);
  }

  private clearCelebrationTimer(): void {
    if (this.celebrationTimeoutId !== null) {
      clearTimeout(this.celebrationTimeoutId);
      this.celebrationTimeoutId = null;
    }
  }
}
