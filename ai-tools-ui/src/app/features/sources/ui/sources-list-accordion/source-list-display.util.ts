import { SourceListItem } from '../../api/sources-api';

export interface SourceDetailRow {
  label: string;
  text: string;
  href?: string;
  isMono?: boolean;
}

export function displaySourceTitle(item: SourceListItem): string {
  const name = item.name?.trim();
  if (name) {
    return name;
  }
  try {
    return new URL(item.url).hostname;
  } catch {
    return item.url;
  }
}

export function formatSourceDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return iso;
  }
  return d.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function buildSourceDetailRows(src: SourceListItem): SourceDetailRow[] {
  const rows: SourceDetailRow[] = [{ label: 'URL', text: src.url, href: src.url }];
  const rssFeeds = src.rss_urls?.length
    ? src.rss_urls
    : (src.rss_url ?? '').trim()
      ? [src.rss_url!.trim()]
      : [];
  if (rssFeeds.length) {
    rows.push({
      label: rssFeeds.length > 1 ? 'RSS-фиды' : 'RSS',
      text: rssFeeds.join('\n'),
      href: rssFeeds[0],
    });
  }
  const paths = src.discovery_paths ?? [];
  if (paths.length) {
    rows.push({ label: 'Пути обхода', text: paths.join(', ') });
  }
  const country = (src.country_code ?? '').trim();
  rows.push(
    {
      label: 'Тип документа',
      text: `${src.document_type_name} (${src.document_type_code})`,
    },
    { label: 'Страна', text: country ? country : '—' },
    { label: 'Добавил', text: src.added_by_username },
    { label: 'Идентификатор', text: src.source_id, isMono: true },
  );
  return rows;
}
