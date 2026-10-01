# Multi-stage, lightweight, secure container for SHADE Robot Node
FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml setup.py /app/
COPY shade /app/shade

RUN pip install --no-cache-dir --upgrade pip && \
    pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels .

# Final runtime image
FROM python:3.12-slim AS runner

WORKDIR /app

# Create non-root user for container security
RUN useradd -m -u 1000 shade && \
    chown -R shade:shade /app

COPY --from=builder /app/wheels /app/wheels
RUN pip install --no-cache-dir /app/wheels/* && rm -rf /app/wheels

USER shade

# Defaults
ENV ROBOT_ID=0 \
    INIT_X=10.0 \
    INIT_Y=10.0 \
    BATTERY=100.0 \
    PORT=8080 \
    GOSSIP_PORT=9999 \
    THETA=0.25 \
    LEASE=6.0

EXPOSE 8080 9999/udp

# Standard container healthcheck
HEALTHCHECK --interval=5s --timeout=3s --start-period=3s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

ENTRYPOINT ["python3", "-m", "shade.cli", "node"]
CMD ["--robot-id", "0", "--port", "8080"]
