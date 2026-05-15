import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { InputTextModule } from 'primeng/inputtext';

@Component({
  selector: 'app-string-list-input',
  standalone: true,
  imports: [CommonModule, FormsModule, InputTextModule],
  templateUrl: './string-list-input.component.html',
  styleUrl: './string-list-input.component.scss',
})
export class StringListInputComponent {
  @Input() items: string[] = [''];
  @Output() readonly itemsChange = new EventEmitter<string[]>();

  @Input() placeholder = '';
  @Input() disabled = false;
  @Input() maxItems = 32;
  @Input() inputNamePrefix = 'string_list';
  @Input() addButtonLabel = 'Добавить';

  addItem(): void {
    if (this.disabled || this.items.length >= this.maxItems) {
      return;
    }
    this.updateItems([...this.items, '']);
  }

  removeItem(index: number): void {
    if (this.disabled) {
      return;
    }
    const next = this.items.filter((_, i) => i !== index);
    this.updateItems(next.length ? next : ['']);
  }

  onItemInput(index: number, value: string): void {
    const next = [...this.items];
    next[index] = value;
    this.updateItems(next);
  }

  trackByIndex(index: number): number {
    return index;
  }

  private updateItems(items: string[]): void {
    this.items = items;
    this.itemsChange.emit(items);
  }
}
