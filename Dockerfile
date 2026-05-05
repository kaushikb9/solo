FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Trust custom CA certs (e.g. Zscaler) if present
COPY certs/ /usr/local/share/ca-certificates/custom/
RUN if ls /usr/local/share/ca-certificates/custom/*.pem 1>/dev/null 2>&1; then \
      for f in /usr/local/share/ca-certificates/custom/*.pem; do \
        cp "$f" "/usr/local/share/ca-certificates/$(basename "$f" .pem).crt"; \
      done && \
      update-ca-certificates; \
    fi

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY src/ src/

CMD ["uv", "run", "python", "-m", "solo"]
