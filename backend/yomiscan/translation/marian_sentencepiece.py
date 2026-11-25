"""MarianTokenizer's encode/decode for OPUS-MT without transformers (Stage 5b).

Source text -> source.spm pieces -> vocab.json ids (unknown pieces map to <unk>) + </s>.
Output ids -> vocab tokens with </s>, <unk> and <pad> skipped -> target.spm decode, "▁" -> space,
stripped.
On the 153-line translation set this matched MarianTokenizer exactly in both directions.
"""

import json
from pathlib import Path

SKIPPED = frozenset({"</s>", "<unk>", "<pad>"})


class MarianSentencePiece:
    def __init__(self, folder: Path) -> None:
        import sentencepiece

        self.source = sentencepiece.SentencePieceProcessor(model_file=str(folder / "source.spm"))
        self.target = sentencepiece.SentencePieceProcessor(model_file=str(folder / "target.spm"))
        self.vocabulary: dict[str, int] = json.loads((folder / "vocab.json").read_text(encoding="utf-8"))
        self.tokens = {index: token for token, index in self.vocabulary.items()}
        self.unk_id, self.eos_id, self.pad_id = (self.vocabulary[t] for t in ("<unk>", "</s>", "<pad>"))

    def encode(self, text: str) -> list[int]:
        pieces = self.source.encode(text, out_type=str)
        return [self.vocabulary.get(piece, self.unk_id) for piece in pieces] + [self.eos_id]

    def decode(self, ids: list[int]) -> str:
        pieces = [self.tokens[i] for i in ids if self.tokens.get(i) not in SKIPPED]
        # MarianTokenizer.convert_tokens_to_string also replaces any remaining "▁" with a space.
        return self.target.decode_pieces(pieces).replace("▁", " ").strip()
