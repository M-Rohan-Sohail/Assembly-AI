FROM python:3.11-slim

# Install system dependencies for audio (portaudio), TTS (espeak), and Node.js
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    portaudio19-dev \
    python3-dev \
    espeak \
    ffmpeg \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the entire backend pipeline
COPY . /app/

# Install Node.js dependencies for Person 2 Intelligence Server
RUN cd ts_intelligence && npm install

# Install Python dependencies for Person 1 & 3
RUN pip install --no-cache-dir -r python_core/requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# Expose the FastAPI WebSocket port (the Node server runs internally on 8787)
EXPOSE 8000

# Run the master orchestrator script which launches both Python API and Node.js server
CMD ["python", "main.py"]
