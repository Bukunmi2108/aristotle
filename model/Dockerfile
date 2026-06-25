FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    curl \
    git \
    ca-certificates \
    libcurl4-openssl-dev \
    libssl-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

RUN git clone https://github.com/ggml-org/llama.cpp.git \
    && cd llama.cpp \
    && cmake -B build -DLLAMA_CURL=ON -DLLAMA_OPENSSL=ON \
    && cmake --build build --config Release -j"$(nproc)"

ENV PATH="/opt/llama.cpp/build/bin:${PATH}"

WORKDIR /app
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 7860

CMD ["/app/start.sh"]
