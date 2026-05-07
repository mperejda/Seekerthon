FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV SOLANA_VERSION=1.18.26
ENV ANCHOR_VERSION=0.30.1
ENV NODE_VERSION=20
ENV RUST_TOOLCHAIN=nightly-2024-11-22

# System deps
RUN apt-get update && apt-get install -y \
    curl git build-essential pkg-config libssl-dev libudev-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Rust (stable bootstrapper, then pin the project toolchain)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --default-toolchain stable --no-modify-path
ENV PATH="/root/.cargo/bin:$PATH"

RUN rustup toolchain install ${RUST_TOOLCHAIN} --component rustfmt --component clippy \
    && rustup target add wasm32-unknown-unknown --toolchain ${RUST_TOOLCHAIN}

# Solana CLI
RUN curl -sSfL "https://release.solana.com/v${SOLANA_VERSION}/install" | sh \
    && ln -sf /root/.local/share/solana/install/active_release/bin/* /usr/local/bin/

# Node.js + yarn (required by Anchor CLI)
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g yarn \
    && rm -rf /var/lib/apt/lists/*

# AVM + Anchor
RUN cargo install --git https://github.com/coral-xyz/anchor avm --locked --force \
    && ln -sf /root/.cargo/bin/avm /usr/local/bin/avm
RUN avm install ${ANCHOR_VERSION} && avm use ${ANCHOR_VERSION} \
    && ln -sf /root/.avm/bin/anchor /usr/local/bin/anchor

WORKDIR /workspace

CMD ["/bin/bash"]
