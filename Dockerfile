FROM python:3.12-slim

WORKDIR /opt/mobiletrace

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source
COPY . .

# AIFT shared mobile modules go to /aift_mobile (mounted at runtime)
RUN mkdir -p /aift_mobile

ENV PYTHONPATH="/opt/mobiletrace:/aift_mobile"
ENV MOBILETRACE_DB_PATH="/opt/mobiletrace/data/mobiletrace.db"
ENV FLASK_APP="app"

EXPOSE 5001

CMD ["python", "-m", "flask", "run", "--host=0.0.0.0", "--port=5001"]
