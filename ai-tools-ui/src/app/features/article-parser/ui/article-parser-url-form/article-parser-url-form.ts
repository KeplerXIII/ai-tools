import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FloatLabelModule } from 'primeng/floatlabel';
import { InputTextModule } from 'primeng/inputtext';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import {
  ButtonVariant,
  OutlineButtonComponent,
} from '../../../../shared/ui/outline-button/outline-button.component';
import { PrimaryButtonComponent } from '../../../../shared/ui/primary-button/primary-button.component';

@Component({
  selector: 'app-article-parser-url-form',
  standalone: true,
  imports: [
    FormsModule,
    FloatLabelModule,
    InputTextModule,
    MatProgressSpinnerModule,
    PrimaryButtonComponent,
    OutlineButtonComponent,
  ],
  templateUrl: './article-parser-url-form.html',
  styleUrl: './article-parser-url-form.scss',
})
export class ArticleParserUrlFormComponent {
  @Input() url = '';
  @Input() loading = false;
  @Output() urlChange = new EventEmitter<string>();
  @Output() submitUrl = new EventEmitter<void>();
  @Output() clearClicked = new EventEmitter<void>();

  readonly ButtonVariant = ButtonVariant;
  touched = false;

  onSubmit(): void {
    this.urlChange.emit(this.url);
    this.submitUrl.emit();
  }

  showUrlError(): boolean {
    return this.touched && !!this.url && !this.isValidUrl(this.url);
  }

  isValidUrl(value: string): boolean {
    try {
      new URL(value);
      return true;
    } catch {
      return false;
    }
  }

  onClear(): void {
    this.url = '';
    this.urlChange.emit('');
    this.clearClicked.emit();
  }
}
