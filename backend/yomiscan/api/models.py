from pydantic import BaseModel

from yomiscan.analysis import ImageAnalysisResult


class ProcessingTimes(BaseModel):
    ocr_ms: float
    translation_ms: float
    analysis_ms: float
    total_ms: float


class Meaning(BaseModel):
    entry_id: int
    glosses: list[str]
    parts_of_speech: list[str]
    spellings: list[str]
    readings: list[str]
    notes: list[str]
    labels: list[str]


class TokenResponse(BaseModel):
    surface: str
    reading: str | None
    lemma: str | None
    dictionary_form: str | None
    part_of_speech: str | None
    conjugation_type: str | None
    conjugation_form: str | None
    meanings: list[Meaning]


class ImageAnalysisResponse(BaseModel):
    original_text: str
    translation: str | None
    processing: ProcessingTimes
    tokens: list[TokenResponse]

    @classmethod
    def from_result(cls, result: ImageAnalysisResult, total_ms: float) -> "ImageAnalysisResponse":
        analysis = result.analysis
        return cls(
            original_text=analysis.original_text,
            translation=analysis.translation.translated_text if analysis.translation else None,
            processing=ProcessingTimes(
                ocr_ms=result.ocr.processing_time_ms,
                translation_ms=analysis.translation.processing_time_ms if analysis.translation else 0,
                analysis_ms=analysis.processing_time_ms, total_ms=total_ms,
            ),
            tokens=[TokenResponse(
                surface=item.token.surface, reading=item.token.reading, lemma=item.token.lemma,
                dictionary_form=item.lookup_form or item.token.orthographic_base or item.token.lemma,
                part_of_speech=item.token.part_of_speech,
                conjugation_type=item.token.conjugation_type,
                conjugation_form=item.token.conjugation_form,
                meanings=[Meaning(entry_id=entry_id, **sense.__dict__)
                          for entry_id in item.entry_ids
                          for sense in analysis.dictionary_entries[entry_id].senses],
            ) for item in analysis.tokens],
        )
