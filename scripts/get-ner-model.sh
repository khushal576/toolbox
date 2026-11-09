#!/usr/bin/env bash
# Downloads the name-finding model for the Text Editor's Mask → "Find names (AI)" into ./models/ner (git-ignored,
# ~115 MB, one time). The files are then served by the Text Editor itself, so no text ever leaves the browser and
# nothing is fetched from the internet when you use it. Needs internet only now. Re-run to repair a partial download.
set -euo pipefail
cd "$(dirname "$0")/.."
DEST=models/ner
TF=https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.5.2/dist
HF=https://huggingface.co/Xenova/bert-base-NER/resolve/main
M=$DEST/models/Xenova/bert-base-NER
mkdir -p "$M/onnx"
get() { # url dest — skip files that are already complete
  if [ -s "$2" ]; then echo "have  $2"; return; fi
  echo "get   $2"; curl -fL -sS --retry 3 -o "$2.part" "$1" && mv "$2.part" "$2"
}
get $TF/transformers.min.js                 $DEST/transformers.min.js
get $TF/ort-wasm-simd-threaded.jsep.mjs     $DEST/ort-wasm-simd-threaded.jsep.mjs
get $TF/ort-wasm-simd-threaded.jsep.wasm   $DEST/ort-wasm-simd-threaded.jsep.wasm
for f in config.json tokenizer.json tokenizer_config.json special_tokens_map.json; do get $HF/$f $M/$f; done
get $HF/onnx/model_quantized.onnx $M/onnx/model_quantized.onnx
echo "done: $(du -sh $DEST | cut -f1) in $DEST — restart rt-light: docker-compose up -d --force-recreate rt-light"
