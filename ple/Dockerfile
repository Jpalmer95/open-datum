# Multi-stage offline-ready container for PLE (Physical-Engineering's Last Exam)
# Builds the static Rust `odatum` binary and installs OpenDatum's zero-internet MCP server & solvers.

FROM rust:1.83-slim AS rust-builder
WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
RUN cargo build --release --bin odatum

FROM python:3.12-slim AS runtime
WORKDIR /app

COPY --from=rust-builder /build/target/release/odatum /usr/local/bin/odatum
COPY pyproject.toml README.md LICENSE ./
COPY python ./python
COPY data ./data
COPY ple ./ple

# Install OpenDatum (zero required deps; optional CAD/BIM extras install cleanly at build time)
RUN pip install --no-cache-dir -e . && \
    pip install --no-cache-dir ezdxf trimesh || true

ENV OPENDATUM_OFFLINE=1
ENV PYTHONPATH=/app/python:/app

# Default entrypoint exposes the PLE JSON-RPC / MCP harness bridge
ENTRYPOINT ["python3", "ple/serve.py"]
