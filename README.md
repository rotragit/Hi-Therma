# 🏠 Hisense H-NET Protocol Decoder

Decoder per il protocollo Hisense H-NET con supporto Docker e pubblicazione MQTT strutturata.

## 📋 Caratteristiche

- 🔍 **Decodifica completa** del protocollo H-NET (opcode 0xB1, 0xB6, 0xB8)
- 📡 **Pubblicazione MQTT** su topic strutturati `PDC/...`
- 🐳 **Container Docker** pronto per il deployment
- 📊 **Logging avanzato** con rotazione file
- ⚙️ **Configurazione YAML** flessibile
- 🏥 **Health check** integrato
- 🔄 **Reconnessione automatica** MQTT

## 🚀 Quick Start

### Con Docker Compose (Raccomandato)

1. **Clona o estrai l'archivio**
```bash
unzip hisense-hnet-decoder.zip
cd hisense-hnet-decoder
```

2. **Configura le variabili** (copia e modifica `.env`)
```bash
cp .env.example .env
nano .env
```

3. **Avvia i servizi**
```bash
docker-compose up -d
```

### Con Docker Build

```bash
# Build dell'immagine
docker build -t hisense-hnet-decoder .

# Esecuzione container
docker run -d \
  --name hnet-decoder \
  -e MQTT_BROKER=your-broker-ip \
  -e MQTT_TOPIC=hisense/hnet/raw \
  -e PUBLISH_PREFIX=PDC \
  -v ./logs:/app/logs \
  hisense-hnet-decoder
```

## ⚙️ Configurazione

### Variabili d'ambiente principali

```bash
# MQTT Broker
MQTT_BROKER=localhost          # IP del broker MQTT
MQTT_PORT=1883                 # Porta broker MQTT
MQTT_USER=                     # Username (opzionale)
MQTT_PASSWORD=                 # Password (opzionale)

# Topic
MQTT_TOPIC=hisense/hnet/raw    # Topic input per frame raw
PUBLISH_PREFIX=PDC             # Prefisso topic output

# Logging
LOG_LEVEL=INFO                 # DEBUG, INFO, WARNING, ERROR
```

### File di configurazione (`config/config.yml`)

Il decoder supporta configurazione avanzata tramite file YAML con:
- Mapping topic personalizzati
- Configurazioni MQTT avanzate
- Parametri protocollo H-NET
- Opzioni debug e logging

## 📡 Topic MQTT Pubblicati

### 🏠 Controller Interno (`PDC/indoor/...`)
- `status` - Stato connessione
- `operation_command` - Comando operativo
- `mode` - Modalità (HEATING/COOLING/AUTO)  
- `cycle_status` - Stato ciclo (ON/OFF)
- `water_setpoint` - Temperatura impostata acqua
- `dhw_setpoint` - Temperatura ACS
- `ambient_setpoint` - Temperatura ambiente
- `system_datetime` - Data/ora sistema

### 🏭 Unità Esterna (`PDC/outdoor/...`)
- `status` - Stato connessione
- `pump_status` - Stato pompa
- `inverter_frequency` - Frequenza inverter (Hz)
- `evo_current` - Corrente EVO (A)

### 🌡️ Sensori (`PDC/sensors/...`)
- `water_inlet_temperature` - Temp. acqua ingresso
- `water_outlet_temperature_1/2` - Temp. acqua uscita
- `heat_exchanger_outlet_temperature` - Temp. scambiatore
- `ambient_temperature` - Temp. ambiente
- `gas_ui_temperature` - Temp. gas UI
- `liquid_ui_temperature` - Temp. liquido UI
- `water_flow` - Flusso acqua
- `exhaust_temperature` - Temp. scarico

## 📊 Formato Dati

Ogni valore viene pubblicato con formato JSON:

```json
{
  "value": 25,
  "timestamp": "2025-07-26T14:30:00.123456",
  "unit": "°C"
}
```

## 🔍 Formato Frame Input

Il decoder supporta frame in formato:

**JSON Array:**
```json
[137, 0, 76, 1, 1, 1, 1, 1, 1, 182, ...]
```

**Stringa Esadecimale:**
```
89004C010101010101B6001A1C1C81811C...
```

## 📝 Logging

I log sono salvati in `/app/logs/`:
- `hnet_decoder.log` - Log principale
- `unknown_frames.log` - Frame non riconosciuti (se debug abilitato)

## 🏥 Monitoring

### Health Check
Il container include un health check automatico che verifica:
- Presenza processo decoder
- Attività nei log
- Connettività MQTT
- Configurazione

### Logs Docker
```bash
# Visualizza log container
docker logs hisense-hnet-decoder -f

# Visualizza log decoder
docker exec hisense-hnet-decoder tail -f /app/logs/hnet_decoder.log
```

## 🔧 Sviluppo

### Struttura Progetto
```
hisense-hnet-decoder/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── README.md
├── src/
│   ├── hnet_decoder.py      # Decoder principale
│   └── healthcheck.py       # Health check
├── config/
│   └── config.yml           # Configurazione YAML
├── logs/                    # Directory log
└── mosquitto/              # Config Mosquitto (opzionale)
```

### Build Locale
```bash
# Installazione dipendenze
pip install -r requirements.txt

# Esecuzione diretta
python src/hnet_decoder.py
```

## 🧪 Test

### Test Frame
Pubblica un frame di test sul topic MQTT:

```bash
mosquitto_pub -h localhost -t hisense/hnet/raw -m '[137,0,76,1,1,1,1,1,1,182,0,26,28,28,129,129,28,129,129,129,129,20,20,20,20,20,60,50,20,24,0,60,52,55,45,55,60,55,55,30,29,24,129,26,24,22,0,0,0,38,0,0,0,0,0,0,0,0,0,0,128,0,129,129,129,129,0,0,100,30,25,0,4,5,249,0,0,64]'
```

### Verifica Output
```bash
# Monitora topic output
mosquitto_sub -h localhost -t 'PDC/+/+' -v
```

## 🏡 Integrazione Home Assistant

I topic MQTT sono compatibili con Home Assistant. Esempio configurazione:

```yaml
sensor:
  - platform: mqtt
    name: "PDC Water Temperature"
    state_topic: "PDC/sensors/water_inlet_temperature"
    value_template: "{{ value_json.value }}"
    unit_of_measurement: "°C"
    device_class: temperature
```

## 🐛 Troubleshooting

### Container non si avvia
- Verifica configurazione MQTT in `.env`
- Controlla log: `docker logs hisense-hnet-decoder`
- Verifica connettività broker MQTT

### Nessun dato sui topic
- Verifica topic input configurato correttamente
- Controlla formato frame (JSON array o hex string)
- Abilita debug logging: `LOG_LEVEL=DEBUG`

### Errori checksum
- Frame corrotti o formato errato
- Controlla `logs/unknown_frames.log` per analisi

## 📚 Riferimenti

- **Articolo originale**: [Inside the Hisense H-NET Protocol](https://www.alessiovaleri.it/index.php/2025/07/09/inside-the-hisense-h-link-protocol-a-reverse-engineering-journey/)
- **Protocollo base**: Home Bus System (HBS)
- **MQTT**: [Eclipse Mosquitto](https://mosquitto.org/)

## 📄 Licenza

Progetto open source per scopi educativi e di integrazione domotica.

---

**🏠 Happy Home Automation!**
