FROM python:3.11-slim
WORKDIR /app

# Generate requirements from pyproject to keep Docker/CI in sync
COPY pyproject.toml ./
COPY scripts/generate_requirements.py ./scripts/generate_requirements.py
RUN python scripts/generate_requirements.py --output requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8888
ENTRYPOINT ["python", "src/main.py"]
CMD []