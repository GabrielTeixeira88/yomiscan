# Local OCR samples

Do **not** commit copyrighted manga images. Place screenshots you may use locally in
this directory. `.gitignore` ignores all sample content except this README, including
nested directories and any local notes. Never force-add copyrighted samples.

Crop one speech bubble or text region into `samples/test.png` and run:

```powershell
uv run python scripts/ocr_image.py samples/test.png --cpu
```

Build a representative test set covering:

- Vertical speech bubble text and horizontal text
- Small text and large text
- White speech bubbles and text over artwork
- Furigana and unusual fonts
- Punctuation and stylized dialogue
- Sound effects

For each crop, record a manually checked expected transcription, actual OCR output,
image dimensions, category, CPU/GPU, and reported inference time in a local notes file.
Record omissions, substitutions, invented text, and punctuation differences. Include
some blank/no-text crops to observe hallucinations. Keep exact transcription comparisons
separate from comparisons that normalize spacing or punctuation.

Record model startup separately from inference. Rerunning the CLI reloads the model;
benchmark repeated recognition through one engine instance when measuring steady-state
latency. Once weights are cached, repeat with `HF_HUB_OFFLINE=1` to verify local operation.
Do not conclude reliability from a single successful screenshot.
