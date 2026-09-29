from yomiscan.japanese import hiragana

from .base import JapaneseToken, TokenizerError


def _value(value: str | None) -> str | None:
    return value if value and value != "*" else None


class FugashiTokenizer:
    def __init__(self) -> None:
        try:
            from fugashi import Tagger
            import unidic_lite

            # Explicitly select the bundled dictionary, even if full UniDic is installed.
            self._tagger = Tagger(f'-d "{unidic_lite.DICDIR}"')
        except (ImportError, RuntimeError) as exc:
            raise TokenizerError(f"Cannot initialize fugashi/UniDic-lite; run uv sync: {exc}") from exc

    def tokenize(self, text: str) -> list[JapaneseToken]:
        if not text.strip():
            return []
        try:
            words = self._tagger(text)
        except RuntimeError as exc:
            raise TokenizerError(f"Japanese tokenization failed: {exc}") from exc
        tokens = []
        for word in words:
            f = word.feature
            # kana preserves written readings (ダイジョウブ); pron may use ダイジョーブ.
            reading = _value(f.kana)
            base_reading = _value(f.kanaBase)
            tokens.append(JapaneseToken(
                surface=word.surface,
                lemma=_value(f.lemma),
                reading=hiragana(reading) if reading else None,
                part_of_speech=" / ".join(
                    p for p in (f.pos1, f.pos2, f.pos3, f.pos4) if _value(p)
                ) or None,
                conjugation_type=_value(f.cType),
                conjugation_form=_value(f.cForm),
                orthographic_base=_value(f.orthBase),
                lemma_reading=hiragana(base_reading) if base_reading else None,
            ))
        return tokens
