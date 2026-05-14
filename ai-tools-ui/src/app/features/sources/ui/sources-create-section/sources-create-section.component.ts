import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Output } from '@angular/core';
import { AccordionModule } from 'primeng/accordion';
import { SourcesCreateFormComponent } from '../sources-create-form/sources-create-form.component';

@Component({
  selector: 'app-sources-create-section',
  standalone: true,
  imports: [CommonModule, AccordionModule, SourcesCreateFormComponent],
  templateUrl: './sources-create-section.component.html',
  styleUrl: './sources-create-section.component.scss',
})
export class SourcesCreateSectionComponent {
  @Output() readonly sourceCreated = new EventEmitter<void>();

  sourceCreateAccordionValue: string | undefined = undefined;
}
