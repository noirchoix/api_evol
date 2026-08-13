FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV AEA_ENVIRONMENT=production AEA_DATA_DIR=/data AEA_ALLOW_LOCAL_EXECUTION=0
RUN mkdir -p /data/repositories /data/artifacts
EXPOSE 8000
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8000"]
