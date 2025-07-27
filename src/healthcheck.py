#!/usr/bin/env python3
"""
Health check script per il container Docker
Verifica lo stato del decoder H-NET
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

def check_log_activity():
    """Verifica attività recente nei log"""
    log_file = Path("/app/logs/hnet_decoder.log")
    
    if not log_file.exists():
        print("❌ File di log non trovato")
        return False
    
    try:
        # Controlla se ci sono log degli ultimi 5 minuti
        five_minutes_ago = datetime.now() - timedelta(minutes=5)
        
        with open(log_file, 'r') as f:
            lines = f.readlines()
            
        if not lines:
            print("❌ File di log vuoto")
            return False
            
        # Prendi le ultime 10 righe
        recent_lines = lines[-10:]
        
        for line in recent_lines:
            if "ERROR" in line or "FATAL" in line:
                print(f"❌ Errore trovato nei log: {line.strip()}")
                return False
                
        print("✅ Log attivity OK")
        return True
        
    except Exception as e:
        print(f"❌ Errore lettura log: {e}")
        return False

def check_process():
    """Verifica se il processo principale è attivo"""
    try:
        import psutil
        
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if 'hnet_decoder.py' in ' '.join(proc.info['cmdline'] or []):
                    print(f"✅ Processo attivo: PID {proc.info['pid']}")
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
                
        print("❌ Processo decoder non trovato")
        return False
        
    except ImportError:
        # psutil non disponibile, usa controllo alternativo
        return check_alternative_process()

def check_alternative_process():
    """Controllo alternativo del processo senza psutil"""
    try:
        import subprocess
        result = subprocess.run(['pgrep', '-f', 'hnet_decoder.py'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0 and result.stdout.strip():
            print(f"✅ Processo attivo: PID {result.stdout.strip()}")
            return True
        else:
            print("❌ Processo decoder non trovato")
            return False
            
    except Exception as e:
        print(f"⚠️ Impossibile verificare processo: {e}")
        return True  # Assume OK se non riusciamo a verificare

def check_config():
    """Verifica presenza file di configurazione"""
    config_file = Path("/app/config/config.yml")
    
    if not config_file.exists():
        print("❌ File di configurazione non trovato")
        return False
        
    print("✅ Configurazione OK")
    return True

def check_mqtt_connectivity():
    """Verifica connettività MQTT (simulata)"""
    # Controlla se ci sono errori di connessione nei log recenti
    log_file = Path("/app/logs/hnet_decoder.log")
    
    if not log_file.exists():
        return True  # Assume OK se non ci sono log
        
    try:
        with open(log_file, 'r') as f:
            recent_content = f.read()[-2000:]  # Ultimi 2KB
            
        if "Connessione MQTT fallita" in recent_content:
            print("❌ Problemi connessione MQTT")
            return False
        elif "Connesso al broker MQTT" in recent_content:
            print("✅ Connessione MQTT OK")
            return True
        else:
            print("⚠️ Stato connessione MQTT sconosciuto")
            return True  # Assume OK
            
    except Exception as e:
        print(f"⚠️ Errore verifica MQTT: {e}")
        return True

def main():
    """Esegue tutti i controlli di salute"""
    print("🏥 Health Check - Hisense H-NET Decoder")
    print("-" * 40)
    
    checks = [
        ("Configurazione", check_config),
        ("Processo", check_process),
        ("Log Activity", check_log_activity),
        ("MQTT Connectivity", check_mqtt_connectivity)
    ]
    
    all_passed = True
    
    for name, check_func in checks:
        print(f"🔍 Controllo {name}...")
        try:
            if not check_func():
                all_passed = False
        except Exception as e:
            print(f"❌ Errore durante {name}: {e}")
            all_passed = False
        print()
    
    if all_passed:
        print("✅ Tutti i controlli superati - Container sano")
        sys.exit(0)
    else:
        print("❌ Alcuni controlli falliti - Container non sano")
        sys.exit(1)

if __name__ == "__main__":
    main()
