FROM python:3.11-slim

WORKDIR /app

COPY . /app

RUN pip install uv && uv pip install --no-cache-dir -r requirements.txt --system

# Make port 8888 available to the world outside this container
# This is for the Spotify OAuth callback
EXPOSE 8888

# Create a volume for persistent storage of the SQLite database
VOLUME /app/data

# Set permissions for the data directory
RUN mkdir -p /app/data && chmod 777 /app/data

CMD []