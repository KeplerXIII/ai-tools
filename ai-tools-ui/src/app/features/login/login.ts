import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { finalize } from 'rxjs';
import { AuthService } from '../../core/auth/auth.service';
import { PrimaryButtonComponent } from '../../shared/ui/primary-button/primary-button.component';

@Component({
  selector: 'app-login',
  imports: [FormsModule, PrimaryButtonComponent],
  templateUrl: './login.html',
  styleUrl: './login.scss',
})
export class Login implements OnInit {
  username = '';
  password = '';
  loading = false;
  error = '';

  constructor(
    private readonly authService: AuthService,
    private readonly router: Router,
  ) {}

  ngOnInit(): void {
    if (this.authService.isAuthenticated()) {
      this.router.navigate(['/translate']);
    }
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
          this.router.navigate(['/translate']);
        },
        error: () => {
          this.error = 'Неверный логин или пароль';
        },
      });
  }
}
