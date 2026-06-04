# ------------ Backend image ------------
FROM python:3.11-slim AS backend
WORKDIR /app/backend
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY backend/requirements.txt .
RUN pip install -r requirements.txt \
    && pip install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/

COPY backend/ .

EXPOSE 8001
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
