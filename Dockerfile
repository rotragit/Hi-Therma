# Dockerfile per Hisense H-NET Protocol Decoder
FROM python:3.11-slim

# Metadata
LABEL maintainer="Hisense H-NET Decoder"
LABEL description="Decoder per protocollo Hisense H-NET con pubblicazione MQTT"
LABEL version="1.0"

# Imposta directory di lavoro
WORKDIR /app

# Installa dipendenze di sistema
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia i file requirements
COPY requirements.txt .

# Installa dipendenze Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia il codice sorgente
COPY src/ ./src/
COPY config/ ./config/

# Crea utente non-root per sicurezza
RUN useradd -m -u 1000 hnet && \
    chown -R hnet:hnet /app
USER hnet

# Espone porta per health check (opzionale)
EXPOSE 8080

# Variabili d'ambiente di default
ENV MQTT_BROKER=localhost
ENV MQTT_PORT=1883
ENV MQTT_TOPIC=hisense/hnet/raw
ENV MQTT_USER=""
ENV MQTT_PASSWORD=""
ENV PUBLISH_PREFIX=PDC
ENV LOG_LEVEL=INFO

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python src/healthcheck.py || exit 1

# Comando di avvio
CMD ["python", "src/hnet_decoder.py"]
