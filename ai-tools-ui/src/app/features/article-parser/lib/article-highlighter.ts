export interface HighlightGroup {
  className: string;
  entities: string[];
}

export function buildHighlightedArticleText(text: string, entities: string[]): string {
  return buildHighlightedArticleTextByGroups(text, [
    {
      className: 'highlighted-entity',
      entities,
    },
  ]);
}

export function buildHighlightedArticleTextByGroups(text: string, groups: HighlightGroup[]): string {
  if (!text) {
    return '';
  }

  const normalizedGroups = groups
    .map((group) => ({
      className: group.className,
      entities: group.entities
        .map((entity) => entity.trim())
        .filter(Boolean)
        .sort((a, b) => b.length - a.length),
    }))
    .filter((group) => !!group.className && !!group.entities.length);

  let result = escapeHtml(text);

  for (const group of normalizedGroups) {
    for (const entity of group.entities) {
      const escapedEntity = escapeHtml(entity);
      const pattern = createFlexibleEntityPattern(escapedEntity);

      result = result.replace(pattern, (match) => {
        if (match.includes('highlighted-entity')) {
          return match;
        }

        return `<span class="${group.className}">${match}</span>`;
      });
    }
  }

  return result.replace(/\n/g, '<br>');
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function createFlexibleEntityPattern(value: string): RegExp {
  const escaped = value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const flexible = escaped.replace(/\\ /g, '\\s+').replace(/-/g, '[-–—-]?');
  return new RegExp(flexible, 'gi');
}