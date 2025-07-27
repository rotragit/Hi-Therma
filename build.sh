#!/bin/bash
# Script di build e deployment per Hisense H-NET Decoder

set -e

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Funzioni helper
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Configurazione
IMAGE_NAME="hisense-hnet-decoder"
CONTAINER_NAME="hisense-hnet-decoder"
VERSION="1.0"

# Funzione di help
show_help() {
    cat << EOF
🏠 Hisense H-NET Decoder - Build Script

Utilizzo: $0 [OPZIONE]

OPZIONI:
  build     Costruisce l'immagine Docker
  run       Avvia il container
  stop      Ferma il container
  restart   Riavvia il container
  logs      Mostra i log del container
  clean     Rimuove container e immagine
  compose   Avvia con docker-compose
  test      Esegue test di funzionamento
  help      Mostra questo messaggio

ESEMPI:
  $0 build          # Costruisce l'immagine
  $0 compose        # Avvia tutti i servizi
  $0 logs           # Mostra log in tempo reale
EOF
}

# Verifica Docker
check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker non trovato. Installare Docker prima di continuare."
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        log_error "Docker daemon non in esecuzione."
        exit 1
    fi
    
    log_info "Docker OK"
}

# Build immagine
build_image() {
    log_info "Costruzione immagine Docker..."
    
    docker build \
        --tag "${IMAGE_NAME}:${VERSION}" \
        --tag "${IMAGE_NAME}:latest" \
        --build-arg VERSION="${VERSION}" \
        .
    
    log_success "Immagine costruita: ${IMAGE_NAME}:${VERSION}"
}

# Avvia container
run_container() {
    log_info "Avvio container..."
    
    # Ferma container esistente se presente
    if docker ps -q -f name="${CONTAINER_NAME}" | grep -q .; then
        log_warning "Container già in esecuzione, riavvio..."
        docker stop "${CONTAINER_NAME}" || true
        docker rm "${CONTAINER_NAME}" || true
    fi
    
    # Crea directory per log se non esistente
    mkdir -p ./logs
    
    # Avvia nuovo container
    docker run -d \
        --name "${CONTAINER_NAME}" \
        --restart unless-stopped \
        -e MQTT_BROKER="${MQTT_BROKER:-localhost}" \
        -e MQTT_PORT="${MQTT_PORT:-1883}" \
        -e MQTT_TOPIC="${MQTT_TOPIC:-hisense/hnet/raw}" \
        -e PUBLISH_PREFIX="${PUBLISH_PREFIX:-PDC}" \
        -e LOG_LEVEL="${LOG_LEVEL:-INFO}" \
        -v "$(pwd)/logs:/app/logs" \
        -v "$(pwd)/config:/app/config:ro" \
	-v "$(pwd)/src:/app/src:ro" \
        "${IMAGE_NAME}:latest"
    
    log_success "Container avviato: ${CONTAINER_NAME}"
}

# Ferma container
stop_container() {
    log_info "Arresto container..."
    
    if docker ps -q -f name="${CONTAINER_NAME}" | grep -q .; then
        docker stop "${CONTAINER_NAME}"
        docker rm "${CONTAINER_NAME}"
        log_success "Container arrestato"
    else
        log_warning "Container non in esecuzione"
    fi
}

# Riavvia container
restart_container() {
    stop_container
    run_container
}

# Mostra log
show_logs() {
    log_info "Log del container (Ctrl+C per uscire):"
    docker logs -f "${CONTAINER_NAME}" 2>&1 || {
        log_error "Container non trovato o non in esecuzione"
        exit 1
    }
}

# Pulizia completa
clean_all() {
    log_warning "Rimozione container e immagini..."
    
    # Ferma e rimuovi container
    docker stop "${CONTAINER_NAME}" 2>/dev/null || true
    docker rm "${CONTAINER_NAME}" 2>/dev/null || true
    
    # Rimuovi immagini
    docker rmi "${IMAGE_NAME}:${VERSION}" 2>/dev/null || true
    docker rmi "${IMAGE_NAME}:latest" 2>/dev/null || true
    
    # Pulisci immagini dangling
    docker image prune -f
    
    log_success "Pulizia completata"
}

# Avvia con docker-compose
compose_up() {
    log_info "Avvio servizi con docker-compose..."
    
    if ! command -v docker-compose &> /dev/null; then
        log_error "docker-compose non trovato"
        exit 1
    fi
    
    # Crea file .env se non esiste
    if [ ! -f .env ]; then
        log_warning "File .env non trovato, creazione da template..."
        cp .env.example .env
        log_info "Modifica il file .env prima di riavviare"
    fi
    
    # Avvia servizi
    docker-compose up -d
    
    log_success "Servizi avviati con docker-compose"
    log_info "Usa 'docker-compose logs -f' per vedere i log"
}

# Test di funzionamento
test_deployment() {
    log_info "Test del deployment..."
    
    # Verifica container in esecuzione
    if ! docker ps -q -f name="${CONTAINER_NAME}" | grep -q .; then
        log_error "Container non in esecuzione"
        exit 1
    fi
    
    # Verifica health check
    log_info "Esecuzione health check..."
    if docker exec "${CONTAINER_NAME}" python src/healthcheck.py; then
        log_success "Health check superato"
    else
        log_error "Health check fallito"
        exit 1
    fi
    
    # Verifica log
    log_info "Verifica log..."
    if docker exec "${CONTAINER_NAME}" ls -la /app/logs/hnet_decoder.log &> /dev/null; then
        log_success "File di log presente"
    else
        log_warning "File di log non trovato (normale al primo avvio)"
    fi
    
    log_success "Test completato con successo!"
}

# Main script
main() {
    echo "🏠 Hisense H-NET Decoder - Build Script"
    echo "========================================"
    
    # Carica variabili d'ambiente se presente
    if [ -f .env ]; then
        source .env
        log_info "Variabili d'ambiente caricate da .env"
    fi
    
    case "${1:-help}" in
        build)
            check_docker
            build_image
            ;;
        run)
            check_docker
            run_container
            ;;
        stop)
            check_docker
            stop_container
            ;;
        restart)
            check_docker
            restart_container
            ;;
        logs)
            check_docker
            show_logs
            ;;
        clean)
            check_docker
            clean_all
            ;;
        compose)
            check_docker
            compose_up
            ;;
        test)
            check_docker
            test_deployment
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            log_error "Opzione non riconosciuta: $1"
            show_help
            exit 1
            ;;
    esac
}

# Esegui script
main "$@"
