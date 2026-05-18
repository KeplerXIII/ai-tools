import { Injectable } from '@angular/core';
import { Subject } from 'rxjs';

/** Атрибуты на DOM-узлах с привязкой к документу (RAG, редактор и т.д.). */
export const WB_DOCUMENT_ID_ATTR = 'data-wb-document-id';
export const WB_DOCUMENT_TITLE_ATTR = 'data-wb-document-title';

export interface AddToWorkbookOpenPayload {
  initialText: string;
  documentId?: string;
  documentTitle?: string;
}

interface DocumentContext {
  documentId?: string;
  documentTitle?: string;
}

@Injectable({ providedIn: 'root' })
export class AddToWorkbookService {
  private readonly openSubject = new Subject<AddToWorkbookOpenPayload>();

  readonly open$ = this.openSubject.asObservable();

  /** Открыть диалог: выделение → текст; DOM/URL → источник при возможности. */
  openFromPage(): void {
    const selection = this.readSelectionText();
    const fromDom = this.detectDocumentFromSelection();
    const fromUrl = this.detectDocumentFromUrl();
    this.openSubject.next({
      initialText: selection,
      documentId: fromDom.documentId ?? fromUrl.documentId,
      documentTitle: fromDom.documentTitle ?? fromUrl.documentTitle,
    });
  }

  private readSelectionText(): string {
    try {
      return window.getSelection()?.toString().trim() ?? '';
    } catch {
      return '';
    }
  }

  /** Источник из ближайшего предка с data-wb-document-id (контексты RAG, блоки документа). */
  private detectDocumentFromSelection(): DocumentContext {
    try {
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0) {
        return {};
      }
      let node: Node | null = sel.anchorNode;
      if (!node) {
        return {};
      }
      const element =
        node.nodeType === Node.ELEMENT_NODE ? (node as Element) : node.parentElement;
      if (!element) {
        return {};
      }
      const host = element.closest(`[${WB_DOCUMENT_ID_ATTR}]`);
      if (!host) {
        return {};
      }
      const documentId = host.getAttribute(WB_DOCUMENT_ID_ATTR)?.trim() || undefined;
      if (!documentId) {
        return {};
      }
      const documentTitle = host.getAttribute(WB_DOCUMENT_TITLE_ATTR)?.trim() || undefined;
      return { documentId, documentTitle };
    } catch {
      return {};
    }
  }

  private detectDocumentFromUrl(): DocumentContext {
    try {
      const params = new URLSearchParams(window.location.search);
      const documentId =
        params.get('document_id')?.trim() || params.get('id')?.trim() || undefined;
      if (!documentId) {
        return {};
      }
      return { documentId };
    } catch {
      return {};
    }
  }
}
