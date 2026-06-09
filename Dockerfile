FROM python:3.12-slim

# System deps: curl (used by enrichment.py to download CSVs), ca-certificates for SSL
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY config.py run.py entrypoint.sh ./
COPY lib/ lib/
COPY scrapers/ scrapers/
COPY web/ web/

# Create data and logs directories
RUN mkdir -p data logs

# Static data file needed by tender renewals engine
COPY data/security_product_tenders.json data/

RUN chmod +x entrypoint.sh

# Expose dashboard port
EXPOSE 8081

# Health check against the FastAPI /api/health endpoint
#HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
#    CMD curl -f http://localhost:8081/api/health || exit 1

# Run dashboard + scraper scheduler
CMD ["./entrypoint.sh"]
