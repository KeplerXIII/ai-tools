import { NgClass } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { SvgIconComponent } from '../svg-icon/svg-icon.component';


@Component({
  selector: 'app-primary-button',
  standalone: true,
  imports: [SvgIconComponent, NgClass],
  templateUrl: './primary-button.component.html',
  styleUrl: './primary-button.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PrimaryButtonComponent {
  @Input() public text: string = '';
  @Input() public icon?: string;
  @Input() public disabled: boolean = false;
  @Input() public isRotate: boolean = false;
  @Input() public type: 'button' | 'submit' | 'reset' = 'button';
  @Input() public variant: 'rounded' | 'rect' | 'rounded-rect' = 'rounded';
  @Input() public size:
    | 'small'
    | 'medium'
    | 'large'
    | 'large-plus'
    | 'extra-large'
    | 'super-large' = 'medium';
  @Input() public font: 'light' | 'medium' | 'semibold' | 'bold' = 'light';

  @Output() public clicked = new EventEmitter<void>();

  public onClick(event: Event): void {
    if (this.type !== 'submit') {
      event.preventDefault();
    }
    this.clicked.emit();
  }
}
