FROM python:3.14-slim

WORKDIR /app

# A small static ffmpeg, only used to cut a thumbnail frame out of uploaded videos
# (app/services/thumbnail_service.py). Pinned by digest so the build cannot change
# underneath us; Debian's ffmpeg package would add hundreds of MB of graphics libraries.
COPY --from=mwader/static-ffmpeg:7.1@sha256:a8090df5f5608daef387e1b2e93b98aaacb4d92153ad904e7d715c725724fca4 /ffmpeg /usr/local/bin/ffmpeg

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Migrations run before the server starts (see entrypoint.sh).
ENTRYPOINT ["bash", "/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
