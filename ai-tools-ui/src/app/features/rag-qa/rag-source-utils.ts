import { RagSource } from './rag-api';

export type RagSortOrder = 'retrieval' | 'score_desc' | 'score_asc';

export interface RagDocumentHit {
  document_id: string;
  title: string;
  url: string | null;
  /** Максимальный rerank (или retrieval) среди чанков документа — для сортировки групп. */
  bestScore: number;
  rank: number;
  chunks: RagSource[];
}

const CHUNK_TYPE_LABELS_RU: Record<string, string> = {
  translated: 'Перевод',
  original: 'Оригинал',
  annotation: 'Аннотация',
};

/** Русская подпись типа чанка (translated → Перевод). */
export function chunkTypeLabelRu(chunkType: string): string {
  return CHUNK_TYPE_LABELS_RU[chunkType] ?? chunkType;
}

export function sortSources(sources: RagSource[], order: RagSortOrder): RagSource[] {
  const copy = [...sources];
  if (order === 'retrieval') {
    copy.sort((a, b) => a.rank - b.rank);
    return copy;
  }
  copy.sort((a, b) => (order === 'score_desc' ? b.score - a.score : a.score - b.score));
  return copy;
}

/** Один документ — лучший score среди чанков. */
export function groupSourcesByDocument(
  sources: RagSource[],
  order: RagSortOrder,
): RagDocumentHit[] {
  const sorted = sortSources(sources, order);
  const byDoc = new Map<string, RagDocumentHit>();
  const docOrder: string[] = [];

  for (const s of sorted) {
    let doc = byDoc.get(s.document_id);
    if (!doc) {
      doc = {
        document_id: s.document_id,
        title: s.title,
        url: s.url,
        bestScore: s.score,
        rank: 0,
        chunks: [],
      };
      byDoc.set(s.document_id, doc);
      docOrder.push(s.document_id);
    }
    doc.chunks.push(s);
    if (s.score > doc.bestScore) {
      doc.bestScore = s.score;
      doc.title = s.title;
      doc.url = s.url;
    }
  }

  const chunkCmp =
    order === 'retrieval'
      ? (a: RagSource, b: RagSource) => a.rank - b.rank
      : order === 'score_desc'
        ? (a: RagSource, b: RagSource) => b.score - a.score
        : (a: RagSource, b: RagSource) => a.score - b.score;
  for (const doc of byDoc.values()) {
    doc.chunks.sort(chunkCmp);
  }

  let docs: RagDocumentHit[];
  if (order === 'retrieval') {
    docs = docOrder.map((id) => byDoc.get(id)!);
  } else {
    docs = Array.from(byDoc.values());
    docs.sort((a, b) =>
      order === 'score_desc' ? b.bestScore - a.bestScore : a.bestScore - b.bestScore,
    );
  }
  docs.forEach((doc, index) => {
    doc.rank = index + 1;
  });
  return docs;
}
