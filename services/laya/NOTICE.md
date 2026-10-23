# Laya model service

Uses Laya 0.4.13 from https://github.com/NandhaKishorM/laya (Apache-2.0).
Checkpoint: https://huggingface.co/convaiinnovations/laya-multilingual (Apache-2.0).
Pinned revision: e4e9ddf21a7b1903b7acffd8814ad4307bf63a67.
Checkpoint model card/license files are retained in the image's model directory.
Orcha workflow policy v1 adapts only the checkpoint's final 768 scoring weights.
The 3,152-byte safetensors derivative and reproducible synthetic fitting scripts
are distributed under the upstream Apache-2.0 terms. The encoder and transformer
head are unchanged. See ../../docs/LAYA_REFINEMENT.md for scope and provenance.
Python/PyTorch/Transformers and their dependencies retain their own licenses.
