import { SourceListItem } from '../../api/sources-api';
import { formatSourceDate } from './source-list-display.util';

function sourceStatsCoalesceCount(value: unknown): number {
  if (value === null || value === undefined) {
    return 0;
  }
  const n = Number(value);
  if (Number.isNaN(n)) {
    return 0;
  }
  return Math.max(0, Math.floor(n));
}

export function sourceStatsKnobMax(src: SourceListItem): number {
  const total = sourceStatsCoalesceCount(src.documents_total);
  const unprocessed = sourceStatsCoalesceCount(src.documents_unprocessed);
  const last = sourceStatsCoalesceCount(src.last_parse_created_total);
  const peak = Math.max(total, unprocessed, last, 1);
  return Math.max(100, peak);
}

export function hasSourceStatNumber(value: unknown): boolean {
  if (value === null || value === undefined) {
    return false;
  }
  const n = Number(value);
  return !Number.isNaN(n);
}

export function sourceStatsKnobColor(value: number | null | undefined, max: number): string {
  const v = Math.max(0, Number(value) || 0);
  const m = Math.max(1, max);
  const pct = Math.round((v / m) * 100);
  if (pct <= 10) {
    return '#ef4444';
  }
  if (pct <= 30) {
    return '#f97316';
  }
  if (pct <= 50) {
    return '#eab308';
  }
  if (pct <= 80) {
    return '#AEEB9D';
  }
  return '#22c55e';
}

export function lastParseAtTooltip(src: SourceListItem): string {
  if (!src.last_parse_at) {
    return '';
  }
  return `Последний разбор: ${formatSourceDate(src.last_parse_at)}`;
}
