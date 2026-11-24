# Stage 2 spike: full OCR browser matrix, one fresh Chrome per configuration (clean memory peaks).
# Run from research/stage-2/browser:  powershell -NoProfile -File run-matrix.ps1
$configs = @(
  "fp32:webgpu:greedy", "fp16:webgpu:greedy", "fp16:webgpu:beam", "int8:webgpu:greedy", "q4:webgpu:greedy", "q4:webgpu:beam",
  "fp32:wasm:greedy", "fp16:wasm:greedy", "int8:wasm:greedy", "int8:wasm:beam", "q4:wasm:greedy",
  "int8:wasm:greedy:t4", "q4:wasm:greedy:t4"
)
foreach ($config in $configs) {
  $name = "ocr-" + ($config -replace ":", "-")
  node run-browser.mjs --configs $config --out $name 2>&1 | Select-Object -Last 1
}
