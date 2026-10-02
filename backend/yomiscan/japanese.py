"""Shared kana normalization; does not guess long vowels or romanize text."""

import unicodedata


def contains_japanese(text: str) -> bool:
    """Require a Japanese script character; punctuation alone is not language evidence."""
    text = unicodedata.normalize("NFKC", text)
    return any("\u3041" <= c <= "\u3096" or "\u30a1" <= c <= "\u30fa" or
               "\u3400" <= c <= "\u4dbf" or "\u4e00" <= c <= "\u9fff" or
               "\uf900" <= c <= "\ufaff" or "\U00020000" <= c <= "\U000323af"
               for c in text)


def is_japanese_punctuation(character: str) -> bool:
    return character in "、。・「」『』【】〈〉《》！？〜ー…‥"


def hiragana(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)
