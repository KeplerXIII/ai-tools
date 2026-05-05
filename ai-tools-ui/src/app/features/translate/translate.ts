import { ChangeDetectorRef, Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FloatLabelModule } from 'primeng/floatlabel';
import { TextareaModule } from 'primeng/textarea';
import { ChipModule } from 'primeng/chip';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { TranslateApi } from './translate-api';
import {
  ButtonVariant,
  OutlineButtonComponent,
} from '../../shared/ui/outline-button/outline-button.component';
import { PrimaryButtonComponent } from '../../shared/ui/primary-button/primary-button.component';
import { UpperCasePipe } from '@angular/common';

@Component({
  selector: 'app-translate',
  imports: [
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressSpinnerModule,
    FloatLabelModule,
    TextareaModule,
    ChipModule,
    OutlineButtonComponent,
    PrimaryButtonComponent,
    UpperCasePipe,
  ],
  templateUrl: './translate.html',
  styleUrl: './translate.scss',
})
export class Translate {
  text = '';
  result = '';
  sourceLang = '';
  targetLang = '';
  loading = false;
  error = '';
  copied = false;

  readonly ButtonVariant = ButtonVariant;

  constructor(
    private translateApi: TranslateApi,
    private cdr: ChangeDetectorRef,
  ) {}

  async translate(): Promise<void> {
    const value = this.text.trim();

    if (!value) {
      return;
    }

    this.loading = true;
    this.error = '';
    this.result = '';
    this.sourceLang = '';
    this.targetLang = '';
    this.copied = false;

    try {
      const response = await this.translateApi.translateStream(value, (chunk) => {
        this.result += chunk;
        this.cdr.detectChanges();
      });

      this.result = response.translation;
      this.sourceLang = response.source_lang ?? '';
      this.targetLang = response.target_lang ?? 'ru';
    } catch (error) {
      console.error(error);
      this.error = 'Ошибка при выполнении перевода';
    } finally {
      this.loading = false;
      this.cdr.detectChanges();
    }
  }

  clear(): void {
    this.text = '';
    this.result = '';
    this.sourceLang = '';
    this.targetLang = '';
    this.error = '';
    this.copied = false;
  }

  async copyResult(): Promise<void> {
    if (!this.result) {
      return;
    }

    await navigator.clipboard.writeText(this.result);

    this.copied = true;
    this.cdr.detectChanges();

    setTimeout(() => {
      this.copied = false;
      this.cdr.detectChanges();
    }, 1500);
  }
}
