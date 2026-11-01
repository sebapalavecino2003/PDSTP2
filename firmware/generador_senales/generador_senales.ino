/*
 * TP Nº2 - RECREACIÓN DE SEÑALES
 * Firmware para ESP32-WROOM-32 (Arduino-ESP32 core 3.x)
 * 
 * OBJETIVO: Recibir muestras de 8 bits (0-255) por UART0 desde PC y escribirlas
 *           al DAC1 (GPIO25) a ritmo fijo determinado por un timer por hardware.
 * 
 * REQUISITOS CUMPLIDOS:
 * - Sin generador de cosenos del DAC, sin PWM/LEDC, sin sigma-delta.
 * - Muestras calculadas por la PC. ESP32 solo recibe, almacena y reproduce.
 * - Buffer circular con productor/consumidor.
 * - ISR dispara por timer a Fs fija.
 * - SYNC_PIN (GPIO27) invierte cada 256 muestras REALMENTE reproducidas (played).
 * - ISR_PIN (GPIO32) opcional con DEBUG_ISR_PIN.
 * - Protocolo binario PC->ESP32 + mensajes ASCII ESP32->PC.
 * - Sin WiFi/Bluetooth.
 * 
 * VERSIÓN CORE: Escrito para Arduino-ESP32 core 3.x
 */

#include <Arduino.h>

// Verificación obligatoria del core
#if defined(ESP_ARDUINO_VERSION_MAJOR)
  #if ESP_ARDUINO_VERSION_MAJOR < 3
    #error "Este sketch requiere el core ESP32 3.x"
  #endif
#else
  #warning "No se pudo detectar ESP_ARDUINO_VERSION_MAJOR. Se asume core 3.x"
#endif

// Pines
#define DAC_PIN      25  // DAC1
#define SYNC_PIN     27  // Inversión cada 256 muestras reproducidas
#define ISR_PIN      32  // Debug ISR (opcional)
#define DAC2_FREE    26  // Queda libre intencionalmente

// Debug
#ifndef DEBUG_ISR_PIN
#define DEBUG_ISR_PIN 0
#endif

// Buffer circular
#ifndef BUF_SIZE
#define BUF_SIZE 4096  // Potencia de 2
#endif

// Parámetros serie
#define UART_BAUD_DEFAULT 921600
#define RX_BUF_SIZE 8192

// Timings
#define STATUS_INTERVAL_MS 20
#define READY_INTERVAL_MS  500

// Protocolo
#define PKT_START  0xA5
#define TYPE_CONFIG 0x01
#define TYPE_DATA   0x02
#define TYPE_STOP   0x03

// Buffer circular
static uint8_t buffer_circ[BUF_SIZE];
static volatile uint16_t head_idx = 0;  // Índice escritura (productor - loop)
static volatile uint16_t tail_idx = 0;  // Índice lectura (consumidor - ISR)
static volatile uint32_t rx_count  = 0; // Muestras recibidas
static volatile uint32_t played   = 0; // Muestras realmente reproducidas
static volatile uint32_t undruns  = 0; // Buffer vacío en ISR
static volatile uint32_t overruns = 0; // Buffer lleno al recibir
static volatile uint16_t seqerr   = 0; // Errores de secuencia
static volatile uint8_t  last_dac = 128;

// Estado
static volatile bool running = false;
static uint32_t fs_pedida = 20000;
static uint32_t fs_real   = 20000;

// Secuencia
static uint8_t expected_seq = 0;
static bool seq_init = false;

// Timer
static hw_timer_t *timer = NULL;

// Parser
typedef enum {
  PARSE_IDLE,
  PARSE_TYPE,
  PARSE_CONFIG_B0,
  PARSE_CONFIG_B1,
  PARSE_CONFIG_B2,
  PARSE_CONFIG_B3,
  PARSE_DATA_SEQ,
  PARSE_DATA_LEN,
  PARSE_DATA_PAYLOAD
} parse_state_t;

static parse_state_t pstate = PARSE_IDLE;
static uint8_t pkt_type = 0;
static uint8_t data_seq = 0;
static uint8_t data_len = 0;
static uint8_t data_cnt = 0;
static uint8_t config_buf[4];
static uint8_t config_cnt = 0;

// Utilidades buffer circular (potencia de 2)
static inline uint16_t buf_mask(void) {
  return (uint16_t)(BUF_SIZE - 1);
}

static inline uint16_t buf_free_count(void) {
  // (head - tail) mod BUF_SIZE
  uint16_t h = head_idx;
  uint16_t t = tail_idx;
  if (h >= t) return (uint16_t)(BUF_SIZE - (h - t));
  else return (uint16_t)(t - h);
}

static inline uint16_t buf_fill_count(void) {
  uint16_t h = head_idx;
  uint16_t t = tail_idx;
  if (h >= t) return (uint16_t)(h - t);
  else return (uint16_t)(BUF_SIZE - (t - h));
}

static inline bool buf_is_full(void) {
  // Ocupado = BUF_SIZE-1 para distinguir lleno/vacío
  return (buf_fill_count() >= (BUF_SIZE - 1));
}

static inline bool buf_is_empty(void) {
  return (head_idx == tail_idx);
}

// ISR - lo más corta posible
void IRAM_ATTR onTimer(void) {
#if DEBUG_ISR_PIN
  digitalWrite(ISR_PIN, HIGH);
#endif

  if (!running) {
#if DEBUG_ISR_PIN
    digitalWrite(ISR_PIN, LOW);
#endif
    return;
  }

  if (buf_is_empty()) {
    // Sin muestra: mantener último valor, contar underrun
    undruns++;
    // NO escribir DAC de nuevo para evitar jitter innecesario; ya está en último valor
  } else {
    // Sacar muestra
    uint16_t t = tail_idx;
    uint8_t sample = buffer_circ[t];
    tail_idx = (uint16_t)((t + 1) & buf_mask());
    
    // Escribir al DAC
    // dacWrite es función del core; si se verifica insegura en ISR se podría usar registro.
    // Se mantiene dacWrite aquí por compatibilidad con API Arduino-ESP32. Comentario: revisar fuente core.
    dacWrite(DAC_PIN, sample);
    last_dac = sample;
    played++;
    
    // SYNC: invertir cada 256 muestras REALMENTE reproducidas
    if ((played % 256) == 0) {
      digitalWrite(SYNC_PIN, !digitalRead(SYNC_PIN));
    }
  }

#if DEBUG_ISR_PIN
  digitalWrite(ISR_PIN, LOW);
#endif
}

// Configurar timer
static void stop_timer(void) {
  if (timer) {
    timerStop(timer);
    timerDetachInterrupt(timer);
    timerEnd(timer);
    timer = NULL;
  }
  running = false;
}

static void start_timer(uint32_t fs) {
  if (fs == 0) fs = 1;
  if (fs > 100000) fs = 100000; // Límite defensivo
  
  fs_pedida = fs;
  
  // Usar base 1MHz para mayor compatibilidad con core 3.x
  uint64_t alarm_us = 1000000ULL / (uint64_t)fs;
  if (alarm_us < 1) alarm_us = 1;
  
  fs_real = (uint32_t)(1000000ULL / alarm_us);
  
  stop_timer();
  delay(10);
  
  timer = timerBegin(1000000);
  timerAttachInterrupt(timer, &onTimer);
  timerAlarm(timer, alarm_us, true, 0);
  
  running = false; // Se activará cuando lleguen muestras al buffer
}

// Reset estado
static void reset_state(void) {
  head_idx = 0;
  tail_idx = 0;
  rx_count = 0;
  played   = 0;
  undruns  = 0;
  overruns = 0;
  seqerr   = 0;
  seq_init = false;
  expected_seq = 0;
  // Poner DAC en valor neutro
  dacWrite(DAC_PIN, 128);
  last_dac = 128;
  digitalWrite(SYNC_PIN, LOW);
}

static void push_sample(uint8_t s) {
  if (buf_is_full()) {
    overruns++;
    // Descartar muestra si buffer lleno (según protocolo)
    return;
  }
  uint16_t h = head_idx;
  buffer_circ[h] = s;
  head_idx = (uint16_t)((h + 1) & buf_mask());
  rx_count++;
}

void setup() {
  pinMode(DAC_PIN, ANALOG);
  pinMode(SYNC_PIN, OUTPUT);
  digitalWrite(SYNC_PIN, LOW);
  
#if DEBUG_ISR_PIN
  pinMode(ISR_PIN, OUTPUT);
  digitalWrite(ISR_PIN, LOW);
#endif
  
  // UART0
  Serial.setRxBufferSize(RX_BUF_SIZE);
  Serial.begin(UART_BAUD_DEFAULT);
  
  // Inicializar DAC
  dacWrite(DAC_PIN, 128);
  last_dac = 128;
  
  // Estado inicial
  reset_state();
  running = false;
  stop_timer();
  
  // Enviar READY periódicamente hasta recibir CONFIG (lo maneja loop)
}

void loop() {
  static uint32_t last_ready = 0;
  static uint32_t last_status = 0;
  uint32_t now = millis();
  
  // READY si no está corriendo o nunca recibió CONFIG
  if (!running) {
    if (now - last_ready >= READY_INTERVAL_MS) {
      Serial.println("READY");
      last_ready = now;
    }
  } else {
    // STATUS cada 20ms mientras corre
    if (now - last_status >= STATUS_INTERVAL_MS) {
      // Calcular fill
      uint16_t fill = buf_fill_count();
      Serial.print("S rx=");
      Serial.print(rx_count);
      Serial.print(" played=");
      Serial.print(played);
      Serial.print(" fill=");
      Serial.print(fill);
      Serial.print(" und=");
      Serial.print(undruns);
      Serial.print(" ovr=");
      Serial.print(overruns);
      Serial.print(" seqerr=");
      Serial.println(seqerr);
      last_status = now;
    }
  }
  
  // Parser máquina de estados
  while (Serial.available() > 0) {
    int c = Serial.read();
    if (c < 0) break;
    uint8_t b = (uint8_t)c;
    
    switch (pstate) {
      case PARSE_IDLE:
        if (b == PKT_START) {
          pstate = PARSE_TYPE;
        }
        // Ignorar basura (bootloader)
        break;
        
      case PARSE_TYPE:
        pkt_type = b;
        if (pkt_type == TYPE_CONFIG) {
          config_cnt = 0;
          pstate = PARSE_CONFIG_B0;
        } else if (pkt_type == TYPE_DATA) {
          pstate = PARSE_DATA_SEQ;
        } else if (pkt_type == TYPE_STOP) {
          // STOP: detener, limpiar buffer, DAC a 128
          stop_timer();
          reset_state();
          dacWrite(DAC_PIN, 128);
          last_dac = 128;
          digitalWrite(SYNC_PIN, LOW);
          pstate = PARSE_IDLE;
        } else {
          // Tipo desconocido, resincronizar
          pstate = PARSE_IDLE;
        }
        break;
        
      case PARSE_CONFIG_B0:
        config_buf[0] = b;
        pstate = PARSE_CONFIG_B1;
        break;
      case PARSE_CONFIG_B1:
        config_buf[1] = b;
        pstate = PARSE_CONFIG_B2;
        break;
      case PARSE_CONFIG_B2:
        config_buf[2] = b;
        pstate = PARSE_CONFIG_B3;
        break;
      case PARSE_CONFIG_B3:
        config_buf[3] = b;
        // fs little-endian
        {
          uint32_t fs_new = (uint32_t)config_buf[0] |
                            ((uint32_t)config_buf[1] << 8) |
                            ((uint32_t)config_buf[2] << 16) |
                            ((uint32_t)config_buf[3] << 24);
          // Aplicar CONFIG: detener, vaciar, reset contadores, reiniciar con nueva Fs
          stop_timer();
          reset_state();
          // Iniciar timer
          start_timer(fs_new);
          // Respuesta CFG
          Serial.print("CFG fs_pedida=");
          Serial.print(fs_pedida);
          Serial.print(" fs_real=");
          Serial.println(fs_real);
        }
        pstate = PARSE_IDLE;
        break;
        
      case PARSE_DATA_SEQ:
        data_seq = b;
        if (!seq_init) {
          expected_seq = data_seq;
          seq_init = true;
        } else {
          if (data_seq != expected_seq) {
            // Error de secuencia: incrementar y resincronizar con recibido
            seqerr++;
            expected_seq = data_seq;
          }
          // Avanzar esperado
          expected_seq = (uint8_t)(expected_seq + 1);
        }
        pstate = PARSE_DATA_LEN;
        break;
        
      case PARSE_DATA_LEN:
        data_len = b;
        if (data_len == 0 || data_len > 250) {
          // Inválido, resincronizar
          pstate = PARSE_IDLE;
        } else {
          data_cnt = 0;
          pstate = PARSE_DATA_PAYLOAD;
        }
        break;
        
      case PARSE_DATA_PAYLOAD:
        // Recibir muestra en buffer
        push_sample(b);
        data_cnt++;
        if (data_cnt >= data_len) {
          pstate = PARSE_IDLE;
          // Iniciar reproducción una vez que hay muestras en el buffer
          if (!running && timer != NULL && buf_fill_count() >= 200) {
            running = true;
          }
        }
        break;
        
      default:
        pstate = PARSE_IDLE;
        break;
    }
  }
}
