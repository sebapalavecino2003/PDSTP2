#!/bin/bash
# LEVANTAR TODO PARA TP2 - RECREACIÓN DE SEÑALES
# Ejecutar desde /home/sebastian/Escritorio/procesamientos

echo "=== TP2 - Iniciando ==="
echo ""

# 1) Verificar permisos y puerto
echo "[1] Verificando puerto /dev/ttyUSB0..."
ls -la /dev/ttyUSB0 2>&1
echo ""

# 2) Agregar usuario al grupo dialout si falta (solo informativo)
echo "[2] Grupos del usuario:"
groups | grep dialout && echo "OK - ya estás en dialout" || echo "ATENCIÓN - no estás en dialout. Ejecutar: sudo usermod -a -G dialout \$USER && cerrar sesión"
echo ""

# 3) Liberar puerto por si queda ocupado
echo "[3] Liberando puerto por si queda ocupado..."
sudo -n fuser -k /dev/ttyUSB0 2>/dev/null
sleep 1
echo "Listo"
echo ""

# 4) Levantar servidor web
echo "[4] Levantando servidor web en http://localhost:8000/app/"
pkill -f "python3 -m http.server 8000" 2>/dev/null
sleep 1
cd /home/sebastian/Escritorio/procesamientos
nohup python3 -m http.server 8000 >/tmp/http_tp2.log 2>&1 &
sleep 2
echo "Servidor corriendo (PID: $(pgrep -f 'http.server 8000'))"
echo ""

echo "=== LISTO ==="
echo ""
echo "ABRIR EN CHROME/EDGE:"
echo "  http://localhost:8000/app/"
echo ""
echo "ORDEN:"
echo "  1. Conectar (/dev/ttyUSB0)"
echo "  2. Enviar CONFIG con Fs pedida"
echo "  3. Elegir forma/frecuencia/amplitud -> Iniciar"
echo ""
echo "PARA CAMBIAR: Detener -> cambiar -> Iniciar"
echo "PARA CAMBIAR Fs: Detener -> Enviar CONFIG -> Iniciar"
echo "PARA RÁFAGA (5c): Detener -> Ráfaga k=10 (con SYNC en osciloscopio)"
echo ""
echo "SI DA 'Device or resource busy': cerrar Arduino IDE COMPLETO y volver a ejecutar este script"
echo ""
