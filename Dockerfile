# STILL WIP

FROM python:3.11-slim

WORKDIR /app

COPY . /app

RUN pip install uv && uv pip install --no-cache-dir -r requirements.txt --system

EXPOSE 8888

VOLUME /app

RUN mkdir -p /app && chmod 777 /app

CMD []