#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import serial
import serial.tools.list_ports
import threading
import time
import math
import struct
import tkinter as tk
from tkinter import ttk, messagebox

# Protocolo
PKT_START = 0xA5
TYPE_CONFIG = 0x01
TYPE_DATA = 0x02
TYPE_STOP = 0x03

# Generador de muestras (igual lógica que muestras.js)
class Generador:
    def __init__(self):
        self.fase = 0.0
        self.forma = "senoidal"
        self.modo = "libre"
        self.fs = 20000
        self.f = 1000.0
        self.N = 100
        self.amp = 100
        self.rampa_contador = 0
    
    def reiniciar(self, forma="senoidal", modo="libre", fs=20000, f=1000.0, N=100, amp=100):
        self.forma = forma
        self.modo = modo
        self.fs = fs
        self.f = float(f)
        self.N = max(2, int(N))
        self.amp = max(0, min(100, int(amp)))
        self.fase = 0.0
    
    def iniciar_rampa(self):
        self.rampa_contador = 0
    
    def incremento_fase(self):
        if self.modo == "N":
            if self.N < 2:
                return 1.0 / 2.0
            return 1.0 / self.N
        else:
            if self.fs <= 0:
                return 0.0
            return self.f / self.fs
    
    def forma_w(self, p):
        if self.forma == "cuadrada":
            if p < 0.5:
                return 1.0
            else:
                return -1.0
        elif self.forma == "triangular":
            val = 1.0 - 4.0 * abs(p - 0.5)
            return val
        elif self.forma == "senoidal":
            return math.sin(2.0 * math.pi * p)
        elif self.forma == "rampa":
            return (2.0 * p) - 1.0
        else:
            return math.sin(2.0 * math.pi * p)
    
    def generar_bloque(self, n):
        muestras = bytearray(n)
        if self.forma == "fijo":
            codigo_fijo = max(0, min(255, int(self.amp) if False else 128))
            # se maneja desde afuera
            for i in range(n):
                muestras[i] = codigo_fijo
            return bytes(muestras)
        if self.forma == "rampa":
            for i in range(n):
                muestras[i] = self.rampa_contador & 0xFF
                self.rampa_contador = (self.rampa_contador + 1) & 0xFFFFFFFF
            return bytes(muestras)
        delta = self.incremento_fase()
        amp_pct = max(0, min(100, self.amp))
        for i in range(n):
            p = self.fase
            if p >= 1.0:
                p = p - math.floor(p)
                self.fase = p
            if p < 0.0:
                p = 0.0
            w = self.forma_w(p)
            codigo = 127.5 + (amp_pct / 100.0) * 127.5 * w
            codigo = int(round(codigo))
            if codigo < 0:
                codigo = 0
            if codigo > 255:
                codigo = 255
            muestras[i] = codigo & 0xFF
            self.fase += delta
        return bytes(muestras)

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("TP2 - Recreación de señales")
        self.root.geometry("320x280")
        self.root.resizable(False, False)
        
        self.ser = None
        self.running = False
        self.envio_thread = None
        self.lectura_thread = None
        self.enviadas = 0
        self.seq = 0
        self.ready_flag = False
        self.gen = Generador()
        self.fijo_codigo = 128
        
        # Puertos
        frm_puerto = ttk.LabelFrame(root, text="Puerto", padding=5)
        frm_puerto.pack(fill="x", padx=5, pady=2)
        
        self.puerto_var = tk.StringVar()
        self.combo_puerto = ttk.Combobox(frm_puerto, textvariable=self.puerto_var, state="readonly", width=20)
        self.combo_puerto.pack(side="left")
        ttk.Button(frm_puerto, text="Actualizar", command=self.actualizar_puertos).pack(side="left", padx=2)
        
        # Baudrate
        frm_baud = ttk.Frame(root)
        frm_baud.pack(fill="x", padx=5, pady=2)
        ttk.Label(frm_baud, text="Baudrate:").pack(side="left")
        self.baud_var = tk.StringVar(value="921600")
        ttk.Combobox(frm_baud, textvariable=self.baud_var, values=["115200","460800","921600","1000000"], state="readonly", width=10).pack(side="left", padx=2)
        
        # Botones conexión
        frm_conn = ttk.Frame(root)
        frm_conn.pack(fill="x", padx=5, pady=2)
        self.btn_conectar = ttk.Button(frm_conn, text="Conectar", command=self.conectar)
        self.btn_conectar.pack(side="left")
        self.btn_desconectar = ttk.Button(frm_conn, text="Desconectar", command=self.desconectar, state="disabled")
        self.btn_desconectar.pack(side="left", padx=2)
        self.btn_config = ttk.Button(frm_conn, text="Enviar CONFIG", command=self.enviar_config, state="disabled")
        self.btn_config.pack(side="left", padx=2)
        
        # Fs
        frm_fs = ttk.Frame(root)
        frm_fs.pack(fill="x", padx=5, pady=2)
        ttk.Label(frm_fs, text="Fs:").pack(side="left")
        self.fs_var = tk.StringVar(value="20000")
        ttk.Entry(frm_fs, textvariable=self.fs_var, width=8).pack(side="left", padx=2)
        ttk.Label(frm_fs, text="Sa/s").pack(side="left")
        
        # Señal
        frm_sig = ttk.LabelFrame(root, text="Señal", padding=5)
        frm_sig.pack(fill="x", padx=5, pady=2)
        
        frm_f1 = ttk.Frame(frm_sig)
        frm_f1.pack(fill="x")
        ttk.Label(frm_f1, text="Forma:").pack(side="left")
        self.forma_var = tk.StringVar(value="senoidal")
        ttk.Combobox(frm_f1, textvariable=self.forma_var, values=["senoidal","triangular","cuadrada"], state="readonly", width=10).pack(side="left", padx=2)
        ttk.Label(frm_f1, text="f:").pack(side="left", padx=2)
        self.f_var = tk.StringVar(value="1000")
        ttk.Entry(frm_f1, textvariable=self.f_var, width=6).pack(side="left")
        ttk.Label(frm_f1, text="Hz").pack(side="left")
        
        frm_f2 = ttk.Frame(frm_sig)
        frm_f2.pack(fill="x", pady=1)
        ttk.Label(frm_f2, text="Amplitud:").pack(side="left")
        self.amp_var = tk.StringVar(value="100")
        ttk.Scale(frm_f2, from_=0, to=100, orient="horizontal", variable=self.amp_var, length=150).pack(side="left")
        ttk.Label(frm_f2, textvariable=self.amp_var).pack(side="left")
        
        # Control
        frm_ctrl = ttk.Frame(root)
        frm_ctrl.pack(fill="x", padx=5, pady=4)
        self.btn_iniciar = ttk.Button(frm_ctrl, text="Iniciar", command=self.iniciar, state="disabled")
        self.btn_iniciar.pack(side="left")
        self.btn_detener = ttk.Button(frm_ctrl, text="Detener", command=self.detener, state="disabled")
        self.btn_detener.pack(side="left", padx=2)
        self.btn_rafaga = ttk.Button(frm_ctrl, text="Ráfaga k=10", command=self.enviar_rafaga, state="disabled")
        self.btn_rafaga.pack(side="left", padx=2)
        
        self.estado = ttk.Label(root, text="Desconectado")
        self.estado.pack(pady=2)
        
        self.actualizar_puertos()
    
    def actualizar_puertos(self):
        puertos = []
        for p in serial.tools.list_ports.comports():
            dev = p.device
            # Solo puertos USB reales (CH340/CP2102/FTDI)
            if dev.startswith('/dev/ttyUSB') or dev.startswith('/dev/ttyACM'):
                puertos.append(dev)
        self.combo_puerto['values'] = puertos
        if puertos:
            self.combo_puerto.current(0)
        else:
            self.puerto_var.set('')
    
    def conectar(self):
        puerto = self.puerto_var.get()
        if not puerto:
            messagebox.showerror("Error", "Seleccionar puerto")
            return
        try:
            baud = int(self.baud_var.get())
            self.ser = serial.Serial(port=puerto, baudrate=baud, bytesize=8, parity='N', stopbits=1, timeout=0.1, rtscts=False, dsrdtr=False)
            # Desactivar DTR/RTS
            try:
                self.ser.dtr = False
                self.ser.rts = False
            except:
                pass
            self.ready_flag = False
            self.lectura_thread = threading.Thread(target=self.leer_serie, daemon=True)
            self.lectura_thread.start()
            self.btn_conectar.config(state="disabled")
            self.btn_desconectar.config(state="normal")
            self.estado.config(text="Conectando... esperando READY")
            # Esperar un poco para habilitar config
            self.root.after(2000, self.habilitar_config)
        except Exception as e:
            messagebox.showerror("Error", str(e))
    
    def habilitar_config(self):
        if self.ser and self.ser.is_open and self.ready_flag:
            self.btn_config.config(state="normal")
            self.estado.config(text="READY - Enviar CONFIG")
        elif self.ser and self.ser.is_open:
            self.btn_config.config(state="normal")
            self.estado.config(text="Listo - Enviar CONFIG")
    
    def leer_serie(self):
        while self.ser and self.ser.is_open:
            try:
                line = self.ser.readline()
                if line:
                    try:
                        s = line.decode('ascii', errors='ignore').strip()
                        if s == 'READY':
                            self.ready_flag = True
                        elif s.startswith('CFG'):
                            self.root.after(0, lambda: self.estado.config(text=s))
                            self.root.after(0, lambda: self.btn_iniciar.config(state="normal"))
                            self.root.after(0, lambda: self.btn_rafaga.config(state="normal"))
                    except:
                        pass
            except:
                break
            time.sleep(0.01)
    
    def enviar_config(self):
        if not self.ser or not self.ser.is_open:
            return
        try:
            fs = int(self.fs_var.get())
            # Paquete 0xA5 0x01 + fs little endian
            pkt = bytearray([PKT_START, TYPE_CONFIG])
            pkt += struct.pack('<I', fs)
            self.ser.write(bytes(pkt))
            self.estado.config(text="CONFIG enviado")
            self.gen.fs = fs
        except Exception as e:
            messagebox.showerror("Error", str(e))
    
    def iniciar(self):
        if not self.ser or not self.ser.is_open:
            return
        forma = self.forma_var.get()
        f = float(self.f_var.get())
        amp = int(float(self.amp_var.get()))
        self.gen.reiniciar(forma=forma, modo="libre", fs=self.gen.fs, f=f, amp=amp)
        self.enviadas = 0
        self.seq = 0
        self.running = True
        self.envio_thread = threading.Thread(target=self.bucle_envio, daemon=True)
        self.envio_thread.start()
        self.btn_iniciar.config(state="disabled")
        self.btn_detener.config(state="normal")
        self.btn_config.config(state="disabled")
        self.estado.config(text="Enviando...")
    
    def bucle_envio(self):
        # Pre-llenado de buffer (~2000 muestras) en ESP32 para evitar underrun inicial
        for _ in range(10):
            if not self.running or not self.ser or not self.ser.is_open:
                break
            try:
                bloque = self.gen.generar_bloque(200)
                pkt = bytearray([PKT_START, TYPE_DATA, self.seq & 0xFF, len(bloque)])
                pkt += bloque
                self.ser.write(bytes(pkt))
                self.enviadas += len(bloque)
                self.seq = (self.seq + 1) & 0xFF
            except:
                break
        while self.running and self.ser and self.ser.is_open:
            try:
                bloque = self.gen.generar_bloque(200)
                # Paquete DATA: 0xA5 0x02 SEQ LEN + muestras
                pkt = bytearray([PKT_START, TYPE_DATA, self.seq & 0xFF, len(bloque)])
                pkt += bloque
                self.ser.write(bytes(pkt))
                self.enviadas += len(bloque)
                self.seq = (self.seq + 1) & 0xFF
                fs_cadencia = self.gen.fs if self.gen.fs > 0 else 40000
                time.sleep(max(0.001, (len(bloque) / float(fs_cadencia)) * 0.95))
            except:
                break
    
    def detener(self):
        self.running = False
        time.sleep(0.01)
        if self.ser and self.ser.is_open:
            try:
                pkt = bytearray([PKT_START, TYPE_STOP])
                self.ser.write(bytes(pkt))
            except:
                pass
        self.btn_iniciar.config(state="normal")
        self.btn_detener.config(state="disabled")
        self.btn_config.config(state="normal")
        if hasattr(self, 'btn_rafaga'):
            self.btn_rafaga.config(state="normal")
        self.estado.config(text="Detenido")
    
    def enviar_rafaga(self):
        if not self.ser or not self.ser.is_open:
            return
        try:
            self.running = False
            time.sleep(0.01)
            try:
                pkt_stop = bytearray([PKT_START, TYPE_STOP])
                self.ser.write(bytes(pkt_stop))
                time.sleep(0.01)
            except:
                pass
            self.gen.reiniciar(forma="rampa", modo="libre", fs=self.gen.fs, f=1000, amp=100)
            self.gen.iniciar_rampa()
            k = 10
            total = k * 256
            sent = 0
            self.seq = 0
            self.estado.config(text="Enviando ráfaga k=10...")
            if hasattr(self, 'btn_rafaga'):
                self.btn_rafaga.config(state="disabled")
            while sent < total and self.ser and self.ser.is_open:
                n = min(200, total - sent)
                bloque = self.gen.generar_bloque(n)
                pkt = bytearray([PKT_START, TYPE_DATA, self.seq & 0xFF, len(bloque)])
                pkt += bloque
                self.ser.write(bytes(pkt))
                sent += len(bloque)
                self.seq = (self.seq + 1) & 0xFF
                time.sleep(0.002)
            self.estado.config(text="Ráfaga enviada (k=10). Ver SYNC en osciloscopio (GPIO27)")
            if hasattr(self, 'btn_rafaga'):
                self.btn_rafaga.config(state="normal")
        except Exception as e:
            messagebox.showerror("Error", str(e))
    
    def desconectar(self):
        self.detener()
        time.sleep(0.05)
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except:
                pass
        self.ser = None
        self.btn_conectar.config(state="normal")
        self.btn_desconectar.config(state="disabled")
        self.btn_iniciar.config(state="disabled")
        self.btn_desconectar.config(state="disabled")
        self.btn_iniciar.config(state="disabled")
        self.btn_detener.config(state="disabled")
        self.btn_config.config(state="disabled")
        if hasattr(self, 'btn_rafaga'):
            self.btn_rafaga.config(state="disabled")
        self.estado.config(text="Desconectado")

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
