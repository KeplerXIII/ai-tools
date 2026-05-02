from enum import StrEnum


class LLMTask(StrEnum):
    SUMMARY = "summary"
    SUMMARY_REFINE = "summary_refine"
    TRANSLATION = "translation"
    TAGGING = "tagging"
    ENTITY_EXTRACTION = "entity_extraction"
