import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { RouterLink } from '@angular/router';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TextareaModule } from 'primeng/textarea';
import { PrimaryButtonComponent } from '../../shared/ui/primary-button/primary-button.component';
import { OutlineButtonComponent } from '../../shared/ui/outline-button/outline-button.component';
import { RagApi, RagAskRequest, RagMetrics, RagSource } from './rag-api';
import {
  chunkTypeLabelRu,
  groupSourcesByDocument,
  RagDocumentHit,
  RagSortOrder,
  sortSources,
} from './rag-source-utils';

const RAG_FETCH_K = 32;
const RAG_LLM_TOP_K = 12;

@Component({
  selector: 'app-rag-qa',
  standalone: true,
  imports: [
    DecimalPipe,
    NgTemplateOutlet,
    FormsModule,
    RouterLink,
    MatCheckboxModule,
    MatTooltipModule,
    MatProgressSpinnerModule,
    TextareaModule,
    PrimaryButtonComponent,
    OutlineButtonComponent,
  ],
  templateUrl: './rag-qa.html',
  styleUrl: './rag-qa.scss',
})
export class RagQa implements OnInit {
  query = '';
  answer = '';
  /** Все фрагменты после поиска (сортировка только здесь). */
  sources: RagSource[] = [];
  /** Фрагменты в промпте LLM: [1]…[N] — порядок не менять. */
  contextSources: RagSource[] = [];
  loading = false;
  error = '';

  retrieveOnly = false;
  useStream = true;
  strategy: 'vector' | 'hybrid' | 'hybrid_bm25' | 'hybrid_all' = 'hybrid_all';
  reranker: 'none' | 'cross_encoder' = 'cross_encoder';
  expandQuery = false;
  minScore: number | null = null;
  groupByDocument = true;
  resultSortOrder: RagSortOrder = 'score_desc';

  retrievalMs: number | null = null;
  generationMs: number | null = null;
  metrics: RagMetrics | null = null;

  readonly ragFetchK = RAG_FETCH_K;
  readonly ragLlmTopK = RAG_LLM_TOP_K;

  constructor(
    private readonly ragApi: RagApi,
    private readonly cdr: ChangeDetectorRef,
    private readonly sanitizer: DomSanitizer,
  ) {}

  ngOnInit(): void {
    marked.setOptions({ gfm: true, breaks: true });
    void this.loadMetrics();
  }

  answerMarkdownHtml(): SafeHtml {
    const src = this.answer?.trim() ?? '';
    if (!src) {
      return this.sanitizer.bypassSecurityTrustHtml('');
    }
    try {
      const rawHtml = marked.parse(src, { async: false }) as string;
      const clean = DOMPurify.sanitize(rawHtml);
      return this.sanitizer.bypassSecurityTrustHtml(clean);
    } catch {
      return this.sanitizer.bypassSecurityTrustHtml(
        '<p class="rag-page__answer-md-error">Не удалось разобрать Markdown</p>',
      );
    }
  }

  private buildRequest(): RagAskRequest {
    const req: RagAskRequest = {
      query: this.query.trim(),
      fetch_k: RAG_FETCH_K,
      sources_k: RAG_FETCH_K,
      top_k: RAG_LLM_TOP_K,
      retrieval_strategy: this.strategy,
      reranker: this.reranker,
      expand_query: this.expandQuery,
    };
    if (this.minScore != null && !Number.isNaN(this.minScore) && this.minScore > 0) {
      req.min_score = this.minScore;
    }
    return req;
  }

  get sortedSearchSources(): RagSource[] {
    return sortSources(this.sources, this.resultSortOrder);
  }

  get searchDocumentHits(): RagDocumentHit[] {
    return groupSourcesByDocument(this.sources, this.resultSortOrder);
  }

  get hasLlmContext(): boolean {
    return this.contextSources.length > 0 && !this.retrieveOnly;
  }

  bestChunk(doc: RagDocumentHit): RagSource {
    return doc.chunks[0];
  }

  chunkTypeLabel = chunkTypeLabelRu;

  /** Номер фрагмента в документе для UI (в БД chunk_index с 0). */
  fragmentNumber(chunkIndex: number): number {
    return chunkIndex + 1;
  }

  docHasLlmChunk(doc: RagDocumentHit): boolean {
    return doc.chunks.some((c) => c.citation_id != null);
  }

  llmChunks(doc: RagDocumentHit): RagSource[] {
    return doc.chunks.filter((c) => c.citation_id != null);
  }

  wasReranked(source: RagSource): boolean {
    return source.score_from === 'reranker';
  }

  hasRetrievalScores(source: RagSource): boolean {
    const r = source.retrieval_scores;
    return !!r && Object.keys(r).length > 0;
  }

  /** Подписи vector / FTS / bm25 (включая 0 — нет совпадения в top-k этого бэкенда). */
  retrievalScoreBadges(source: RagSource): { key: string; label: string; value: number }[] {
    const r = source.retrieval_scores ?? {};
    const order: { key: string; label: string }[] = [
      { key: 'vector', label: 'Vector' },
      { key: 'lexical', label: 'FTS' },
      { key: 'bm25', label: 'BM25' },
    ];
    return order
      .filter((o) => Object.prototype.hasOwnProperty.call(r, o.key))
      .map((o) => ({ key: o.key, label: o.label, value: Number(r[o.key]) }));
  }

  onSortChange(): void {
    this.cdr.markForCheck();
  }

  onQueryKeydown(event: Event): void {
    if (!(event instanceof KeyboardEvent) || event.key !== 'Enter' || event.shiftKey) {
      return;
    }
    event.preventDefault();
    if (!this.loading && this.query.trim()) {
      void this.submit();
    }
  }

  private applyMeta(sources: RagSource[], contextSources: RagSource[]): void {
    this.sources = sources;
    this.contextSources = contextSources;
  }

  async loadMetrics(): Promise<void> {
    try {
      this.metrics = await this.ragApi.metrics();
    } catch {
      this.metrics = null;
    }
    this.cdr.markForCheck();
  }

  async submit(): Promise<void> {
    const q = this.query.trim();
    if (!q || this.loading) {
      return;
    }

    this.loading = true;
    this.error = '';
    this.answer = '';
    this.sources = [];
    this.contextSources = [];
    this.retrievalMs = null;
    this.generationMs = null;
    this.cdr.detectChanges();

    const body = this.buildRequest();

    try {
      if (this.retrieveOnly) {
        const res = await this.ragApi.ask(body, true);
        this.applyMeta(res.sources, []);
        this.retrievalMs = res.retrieval_ms;
        this.generationMs = res.generation_ms;
      } else if (this.useStream) {
        const started = performance.now();
        await this.ragApi.askStream(body, {
          onMeta: (meta) => {
            this.applyMeta(meta.sources, meta.context_sources ?? []);
            this.retrievalMs = meta.retrieval_ms;
            this.cdr.detectChanges();
          },
          onChunk: (chunk) => {
            this.answer += chunk;
            this.cdr.detectChanges();
          },
        });
        this.generationMs = Math.round(performance.now() - started - (this.retrievalMs ?? 0));
      } else {
        const res = await this.ragApi.ask(body, false);
        this.answer = res.answer ?? '';
        this.applyMeta(res.sources, res.context_sources ?? []);
        this.retrievalMs = res.retrieval_ms;
        this.generationMs = res.generation_ms;
      }
      await this.loadMetrics();
    } catch (e) {
      console.error(e);
      this.error = 'Не удалось выполнить запрос к базе знаний';
    } finally {
      this.loading = false;
      this.cdr.detectChanges();
    }
  }

  clear(): void {
    this.query = '';
    this.answer = '';
    this.sources = [];
    this.contextSources = [];
    this.error = '';
    this.retrievalMs = null;
    this.generationMs = null;
  }

  documentLink(source: RagSource): string[] {
    return ['/document'];
  }

  documentQueryParams(source: RagSource): { id: string } {
    return { id: source.document_id };
  }
}
