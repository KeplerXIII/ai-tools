/** Нормализует список строк из отдельных полей (без разбиения по запятым). */
export function normalizeStringList(items: string[] | null | undefined): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of items ?? []) {
    const p = raw.trim();
    if (!p || seen.has(p)) {
      continue;
    }
    seen.add(p);
    out.push(p);
  }
  return out;
}

/** Значения из API → поля формы (минимум одно пустое поле). */
export function stringListForForm(values: string[] | null | undefined): string[] {
  const stored = values?.filter((v) => v.trim().length > 0) ?? [];
  return stored.length ? [...stored] : [''];
}
