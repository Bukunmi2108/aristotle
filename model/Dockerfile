FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG MODEL_REPO_ID=Qwen/Qwen3-8B-GGUF
ARG MODEL_FILENAME=Qwen3-8B-Q4_K_M.gguf
ARG MODEL_DIR=/models
ARG LLAMA_CPP_REF=master

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    curl \
    ca-certificates \
    libcurl4-openssl-dev \
    libssl-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

RUN mkdir -p /opt/llama.cpp \
    && echo "Downloading llama.cpp source archive: ${LLAMA_CPP_REF}" \
    && curl \
        --location \
        --fail \
        --show-error \
        --progress-bar \
        --retry 3 \
        --retry-delay 5 \
        --connect-timeout 30 \
        "https://github.com/ggml-org/llama.cpp/archive/${LLAMA_CPP_REF}.tar.gz" \
        --output /tmp/llama.cpp.tar.gz \
    && tar -xzf /tmp/llama.cpp.tar.gz --strip-components=1 -C /opt/llama.cpp \
    && rm /tmp/llama.cpp.tar.gz \
    && cd /opt/llama.cpp \
    && cmake -B build -DLLAMA_CURL=ON -DLLAMA_OPENSSL=ON \
    && cmake --build build --config Release --target llama-server -j"$(nproc)"

ENV PATH="/opt/llama.cpp/build/bin:${PATH}"

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
    && echo "  MODEL_REPO_ID=${MODEL_REPO_ID}" \
    && echo "  MODEL_FILENAME=${MODEL_FILENAME}" \
    && echo "  MODEL_URL=${MODEL_URL}" \
    && echo "  MODEL_PATH=${MODEL_PATH}" \
    && echo "============================================================" \
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
