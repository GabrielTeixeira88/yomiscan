"""Shared kana normalization; does not guess long vowels or romanize text."""

import unicodedata


def hiragana(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)
