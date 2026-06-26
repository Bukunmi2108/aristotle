---
title: Aristotle Model
emoji: 🌖
colorFrom: red
colorTo: yellow
sdk: docker
pinned: false
---

# Aristotle Model Service

Dockerized `llama.cpp` server for Aristotle's OpenAI-compatible model endpoint.

## Current Model

- Repo: `nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF`
- File: `NVIDIA-Nemotron3-Nano-4B-Q4_K_M.gguf`
- Context: `32768`
- Parallel slots: `1`
- Threads: `2`

The image bakes the GGUF into `/models`, so cold starts load the local file instead of downloading it again.

## Local Build

```sh
docker build -t aristotle-model ./model
```

## Local Run

```sh
docker run --rm -p 8200:7860 aristotle-model
```

Check:

```sh
curl http://localhost:8200/v1/models
```

Smoke test:

```sh
MODEL_BASE_URL=http://localhost:8200 ./model/scripts/smoke.sh
```

## Hosted

```text
https://bukunmi2108-aristotle-model.hf.space
```

OpenAI-compatible endpoints:

```text
GET  /v1/models
POST /v1/chat/completions
```

The model exposes thinking in `reasoning_content`, which Aristotle's agent runtime should preserve separately from final assistant content.
