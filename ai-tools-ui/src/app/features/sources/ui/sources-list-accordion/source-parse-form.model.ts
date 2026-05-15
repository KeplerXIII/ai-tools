import { PostParseProcessingOptions } from '../../api/sources-api';
import { clampBoundedInteger } from './bounded-integer-input.util';

export interface SourceParseFormState {
  parseDays: number;
  parseSkipUndated: boolean;
  parsePostFullPipeline: boolean;
  parsePostLlmTagOriginal: boolean;
  parsePostLlmTranslate: boolean;
  parsePostLlmExtractor: boolean;
  parsePostLlmTagTranslated: boolean;
  parsePostLlmAnnotate: boolean;
  parsePostLlmCategorize: boolean;
  parsePostTargetLang: string;
  parsePostMaxTags: number;
}

export function createDefaultSourceParseFormState(): SourceParseFormState {
  return {
    parseDays: 3,
    parseSkipUndated: true,
    parsePostFullPipeline: true,
    parsePostLlmTagOriginal: false,
    parsePostLlmTranslate: false,
    parsePostLlmExtractor: false,
    parsePostLlmTagTranslated: false,
    parsePostLlmAnnotate: false,
    parsePostLlmCategorize: false,
    parsePostTargetLang: 'ru',
    parsePostMaxTags: 12,
  };
}

export function parsePostHasAnyGranular(form: SourceParseFormState): boolean {
  return (
    form.parsePostLlmTagOriginal ||
    form.parsePostLlmTranslate ||
    form.parsePostLlmExtractor ||
    form.parsePostLlmTagTranslated ||
    form.parsePostLlmAnnotate ||
    form.parsePostLlmCategorize
  );
}

export function parsePostShowLangAndMaxTags(form: SourceParseFormState): boolean {
  return form.parsePostFullPipeline || parsePostHasAnyGranular(form);
}

export function buildPostParsePayload(form: SourceParseFormState): PostParseProcessingOptions | undefined {
  const target_lang = (form.parsePostTargetLang || 'ru').trim().slice(0, 8) || 'ru';
  const max_tags = clampBoundedInteger(form.parsePostMaxTags, 1, 12, 12);
  if (form.parsePostFullPipeline) {
    return { full_llm_pipeline: true, target_lang, max_tags };
  }
  if (!parsePostHasAnyGranular(form)) {
    return undefined;
  }
  return {
    full_llm_pipeline: false,
    llm_tag_original: form.parsePostLlmTagOriginal || undefined,
    llm_translate: form.parsePostLlmTranslate || undefined,
    llm_extractor: form.parsePostLlmExtractor || undefined,
    llm_tag_translated: form.parsePostLlmTagTranslated || undefined,
    llm_annotate: form.parsePostLlmAnnotate || undefined,
    llm_categorize: form.parsePostLlmCategorize || undefined,
    target_lang,
    max_tags,
  };
}
