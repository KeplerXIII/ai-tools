import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';

export interface TranslateResponse {
  translation: string;
  source_lang?: string;
  target_lang?: string;
}

export interface TranslateStreamResponse {
  translation: string;
  source_lang: string | null;
  target_lang: string | null;
}

@Injectable({
  providedIn: 'root',
})
export class TranslateApi {
  private readonly apiUrl = '/api/v1/translate';

  constructor(private http: HttpClient) {}

  translate(text: string) {
    return this.http.post<TranslateResponse>(this.apiUrl, {
      text,
      target_lang: 'ru',
    });
  }

  async translateStream(
    text: string,
    onChunk: (chunk: string) => void,
  ): Promise<TranslateStreamResponse> {
    const response = await fetch(`${this.apiUrl}/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify({
        text,
        target_lang: 'ru',
      }),
    });

    if (!response.ok) {
      throw new Error(`Ошибка перевода: ${response.status}`);
    }

    const sourceLang = response.headers.get('X-Source-Lang');
    const targetLang = response.headers.get('X-Target-Lang');

    if (!response.body) {
      throw new Error('Пустой streaming response body');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');

    let translation = '';
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();

      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmedLine = line.trim();

        if (trimmedLine.startsWith('event: error')) {
          throw new Error('Ошибка потокового перевода');
        }

        if (!trimmedLine.startsWith('data:')) {
          continue;
        }

        const data = trimmedLine.replace(/^data:\s?/, '');

        if (data === '[DONE]') {
          return {
            translation,
            source_lang: sourceLang,
            target_lang: targetLang,
          };
        }

        translation += data;
        onChunk(data);
      }
    }

    return {
      translation,
      source_lang: sourceLang,
      target_lang: targetLang,
    };
  }
}
