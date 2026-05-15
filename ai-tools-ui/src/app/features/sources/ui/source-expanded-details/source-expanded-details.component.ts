import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { KnobModule } from 'primeng/knob';
import { TableModule } from 'primeng/table';
import { TooltipModule } from 'primeng/tooltip';
import { SourceListItem } from '../../api/sources-api';
import { buildSourceDetailRows } from '../sources-list-accordion/source-list-display.util';
import {
  hasSourceStatNumber,
  lastParseAtTooltip,
  sourceStatsKnobColor,
  sourceStatsKnobMax,
} from '../sources-list-accordion/source-stats.util';

@Component({
  selector: 'app-source-expanded-details',
  standalone: true,
  imports: [CommonModule, FormsModule, KnobModule, TableModule, TooltipModule],
  templateUrl: './source-expanded-details.component.html',
  styleUrl: './source-expanded-details.component.scss',
})
export class SourceExpandedDetailsComponent {
  readonly knobNullStroke = '#94a3b8';

  @Input({ required: true }) src!: SourceListItem;

  detailRows(src: SourceListItem) {
    return buildSourceDetailRows(src);
  }

  knobMax(src: SourceListItem): number {
    return sourceStatsKnobMax(src);
  }

  hasStatNumber(value: unknown): boolean {
    return hasSourceStatNumber(value);
  }

  knobColor(value: number | null | undefined, max: number): string {
    return sourceStatsKnobColor(value, max);
  }

  parseAtTooltip(src: SourceListItem): string {
    return lastParseAtTooltip(src);
  }
}
