# PDSTP2 - Recreación de Señales (PDS)

Sistema de recreación de señales por *streaming* desde una aplicación web en la PC hacia un microcontrolador ESP32-WROOM-32 utilizando el DAC integrado.

---

## 🚀 Cómo correr la aplicación

1. Conectar el ESP32 por puerto USB.
2. Ejecutar el script para levantar el servidor web local:
```bash
./LEVANTAR_TP2.sh
```
3. Abrir en el navegador (Google Chrome o Microsoft Edge compatible con Web Serial API):
```
http://localhost:8000/app/
```

---

## ⚙️ Cómo funciona la aplicación

1. **Interfaz Web y Web Serial API**: 
   La aplicación está desarrollada en JavaScript vainilla y HTML (`app/index.html` y `app/muestras.js`), sirviéndose mediante un servidor local en Python (`app/app.py`). Utiliza la **Web Serial API** del navegador para establecer comunicación directa por puerto serie USB con el microcontrolador.

2. **Generación y Streaming de Muestras (PC)**:
   - Desde la interfaz web, el usuario selecciona la **forma de onda** (Senoidal, Triangular, Cuadrada, Rampa o Código Fijo), la **frecuencia** ($f_0$), la **frecuencia de muestreo** ($f_s$) y la **amplitud**.
   - Un acumulador de fase calcula en tiempo real los valores discretos de la señal (0 a 255, adaptados al DAC de 8 bits del ESP32).
   - Los datos se transmiten por streaming serial mediante un protocolo binario paquetizado.

3. **Recepción, Búfer y Reproducción por Hardware (ESP32)**:
   - El firmware (`firmware/generador_senales/generador_senales.ino`) procesa los paquetes serie mediante una máquina de estados y los almacena en un búfer circular.
   - Un **temporizador por hardware configurado a 80 MHz** dispara interrupciones (ISR) con precisión exacta a la frecuencia de muestreo ($f_s$).
   - En cada interrupción, la ISR lee el búfer circular y escribe el valor digital en el **DAC1 (GPIO25)**, garantizando un instante de actualización constante e independiente de la carga de la PC.
   - El sistema cuenta con telemetría en tiempo real (muestras reproducidas, *underruns*, *overruns*) y un pin de sincronización (`SYNC_PIN` en GPIO27) para verificación con osciloscopio.
