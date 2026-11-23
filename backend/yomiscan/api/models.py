from pydantic import BaseModel

from yomiscan.analysis import ImageAnalysisResult, TextAnalysisResult
from yomiscan.ocr import OCRResult
from yomiscan.page import PageAnalysisResult


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
    target_language: str = "en"
    dictionary_language: str = "en"
    provenance: dict[str, object] = {}

    @classmethod
    def from_result(cls, result: ImageAnalysisResult, total_ms: float) -> "ImageAnalysisResponse":
        response = cls.from_analysis(result.analysis, ocr_ms=result.ocr.processing_time_ms, total_ms=total_ms)
        study = result.ocr.metadata.get("study_ocr")
        if isinstance(study, dict):
            # Allowlisted, text-free fields only: how the selection was read.
            response.provenance["study_ocr"] = {key: study[key] for key in ("mode", "blocks", "reason") if key in study}
        return response

    @classmethod
    def from_analysis(cls, analysis: TextAnalysisResult, *, ocr_ms: float = 0, total_ms: float = 0, origin: str = "study") -> "ImageAnalysisResponse":
        from ..diagnostics import model_info
        translation = analysis.translation
        return cls(
            original_text=analysis.original_text,
            translation=analysis.translation.translated_text if analysis.translation else None,
            target_language=str(analysis.translation.metadata.get("requested_target", analysis.translation.metadata.get("target_language", "en")))
                if analysis.translation else "en",
            processing=ProcessingTimes(
                ocr_ms=ocr_ms,
                translation_ms=analysis.translation.processing_time_ms if analysis.translation else 0,
                analysis_ms=analysis.processing_time_ms, total_ms=total_ms,
            ),
            provenance=(model_info({"engine": translation.engine, "model": translation.model, **translation.metadata}) if translation else {})|{"analysis_origin": origin},
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


class BoxResponse(BaseModel):
    left: int
    top: int
    right: int
    bottom: int


class BlockResponse(BaseModel):
    id: int
    region_ids: list[int]
    bbox: BoxResponse
    orientation: str
    reading_order: int
    original_text: str
    translation: str | None
    tokens: list[TokenResponse]
    confidence: float | None
    category: str
    status: str
    error_message: str | None


class PageProcessingTimes(ProcessingTimes):
    detection_ms: float


class PageAnalysisResponse(BaseModel):
    width: int
    height: int
    regions_detected: int
    regions_filtered: int
    text_blocks: list[BlockResponse]
    processing: PageProcessingTimes

    @classmethod
    def from_result(cls, result: PageAnalysisResult) -> "PageAnalysisResponse":
        blocks = []
        for block in result.text_blocks:
            # Reuse the stable Study Mode lexical DTO mapping.
            analysis = ImageAnalysisResponse.from_result(
                ImageAnalysisResult(OCRResult(block.original_text, "page", 0), block.analysis), 0,
            ) if block.analysis is not None else None
            blocks.append(BlockResponse(
                id=block.id, region_ids=list(block.region_ids), bbox=BoxResponse(**block.bbox.__dict__),
                orientation=block.orientation, reading_order=block.reading_order,
                original_text=block.original_text, translation=analysis.translation if analysis else None,
                tokens=analysis.tokens if analysis else [], confidence=block.confidence,
                category=block.category, status=block.status, error_message=block.error_message,
            ))
        return cls(width=result.width, height=result.height, regions_detected=len(result.regions),
                   regions_filtered=len(result.filtered_regions), text_blocks=blocks,
                   processing=PageProcessingTimes(**result.processing.__dict__))
