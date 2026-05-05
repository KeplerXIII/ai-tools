import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

export enum ButtonVariant {
  Rounded = 'rounded',
  Sharp = 'sharp',
  Square = 'square',
}

@Component({
  selector: 'app-outline-button',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './outline-button.component.html',
  styleUrls: ['./outline-button.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OutlineButtonComponent {
  @Input() public text: string = '';
  @Input() public iconName?: string;
  @Output() public clicked = new EventEmitter<void>();
  @Input() public variant: ButtonVariant = ButtonVariant.Rounded;
  @Input() public size: 'small' | 'medium' | 'large' | 'large-plus' | 'extra-large' = 'medium';
  @Input() public disabled = false;
  @Input() public theme: 'default' | 'light' = 'default';
  public readonly ButtonVariant = ButtonVariant;

  public onClick(event: MouseEvent): void {
    if (this.disabled || event.defaultPrevented) return;
    this.clicked.emit();
  }

  public get sizeClass(): string {
    return `size-${this.size}`;
  }

  public get variantClass(): string {
    return this.variant;
  }

  public get themeClass(): string {
    return `theme-${this.theme}`;
  }
}
