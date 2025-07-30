#!/usr/bin/env python3
"""
Hisense H-NET Protocol Decoder - Enhanced Docker Version with Home Assistant Discovery
Decoder per il protocollo Hisense H-NET con supporto configurazione YAML, logging avanzato e Home Assistant Discovery
"""

import os
import sys
import json
import yaml
import logging
import signal
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union
from dotenv import load_dotenv

import paho.mqtt.client as mqtt

# Carica variabili d'ambiente
load_dotenv()

class HNetProtocolDecoder:
    """
    Decoder avanzato per il protocollo Hisense H-NET con supporto configurazione e Home Assistant Discovery
    """
    
    def __init__(self, config_path: str = "config/config.yml"):
        """Inizializza il decoder con configurazione da file YAML"""
        self.config = self._load_config(config_path)
        self.logger = self._setup_logging()
        self.client = None
        self.running = False
        self.ha_discovery_sent = set()  # Tiene traccia delle entità HA già pubblicate
        
        # Setup signal handlers per shutdown graceful
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Mapping per i codici operativi
        self.OPERATION_COMMANDS = {
            0x04: "AUTO MODE - CYCLE OFF",
            0x05: "AUTO MODE - CYCLE ON", 
            0x08: "COOLING MODE - CYCLE OFF",
            0x09: "COOLING MODE - CYCLE ON",
            0x64: "HEATING MODE - CYCLE OFF",
            0x65: "HEATING MODE - CYCLE ON"
        }
        
        # Mapping per le modalità operative
        self.OPERATION_MODES = {
            0x00: "COOLING",
            0x14: "HEATING", 
            0x28: "AUTO"
        }
        
        # Indirizzi dispositivi dalla configurazione
        self.INDOOR_CONTROLLER_ADDR = self.config['hnet']['indoor_controller_addr']
        self.OUTDOOR_UNIT_ADDR = self.config['hnet']['outdoor_unit_addr']
        self.INVALID_SENSOR_VALUE = self.config['hnet']['invalid_sensor_value']
        
        # Configurazione Home Assistant Discovery
        self.ha_discovery_prefix = self.config.get('homeassistant', {}).get('discovery_prefix', 'homeassistant')
        self.ha_device_name = self.config.get('homeassistant', {}).get('device_name', 'Hisense Heat Pump')
        self.ha_device_id = self.config.get('homeassistant', {}).get('device_id', 'hisense_hnet')
        
    def _load_config(self, config_path: str) -> dict:
        """Carica configurazione da file YAML con sostituzione variabili d'ambiente"""
        try:
            with open(config_path, 'r') as file:
                config_content = file.read()
                
            # Sostituisci variabili d'ambiente
            for key, value in os.environ.items():
                config_content = config_content.replace(f"${{{key}}}", value)
                config_content = config_content.replace(f"${{{key}:-}}", value if value else "")
                
            # Gestisci default values
            import re
            pattern = r'\$\{([^}]+):-([^}]*)\}'
            matches = re.findall(pattern, config_content)
            for var_name, default_value in matches:
                env_value = os.environ.get(var_name, default_value)
                config_content = config_content.replace(f"${{{var_name}:-{default_value}}}", env_value)
                
            return yaml.safe_load(config_content)
            
        except FileNotFoundError:
            print(f"❌ File di configurazione non trovato: {config_path}")
            return self._get_default_config()
        except yaml.YAMLError as e:
            print(f"❌ Errore nel parsing YAML: {e}")
            return self._get_default_config()
    
    def _get_default_config(self) -> dict:
        """Restituisce configurazione di default"""
        return {
            'mqtt': {
                'broker': os.getenv('MQTT_BROKER', 'localhost'),
                'port': int(os.getenv('MQTT_PORT', 1883)),
                'username': os.getenv('MQTT_USER', ''),
                'password': os.getenv('MQTT_PASSWORD', ''),
                'input_topic': os.getenv('MQTT_TOPIC', 'hisense/hnet/raw'),
                'publish_prefix': os.getenv('PUBLISH_PREFIX', 'PDC'),
                'keepalive': 60,
                'qos': 1,
                'retain': True,
                'reconnect_delay': 5
            },
            'hnet': {
                'indoor_controller_addr': 0x21,
                'outdoor_unit_addr': 0x12,
                'invalid_sensor_value': 129,
                'supported_opcodes': [0xB1, 0xB6, 0xB8]
            },
            'homeassistant': {
                'discovery_enabled': True,
                'discovery_prefix': 'homeassistant',
                'device_name': 'Hisense Heat Pump',
                'device_id': 'hisense_hnet',
                'manufacturer': 'Hisense',
                'model': 'H-NET Heat Pump',
                'sw_version': '1.0.0'
            },
            'logging': {
                'level': os.getenv('LOG_LEVEL', 'INFO'),
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                'file': '/app/logs/hnet_decoder.log'
            },
            'debug': {
                'print_raw_frames': True,
                'save_unknown_frames': True,
                'unknown_frames_file': '/app/logs/unknown_frames.log'
            }
        }
    
    def _setup_logging(self) -> logging.Logger:
        """Configura il sistema di logging"""
        # Crea directory logs se non esistente
        log_dir = Path("/app/logs")
        log_dir.mkdir(exist_ok=True)
        
        logger = logging.getLogger('HNetDecoder')
        logger.setLevel(getattr(logging, self.config['logging']['level']))
        
        # Handler per file
        if 'file' in self.config['logging']:
            file_handler = logging.FileHandler(self.config['logging']['file'])
            file_handler.setFormatter(logging.Formatter(self.config['logging']['format']))
            logger.addHandler(file_handler)
        
        # Handler per console
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(self.config['logging']['format']))
        logger.addHandler(console_handler)
        
        return logger
    
    def _signal_handler(self, signum, frame):
        """Gestisce i segnali di sistema per shutdown graceful"""
        self.logger.info(f"Ricevuto segnale {signum}, avvio shutdown...")
        self.running = False
    
    def _setup_mqtt(self):
        """Configura il client MQTT"""
        self.client = mqtt.Client()
        
        # Setup autenticazione se configurata
        mqtt_config = self.config['mqtt']
        if mqtt_config.get('username') and mqtt_config.get('password'):
            self.client.username_pw_set(mqtt_config['username'], mqtt_config['password'])
        
        # Setup callbacks
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        
        return self.client
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback per connessione MQTT"""
        if rc == 0:
            self.logger.info(f"✅ Connesso al broker MQTT {self.config['mqtt']['broker']}:{self.config['mqtt']['port']}")
            client.subscribe(self.config['mqtt']['input_topic'], self.config['mqtt']['qos'])
            self.logger.info(f"📡 Sottoscritto al topic: {self.config['mqtt']['input_topic']}")
            
            # Pubblica Home Assistant Discovery se abilitato
            if self.config.get('homeassistant', {}).get('discovery_enabled', True):
                self._publish_ha_discovery()
        else:
            self.logger.error(f"❌ Connessione MQTT fallita con codice: {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback per disconnessione MQTT"""
        if rc != 0:
            self.logger.warning(f"⚠️ Disconnessione inaspettata dal broker MQTT (rc: {rc})")
        else:
            self.logger.info("🔌 Disconnesso dal broker MQTT")
    
    def _on_message(self, client, userdata, msg):
        """Callback per messaggi MQTT ricevuti"""
        try:
            payload = msg.payload.decode('utf-8')
            self.logger.debug(f"📥 Ricevuto messaggio: {payload[:100]}...")
            payload = payload.split()[-1]
            self.logger.debug(f"📥 Ricevuto messaggio: {payload[:100]}...")

            # Parsing del payload
            if payload.startswith('[') and payload.endswith(']'):
                frame_data = json.loads(payload)
            elif all(c in '0123456789abcdefABCDEF ' for c in payload.replace(',', ' ')):
                hex_values = payload.replace(',', ' ').split()
                # frame_data = [int(x, 16) for x in hex_values if x]
                frame_data = []
                for i in range(0, len(payload), 2):
                    hex_pair = payload[i:i+2]
                    try:
                        decimal_value = int(hex_pair, 16)
                        frame_data.append(decimal_value)
                    except ValueError:
                        raise ValueError(f"Caratteri non validi trovati: '{hex_pair}' alla posizione {i}")

            else:
                self.logger.warning(f"⚠️  Formato payload non riconosciuto: {payload}")
                return
                
            # Decodifica il frame
            self._decode_frame(frame_data)
            
        except Exception as e:
            self.logger.error(f"❌ Errore nel processare il messaggio: {e}")
    
    def _get_ha_device_info(self) -> dict:
        """Restituisce le informazioni del dispositivo per Home Assistant"""
        return {
            "identifiers": [self.ha_device_id],
            "name": self.ha_device_name,
            "manufacturer": self.config.get('homeassistant', {}).get('manufacturer', 'Hisense'),
            "model": self.config.get('homeassistant', {}).get('model', 'H-NET Heat Pump'),
            "sw_version": self.config.get('homeassistant', {}).get('sw_version', '1.0.0'),
            "via_device": self.ha_device_id
        }
    
    def _publish_ha_discovery(self):
        """Pubblica le configurazioni di discovery per Home Assistant"""
        self.logger.info("🏠 Pubblicazione configurazioni Home Assistant Discovery...")
        
        # Definizione delle entità per Home Assistant
        entities = [
            # Sensori temperatura
            {"domain": "sensor", "id": "sensors/water_inlet_temperature", "name": "Water Inlet Temperature", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            {"domain": "sensor", "id": "sensors/water_outlet_temperature_1", "name": "Water Outlet Temperature 1", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            {"domain": "sensor", "id": "sensors/water_outlet_temperature_2", "name": "Water Outlet Temperature 2", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            {"domain": "sensor", "id": "sensors/heat_exchanger_outlet_temperature", "name": "Heat Exchanger Outlet Temperature", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            {"domain": "sensor", "id": "sensors/gas_ui_temperature", "name": "Gas UI Temperature", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            {"domain": "sensor", "id": "sensors/liquid_ui_temperature", "name": "Liquid UI Temperature", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            {"domain": "sensor", "id": "sensors/ambient_temperature", "name": "Ambient Temperature", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            {"domain": "sensor", "id": "sensors/ambient_temperature_avg", "name": "Ambient Temperature Average", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            {"domain": "sensor", "id": "sensors/exhaust_temperature", "name": "Exhaust Temperature", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            {"domain": "sensor", "id": "sensors/liquid_evaporation_temperature", "name": "Liquid Evaporation Temperature", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            
            # Sensori setpoint
            {"domain": "sensor", "id": "indoor/water_setpoint", "name": "Indoor Water Setpoint", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermostat"},
            {"domain": "sensor", "id": "outdoor/water_setpoint", "name": "Outdoor Water Setpoint", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermostat"},
            {"domain": "sensor", "id": "indoor/dhw_setpoint", "name": "Indoor DHW Setpoint", "unit": "°C", "device_class": "temperature", "icon": "mdi:water-thermometer"},
            {"domain": "sensor", "id": "outdoor/dhw_setpoint", "name": "Outdoor DHW Setpoint", "unit": "°C", "device_class": "temperature", "icon": "mdi:water-thermometer"},
            {"domain": "sensor", "id": "indoor/pool_setpoint", "name": "Indoor Pool Setpoint", "unit": "°C", "device_class": "temperature", "icon": "mdi:pool-thermometer"},
            {"domain": "sensor", "id": "outdoor/pool_setpoint", "name": "Outdoor Pool Setpoint", "unit": "°C", "device_class": "temperature", "icon": "mdi:pool-thermometer"},
            {"domain": "sensor", "id": "indoor/ambient_setpoint", "name": "Indoor Ambient Setpoint", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermostat"},
            {"domain": "sensor", "id": "outdoor/ambient_setpoint", "name": "Outdoor Ambient Setpoint", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermostat"},
            
            # Temperature interne
            {"domain": "sensor", "id": "indoor/indoor_temperature_1", "name": "Indoor Temperature 1", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            {"domain": "sensor", "id": "indoor/indoor_temperature_2", "name": "Indoor Temperature 2", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            {"domain": "sensor", "id": "outdoor/indoor_temperature_1", "name": "Outdoor Indoor Temperature 1", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            {"domain": "sensor", "id": "outdoor/indoor_temperature_2", "name": "Outdoor Indoor Temperature 2", "unit": "°C", "device_class": "temperature", "icon": "mdi:thermometer"},
            
            # Sensori modalità e stato
            {"domain": "sensor", "id": "indoor/operation_command", "name": "Indoor Operation Command", "icon": "mdi:cog"},
            {"domain": "sensor", "id": "outdoor/operation_command", "name": "Outdoor Operation Command", "icon": "mdi:cog"},
            {"domain": "sensor", "id": "indoor/mode", "name": "Indoor Mode", "icon": "mdi:hvac"},
            {"domain": "sensor", "id": "outdoor/mode", "name": "Outdoor Mode", "icon": "mdi:hvac"},
            {"domain": "sensor", "id": "indoor/cycle_status", "name": "Indoor Cycle Status", "icon": "mdi:power"},
            {"domain": "sensor", "id": "outdoor/cycle_status", "name": "Outdoor Cycle Status", "icon": "mdi:power"},
            {"domain": "sensor", "id": "indoor/operation_mode", "name": "Indoor Operation Mode", "icon": "mdi:hvac"},
            {"domain": "sensor", "id": "outdoor/operation_mode", "name": "Outdoor Operation Mode", "icon": "mdi:hvac"},
            
            # Sensori flusso e velocità
            {"domain": "sensor", "id": "sensors/water_flow", "name": "Water Flow", "unit": "L/min", "icon": "mdi:water-pump"},
            {"domain": "sensor", "id": "sensors/water_speed", "name": "Water Speed", "icon": "mdi:speedometer"},
            
            # Sensori sistema outdoor
            {"domain": "sensor", "id": "outdoor/pump_status", "name": "Outdoor Pump Status", "icon": "mdi:pump"},
            {"domain": "sensor", "id": "outdoor/inverter_frequency", "name": "Inverter Frequency", "unit": "Hz", "icon": "mdi:sine-wave"},
            {"domain": "sensor", "id": "outdoor/evo", "name": "EVO", "unit": "A", "device_class": "current", "icon": "mdi:current-ac"},
            {"domain": "sensor", "id": "outdoor/current", "name": "Current", "unit": "A", "device_class": "current", "icon": "mdi:current-ac"},
            {"domain": "sensor", "id": "outdoor/system_param_1", "name": "System Parameter 1", "icon": "mdi:cog"},
            {"domain": "sensor", "id": "outdoor/system_param_2", "name": "System Parameter 2", "icon": "mdi:cog"},
            
            # Sensori di stato online
            {"domain": "sensor", "id": "indoor/status", "name": "Indoor Unit Status", "device_class": "connectivity", "icon": "mdi:connection"},
            {"domain": "sensor", "id": "outdoor/status", "name": "Outdoor Unit Status", "device_class": "connectivity", "icon": "mdi:connection"},
            
            # Switch cicli
            {"domain": "sensor", "id": "indoor/cycle_1_active", "name": "Indoor Cycle 1 Active", "icon": "mdi:power"},
            {"domain": "sensor", "id": "indoor/cycle_2_active", "name": "Indoor Cycle 2 Active", "icon": "mdi:power"},
            {"domain": "sensor", "id": "outdoor/cycle_1_active", "name": "Outdoor Cycle 1 Active", "icon": "mdi:power"},
            {"domain": "sensor", "id": "outdoor/cycle_2_active", "name": "Outdoor Cycle 2 Active", "icon": "mdi:power"},
            {"domain": "sensor", "id": "indoor/cycle_dhw_active", "name": "Indoor Cycle DHW Active", "icon": "mdi:power"},
            {"domain": "sensor", "id": "outdoor/cycle_dhw_active", "name": "Outdoor Cycle DHW Active", "icon": "mdi:power"},
            {"domain": "sensor", "id": "indoor/cycle_pool_active", "name": "Indoor Cycle POOL Active", "icon": "mdi:power"},
            {"domain": "sensor", "id": "outdoor/cycle_pool_active", "name": "Outdoor Cycle POOL Active", "icon": "mdi:power"},
            
            # Sensori data/ora
            {"domain": "sensor", "id": "indoor/system_datetime", "name": "Indoor System DateTime",  "icon": "mdi:clock"},
            {"domain": "sensor", "id": "outdoor/system_datetime", "name": "Outdoor System DateTime", "icon": "mdi:clock"},
        ]
        
        # Pubblica ogni entità
        for entity in entities:
            self._publish_single_ha_discovery(entity)
        
        self.logger.info(f"✅ Pubblicate {len(entities)} configurazioni Home Assistant Discovery")
    
    def _publish_single_ha_discovery(self, entity: dict):
        """Pubblica una singola configurazione di discovery per Home Assistant"""
        try:
            entity_id = f"{self.ha_device_id}_{entity['id']}"
            discovery_topic = f"{self.ha_discovery_prefix}/{entity['domain']}/{entity_id}/config"
            
            # Costruisci il topic dello stato basato sulla struttura esistente
            if entity['id'].startswith('sensors/'):
                state_topic = f"{self.config['mqtt']['publish_prefix']}/{entity['id']}"
            else:
                state_topic = f"{self.config['mqtt']['publish_prefix']}/{entity['id']}"
            
            config = {
                "unique_id": entity_id,
                "name": entity['name'],
                "state_topic": state_topic,
                "device": self._get_ha_device_info(),
                "availability_topic": f"{self.config['mqtt']['publish_prefix']}/availability",
                "payload_available": "online",
                "payload_not_available": "offline"
            }
            
            # Aggiungi attributi specifici per dominio
            if entity['domain'] == 'sensor':
                if 'unit' in entity:
                    config['unit_of_measurement'] = entity['unit']
                if 'device_class' in entity:
                    config['device_class'] = entity['device_class']
                if 'icon' in entity:
                    config['icon'] = entity['icon']
                # Per i sensori, il valore è diretto (non JSON)
                # config['value_template'] = "{{ value }}"  # Rimosso, HA usa il valore diretto
            elif entity['domain'] == 'binary_sensor':
                config['payload_on'] = "ON"
                config['payload_off'] = "OFF"
                if 'device_class' in entity:
                    config['device_class'] = entity['device_class']
                if 'icon' in entity:
                    config['icon'] = entity['icon']
            
            # Aggiungi topic attributi se disponibile
            attributes_topic = f"{state_topic}/attributes"
            config['json_attributes_topic'] = attributes_topic
            
            # Pubblica la configurazione
            result = self.client.publish(
                discovery_topic,
                json.dumps(config),
                qos=self.config['mqtt']['qos'],
                retain=True
            )
            
            if result[0] == 0:
                self.logger.debug(f"🏠 HA Discovery: {entity['name']} -> {discovery_topic}")
                self.ha_discovery_sent.add(entity_id)
            else:
                self.logger.error(f"❌ Errore pubblicazione HA Discovery per {entity['name']}")
                
        except Exception as e:
            self.logger.error(f"❌ Errore pubblicazione HA Discovery per {entity.get('name', 'unknown')}: {e}")
    
    def _publish_mqtt_value(self, topic_suffix: str, value: Union[str, int, float, bool], 
                           unit: str = None, retain: bool = None, ha_compatible: bool = True):
        """Pubblica un valore su topic MQTT con compatibilità Home Assistant"""
        if not self.client:
            self.logger.warning(f"⚠️  MQTT self.client not defined")
            return
            
        if retain is None:
            retain = self.config['mqtt']['retain']
            
        full_topic = f"{self.config['mqtt']['publish_prefix']}/{topic_suffix}"
        
        # Formato compatibile con Home Assistant
        if ha_compatible and self.config.get('homeassistant', {}).get('discovery_enabled', True):
            # Per HA, pubblica solo il valore diretto
            if isinstance(value, bool):
                # Per binary_sensor, usa ON/OFF
                payload = "ON" if value else "OFF"
            elif isinstance(value, (int, float)):
                # Per i sensori numerici, formatta con precisione appropriata
                if isinstance(value, float):
                    payload = f"{value:.2f}" if value != int(value) else str(int(value))
                else:
                    payload = str(value)
            elif value == "online":
                # Per availability, usa i payload standard di HA
                payload = "online"
            elif value == "offline":
                payload = "offline"
            else:
                # Per tutti gli altri casi, usa il valore come stringa
                payload = str(value)
                
            # Pubblica anche un topic con attributi per informazioni aggiuntive
            attributes_topic = f"{full_topic}/attributes"
            attributes_payload = {
                "timestamp": datetime.now().isoformat(),
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            if unit:
                attributes_payload["unit_of_measurement"] = unit
                
            # Pubblica gli attributi
            try:
                self.client.publish(
                    attributes_topic,
                    json.dumps(attributes_payload),
                    qos=self.config['mqtt']['qos'],
                    retain=False  # Gli attributi non hanno bisogno di retain
                )
            except Exception as e:
                self.logger.debug(f"⚠️ Warning pubblicazione attributi {attributes_topic}: {e}")
        else:
            # Formato originale con JSON
            payload_dict = {
                "value": value,
                "timestamp": datetime.now().isoformat(),
            }
            
            if unit:
                payload_dict["unit"] = unit
                
            payload = json.dumps(payload_dict)
            
        try:
            result = self.client.publish(
                full_topic, 
                payload, 
                qos=self.config['mqtt']['qos'],
                retain=retain
            )
            status = result[0]
            if status == 0:
                self.logger.debug(f"📤 {full_topic}: {value}{' ' + unit if unit else ''}")
            else:
                self.logger.error(f"❌ Errore pubblicazione {full_topic}")
        except Exception as e:
            self.logger.error(f"❌ Errore pubblicazione {full_topic}: {e}")
    
    def _verify_checksum(self, frame: List[int]) -> bool:
        """Verifica il checksum del frame usando l'algoritmo XOR"""
        if len(frame) < 4:
            return False
            
        checksum = 0
        data = frame[:-1]
        src_address = frame[0]
        
        for byte in data:
            checksum ^= byte
        checksum ^= src_address
        
        return (checksum & 0xFF) == frame[-1]

    def _hex_string_to_int_array(hex_string):
        """
        Converte una stringa esadecimale in un array di interi.
        Ogni coppia di caratteri esadecimali viene convertita in un intero.
    
        Args:
            hex_string (str): Stringa esadecimale (deve avere lunghezza pari)
    
        Returns:
            list: Lista di interi
    
        Raises:
            ValueError: Se la stringa ha lunghezza dispari o contiene caratteri non esadecimali
        """
        # Rimuove spazi e converte in maiuscolo per sicurezza
        hex_string = hex_string.replace(" ", "").upper()
    
        # Controlla che la lunghezza sia pari
        if len(hex_string) % 2 != 0:
            raise ValueError("La stringa esadecimale deve avere lunghezza pari")
    
        # Converte ogni coppia di caratteri in un intero
        result = []
        for i in range(0, len(hex_string), 2):
            hex_pair = hex_string[i:i+2]
            try:
                decimal_value = int(hex_pair, 16)
                result.append(decimal_value)
            except ValueError:
                raise ValueError(f"Caratteri non validi trovati: '{hex_pair}' alla posizione {i}")
    
        return result
    
    def _decode_frame(self, frame: List[int]):
        """Decodifica un frame H-NET"""
        if len(frame) < 4:
            self.logger.warning("⚠️ Frame troppo corto")
            return
            
        # Header del frame
        src_addr = frame[0]
        ctrl_byte = frame[1] 
        msg_len = frame[2]
        checksum_valid = self._verify_checksum(frame)
        
        self.logger.info(f"🔍 FRAME H-NET - Src: 0x{src_addr:02X}, Ctrl: 0x{ctrl_byte:02X}, Len: {msg_len}")
        
        if not checksum_valid:
            self.logger.warning("⚠️ Checksum invalido")
            if self.config['debug']['save_unknown_frames']:
                self._save_unknown_frame(frame, "invalid_checksum")
        
        # Se è solo un ACK, non decodificare oltre
        if ctrl_byte == 0x06:
            self.logger.debug("📤 Messaggio ACK")
            return
            
        if len(frame) < 10:
            self.logger.warning("⚠️ Frame troppo corto per dati utili")
            return
            
        # Estrai opcode
        msg_type = frame[3]
        opcode = frame[9] if len(frame) > 9 else None
        
        if opcode:
            self.logger.info(f"🔧 Opcode: 0x{opcode:02X}")
            
            # Decodifica basata sull'opcode
            if opcode == 0xB1:
                self._decode_status_message(frame, src_addr)
            elif opcode == 0xB6:
                self._decode_sensor_data(frame)
            elif opcode == 0xB8:
                self._decode_system_info(frame)
            else:
                self.logger.warning(f"❓ Opcode sconosciuto: 0x{opcode:02X}")
                if self.config['debug']['save_unknown_frames']:
                    self._save_unknown_frame(frame, f"unknown_opcode_0x{opcode:02X}")
                    
            # Pubblica stato dispositivo
            device_name = "indoor" if src_addr == self.INDOOR_CONTROLLER_ADDR else "outdoor"
            self._publish_mqtt_value(f"{device_name}/status", "online")
        
        # Log dati raw se abilitato
        if self.config['debug']['print_raw_frames']:
            hex_data = ' '.join([f'{b:02X}' for b in frame])
            self.logger.debug(f"🔢 Raw: {hex_data}")
    
    def _save_unknown_frame(self, frame: List[int], reason: str):
        """Salva frame sconosciuti per analisi"""
        try:
            with open(self.config['debug']['unknown_frames_file'], 'a') as f:
                hex_data = ' '.join([f'{b:02X}' for b in frame])
                timestamp = datetime.now().isoformat()
                f.write(f"{timestamp} - {reason}: {hex_data}\n")
        except Exception as e:
            self.logger.error(f"❌ Errore salvataggio frame sconosciuto: {e}")
    
    def _decode_status_message(self, frame: List[int], src_addr: int):
        """Decodifica messaggi di stato (opcode 0xB1)"""
        if len(frame) < 48:
            self.logger.warning("⚠️ Frame di stato troppo corto")
            return
            
        device_prefix = "indoor" if src_addr == self.INDOOR_CONTROLLER_ADDR else "outdoor"
        self.logger.info(f"🏠 Decodifica stato per {device_prefix}")
        
        try:
            # Comando operativo (byte 10)
            if len(frame) > 10:
                op_cmd = frame[10]
                if op_cmd in self.OPERATION_COMMANDS:
                    op_description = self.OPERATION_COMMANDS[op_cmd]
                    self._publish_mqtt_value(f"{device_prefix}/operation_command", op_description)
                    
                    # Estrai modalità e stato ciclo
                    if "AUTO" in op_description:
                        mode = "AUTO"
                    elif "COOLING" in op_description:
                        mode = "COOLING"  
                    elif "HEATING" in op_description:
                        mode = "HEATING"
                    else:
                        mode = "UNKNOWN"
                    
                    cycle_on = "ON" in op_description
                    self._publish_mqtt_value(f"{device_prefix}/mode", mode)
                    self._publish_mqtt_value(f"{device_prefix}/cycle_status", "ON" if cycle_on else "OFF")
            
            # Temperature e altri parametri
            if len(frame) > 12 and frame[12] != 0:
                self._publish_mqtt_value(f"{device_prefix}/water_setpoint", frame[12], "°C")
            
            if len(frame) > 13:
                op_mode = frame[13]
                if op_mode in self.OPERATION_MODES:
                    self._publish_mqtt_value(f"{device_prefix}/operation_mode", self.OPERATION_MODES[op_mode])
            
            if len(frame) > 14 and frame[14] != 0:
                self._publish_mqtt_value(f"{device_prefix}/dhw_setpoint", frame[14], "°C")
            
            if len(frame) > 15 and frame[15] != 0:
                self._publish_mqtt_value(f"{device_prefix}/pool_setpoint", frame[15], "°C")
            
            # Altre temperature e parametri...
            self._decode_additional_status_params(frame, device_prefix)
                    
        except IndexError as e:
            self.logger.error(f"❌ Errore accesso dati frame stato: {e}")
    
    def _decode_additional_status_params(self, frame: List[int], device_prefix: str):
        """Decodifica parametri aggiuntivi del messaggio di stato"""
        try:
            # Temperature interne
            if len(frame) > 18 and frame[18] != 0:
                self._publish_mqtt_value(f"{device_prefix}/indoor_temperature_1", frame[18], "°C")
            
            if len(frame) > 27 and frame[27] != 0:
                self._publish_mqtt_value(f"{device_prefix}/indoor_temperature_2", frame[26], "°C")
            
            # Temperatura ambiente impostata
            if len(frame) > 19 and frame[19] != 0:
                self._publish_mqtt_value(f"{device_prefix}/ambient_setpoint", frame[19], "°C")
            
            # Selezione ciclo
            if len(frame) > 16:
                cycle_sel = frame[16]
                self._publish_mqtt_value(f"{device_prefix}/cycle_1_active", bool(cycle_sel & 0x01))
                self._publish_mqtt_value(f"{device_prefix}/cycle_2_active", bool(cycle_sel & 0x02))
                self._publish_mqtt_value(f"{device_prefix}/cycle_dhw_active", bool(cycle_sel & 0x04))
                self._publish_mqtt_value(f"{device_prefix}/cycle_pool_active", bool(cycle_sel & 0x08))
            
            # Data e ora se presente
            if len(frame) > 37:
                self._decode_datetime(frame[34:41], device_prefix)
                
        except Exception as e:
            self.logger.error(f"❌ Errore decodifica parametri aggiuntivi: {e}")
    
    def _decode_datetime(self, datetime_bytes: List[int], device_prefix: str):
        """Decodifica data e ora dal frame"""
        try:
            self.logger.debug(f"📥 Ricevuto DATETIME: {datetime_bytes[:100]}...")
            if len(datetime_bytes) >= 7:
                year = datetime_bytes[0] if datetime_bytes[0] != 0 else None
                year = year * 100 + datetime_bytes[1] if datetime_bytes[1] != 0 else None
                month = datetime_bytes[2] if datetime_bytes[2] != 0 else None
                day = (datetime_bytes[3] - 32) if datetime_bytes[3] != 0 else None
                hour = datetime_bytes[4] if datetime_bytes[4] != 0 else None
                minute = datetime_bytes[5] if datetime_bytes[5] != 0 else None
                second = datetime_bytes[6] if datetime_bytes[6] != 0 else None
                
                if all(x is not None for x in [year, month, day, hour, minute, second]):
                    datetime_str = f"{day:02d}/{month:02d}/{year} {hour:02d}:{minute:02d}:{second:02d}"
                    self._publish_mqtt_value(f"{device_prefix}/system_datetime", datetime_str)
        except Exception as e:
            self.logger.error(f"❌ Errore decodifica datetime: {e}")
    
    def _decode_sensor_data(self, frame: List[int]):
        """Decodifica dati sensori (opcode 0xB6)"""
        if len(frame) < 76:
            self.logger.warning("⚠️ Frame sensori troppo corto")
            return
            
        self.logger.info("🌡️ Decodifica dati sensori")
        
        try:
            # Temperature acqua
            sensor_mappings = [
                (11, "sensors/water_inlet_temperature", "°C"),
                (12, "sensors/water_outlet_temperature_1", "°C"),
                (13, "sensors/heat_exchanger_outlet_temperature", "°C"),
                (16, "sensors/water_outlet_temperature_2", "°C"),
                (39, "sensors/gas_ui_temperature", "°C"),
                (40, "sensors/liquid_ui_temperature", "°C"),
                (43, "sensors/ambient_temperature", "°C"),
                (44, "sensors/ambient_temperature_avg", "°C")
            ]
            
            for byte_idx, topic, unit in sensor_mappings:
                if len(frame) > byte_idx and frame[byte_idx] != self.INVALID_SENSOR_VALUE and frame[byte_idx] != 0:
                    self._publish_mqtt_value(topic, frame[byte_idx], unit)
            
            # Flusso e velocità acqua
            if len(frame) > 65 and frame[65] != 0:
                self._publish_mqtt_value("sensors/water_flow", frame[65], "L/min")
            
            if len(frame) > 66 and frame[66] != 0:
                self._publish_mqtt_value("sensors/water_speed", frame[66])
            
            # Temperature di scarico ed evaporazione
            if len(frame) > 67 and frame[67] != 0:
                self._publish_mqtt_value("sensors/exhaust_temperature", frame[67], "°C")
                
            if len(frame) > 68 and frame[68] != 0:
                self._publish_mqtt_value("sensors/liquid_evaporation_temperature", frame[68], "°C")
                
            # Stato pompa
            if len(frame) > 11:
                self._publish_mqtt_value("outdoor/pump_status", frame[11])
                
        except IndexError as e:
            self.logger.error(f"❌ Errore accesso dati sensori: {e}")
    
    def _decode_system_info(self, frame: List[int]):
        """Decodifica informazioni sistema (opcode 0xB8)"""
        if len(frame) < 30:
            self.logger.warning("⚠️ Frame info sistema troppo corto")
            return
            
        self.logger.info("⚙️ Decodifica info sistema")
        
        try:
            # Frequenza inverter
            if len(frame) > 21 and frame[21] != 0:
                self._publish_mqtt_value("outdoor/inverter_frequency", frame[21], "Hz")
            
            # EVO
            if len(frame) > 23 and frame[23] != 0:
                self._publish_mqtt_value("outdoor/evo", frame[23], "..") 

            # Current
            if len(frame) > 24 and frame[24] != 0:
                self._publish_mqtt_value("outdoor/current", frame[24], "A") 


            # if len(frame) > 24:
            #    evo_current = (frame[24] << 8) | frame[23] if frame[23] != 0 or frame[24] != 0 else 0
            #    if evo_current != 0:
            #        current_value = evo_current / 10.0
            #        self._publish_mqtt_value("outdoor/evo_current", current_value, "A")
                    
            # Altri parametri sistema
            if len(frame) > 10:
                self._publish_mqtt_value("outdoor/system_param_1", frame[10])
            if len(frame) > 11:
                self._publish_mqtt_value("outdoor/system_param_2", frame[11])
                    
        except IndexError as e:
            self.logger.error(f"❌ Errore accesso info sistema: {e}")
    
    def _publish_availability(self, status: str = "online"):
        """Pubblica lo stato di disponibilità per Home Assistant"""
        try:
            availability_topic = f"{self.config['mqtt']['publish_prefix']}/availability"
            result = self.client.publish(
                availability_topic,
                status,
                qos=self.config['mqtt']['qos'],
                retain=True
            )
            if result[0] == 0:
                self.logger.debug(f"📤 Availability: {status}")
        except Exception as e:
            self.logger.error(f"❌ Errore pubblicazione availability: {e}")
    
    def start_monitoring(self):
        """Avvia il monitoraggio MQTT"""
        self.logger.info("🚀 Avvio Hisense H-NET Protocol Decoder con Home Assistant Discovery")
        self.logger.info(f"🌐 Broker: {self.config['mqtt']['broker']}:{self.config['mqtt']['port']}")
        self.logger.info(f"📥 Topic input: {self.config['mqtt']['input_topic']}")
        self.logger.info(f"📤 Prefisso output: {self.config['mqtt']['publish_prefix']}")
        
        if self.config.get('homeassistant', {}).get('discovery_enabled', True):
            self.logger.info(f"🏠 Home Assistant Discovery: {self.ha_discovery_prefix}")
        
        try:
            self._setup_mqtt()
            self.running = True
            
            # Connessione con retry
            while self.running:
                try:
                    self.client.connect(
                        self.config['mqtt']['broker'], 
                        self.config['mqtt']['port'], 
                        self.config['mqtt']['keepalive']
                    )
                    break
                except Exception as e:
                    self.logger.error(f"❌ Errore connessione MQTT: {e}")
                    time.sleep(self.config['mqtt']['reconnect_delay'])
            
            # Pubblica availability online
            self._publish_availability("online")
            
            # Loop principale
            while self.running:
                self.client.loop(timeout=1.0)
                
        except KeyboardInterrupt:
            self.logger.info("👋 Interruzione richiesta dall'utente")
        except Exception as e:
            self.logger.error(f"❌ Errore durante il monitoraggio: {e}")
        finally:
            # Pubblica availability offline prima di disconnettere
            if self.client and self.client.is_connected():
                self._publish_availability("offline")
                time.sleep(0.1)  # Breve pausa per assicurare la pubblicazione
                self.client.disconnect()
            self.logger.info("🔌 Decoder arrestato")

def main():
    """Funzione principale"""
    print("🏠 Hisense H-NET Protocol Decoder - Docker Version with Home Assistant Discovery")
    print("=" * 80)
    
    # Percorso configurazione
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yml")
    
    try:
        # Crea e avvia il decoder
        decoder = HNetProtocolDecoder(config_path)
        decoder.start_monitoring()
    except Exception as e:
        print(f"❌ Errore fatale: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
