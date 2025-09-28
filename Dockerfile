FROM python:3.11-slim

WORKDIR /app

# Install uv without pip
RUN apt-get update \
	&& apt-get install -y --no-install-recommends curl ca-certificates \
	&& rm -rf /var/lib/apt/lists/* \
	&& curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:${PATH}"

COPY pyproject.toml uv.lock ./

# Sync production dependencies into a virtual environment managed by uv
RUN uv sync --frozen --no-dev

# Make virtualenv the default interpreter for subsequent commands
ENV PATH="/app/.venv/bin:${PATH}"

COPY . .

EXPOSE 8888

ENTRYPOINT ["python", "src/main.py"]
CMD []