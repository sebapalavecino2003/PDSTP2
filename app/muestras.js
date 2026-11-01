// TP Nº2 - Recreación de señales
// muestras.js - Generación de muestras en la PC (SIN APIs de audio)
// Expone: reiniciarGenerador(params) y generarBloque(n)
// Mantiene acumulador de fase entre bloques

let _fase = 0.0;        // acumulador de fase en [0,1)
let _params = {
  forma: "senoidal",   // "senoidal","triangular","cuadrada","rampa","fijo"
  modo: "libre",       // "libre" o "N"
  fs: 20000,
  f: 1000,
  N: 100,
  amp: 100,            // 0-100
  codigo: 128          // para fijo
};

function reiniciarGenerador(params) {
  // params puede tener subset
  if (params) {
    if (typeof params.forma === "string") _params.forma = params.forma;
    if (typeof params.modo === "string") _params.modo = params.modo;
    if (typeof params.fs === "number") _params.fs = params.fs;
    if (typeof params.f === "number") _params.f = params.f;
    if (typeof params.N === "number") _params.N = Math.max(2, Math.floor(params.N));
    if (typeof params.amp === "number") _params.amp = Math.max(0, Math.min(100, params.amp));
    if (typeof params.codigo === "number") _params.codigo = Math.max(0, Math.min(255, Math.floor(params.codigo)));
  }
  _fase = 0.0; // reiniciar fase sin saltos
}

function _incrementoFase() {
  if (_params.modo === "N") {
    if (_params.N < 2) return 1.0 / 2.0;
    return 1.0 / _params.N;
  } else {
    // modo libre
    if (_params.fs <= 0) return 0.0;
    return _params.f / _params.fs;
  }
}

function _formaW(p) {
  // p en [0,1), devuelve w en [-1,1]
  const forma = _params.forma;
  if (forma === "cuadrada") {
    if (p < 0.5) return 1.0;
    else return -1.0;
  } else if (forma === "triangular") {
    // w = 1 - 4*|p - 0.5|
    const val = 1.0 - 4.0 * Math.abs(p - 0.5);
    return val;
  } else if (forma === "senoidal") {
    // w = sin(2*pi*p)
    const w = Math.sin(2.0 * Math.PI * p);
    return w;
  } else if (forma === "rampa") {
    // Generación especial: se maneja por contador global? 
    // Para mantener compatibilidad con acumulador, usar p como contador 0-255
    // Pero reiniciarGenerador reinicia fase; para rampa continua usar lógica externa
    // Aquí: mapear p -> 0->1 lineal
    return (2.0 * p) - 1.0; // -1 a 1
  } else if (forma === "fijo") {
    return 0.0; // se ignora
  }
  // default
  return Math.sin(2.0 * Math.PI * p);
}

// Generador de rampa global para botón Rampa (0-255)
let _rampa_contador = 0;

function generarBloque(n) {
  const muestras = new Uint8Array(n);
  const forma = _params.forma;
  
  if (forma === "fijo") {
    const codigoFijo = Math.max(0, Math.min(255, Math.floor(_params.codigo)));
    for (let i = 0; i < n; i++) {
      muestras[i] = codigoFijo;
    }
    return muestras;
  }
  
  if (forma === "rampa") {
    // Rampa 0,1,...,255,... cíclica
    for (let i = 0; i < n; i++) {
      muestras[i] = _rampa_contador & 0xFF;
      _rampa_contador = (_rampa_contador + 1) >>> 0;
    }
    return muestras;
  }
  
  // Formas normales con acumulador de fase
  const delta = _incrementoFase();
  const ampPct = Math.max(0, Math.min(100, _params.amp));
  
  for (let i = 0; i < n; i++) {
    let p = _fase;
    if (p >= 1.0) {
      p = p - Math.floor(p);
      _fase = p;
    }
    if (p < 0.0) p = 0.0;
    
    const w = _formaW(p);
    // Escalado: codigo = round(127.5 + (amp/100)*127.5*w), recortado 0-255
    let codigo = 127.5 + (ampPct / 100.0) * 127.5 * w;
    codigo = Math.round(codigo);
    if (codigo < 0) codigo = 0;
    if (codigo > 255) codigo = 255;
    
    muestras[i] = codigo & 0xFF;
    
    // Avanzar fase
    _fase += delta;
  }
  
  return muestras;
}

// Función para iniciar rampa desde 0
function iniciarRampa() {
  _rampa_contador = 0;
}

// Función para obtener info de fase (debug)
function getFase() {
  return _fase;
}

// Exportar funciones al scope global
if (typeof window !== "undefined") {
  window.reiniciarGenerador = reiniciarGenerador;
  window.generarBloque = generarBloque;
  window.iniciarRampa = iniciarRampa;
  window.getFase = getFase;
}
