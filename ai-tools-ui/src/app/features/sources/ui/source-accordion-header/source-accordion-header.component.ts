import { Component, Input } from '@angular/core';
import { ChipModule } from 'primeng/chip';
import { SourceListItem } from '../../api/sources-api';
import { displaySourceTitle, formatSourceDate } from '../sources-list-accordion/source-list-display.util';

@Component({
  selector: 'app-source-accordion-header',
  standalone: true,
  imports: [ChipModule],
  templateUrl: './source-accordion-header.component.html',
  styleUrl: './source-accordion-header.component.scss',
})
export class SourceAccordionHeaderComponent {
  @Input({ required: true }) src!: SourceListItem;

  title(src: SourceListItem): string {
    return displaySourceTitle(src);
  }

  dateLabel(iso: string): string {
    return formatSourceDate(iso);
  }

  rssChipLabel(src: SourceListItem): string {
    const count = src.rss_urls?.length || (src.rss_url ? 1 : 0);
    return count > 1 ? `RSS: ${count}` : 'RSS';
  }
}
