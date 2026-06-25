FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG MODEL_REPO_ID=Qwen/Qwen3-8B-GGUF
ARG MODEL_FILENAME=Qwen3-8B-Q4_K_M.gguf
ARG MODEL_DIR=/models
ARG BAKE_MODEL=true
ARG LLAMA_CPP_VERSION=b9789
ARG LLAMA_CPP_ARCHIVE=llama-b9789-bin-ubuntu-x64.tar.gz

RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

RUN mkdir -p /opt/llama.cpp \
    && LLAMA_CPP_URL="https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_CPP_VERSION}/${LLAMA_CPP_ARCHIVE}" \
    && echo "Downloading llama.cpp release archive:" \
    && echo "  ${LLAMA_CPP_URL}" \
    && curl \
        --location \
        --fail \
        --show-error \
        --progress-bar \
        --retry 3 \
        --retry-delay 5 \
        --connect-timeout 30 \
        "$LLAMA_CPP_URL" \
        --output /tmp/llama.cpp-bin.tar.gz \
    && tar -xzf /tmp/llama.cpp-bin.tar.gz --strip-components=1 -C /opt/llama.cpp \
    && rm /tmp/llama.cpp-bin.tar.gz \
    && chmod +x /opt/llama.cpp/llama-server \
    && /opt/llama.cpp/llama-server --version

ENV PATH="/opt/llama.cpp:${PATH}" \
    LD_LIBRARY_PATH="/opt/llama.cpp"

ENV MODEL_REPO_ID="${MODEL_REPO_ID}" \
    MODEL_FILENAME="${MODEL_FILENAME}" \
    MODEL_DIR="${MODEL_DIR}" \
    MODEL_NAME="aristotle-local" \
    MODEL_CONTEXT_SIZE="4096" \
    MODEL_THREADS="2" \
    MODEL_PARALLEL="1" \
    MODEL_PORT="7860"

RUN mkdir -p "$MODEL_DIR" \
    && MODEL_URL="https://huggingface.co/${MODEL_REPO_ID}/resolve/main/${MODEL_FILENAME}" \
    && MODEL_PATH="${MODEL_DIR}/${MODEL_FILENAME}" \
    && echo "============================================================" \
    && echo "Baking Aristotle model into image" \
    && echo "  BAKE_MODEL=${BAKE_MODEL}" \
    && echo "  MODEL_REPO_ID=${MODEL_REPO_ID}" \
    && echo "  MODEL_FILENAME=${MODEL_FILENAME}" \
    && echo "  MODEL_URL=${MODEL_URL}" \
    && echo "  MODEL_PATH=${MODEL_PATH}" \
    && echo "============================================================" \
    && if [ "$BAKE_MODEL" != "true" ]; then \
        echo "BAKE_MODEL is not true. Skipping model download."; \
        exit 0; \
    fi \
    && curl \
        --location \
        --fail \
        --show-error \
        --progress-bar \
        --retry 3 \
        --retry-delay 5 \
        --connect-timeout 30 \
        "$MODEL_URL" \
        --output "${MODEL_PATH}.part" \
    && mv "${MODEL_PATH}.part" "$MODEL_PATH" \
    && echo "Baked model file details:" \
    && ls -lh "$MODEL_PATH" \
    && du -h "$MODEL_PATH"

WORKDIR /app
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 7860

CMD ["/app/start.sh"]
