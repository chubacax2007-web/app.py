from datetime import datetime
import json
import os
import queue
import re
import threading
import time
from flask import Flask, Response, jsonify, render_template_string, request
import serial

app = Flask(__name__)

# CONFIGURACIÓN DE PUERTOS SERIALES / TELEMETRÍA ESP32
SERIAL_PORT_1 = "COM3"  # ESP32 Salida / Meta (Pines 34 y 32)
SERIAL_PORT_2 = "COM4"  # ESP32 Giro 50m (Pines 35 y 33)
BAUD_RATE = 115200

data_queue = queue.Queue()
USERS_FILE = "users_db.json"

# Estado global de la sesión activa en piscina (controlada exclusivamente por el Coach)
active_pool_session = {
    "active": False,
    "athlete": None,
    "style": None,
    "distance": None,
    "coach": None,
    "routine_title": None,
    "start_timestamp": None,
}

# Estado en tiempo real del Smartwatch IoT (ESP32 + MPU-9250 por Wi-Fi)
smartwatch_live_state = {
    "connected": False,
    "hand": "Izquierda (Left)",
    "is_left": True,
    "battery": 100,
    "uptime_sec": 0,
    "elbow_angle": 0,
    "elbow_min": 0,
    "elbow_max": 0,
    "shoulder_angle": 0,
    "shoulder_min": 0,
    "shoulder_max": 0,
    "phase_entry": 0,
    "phase_pull": 0,
    "phase_push": 0,
    "force_n": 0,
    "force_left": 0,
    "force_right": 0,
    "strokes": 0,
    "last_seen": 0,
}


def get_default_db():
  return {
      "admins": [{
          "name": "Administrador General",
          "email": "admin@swiitroom.com",
          "password": "admin123",
          "role": "admin",
      }],
      "coaches": [{
          "name": "Pepe Gómez",
          "email": "coach@swiitroom.com",
          "password": "coach123",
          "role": "coach",
      }],
      "athletes": [
          {
              "name": "Mario Peinado",
              "email": "atleta@swiitroom.com",
              "password": "atleta123",
              "role": "athlete",
          },
          {
              "name": "Pepe Juárez",
              "email": "pepej@swiitroom.com",
              "password": "123",
              "role": "athlete",
          },
          {
              "name": "Jaime Pastor",
              "email": "jaime@swiitroom.com",
              "password": "123",
              "role": "athlete",
          },
      ],
      "routines": {
          "Mario Peinado": [
              {
                  "id": "rut-101",
                  "style": "Crol / Libre",
                  "distance": "100 m",
                  "title": "Velocidad Anaeróbica 100m",
                  "desc": (
                      "Salida explosiva desde pad, mantener codo alto (EVF >"
                      " 85°) en tracción y viraje rápido en 50m."
                  ),
                  "assigned_by": "Pepe Gómez",
                  "date": "2026-11-05",
              },
              {
                  "id": "rut-102",
                  "style": "Mariposa",
                  "distance": "50 m",
                  "title": "Potencia de Brazada en Mariposa",
                  "desc": (
                      "Enfoque en simetría de tracción entre brazo izquierdo y"
                      " derecho. Respiración cada 2 brazadas."
                  ),
                  "assigned_by": "Pepe Gómez",
                  "date": "2026-11-07",
              },
          ],
          "Pepe Juárez": [{
              "id": "rut-103",
              "style": "Espalda",
              "distance": "200 m",
              "title": "Resistencia Aeróbica en Espalda",
              "desc": (
                  "Mantener rolido constante y entrada limpia del hombro a 32°."
              ),
              "assigned_by": "Pepe Gómez",
              "date": "2026-11-06",
          }],
      },
      "sessions": [
          {
              "id": "SES-001",
              "athlete": "Mario Peinado",
              "date": "2026-10-20",
              "style": "Crol / Libre",
              "distance": "50 m",
              "distance_m": 50,
              "time_sec": 25.40,
              "split_50m": 25.40,
              "speed_ms": 1.97,
              "elbow_angle": {
                  "avg": 88,
                  "min": 84,
                  "max": 92,
                  "iqr": 4.2,
                  "phase_entry": 32,
                  "phase_pull": 88,
                  "phase_push": 148,
              },
              "shoulder_angle": {"avg": 54, "min": 49, "max": 58, "iqr": 3.5},
              "force_left": {
                  "avg": 425,
                  "min": 405,
                  "max": 442,
                  "strokes": [420, 428, 415, 435, 422, 430],
              },
              "force_right": {
                  "avg": 440,
                  "min": 420,
                  "max": 455,
                  "strokes": [438, 445, 432, 450, 436, 442],
              },
          },
          {
              "id": "SES-002",
              "athlete": "Mario Peinado",
              "date": "2026-10-24",
              "style": "Crol / Libre",
              "distance": "100 m",
              "distance_m": 100,
              "time_sec": 54.80,
              "split_50m": 26.50,
              "speed_ms": 1.82,
              "elbow_angle": {
                  "avg": 89,
                  "min": 85,
                  "max": 93,
                  "iqr": 3.8,
                  "phase_entry": 31,
                  "phase_pull": 89,
                  "phase_push": 150,
              },
              "shoulder_angle": {"avg": 55, "min": 50, "max": 59, "iqr": 3.1},
              "force_left": {
                  "avg": 418,
                  "min": 398,
                  "max": 435,
                  "strokes": [415, 422, 410, 428, 416, 420],
              },
              "force_right": {
                  "avg": 432,
                  "min": 412,
                  "max": 448,
                  "strokes": [430, 436, 425, 442, 428, 434],
              },
          },
          {
              "id": "SES-003",
              "athlete": "Mario Peinado",
              "date": "2026-10-28",
              "style": "Mariposa",
              "distance": "50 m",
              "distance_m": 50,
              "time_sec": 27.10,
              "split_50m": 27.10,
              "speed_ms": 1.85,
              "elbow_angle": {
                  "avg": 92,
                  "min": 88,
                  "max": 96,
                  "iqr": 4.0,
                  "phase_entry": 28,
                  "phase_pull": 92,
                  "phase_push": 154,
              },
              "shoulder_angle": {"avg": 60, "min": 56, "max": 64, "iqr": 3.9},
              "force_left": {
                  "avg": 460,
                  "min": 440,
                  "max": 480,
                  "strokes": [455, 465, 450, 472, 458, 462],
              },
              "force_right": {
                  "avg": 465,
                  "min": 445,
                  "max": 485,
                  "strokes": [460, 470, 455, 478, 462, 468],
              },
          },
          {
              "id": "SES-004",
              "athlete": "Mario Peinado",
              "date": "2026-11-01",
              "style": "Crol / Libre",
              "distance": "100 m",
              "distance_m": 100,
              "time_sec": 53.90,
              "split_50m": 26.10,
              "speed_ms": 1.86,
              "elbow_angle": {
                  "avg": 90,
                  "min": 87,
                  "max": 93,
                  "iqr": 2.9,
                  "phase_entry": 30,
                  "phase_pull": 90,
                  "phase_push": 152,
              },
              "shoulder_angle": {"avg": 56, "min": 52, "max": 59, "iqr": 2.7},
              "force_left": {
                  "avg": 430,
                  "min": 412,
                  "max": 446,
                  "strokes": [425, 434, 420, 440, 428, 433],
              },
              "force_right": {
                  "avg": 442,
                  "min": 425,
                  "max": 456,
                  "strokes": [438, 446, 432, 452, 440, 445],
              },
          },
          {
              "id": "SES-005",
              "athlete": "Mario Peinado",
              "date": "2026-11-04",
              "style": "Crol / Libre",
              "distance": "500 m",
              "distance_m": 500,
              "time_sec": 312.50,
              "split_50m": 30.20,
              "speed_ms": 1.60,
              "elbow_angle": {
                  "avg": 87,
                  "min": 82,
                  "max": 91,
                  "iqr": 4.5,
                  "phase_entry": 33,
                  "phase_pull": 87,
                  "phase_push": 146,
              },
              "shoulder_angle": {"avg": 52, "min": 48, "max": 56, "iqr": 3.8},
              "force_left": {
                  "avg": 390,
                  "min": 370,
                  "max": 410,
                  "strokes": [395, 392, 388, 390, 385, 390],
              },
              "force_right": {
                  "avg": 398,
                  "min": 380,
                  "max": 415,
                  "strokes": [402, 400, 395, 398, 394, 399],
              },
          },
          {
              "id": "SES-006",
              "athlete": "Mario Peinado",
              "date": "2026-11-07",
              "style": "Crol / Libre",
              "distance": "100 m",
              "distance_m": 100,
              "time_sec": 53.15,
              "split_50m": 25.80,
              "speed_ms": 1.88,
              "elbow_angle": {
                  "avg": 91,
                  "min": 88,
                  "max": 94,
                  "iqr": 2.5,
                  "phase_entry": 30,
                  "phase_pull": 91,
                  "phase_push": 155,
              },
              "shoulder_angle": {"avg": 57, "min": 54, "max": 60, "iqr": 2.4},
              "force_left": {
                  "avg": 438,
                  "min": 422,
                  "max": 452,
                  "strokes": [432, 440, 435, 446, 436, 440],
              },
              "force_right": {
                  "avg": 448,
                  "min": 434,
                  "max": 460,
                  "strokes": [445, 450, 442, 456, 446, 450],
              },
          },
          {
              "id": "SES-007",
              "athlete": "Pepe Juárez",
              "date": "2026-11-02",
              "style": "Crol / Libre",
              "distance": "50 m",
              "distance_m": 50,
              "time_sec": 26.20,
              "split_50m": 26.20,
              "speed_ms": 1.91,
              "elbow_angle": {
                  "avg": 86,
                  "min": 82,
                  "max": 90,
                  "iqr": 3.6,
                  "phase_entry": 34,
                  "phase_pull": 86,
                  "phase_push": 145,
              },
              "shoulder_angle": {"avg": 53, "min": 49, "max": 57, "iqr": 3.2},
              "force_left": {
                  "avg": 415,
                  "min": 398,
                  "max": 430,
                  "strokes": [410, 418, 412, 422, 414, 416],
              },
              "force_right": {
                  "avg": 408,
                  "min": 390,
                  "max": 424,
                  "strokes": [405, 412, 404, 415, 406, 408],
              },
          },
          {
              "id": "SES-008",
              "athlete": "Pepe Juárez",
              "date": "2026-11-06",
              "style": "Crol / Libre",
              "distance": "100 m",
              "distance_m": 100,
              "time_sec": 55.40,
              "split_50m": 26.90,
              "speed_ms": 1.81,
              "elbow_angle": {
                  "avg": 85,
                  "min": 81,
                  "max": 89,
                  "iqr": 3.8,
                  "phase_entry": 33,
                  "phase_pull": 85,
                  "phase_push": 144,
              },
              "shoulder_angle": {"avg": 52, "min": 48, "max": 56, "iqr": 3.4},
              "force_left": {
                  "avg": 410,
                  "min": 392,
                  "max": 425,
                  "strokes": [408, 414, 405, 418, 408, 410],
              },
              "force_right": {
                  "avg": 402,
                  "min": 385,
                  "max": 418,
                  "strokes": [400, 406, 398, 410, 400, 402],
              },
          },
          {
              "id": "SES-009",
              "athlete": "Jaime Pastor",
              "date": "2026-11-05",
              "style": "Crol / Libre",
              "distance": "50 m",
              "distance_m": 50,
              "time_sec": 24.95,
              "split_50m": 24.95,
              "speed_ms": 2.00,
              "elbow_angle": {
                  "avg": 91,
                  "min": 88,
                  "max": 94,
                  "iqr": 2.6,
                  "phase_entry": 29,
                  "phase_pull": 91,
                  "phase_push": 156,
              },
              "shoulder_angle": {"avg": 58, "min": 55, "max": 61, "iqr": 2.5},
              "force_left": {
                  "avg": 450,
                  "min": 435,
                  "max": 465,
                  "strokes": [448, 452, 445, 458, 449, 451],
              },
              "force_right": {
                  "avg": 455,
                  "min": 440,
                  "max": 470,
                  "strokes": [452, 458, 450, 462, 454, 456],
              },
          },
      ],
  }


def load_users():
  default_data = get_default_db()
  if os.path.exists(USERS_FILE):
    try:
      with open(USERS_FILE, "r", encoding="utf-8") as f:
        loaded = json.load(f)
        for key in ["admins", "coaches", "athletes", "routines", "sessions"]:
          if key not in loaded:
            loaded[key] = default_data[key]
        for role_key in ["admins", "coaches", "athletes"]:
          existing_emails = {u["email"].lower() for u in loaded[role_key]}
          for default_u in default_data[role_key]:
            if default_u["email"].lower() not in existing_emails:
              loaded[role_key].append(default_u)
        return loaded
    except Exception:
      pass
  save_users(default_data)
  return default_data


def save_users(db):
  try:
    with open(USERS_FILE, "w", encoding="utf-8") as f:
      json.dump(db, f, indent=4, ensure_ascii=False)
  except Exception as e:
    print(f"Error guardando base de datos: {e}")


users_db = load_users()


def parse_distance_meters(dist_str):
  if "1 km" in dist_str or "1000" in dist_str:
    return 1000
  m = re.search(r"(\d+)", dist_str)
  return int(m.group(1)) if m else 50


def read_serial(port_name):
  try:
    ser = serial.Serial(port_name, BAUD_RATE, timeout=1)
    print(f"Conectado a ESP32 en {port_name}")
    while True:
      if ser.in_waiting:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line and active_pool_session["active"]:
          data_queue.put(f"[{port_name}] {line}")
  except Exception as e:
    print(f"Aviso en puerto {port_name}: {e}. (Modo Wi-Fi / Simulación listo)")


threading.Thread(target=read_serial, args=(SERIAL_PORT_1,), daemon=True).start()
threading.Thread(target=read_serial, args=(SERIAL_PORT_2,), daemon=True).start()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SWiiTroom - Plataforma Profesional de Telemetría y Biomecánica</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background-color: #f8fafc; color: #0f172a; font-family: 'Segoe UI', system-ui, sans-serif; min-height: 100vh; }
        .clean-card { background: #ffffff; border: 1px solid #e2e8f0; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.04); }
        .hero-banner { background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%); color: #ffffff; }
        .login-hero-bg { 
            background: linear-gradient(180deg, rgba(3, 105, 161, 0.25) 0%, rgba(5, 11, 24, 0.96) 100%), url('https://images.unsplash.com/photo-1530549387789-4c1017266635?auto=format&fit=crop&w=800&q=80'); 
            background-size: cover; background-position: center; 
        }
        .tab-btn.active { color: #0284c7; border-bottom: 3px solid #0284c7; font-weight: 800; }
        .tab-btn { color: #64748b; border-bottom: 3px solid transparent; }
        .tooltip-box { display: none; }
        .tooltip-trigger:hover .tooltip-box { display: block; }
    </style>
</head>
<body class="flex flex-col">

    <!-- MODAL DE AUTENTICACIÓN, REGISTRO CON VALIDACIÓN Y RECUPERACIÓN DE CUENTA -->
    <div id="auth-modal" class="fixed inset-0 bg-slate-950/90 backdrop-blur-md z-50 flex items-center justify-center p-4">
        
        <div id="login-screen-welcome" class="login-hero-bg rounded-[2.5rem] max-w-sm w-full h-[580px] flex flex-col justify-between p-8 text-center text-white shadow-2xl border border-white/10 relative">
            <div class="pt-8">
                <div class="text-2xl font-black tracking-widest text-white">SWiiT<span class="text-sky-400">room</span></div>
                <p class="text-[11px] text-sky-200 mt-1 font-semibold">Telemetría Piscina 50m & Smartwatch MPU-9250</p>
            </div>
            <div class="space-y-3.5 pb-4">
                <p class="text-xs text-slate-200">Control biomecánico de brazada con punto cero (0°), sensores de contacto ESP32 y análisis histórico por sesión.</p>
                <button onclick="switchAuthMode('login')" class="w-full bg-white text-slate-950 font-extrabold py-3.5 rounded-full text-xs shadow-xl hover:bg-slate-100">
                    Iniciar Sesión
                </button>
                <button onclick="switchAuthMode('register')" class="w-full bg-sky-600 text-white font-extrabold py-3.5 rounded-full text-xs shadow-xl hover:bg-sky-500">
                    Registrarse (Crear Cuenta)
                </button>
            </div>
        </div>

        <div id="login-screen-form" class="clean-card p-8 rounded-3xl max-w-md w-full shadow-2xl border-slate-200 hidden space-y-4">
            <div class="flex justify-between items-center border-b pb-3">
                <span id="form-main-title" class="text-lg font-black text-slate-900">Iniciar Sesión</span>
                <button onclick="switchAuthMode('welcome')" class="text-xs text-slate-400 hover:text-slate-600 font-bold">Volver</button>
            </div>
            
            <div id="auth-error-box" class="bg-rose-50 border border-rose-200 text-rose-700 px-3 py-2 rounded-xl text-xs font-bold hidden"></div>
            <div id="auth-success-box" class="bg-emerald-50 border border-emerald-200 text-emerald-700 px-3 py-2 rounded-xl text-xs font-bold hidden"></div>

            <form id="auth-form" onsubmit="handleAuthSubmit(event)" class="space-y-3">
                <div id="field-name-container" class="hidden">
                    <label class="block text-xs font-bold text-slate-700 mb-1">Nombre Completo</label>
                    <input type="text" id="input-name" placeholder="Ej. Carlos Vela" class="w-full bg-slate-50 border rounded-xl px-3 py-2 text-xs">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-700 mb-1">Correo Electrónico (Validado)</label>
                    <input type="email" id="input-email" required placeholder="usuario@dominio.com" class="w-full bg-slate-50 border rounded-xl px-3 py-2 text-xs">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-700 mb-1">Contraseña</label>
                    <input type="password" id="input-password" required placeholder="••••••••" class="w-full bg-slate-50 border rounded-xl px-3 py-2 text-xs">
                </div>
                <div id="field-role-container">
                    <label class="block text-xs font-bold text-slate-700 mb-1">Rol en el Sistema</label>
                    <select id="input-role" class="w-full bg-slate-50 border rounded-xl px-3 py-2 text-xs font-bold text-sky-700">
                        <option value="athlete">🏊‍♂️ Nadador / Atleta</option>
                        <option value="coach">📋 Entrenador (Coach)</option>
                        <option value="admin">🛡️ Administrador</option>
                    </select>
                </div>
                <button type="submit" id="auth-submit-btn" class="w-full bg-sky-600 hover:bg-sky-700 text-white font-black py-2.5 rounded-xl text-xs shadow-md">
                    Entrar
                </button>
                <div id="forgot-password-link" class="text-center pt-2">
                    <button type="button" onclick="switchAuthMode('recover')" class="text-xs text-sky-600 hover:underline font-bold">
                        ¿Olvidaste tu contraseña? Recuperar cuenta
                    </button>
                </div>
            </form>

            <form id="recover-form" onsubmit="handleRecoverSubmit(event)" class="space-y-3 hidden">
                <p class="text-xs text-slate-500">Ingresa tu correo registrado y define tu nueva contraseña para restablecer el acceso a tu cuenta.</p>
                <div>
                    <label class="block text-xs font-bold text-slate-700 mb-1">Correo Electrónico Registrado</label>
                    <input type="email" id="recover-email" required placeholder="tu_correo@dominio.com" class="w-full bg-slate-50 border rounded-xl px-3 py-2 text-xs">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-700 mb-1">Nueva Contraseña</label>
                    <input type="password" id="recover-new-password" required placeholder="Mínimo 4 caracteres" class="w-full bg-slate-50 border rounded-xl px-3 py-2 text-xs">
                </div>
                <button type="submit" class="w-full bg-amber-600 hover:bg-amber-700 text-white font-black py-2.5 rounded-xl text-xs shadow-md">
                    Restablecer Contraseña
                </button>
                <div class="text-center pt-1">
                    <button type="button" onclick="switchAuthMode('login')" class="text-xs text-slate-500 hover:underline font-bold">
                        Volver a Iniciar Sesión
                    </button>
                </div>
            </form>
        </div>
    </div>

    <!-- MODAL DE CONFIRMACIÓN DEL COACH ANTES DE INICIAR ENTRENAMIENTO -->
    <div id="confirm-session-modal" class="fixed inset-0 bg-slate-950/75 backdrop-blur-sm z-50 hidden items-center justify-center p-4">
        <div class="clean-card p-6 rounded-3xl max-w-md w-full shadow-2xl space-y-4 border-2 border-sky-500">
            <div class="flex items-center gap-3 text-sky-700">
                <i data-lucide="shield-alert" class="w-6 h-6"></i>
                <h3 class="text-base font-black">Confirmar Inicio de Registro en Piscina</h3>
            </div>
            <p class="text-xs text-slate-600 leading-relaxed">
                El reloj biométrico (MPU-9250) y los sensores ESP32 asignarán todos los datos de esta sesión al siguiente nadador. Verifica que sea el atleta correcto antes de iniciar:
            </p>
            <div class="bg-slate-50 p-4 rounded-2xl border space-y-1.5 text-xs">
                <div class="flex justify-between"><span class="text-slate-400 font-bold">Atleta Seleccionado:</span> <span id="conf-athlete" class="font-black text-slate-900"></span></div>
                <div class="flex justify-between"><span class="text-slate-400 font-bold">Estilo Oficial:</span> <span id="conf-style" class="font-bold text-indigo-700"></span></div>
                <div class="flex justify-between"><span class="text-slate-400 font-bold">Distancia Objetivo:</span> <span id="conf-distance" class="font-bold text-emerald-700"></span></div>
                <div class="flex justify-between"><span class="text-slate-400 font-bold">Referencia:</span> <span id="conf-title" class="font-semibold text-slate-700"></span></div>
            </div>
            <div class="flex justify-end gap-3 pt-2">
                <button onclick="closeConfirmModal()" class="px-4 py-2 rounded-xl border text-xs font-bold text-slate-600 hover:bg-slate-100">
                    Cancelar
                </button>
                <button onclick="confirmAndStartPoolSession()" class="bg-emerald-600 hover:bg-emerald-700 text-white font-black px-5 py-2 rounded-xl text-xs shadow-md flex items-center gap-1.5">
                    <i data-lucide="play" class="w-4 h-4"></i> Sí, Iniciar Cronómetro y Captura
                </button>
            </div>
        </div>
    </div>

    <!-- NAVBAR PRINCIPAL -->
    <nav class="clean-card border-b border-slate-200 px-6 py-4 flex justify-between items-center sticky top-0 z-40">
        <div class="flex items-center gap-3">
            <div class="bg-sky-600 text-white p-2 rounded-xl font-black text-lg">SW</div>
            <span class="text-xl font-black text-slate-900">SWiiT<span class="text-sky-600">room</span></span>
        </div>

        <div class="flex items-center gap-4">
            <!-- Selector "Atleta Seleccionado" EXCLUSIVO PARA COACH Y ADMIN -->
            <div id="coach-athlete-selector-container" class="hidden items-center gap-2 bg-slate-100 border px-3.5 py-1.5 rounded-2xl">
                <i data-lucide="waves" class="w-4 h-4 text-sky-600"></i>
                <span class="text-xs text-slate-600 font-semibold hidden sm:inline">Atleta Seleccionado (Vista Coach):</span>
                <select id="select-active-athlete" onchange="changeActiveAthlete(this.value)" class="bg-transparent text-xs font-bold text-sky-700 focus:outline-none">
                </select>
            </div>

            <div class="text-right hidden sm:block">
                <div class="text-sm font-bold text-slate-900" id="nav-username">Usuario</div>
                <span class="text-[10px] px-2.5 py-0.5 rounded-full font-black uppercase bg-sky-100 text-sky-700" id="nav-userrole">Rol</span>
            </div>
            <button onclick="logout()" class="bg-slate-100 hover:bg-rose-50 text-slate-600 p-2.5 rounded-2xl border text-xs" title="Cerrar Sesión">
                <i data-lucide="log-out" class="w-4 h-4"></i>
            </button>
        </div>
    </nav>

    <!-- BANNER DE TELEMETRÍA EN VIVO Y CRONÓMETRO ASCENDENTE -->
    <div class="hero-banner shadow-md px-6 py-3">
        <div class="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4">
            <div class="flex items-center gap-3">
                <div id="live-indicator-dot" class="w-3.5 h-3.5 rounded-full bg-amber-400"></div>
                <div>
                    <div class="text-[10px] text-sky-200 font-extrabold uppercase">ESTADO DE PISCINA 50M (ESP32 #1 SALIDA/META & ESP32 #2 GIRO) + SMARTWATCH MPU-9250</div>
                    <div id="status-text" class="text-sm font-black text-white">⚪ Sin sesión activa en piscina (Esperando inicio del Coach)</div>
                </div>
            </div>
            <div class="flex items-center gap-6 bg-white/10 px-4 py-2 rounded-2xl backdrop-blur-md">
                <div class="text-center">
                    <div class="text-[10px] text-sky-100 font-bold uppercase">Cronómetro Ascendente</div>
                    <div id="banner-stopwatch" class="text-lg font-black text-amber-300 font-mono">00:00.0</div>
                </div>
                <div class="w-px h-6 bg-white/20"></div>
                <div class="text-center">
                    <div class="text-[10px] text-sky-100 font-bold uppercase">Smartwatch Wi-Fi</div>
                    <div id="banner-smartwatch-status" class="text-xs font-black text-sky-200">En espera...</div>
                </div>
                <div class="w-px h-6 bg-white/20"></div>
                <div class="text-center">
                    <div class="text-[10px] text-sky-100 font-bold uppercase">Distancia / Estilo</div>
                    <div id="banner-session-meta" class="text-xs font-black text-emerald-300">--</div>
                </div>
            </div>
        </div>
    </div>

    <!-- PESTAÑAS DE NAVEGACIÓN SUPERIOR -->
    <div class="bg-white border-b border-slate-200 sticky top-[73px] z-30 px-6">
        <div class="max-w-7xl mx-auto flex gap-6 sm:gap-8 justify-center sm:justify-start overflow-x-auto">
            <button onclick="switchTab('progress')" id="tab-btn-progress" class="tab-btn active py-3 text-xs font-black uppercase tracking-wider flex items-center gap-2 whitespace-nowrap">
                <i data-lucide="line-chart" class="w-4 h-4"></i> Historial y Progreso
            </button>
            <button onclick="switchTab('smartwatch')" id="tab-btn-smartwatch" class="tab-btn py-3 text-xs font-black uppercase tracking-wider flex items-center gap-2 whitespace-nowrap">
                <i data-lucide="watch" class="w-4 h-4 text-sky-600"></i> Biomecánica (Smartwatch)
            </button>
            <button onclick="switchTab('activities')" id="tab-btn-activities" class="tab-btn py-3 text-xs font-black uppercase tracking-wider flex items-center gap-2 whitespace-nowrap">
                <i data-lucide="list-checks" class="w-4 h-4"></i> Control de Piscina & Rutinas
            </button>
            <button onclick="switchTab('leaderboard')" id="tab-btn-leaderboard" class="tab-btn py-3 text-xs font-black uppercase tracking-wider flex items-center gap-2 whitespace-nowrap">
                <i data-lucide="trophy" class="w-4 h-4 text-amber-500"></i> Ranking (Estilo y Distancia)
            </button>
            <button onclick="switchTab('profile')" id="tab-btn-profile" class="tab-btn py-3 text-xs font-black uppercase tracking-wider flex items-center gap-2 whitespace-nowrap">
                <i data-lucide="user" class="w-4 h-4"></i> Perfil / Admin
            </button>
        </div>
    </div>

    <!-- CONTENEDOR PRINCIPAL -->
    <div class="flex-1 max-w-7xl w-full mx-auto p-4 md:p-6 space-y-6">

        <!-- 1. HISTORIAL CONSULTABLE POR SESIÓN Y COMPARADOR (PROGRESS) -->
        <div id="tab-content-progress" class="space-y-6">
            <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div class="clean-card p-5 rounded-2xl">
                    <div class="text-[11px] text-slate-400 font-bold uppercase">Atleta Consultado</div>
                    <div class="text-xl font-black text-slate-900 mt-1" id="stat-athlete-name">--</div>
                </div>
                <div class="clean-card p-5 rounded-2xl">
                    <div class="text-[11px] text-slate-400 font-bold uppercase">Distancia Acumulada</div>
                    <div class="text-2xl font-black text-sky-600 mt-1" id="stat-dist">0.00 km</div>
                </div>
                <div class="clean-card p-5 rounded-2xl">
                    <div class="text-[11px] text-slate-400 font-bold uppercase">Tiempo Total Registrado</div>
                    <div class="text-2xl font-black text-indigo-600 mt-1" id="stat-time">0.0 min</div>
                </div>
                <div class="clean-card p-5 rounded-2xl">
                    <div class="text-[11px] text-slate-400 font-bold uppercase">Sesiones Completadas</div>
                    <div class="text-2xl font-black text-emerald-600 mt-1" id="stat-workouts">0 Sesiones</div>
                </div>
            </div>

            <div class="clean-card p-5 rounded-3xl space-y-4">
                <div class="flex flex-wrap items-center justify-between gap-4 border-b pb-3">
                    <div>
                        <h3 class="text-sm font-black text-slate-900 flex items-center gap-2">
                            <i data-lucide="sliders" class="w-4 h-4 text-sky-600"></i> Explorador y Comparador de Sesiones
                        </h3>
                        <p class="text-xs text-slate-500">Filtra por estilo, fecha o compara el rendimiento entre sesiones concretas.</p>
                    </div>
                    <div class="flex flex-wrap gap-3">
                        <div>
                            <label class="block text-[10px] font-bold text-slate-500 uppercase">Filtrar Estilo</label>
                            <select id="filter-session-style" onchange="applySessionFilters()" class="bg-slate-50 border rounded-xl px-3 py-1.5 text-xs font-bold text-slate-800">
                                <option value="ALL">Todos los Estilos</option>
                                <option value="Crol / Libre">Crol / Libre</option>
                                <option value="Espalda">Espalda</option>
                                <option value="Pecho / Braza">Pecho / Braza</option>
                                <option value="Mariposa">Mariposa</option>
                                <option value="Combinado Individual (CI)">Combinado Individual (CI)</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-[10px] font-bold text-slate-500 uppercase">Desde Fecha</label>
                            <input type="date" id="filter-date-from" onchange="applySessionFilters()" class="bg-slate-50 border rounded-xl px-2.5 py-1 text-xs">
                        </div>
                        <div>
                            <label class="block text-[10px] font-bold text-slate-500 uppercase">Hasta Fecha</label>
                            <input type="date" id="filter-date-to" onchange="applySessionFilters()" class="bg-slate-50 border rounded-xl px-2.5 py-1 text-xs">
                        </div>
                        <div>
                            <label class="block text-[10px] font-bold text-slate-500 uppercase">Rango de Comparación</label>
                            <select id="filter-comparison-mode" onchange="applySessionFilters()" class="bg-sky-50 border border-sky-200 rounded-xl px-3 py-1.5 text-xs font-black text-sky-800">
                                <option value="all">Histórico Completo</option>
                                <option value="prev">Última Sesión vs. Anterior</option>
                                <option value="last5">Últimas 5 Sesiones</option>
                                <option value="last10">Últimas 10 Sesiones</option>
                            </select>
                        </div>
                    </div>
                </div>

                <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 items-center">
                    <div class="lg:col-span-8 h-64 w-full relative">
                        <canvas id="chartProgressComparison"></canvas>
                    </div>
                    <div id="comparison-summary-card" class="lg:col-span-4 bg-slate-50 p-4 rounded-2xl border space-y-2 text-xs">
                        <div class="font-black text-slate-800 uppercase text-[11px]">Resumen Comparativo</div>
                        <div id="comparison-summary-body" class="space-y-1.5 text-slate-600">
                            Selecciona una sesión de la tabla inferior para inspeccionar sus métricas o comparar contra la sesión previa.
                        </div>
                    </div>
                </div>
            </div>

            <div class="clean-card p-6 rounded-3xl space-y-4">
                <h3 class="text-sm font-extrabold text-slate-900 flex items-center gap-2">
                    <i data-lucide="calendar-clock" class="w-4 h-4 text-indigo-600"></i> Historial Detallado por Sesión (Haz clic en una sesión para abrir su biomecánica)
                </h3>
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse text-xs">
                        <thead>
                            <tr class="border-b bg-slate-50 text-slate-500 uppercase text-[10px] font-extrabold">
                                <th class="p-3">ID / Fecha</th>
                                <th class="p-3">Estilo</th>
                                <th class="p-3">Distancia</th>
                                <th class="p-3">Tiempo Real</th>
                                <th class="p-3">Velocidad</th>
                                <th class="p-3">Codo Prom.</th>
                                <th class="p-3">Fuerza (Izq/Der)</th>
                                <th class="p-3 text-right">Acción</th>
                            </tr>
                        </thead>
                        <tbody id="sessions-history-tbody" class="divide-y"></tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- 2. SMARTWATCH BIOMECÁNICA (DISPERSIÓN, TOOLTIPS E IMÁGENES ESTÁTICAS CON ÁNGULO EN VIVO) -->
        <div id="tab-content-smartwatch" class="space-y-6 hidden">
            <div class="clean-card p-6 rounded-3xl space-y-6">
                <div class="flex flex-wrap justify-between items-center border-b pb-4 gap-2">
                    <div>
                        <h2 class="text-xl font-black text-slate-900 flex items-center gap-2">
                            <i data-lucide="watch" class="text-sky-600"></i> Biomecánica de Brazada (<span id="smartwatch-athlete-name">Atleta</span>)
                        </h2>
                        <p class="text-xs text-slate-500" id="smartwatch-session-subtitle">Mostrando métricas depuradas de valores atípicos (criterio IQR).</p>
                    </div>
                    <span id="smartwatch-badge-live" class="bg-emerald-100 text-emerald-800 px-3 py-1 rounded-full text-xs font-bold">● MPU-9250 9-Axis & FSR Activos</span>
                </div>

                <!-- Tarjetas de Estado Físico del Smartwatch IoT (Mano GPIO 4 y Batería RTC) -->
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4 bg-sky-50/60 p-4 rounded-2xl border border-sky-100">
                    <div class="flex items-center justify-between">
                        <span class="text-xs font-bold text-slate-600">Mano Configurada (GPIO 4):</span>
                        <span id="sw-live-hand" class="text-xs font-black text-sky-800 bg-white px-3 py-1 rounded-full border">Izquierda (Left)</span>
                    </div>
                    <div class="flex items-center justify-between">
                        <span class="text-xs font-bold text-slate-600">Batería Estimada (RTC):</span>
                        <span id="sw-live-battery" class="text-xs font-black text-emerald-700 bg-white px-3 py-1 rounded-full border">100%</span>
                    </div>
                    <div class="flex items-center justify-between">
                        <span class="text-xs font-bold text-slate-600">Tiempo Activo Acumulado:</span>
                        <span id="sw-live-uptime" class="text-xs font-mono font-bold text-slate-800 bg-white px-3 py-1 rounded-full border">0 s</span>
                    </div>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
                    <div class="bg-slate-50 p-4 rounded-2xl border relative">
                        <div class="flex justify-between items-center">
                            <span class="text-[10px] text-slate-500 font-extrabold uppercase">Ángulo Codo (Tracción)</span>
                            <div class="relative tooltip-trigger cursor-pointer">
                                <span class="w-4 h-4 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center text-[10px] font-black">?</span>
                                <div class="tooltip-box absolute right-0 top-6 w-64 bg-slate-900 text-white p-3 rounded-xl text-[11px] z-50 shadow-xl">
                                    <strong>Cálculo Ángulo de Codo:</strong> Medido con filtro complementario (MPU-9250) desde la referencia de 0° (brazo horizontal a la altura del hombro). Se descartan valores atípicos fuera de Q1 - 1.5*IQR y Q3 + 1.5*IQR.
                                </div>
                            </div>
                        </div>
                        <div class="text-2xl font-black text-indigo-600 mt-1" id="sw-codo-avg">0°</div>
                        <div class="text-[11px] text-slate-500 mt-1 font-semibold" id="sw-codo-disp">Mín: 0° | Máx: 0° (IQR: 0°)</div>
                    </div>

                    <div class="bg-slate-50 p-4 rounded-2xl border relative">
                        <div class="flex justify-between items-center">
                            <span class="text-[10px] text-slate-500 font-extrabold uppercase">Ángulo Hombro (Abducción)</span>
                            <div class="relative tooltip-trigger cursor-pointer">
                                <span class="w-4 h-4 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center text-[10px] font-black">?</span>
                                <div class="tooltip-box absolute right-0 top-6 w-64 bg-slate-900 text-white p-3 rounded-xl text-[11px] z-50 shadow-xl">
                                    <strong>Cálculo Ángulo de Hombro:</strong> Calculado respecto al punto cero (0°) calibrado con el brazo extendido a la altura del hombro, filtrando picos por turbulencia.
                                </div>
                            </div>
                        </div>
                        <div class="text-2xl font-black text-sky-600 mt-1" id="sw-hombro-avg">0°</div>
                        <div class="text-[11px] text-slate-500 mt-1 font-semibold" id="sw-hombro-disp">Mín: 0° | Máx: 0° (IQR: 0°)</div>
                    </div>

                    <div class="bg-slate-50 p-4 rounded-2xl border relative">
                        <div class="flex justify-between items-center">
                            <span class="text-[10px] text-slate-500 font-extrabold uppercase">Fuerza Brazada (Izq / Der)</span>
                            <div class="relative tooltip-trigger cursor-pointer">
                                <span class="w-4 h-4 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center text-[10px] font-black">?</span>
                                <div class="tooltip-box absolute right-0 top-6 w-64 bg-slate-900 text-white p-3 rounded-xl text-[11px] z-50 shadow-xl">
                                    <strong>Cálculo de Fuerza (N):</strong> Estimada combinando aceleración neta dinámica del MPU-9250 (±4g) y empuje hidrodinámico sin valores atípicos.
                                </div>
                            </div>
                        </div>
                        <div class="text-2xl font-black text-amber-600 mt-1" id="sw-fuerza-avg">0 N / 0 N</div>
                        <div class="text-[11px] text-slate-500 mt-1 font-semibold" id="sw-fuerza-disp">Rango limpio: 0 - 0 N</div>
                    </div>

                    <div class="bg-slate-50 p-4 rounded-2xl border relative">
                        <div class="flex justify-between items-center">
                            <span class="text-[10px] text-slate-500 font-extrabold uppercase">Velocidad Media de Nado</span>
                            <div class="relative tooltip-trigger cursor-pointer">
                                <span class="w-4 h-4 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center text-[10px] font-black">?</span>
                                <div class="tooltip-box absolute right-0 top-6 w-64 bg-slate-900 text-white p-3 rounded-xl text-[11px] z-50 shadow-xl">
                                    <strong>Cálculo de Velocidad (m/s):</strong> Relación exacta Distancia / Tiempo Real sincronizada con el cronómetro ascendente y los pads ESP32.
                                </div>
                            </div>
                        </div>
                        <div class="text-2xl font-black text-emerald-600 mt-1" id="sw-vel-avg">0.00 m/s</div>
                        <div class="text-[11px] text-slate-500 mt-1 font-semibold" id="sw-vel-disp">Parcial 50m: 0.00 s</div>
                    </div>
                </div>

                <!-- IMÁGENES DE REFERENCIA ESTÁTICAS CON EL VALOR DEL ÁNGULO ACTUALIZADO -->
                <div class="clean-card p-5 rounded-2xl bg-slate-50/70 space-y-3">
                    <div class="flex justify-between items-center">
                        <h3 class="text-xs font-extrabold text-slate-800 uppercase flex items-center gap-2">
                            <i data-lucide="scan-line" class="w-4 h-4 text-indigo-600"></i> Posturas Biomecánicas de Referencia con Ángulo Actualizado (Punto 0° en Hombro)
                        </h3>
                        <span class="text-[11px] text-slate-500">Diagramas estáticos de referencia con superposición dinámica de medición</span>
                    </div>
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div class="bg-white p-4 rounded-2xl border flex flex-col items-center text-center">
                            <div class="text-xs font-black text-slate-700 mb-2">1. Fase de Entrada y Agarre</div>
                            <svg viewBox="0 0 220 130" class="w-48 h-28">
                                <line x1="10" y1="65" x2="210" y2="65" stroke="#38bdf8" stroke-width="2" stroke-dasharray="4 4"/>
                                <circle cx="70" cy="60" r="10" fill="#64748b"/>
                                <line x1="30" y1="65" x2="85" y2="65" stroke="#334155" stroke-width="6" stroke-linecap="round"/>
                                <line x1="85" y1="65" x2="145" y2="45" stroke="#0284c7" stroke-width="5" stroke-linecap="round"/>
                                <line x1="145" y1="45" x2="190" y2="68" stroke="#0284c7" stroke-width="5" stroke-linecap="round"/>
                                <path d="M 120 53 A 25 25 0 0 1 165 56" fill="none" stroke="#dc2626" stroke-width="2.5"/>
                                <circle cx="145" cy="45" r="4" fill="#dc2626"/>
                            </svg>
                            <div class="mt-2 bg-sky-50 border border-sky-200 px-3 py-1 rounded-full text-xs font-black text-sky-800">
                                Ángulo de Entrada: <span id="ref-angle-entry">0°</span>
                            </div>
                        </div>

                        <div class="bg-white p-4 rounded-2xl border flex flex-col items-center text-center">
                            <div class="text-xs font-black text-slate-700 mb-2">2. Fase de Tracción (Codo Alto)</div>
                            <svg viewBox="0 0 220 130" class="w-48 h-28">
                                <line x1="10" y1="45" x2="210" y2="45" stroke="#38bdf8" stroke-width="2" stroke-dasharray="4 4"/>
                                <circle cx="95" cy="42" r="10" fill="#64748b"/>
                                <line x1="45" y1="48" x2="110" y2="48" stroke="#334155" stroke-width="6" stroke-linecap="round"/>
                                <line x1="110" y1="48" x2="145" y2="68" stroke="#4f46e5" stroke-width="5" stroke-linecap="round"/>
                                <line x1="145" y1="68" x2="145" y2="115" stroke="#4f46e5" stroke-width="5" stroke-linecap="round"/>
                                <path d="M 128 58 A 20 20 0 0 0 145 90" fill="none" stroke="#dc2626" stroke-width="2.5"/>
                                <circle cx="145" cy="68" r="4.5" fill="#dc2626"/>
                            </svg>
                            <div class="mt-2 bg-indigo-50 border border-indigo-200 px-3 py-1 rounded-full text-xs font-black text-indigo-800">
                                Ángulo Codo / Hombro: <span id="ref-angle-pull">0°</span> / <span id="ref-angle-shoulder">0°</span>
                            </div>
                        </div>

                        <div class="bg-white p-4 rounded-2xl border flex flex-col items-center text-center">
                            <div class="text-xs font-black text-slate-700 mb-2">3. Fase de Empuje y Salida</div>
                            <svg viewBox="0 0 220 130" class="w-48 h-28">
                                <line x1="10" y1="55" x2="210" y2="55" stroke="#38bdf8" stroke-width="2" stroke-dasharray="4 4"/>
                                <circle cx="135" cy="50" r="10" fill="#64748b"/>
                                <line x1="75" y1="56" x2="145" y2="56" stroke="#334155" stroke-width="6" stroke-linecap="round"/>
                                <line x1="120" y1="56" x2="85" y2="75" stroke="#059669" stroke-width="5" stroke-linecap="round"/>
                                <line x1="85" y1="75" x2="45" y2="68" stroke="#059669" stroke-width="5" stroke-linecap="round"/>
                                <path d="M 102 65 A 22 22 0 0 1 68 72" fill="none" stroke="#dc2626" stroke-width="2.5"/>
                                <circle cx="85" cy="75" r="4" fill="#dc2626"/>
                            </svg>
                            <div class="mt-2 bg-emerald-50 border border-emerald-200 px-3 py-1 rounded-full text-xs font-black text-emerald-800">
                                Ángulo de Extensión: <span id="ref-angle-push">0°</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
                    <div class="lg:col-span-7 clean-card p-5 rounded-2xl space-y-3">
                        <h3 class="text-xs font-extrabold text-slate-800 uppercase flex items-center gap-2">
                            <i data-lucide="activity" class="text-sky-600"></i> Comparativa de Fuerza por Brazada (Brazo Izquierdo vs. Derecho)
                        </h3>
                        <div class="h-60 w-full relative">
                            <canvas id="chartSmartwatchForce"></canvas>
                        </div>
                    </div>
                    <div class="lg:col-span-5 clean-card p-5 rounded-2xl space-y-3">
                        <h3 class="text-xs font-extrabold text-slate-800 uppercase flex items-center gap-2">
                            <i data-lucide="compass" class="text-indigo-600"></i> Curva de Ángulos por Fase de Brazada
                        </h3>
                        <div class="h-60 w-full relative">
                            <canvas id="chartSmartwatchAngle"></canvas>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 3. CONTROL DE PISCINA (EXCLUSIVO COACH) Y RUTINAS DE REFERENCIA -->
        <div id="tab-content-activities" class="space-y-6 hidden">
            
            <div id="coach-pool-control-panel" class="clean-card p-6 rounded-3xl space-y-4 hidden border-2 border-emerald-200 bg-emerald-50/30">
                <div class="flex flex-wrap justify-between items-center gap-2 border-b border-emerald-200 pb-3">
                    <div>
                        <h3 class="text-base font-black text-slate-900 flex items-center gap-2">
                            <i data-lucide="timer" class="text-emerald-600"></i> Control de Registro en Piscina en Vivo (Exclusivo Entrenador)
                        </h3>
                        <p class="text-xs text-slate-600">Selecciona al atleta que usará el reloj/carril, el estilo y la distancia. Mientras haya una sesión activa no se puede iniciar otra.</p>
                    </div>
                    <span id="pool-control-badge" class="bg-slate-200 text-slate-700 px-3 py-1 rounded-full text-xs font-black">Piscina Libre</span>
                </div>

                <div id="pool-setup-form" class="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
                    <div>
                        <label class="block text-[11px] font-bold text-slate-700 mb-1">1. Atleta en Carril / Reloj</label>
                        <select id="live-session-athlete" class="w-full bg-white border rounded-xl px-3 py-2 text-xs font-bold text-sky-800"></select>
                    </div>
                    <div>
                        <label class="block text-[11px] font-bold text-slate-700 mb-1">2. Estilo Oficial</label>
                        <select id="live-session-style" class="w-full bg-white border rounded-xl px-3 py-2 text-xs font-bold text-indigo-800">
                            <option value="Crol / Libre">Crol / Libre</option>
                            <option value="Espalda">Espalda</option>
                            <option value="Pecho / Braza">Pecho / Braza</option>
                            <option value="Mariposa">Mariposa</option>
                            <option value="Combinado Individual (CI)">Combinado Individual (CI)</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-[11px] font-bold text-slate-700 mb-1">3. Distancia de Prueba</label>
                        <select id="live-session-distance" class="w-full bg-white border rounded-xl px-3 py-2 text-xs font-bold text-emerald-800">
                            <option value="25 m">25 m</option>
                            <option value="50 m" selected>50 m</option>
                            <option value="100 m">100 m</option>
                            <option value="200 m">200 m</option>
                            <option value="400 m">400 m</option>
                            <option value="500 m">500 m</option>
                            <option value="1 km">1 km (1000 m)</option>
                        </select>
                    </div>
                    <div>
                        <button id="btn-open-confirm-session" onclick="openConfirmModalFromForm()" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-black py-2.5 px-4 rounded-xl text-xs shadow-md flex items-center justify-center gap-2">
                            <i data-lucide="play-circle" class="w-4 h-4"></i> Iniciar Entrenamiento
                        </button>
                    </div>
                </div>

                <div id="active-session-box" class="hidden bg-slate-900 text-white p-6 rounded-2xl space-y-4">
                    <div class="flex flex-wrap justify-between items-center gap-4 border-b border-slate-800 pb-3">
                        <div>
                            <div class="text-[10px] text-emerald-400 font-black uppercase tracking-wider">● CAPTURA DE TELEMETRÍA EN CURSO (BLOQUEADO PARA OTROS ATLETAS)</div>
                            <div id="active-session-info" class="text-base font-black mt-0.5">Atleta: -- | Estilo: -- | Distancia: --</div>
                        </div>
                        <button onclick="finishActivePoolSession()" class="bg-rose-600 hover:bg-rose-700 text-white font-black px-5 py-2.5 rounded-xl text-xs shadow-lg flex items-center gap-2">
                            <i data-lucide="square" class="w-4 h-4"></i> Finalizar y Guardar Sesión
                        </button>
                    </div>
                    <div class="flex flex-col items-center justify-center py-2">
                        <span class="text-[11px] text-slate-400 font-bold uppercase">Tiempo Real Transcurrido (Cronómetro Ascendente)</span>
                        <div id="coach-ascending-timer" class="text-5xl font-black font-mono text-amber-300 tracking-wider mt-1">00:00.0</div>
                    </div>
                </div>
            </div>

            <div id="coach-activity-assignment" class="clean-card p-6 rounded-3xl space-y-4 hidden border border-sky-200">
                <h3 class="text-sm font-extrabold text-slate-900 flex items-center gap-2">
                    <i data-lucide="clipboard-pen" class="w-4 h-4 text-sky-600"></i> Enviar Rutina de Referencia Previa al Atleta
                </h3>
                
                <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div>
                        <label class="block text-[11px] font-bold text-slate-600 mb-1">Seleccionar Atleta</label>
                        <select id="activity-target-athlete" class="w-full bg-slate-50 border rounded-xl px-3 py-2 text-xs font-bold text-sky-700"></select>
                    </div>
                    <div>
                        <label class="block text-[11px] font-bold text-slate-600 mb-1">Estilo de Natación (Lista Desplegable)</label>
                        <select id="activity-style" class="w-full bg-slate-50 border rounded-xl px-3 py-2 text-xs font-bold text-indigo-700">
                            <option value="Crol / Libre">Crol / Libre</option>
                            <option value="Espalda">Espalda</option>
                            <option value="Pecho / Braza">Pecho / Braza</option>
                            <option value="Mariposa">Mariposa</option>
                            <option value="Combinado Individual (CI)">Combinado Individual (CI)</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-[11px] font-bold text-slate-600 mb-1">Distancia Asignada (Lista Desplegable)</label>
                        <select id="activity-distance" class="w-full bg-slate-50 border rounded-xl px-3 py-2 text-xs font-bold text-emerald-700">
                            <option value="25 m">25 m</option>
                            <option value="50 m">50 m</option>
                            <option value="100 m" selected>100 m</option>
                            <option value="200 m">200 m</option>
                            <option value="400 m">400 m</option>
                            <option value="500 m">500 m</option>
                            <option value="1 km">1 km</option>
                        </select>
                    </div>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                        <label class="block text-[11px] font-bold text-slate-600 mb-1">Título de la Rutina</label>
                        <input type="text" id="activity-title" placeholder="Ej. Serie de velocidad y control de viraje" class="w-full bg-slate-50 border rounded-xl px-3 py-2 text-xs">
                    </div>
                    <div>
                        <label class="block text-[11px] font-bold text-slate-600 mb-1">Indicaciones Técnicas (Texto Libre)</label>
                        <input type="text" id="activity-desc" placeholder="Ej. Mantener frecuencia de brazada estable, salida explosiva..." class="w-full bg-slate-50 border rounded-xl px-3 py-2 text-xs">
                    </div>
                </div>

                <button onclick="publishRoutine()" class="bg-sky-600 hover:bg-sky-700 text-white font-black px-5 py-2.5 rounded-xl text-xs shadow-md flex items-center gap-2">
                    <i data-lucide="send" class="w-4 h-4"></i> Asignar Rutina de Referencia
                </button>
            </div>

            <div class="clean-card p-6 rounded-3xl space-y-4">
                <div class="flex justify-between items-center">
                    <h3 class="text-sm font-extrabold text-slate-900" id="activities-title-label">Rutinas de Referencia Asignadas</h3>
                    <span class="text-[11px] text-slate-500">El atleta consulta aquí sus indicaciones; el inicio del registro en piscina lo ejecuta el Coach.</span>
                </div>
                <div id="activities-list-container" class="space-y-3"></div>
            </div>
        </div>

        <!-- 4. RANKING (LEADERBOARD) SEPARADO POR ESTILO Y DISTANCIA -->
        <div id="tab-content-leaderboard" class="space-y-6 hidden">
            <div class="clean-card p-6 rounded-3xl space-y-4">
                <div class="flex flex-wrap justify-between items-center gap-4 border-b pb-4">
                    <div>
                        <h2 class="text-xl font-black text-slate-900 flex items-center gap-2">
                            <i data-lucide="trophy" class="text-amber-500"></i> Ranking Oficial por Estilo y Distancia
                        </h2>
                        <p class="text-xs text-slate-500">Comparación justa: cada prueba se clasifica estrictamente dentro de su mismo estilo y metraje.</p>
                    </div>
                    <div class="flex gap-3">
                        <div>
                            <label class="block text-[10px] font-bold text-slate-500 uppercase">Estilo</label>
                            <select id="rank-filter-style" onchange="renderLeaderboard()" class="bg-slate-50 border rounded-xl px-3 py-2 text-xs font-bold text-indigo-700">
                                <option value="Crol / Libre" selected>Crol / Libre</option>
                                <option value="Espalda">Espalda</option>
                                <option value="Pecho / Braza">Pecho / Braza</option>
                                <option value="Mariposa">Mariposa</option>
                                <option value="Combinado Individual (CI)">Combinado Individual (CI)</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-[10px] font-bold text-slate-500 uppercase">Distancia</label>
                            <select id="rank-filter-distance" onchange="renderLeaderboard()" class="bg-slate-50 border rounded-xl px-3 py-2 text-xs font-bold text-emerald-700">
                                <option value="25 m">25 m</option>
                                <option value="50 m" selected>50 m</option>
                                <option value="100 m">100 m</option>
                                <option value="200 m">200 m</option>
                                <option value="400 m">400 m</option>
                                <option value="500 m">500 m</option>
                                <option value="1 km">1 km</option>
                            </select>
                        </div>
                    </div>
                </div>
                <div class="space-y-2.5" id="leaderboard-list-container"></div>
            </div>
        </div>

        <!-- 5. PROFILE & VISTA ADMINISTRADOR -->
        <div id="tab-content-profile" class="space-y-6 hidden">
            <div class="clean-card p-6 rounded-3xl flex items-center gap-6">
                <div class="w-20 h-20 rounded-full bg-sky-600 text-white flex items-center justify-center font-black text-2xl" id="profile-initials">US</div>
                <div>
                    <h2 class="text-2xl font-black text-slate-900" id="profile-name">Nombre</h2>
                    <p class="text-xs text-sky-600 font-bold uppercase" id="profile-role-text">Rol</p>
                    <p class="text-xs text-slate-500 mt-1" id="profile-email">correo@ejemplo.com</p>
                </div>
            </div>

            <div id="admin-management-panel" class="clean-card p-6 rounded-3xl space-y-4 hidden border-2 border-indigo-100">
                <h3 class="text-base font-black text-slate-900 flex items-center gap-2">
                    <i data-lucide="shield-check" class="text-indigo-600"></i> Panel de Administración General (Usuarios y Cuentas Registradas)
                </h3>
                <div id="admin-users-summary" class="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs"></div>
            </div>
        </div>

    </div>

    <script>
        lucide.createIcons();
        let activeAthlete = "";
        let currentUser = null;
        let authMode = 'welcome';
        let allAthletesList = [];
        let allSessionsList = [];
        let selectedSessionObj = null;

        let chartProgressInstance = null;
        let chartForceInstance = null;
        let chartAngleInstance = null;

        let poolSessionState = { active: false };
        let ascendingTimerInterval = null;
        let pendingSessionPayload = null;

        document.addEventListener("DOMContentLoaded", () => {
            const savedUser = localStorage.getItem('sw_user_session');
            if (savedUser) {
                currentUser = JSON.parse(savedUser);
                applyUserData(currentUser);
                document.getElementById('auth-modal').classList.add('hidden');
            }
            loadInitialData();
            setInterval(pollPoolSessionStatus, 2000);
            setInterval(pollSmartwatchLive, 1500);
        });

        async function loadInitialData() {
            const [athRes, sesRes] = await Promise.all([
                fetch('/api/athletes'),
                fetch('/api/sessions')
            ]);
            allAthletesList = await athRes.json();
            allSessionsList = await sesRes.json();

            populateAthleteSelectors();
            await pollPoolSessionStatus();
            await pollSmartwatchLive();
            renderLeaderboard();
            if (currentUser && currentUser.role === 'admin') {
                loadAdminOverview();
            }
        }

        // SINCRONIZACIÓN EN VIVO CON EL SMARTWATCH ESP32 + MPU-9250 CALIBRADO A 0°
        async function pollSmartwatchLive() {
            try {
                const res = await fetch('/api/smartwatch/status');
                const sw = await res.json();
                const bannerSw = document.getElementById('banner-smartwatch-status');
                const badgeLive = document.getElementById('smartwatch-badge-live');
                const handEl = document.getElementById('sw-live-hand');
                const batEl = document.getElementById('sw-live-battery');
                const upEl = document.getElementById('sw-live-uptime');

                if (handEl) handEl.textContent = sw.hand;
                if (batEl) {
                    batEl.textContent = `${sw.battery}%`;
                    batEl.className = `text-xs font-black px-3 py-1 rounded-full border bg-white ${sw.battery <= 20 ? 'text-rose-600 border-rose-300' : 'text-emerald-700'}`;
                }
                if (upEl) upEl.textContent = `${sw.uptime_sec} s`;

                if (sw.connected) {
                    if (bannerSw) {
                        bannerSw.textContent = `🟢 ${sw.hand} (${sw.battery}%)`;
                        bannerSw.className = "text-xs font-black text-emerald-300";
                    }
                    if (badgeLive) {
                        badgeLive.textContent = `● MPU-9250 En Vivo (${sw.hand} | Bat: ${sw.battery}%)`;
                        badgeLive.className = "bg-emerald-100 text-emerald-800 px-3 py-1 rounded-full text-xs font-bold animate-pulse";
                    }

                    // Actualizar tarjetas de Codo, Hombro y Fuerza en tiempo real desde el punto 0°
                    const cMin = sw.elbow_min || 0;
                    const cMax = sw.elbow_max || 0;
                    const cIqr = ((cMax - cMin) * 0.5).toFixed(1);
                    document.getElementById('sw-codo-avg').textContent = `${sw.elbow_angle}°`;
                    document.getElementById('sw-codo-disp').textContent = `Mín: ${cMin}° | Máx: ${cMax}° (IQR: ${cIqr}°)`;

                    const hMin = sw.shoulder_min || 0;
                    const hMax = sw.shoulder_max || 0;
                    const hIqr = ((hMax - hMin) * 0.5).toFixed(1);
                    document.getElementById('sw-hombro-avg').textContent = `${sw.shoulder_angle}°`;
                    document.getElementById('sw-hombro-disp').textContent = `Mín: ${hMin}° | Máx: ${hMax}° (IQR: ${hIqr}°)`;

                    const fLeft = sw.force_left || sw.force_n || 0;
                    const fRight = sw.force_right || sw.force_n || 0;
                    document.getElementById('sw-fuerza-avg').textContent = `${fLeft} N / ${fRight} N`;
                    document.getElementById('sw-fuerza-disp').textContent = `Lectura dinámica actual: ${sw.force_n} N`;

                    // Actualizar imágenes estáticas de referencia
                    const pEntry = sw.phase_entry || 0;
                    const pPull = sw.elbow_angle || 0;
                    const pPush = sw.phase_push || 0;
                    document.getElementById('ref-angle-entry').textContent = `${pEntry}°`;
                    document.getElementById('ref-angle-pull').textContent = `${pPull}°`;
                    document.getElementById('ref-angle-shoulder').textContent = `${sw.shoulder_angle}°`;
                    document.getElementById('ref-angle-push').textContent = `${pPush}°`;

                    // Actualizar gráficas de Smartwatch en vivo
                    renderSmartwatchCharts(
                        [fLeft, fLeft, fLeft, fLeft, fLeft, fLeft],
                        [fRight, fRight, fRight, fRight, fRight, fRight],
                        [pEntry, pPull, pPush]
                    );
                } else {
                    if (bannerSw) {
                        bannerSw.textContent = "⚪ Desconectado / Deep Sleep";
                        bannerSw.className = "text-xs font-bold text-sky-200";
                    }
                    if (badgeLive) {
                        badgeLive.textContent = "⚪ Smartwatch en Espera / Mostrando Histórico";
                        badgeLive.className = "bg-slate-200 text-slate-700 px-3 py-1 rounded-full text-xs font-bold";
                    }
                }
            } catch (e) {}
        }

        function populateAthleteSelectors() {
            const selectActive = document.getElementById('select-active-athlete');
            const selectTarget = document.getElementById('activity-target-athlete');
            const selectLive = document.getElementById('live-session-athlete');

            const optionsHtml = allAthletesList.length === 0 ? '<option value="">Sin atletas</option>' :
                allAthletesList.map(a => `<option value="${a.name}">${a.name}</option>`).join('');

            if (selectActive) selectActive.innerHTML = optionsHtml;
            if (selectTarget) selectTarget.innerHTML = optionsHtml;
            if (selectLive) selectLive.innerHTML = optionsHtml;

            if (currentUser && currentUser.role === 'athlete') {
                activeAthlete = currentUser.name;
            } else if (allAthletesList.length > 0) {
                if (!activeAthlete || !allAthletesList.some(a => a.name === activeAthlete)) {
                    activeAthlete = allAthletesList[0].name;
                }
            }

            if (selectActive) selectActive.value = activeAthlete;
            if (selectTarget) selectTarget.value = activeAthlete;
            if (selectLive) selectLive.value = activeAthlete;

            updateActiveAthleteData(activeAthlete);
        }

        function changeActiveAthlete(name) {
            activeAthlete = name;
            const selectTarget = document.getElementById('activity-target-athlete');
            const selectLive = document.getElementById('live-session-athlete');
            if (selectTarget) selectTarget.value = name;
            if (selectLive && !poolSessionState.active) selectLive.value = name;
            updateActiveAthleteData(name);
        }

        function updateActiveAthleteData(name) {
            document.getElementById('stat-athlete-name').textContent = name || '--';
            document.getElementById('smartwatch-athlete-name').textContent = name || '--';
            document.getElementById('activities-title-label').textContent =
                (currentUser && currentUser.role === 'athlete') ? "Mis Rutinas de Referencia" : "Rutinas Asignadas a: " + name;

            applySessionFilters();
            loadAssignedRoutines(name);
        }

        function applySessionFilters() {
            const styleFilter = document.getElementById('filter-session-style').value;
            const dateFrom = document.getElementById('filter-date-from').value;
            const dateTo = document.getElementById('filter-date-to').value;
            const compMode = document.getElementById('filter-comparison-mode').value;

            let athleteSessions = allSessionsList
                .filter(s => s.athlete === activeAthlete)
                .sort((a, b) => a.date.localeCompare(b.date));

            const totalMeters = athleteSessions.reduce((acc, s) => acc + (s.distance_m || 0), 0);
            const totalSecs = athleteSessions.reduce((acc, s) => acc + (s.time_sec || 0), 0);
            document.getElementById('stat-dist').textContent = (totalMeters / 1000).toFixed(2) + " km";
            document.getElementById('stat-time').textContent = (totalSecs / 60).toFixed(1) + " min";
            document.getElementById('stat-workouts').textContent = athleteSessions.length + " Sesiones";

            let filtered = athleteSessions.filter(s => {
                if (styleFilter !== "ALL" && s.style !== styleFilter) return false;
                if (dateFrom && s.date < dateFrom) return false;
                if (dateTo && s.date > dateTo) return false;
                return true;
            });

            if (compMode === 'prev') {
                filtered = filtered.slice(-2);
            } else if (compMode === 'last5') {
                filtered = filtered.slice(-5);
            } else if (compMode === 'last10') {
                filtered = filtered.slice(-10);
            }

            renderSessionsTable(filtered, athleteSessions);
            renderComparisonChart(filtered);

            if (filtered.length > 0) {
                inspectSessionDetail(filtered[filtered.length - 1].id);
            } else {
                clearBiomechanicsView();
            }
        }

        function renderSessionsTable(sessions, allAthleteSessions) {
            const tbody = document.getElementById('sessions-history-tbody');
            if (sessions.length === 0) {
                tbody.innerHTML = `<tr><td colspan="8" class="p-4 text-center text-slate-400">No hay sesiones registradas con estos filtros para ${activeAthlete}.</td></tr>`;
                document.getElementById('comparison-summary-body').innerHTML = "Sin sesiones para comparar.";
                return;
            }

            tbody.innerHTML = sessions.slice().reverse().map(s => `
                <tr class="hover:bg-sky-50/60 transition cursor-pointer" onclick="inspectSessionDetail('${s.id}')">
                    <td class="p-3 font-bold text-slate-900">${s.id} <span class="block text-[10px] text-slate-400 font-normal">${s.date}</span></td>
                    <td class="p-3 font-bold text-indigo-700">${s.style}</td>
                    <td class="p-3 font-bold text-emerald-700">${s.distance}</td>
                    <td class="p-3 font-mono font-black text-slate-900">${s.time_sec.toFixed(2)} s</td>
                    <td class="p-3 font-mono text-sky-700 font-bold">${s.speed_ms.toFixed(2)} m/s</td>
                    <td class="p-3 font-bold">${s.elbow_angle.avg}° <span class="text-[10px] text-slate-400">(${s.elbow_angle.min}°-${s.elbow_angle.max}°)</span></td>
                    <td class="p-3 font-bold">${s.force_left.avg}N / ${s.force_right.avg}N</td>
                    <td class="p-3 text-right">
                        <button class="bg-sky-100 hover:bg-sky-200 text-sky-800 px-2.5 py-1 rounded-lg font-bold text-[11px]">
                            Ver / Comparar
                        </button>
                    </td>
                </tr>
            `).join('');
        }

        function inspectSessionDetail(sessionId) {
            const athleteSessions = allSessionsList
                .filter(s => s.athlete === activeAthlete)
                .sort((a, b) => a.date.localeCompare(b.date));

            const idx = athleteSessions.findIndex(s => s.id === sessionId);
            if (idx === -1) return;

            const current = athleteSessions[idx];
            const prev = idx > 0 ? athleteSessions[idx - 1] : null;
            selectedSessionObj = current;

            const summaryBody = document.getElementById('comparison-summary-body');
            if (prev) {
                const diffSpeed = (current.speed_ms - prev.speed_ms).toFixed(2);
                const diffElbow = current.elbow_angle.avg - prev.elbow_angle.avg;
                const diffForce = ((current.force_left.avg + current.force_right.avg)/2 - (prev.force_left.avg + prev.force_right.avg)/2).toFixed(1);
                summaryBody.innerHTML = `
                    <div class="font-bold text-sky-800">Sesión ${current.id} (${current.date}) vs. Anterior ${prev.id} (${prev.date})</div>
                    <div>• <strong>Prueba:</strong> ${current.style} (${current.distance})</div>
                    <div>• <strong>Velocidad:</strong> ${current.speed_ms.toFixed(2)} m/s (<span class="${diffSpeed >= 0 ? 'text-emerald-600' : 'text-rose-600'} font-bold">${diffSpeed >= 0 ? '+' : ''}${diffSpeed} m/s</span>)</div>
                    <div>• <strong>Ángulo Codo Prom.:</strong> ${current.elbow_angle.avg}° (<span class="font-bold">${diffElbow >= 0 ? '+' : ''}${diffElbow}°</span>)</div>
                    <div>• <strong>Fuerza Media:</strong> <span class="font-bold">${diffForce >= 0 ? '+' : ''}${diffForce} N</span> respecto a la sesión previa.</div>
                `;
            } else {
                summaryBody.innerHTML = `
                    <div class="font-bold text-sky-800">Sesión ${current.id} (${current.date}) - Primera sesión registrada</div>
                    <div>• <strong>Prueba:</strong> ${current.style} (${current.distance})</div>
                    <div>• <strong>Tiempo Total:</strong> ${current.time_sec.toFixed(2)} s | <strong>Velocidad:</strong> ${current.speed_ms.toFixed(2)} m/s</div>
                    <div>• <strong>Simetría Fuerza:</strong> Izq ${current.force_left.avg} N vs. Der ${current.force_right.avg} N</div>
                `;
            }

            document.getElementById('smartwatch-session-subtitle').textContent =
                `Sesión seleccionada: ${current.id} (${current.date}) — ${current.style} (${current.distance}) | Atípicos filtrados por IQR`;

            document.getElementById('sw-codo-avg').textContent = `${current.elbow_angle.avg}°`;
            document.getElementById('sw-codo-disp').textContent = `Mín: ${current.elbow_angle.min}° | Máx: ${current.elbow_angle.max}° (IQR: ${current.elbow_angle.iqr}°)`;

            document.getElementById('sw-hombro-avg').textContent = `${current.shoulder_angle.avg}°`;
            document.getElementById('sw-hombro-disp').textContent = `Mín: ${current.shoulder_angle.min}° | Máx: ${current.shoulder_angle.max}° (IQR: ${current.shoulder_angle.iqr}°)`;

            document.getElementById('sw-fuerza-avg').textContent = `${current.force_left.avg} N / ${current.force_right.avg} N`;
            document.getElementById('sw-fuerza-disp').textContent = `Rango s/atípicos: ${current.force_left.min}-${current.force_right.max} N`;

            document.getElementById('sw-vel-avg').textContent = `${current.speed_ms.toFixed(2)} m/s`;
            document.getElementById('sw-vel-disp').textContent = `Parcial 50m: ${current.split_50m.toFixed(2)} s`;

            document.getElementById('ref-angle-entry').textContent = `${current.elbow_angle.phase_entry}°`;
            document.getElementById('ref-angle-pull').textContent = `${current.elbow_angle.phase_pull}°`;
            document.getElementById('ref-angle-shoulder').textContent = `${current.shoulder_angle.avg}°`;
            document.getElementById('ref-angle-push').textContent = `${current.elbow_angle.phase_push}°`;

            renderSmartwatchCharts(
                current.force_left.strokes,
                current.force_right.strokes,
                [current.elbow_angle.phase_entry, current.elbow_angle.phase_pull, current.elbow_angle.phase_push]
            );
        }

        function clearBiomechanicsView() {
            document.getElementById('sw-codo-avg').textContent = "0°";
            document.getElementById('sw-hombro-avg').textContent = "0°";
            document.getElementById('sw-fuerza-avg').textContent = "0 N / 0 N";
            document.getElementById('sw-vel-avg').textContent = "0.00 m/s";
            renderSmartwatchCharts([0,0,0,0,0,0], [0,0,0,0,0,0], [0,0,0]);
        }

        function renderComparisonChart(sessions) {
            const ctx = document.getElementById('chartProgressComparison').getContext('2d');
            if (chartProgressInstance) chartProgressInstance.destroy();

            chartProgressInstance = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: sessions.length ? sessions.map(s => `${s.date} (${s.distance})`) : ['Sin sesiones'],
                    datasets: [
                        {
                            label: 'Velocidad Media (m/s)',
                            data: sessions.length ? sessions.map(s => s.speed_ms) : [0],
                            backgroundColor: '#0284c7',
                            borderRadius: 6,
                            yAxisID: 'y'
                        },
                        {
                            label: 'Ángulo Codo Promedio (°)',
                            data: sessions.length ? sessions.map(s => s.elbow_angle.avg) : [0],
                            type: 'line',
                            borderColor: '#4f46e5',
                            backgroundColor: '#4f46e5',
                            tension: 0.3,
                            yAxisID: 'y1'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: { type: 'linear', position: 'left', title: { display: true, text: 'Velocidad (m/s)' } },
                        y1: { type: 'linear', position: 'right', title: { display: true, text: 'Ángulo Codo (°)' }, grid: { drawOnChartArea: false } }
                    }
                }
            });
        }

        function renderSmartwatchCharts(forceLeft, forceRight, angles) {
            const ctxForce = document.getElementById('chartSmartwatchForce').getContext('2d');
            if (chartForceInstance) chartForceInstance.destroy();
            chartForceInstance = new Chart(ctxForce, {
                type: 'bar',
                data: {
                    labels: ['Brazada 1', 'Brazada 2', 'Brazada 3', 'Brazada 4', 'Brazada 5', 'Brazada 6'],
                    datasets: [
                        { label: 'Brazo Izquierdo (N)', data: forceLeft, backgroundColor: '#0284c7', borderRadius: 4 },
                        { label: 'Brazo Derecho (N)', data: forceRight, backgroundColor: '#059669', borderRadius: 4 }
                    ]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });

            const ctxAngle = document.getElementById('chartSmartwatchAngle').getContext('2d');
            if (chartAngleInstance) chartAngleInstance.destroy();
            chartAngleInstance = new Chart(ctxAngle, {
                type: 'line',
                data: {
                    labels: ['Fase 1 (Entrada)', 'Fase 2 (Tracción EVF)', 'Fase 3 (Empuje)'],
                    datasets: [{
                        label: 'Ángulo Articular (°)',
                        data: angles,
                        borderColor: '#6366f1',
                        backgroundColor: 'rgba(99, 102, 241, 0.12)',
                        fill: true,
                        tension: 0.3
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });
        }

        function openConfirmModalFromForm() {
            if (poolSessionState.active) {
                alert("Ya hay una sesión activa en la piscina. Finalízala antes de iniciar otra.");
                return;
            }
            const athlete = document.getElementById('live-session-athlete').value;
            const style = document.getElementById('live-session-style').value;
            const distance = document.getElementById('live-session-distance').value;
            openConfirmModal(athlete, style, distance, "Sesión Directa en Piscina");
        }

        function openConfirmModalFromRoutine(athlete, style, distance, title) {
            if (poolSessionState.active) {
                alert("Ya hay una sesión activa en la piscina. Finalízala antes de iniciar otra.");
                return;
            }
            openConfirmModal(athlete, style, distance, title);
        }

        function openConfirmModal(athlete, style, distance, title) {
            pendingSessionPayload = { athlete, style, distance, routine_title: title, coach: currentUser ? currentUser.name : "Coach" };
            document.getElementById('conf-athlete').textContent = athlete;
            document.getElementById('conf-style').textContent = style;
            document.getElementById('conf-distance').textContent = distance;
            document.getElementById('conf-title').textContent = title;
            const modal = document.getElementById('confirm-session-modal');
            modal.classList.remove('hidden');
            modal.classList.add('flex');
        }

        function closeConfirmModal() {
            const modal = document.getElementById('confirm-session-modal');
            modal.classList.add('hidden');
            modal.classList.remove('flex');
            pendingSessionPayload = null;
        }

        async function confirmAndStartPoolSession() {
            if (!pendingSessionPayload) return;
            const res = await fetch('/api/session/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(pendingSessionPayload)
            });
            const data = await res.json();
            closeConfirmModal();

            if (data.status === 'success') {
                await pollPoolSessionStatus();
            } else {
                alert(data.message || "No se pudo iniciar la sesión.");
            }
        }

        async function finishActivePoolSession() {
            const res = await fetch('/api/session/stop', { method: 'POST' });
            const data = await res.json();
            if (data.status === 'success') {
                alert(`Sesión finalizada y guardada para ${data.session.athlete} (${data.session.style} - ${data.session.distance}) en ${data.session.time_sec} s.`);
                const sesRes = await fetch('/api/sessions');
                allSessionsList = await sesRes.json();
                await pollPoolSessionStatus();
                updateActiveAthleteData(activeAthlete);
                renderLeaderboard();
            }
        }

        async function pollPoolSessionStatus() {
            try {
                const res = await fetch('/api/session/status');
                poolSessionState = await res.json();
                updatePoolSessionUI();
            } catch (e) {}
        }

        function updatePoolSessionUI() {
            const dot = document.getElementById('live-indicator-dot');
            const statusText = document.getElementById('status-text');
            const metaText = document.getElementById('banner-session-meta');
            const activeBox = document.getElementById('active-session-box');
            const btnStart = document.getElementById('btn-open-confirm-session');
            const badge = document.getElementById('pool-control-badge');

            if (poolSessionState.active) {
                dot.className = "w-3.5 h-3.5 rounded-full bg-emerald-400 animate-ping";
                statusText.textContent = `🟢 CAPTURANDO EN PISCINA: ${poolSessionState.athlete} (${poolSessionState.routine_title || 'Sesión activa'})`;
                metaText.textContent = `${poolSessionState.distance} • ${poolSessionState.style}`;
                if (activeBox) activeBox.classList.remove('hidden');
                if (btnStart) {
                    btnStart.disabled = true;
                    btnStart.classList.add('opacity-50', 'cursor-not-allowed');
                }
                if (badge) {
                    badge.textContent = "Sesión en Curso (Bloqueada)";
                    badge.className = "bg-amber-100 text-amber-800 px-3 py-1 rounded-full text-xs font-black";
                }
                const infoEl = document.getElementById('active-session-info');
                if (infoEl) {
                    infoEl.textContent = `Atleta: ${poolSessionState.athlete} | Estilo: ${poolSessionState.style} | Distancia: ${poolSessionState.distance}`;
                }

                if (!ascendingTimerInterval) {
                    ascendingTimerInterval = setInterval(updateAscendingStopwatch, 100);
                }
            } else {
                dot.className = "w-3.5 h-3.5 rounded-full bg-amber-400";
                statusText.textContent = "⚪ Sin sesión activa en piscina (Esperando inicio del Coach)";
                metaText.textContent = "--";
                document.getElementById('banner-stopwatch').textContent = "00:00.0";
                const coachTimer = document.getElementById('coach-ascending-timer');
                if (coachTimer) coachTimer.textContent = "00:00.0";
                if (activeBox) activeBox.classList.add('hidden');
                if (btnStart) {
                    btnStart.disabled = false;
                    btnStart.classList.remove('opacity-50', 'cursor-not-allowed');
                }
                if (badge) {
                    badge.textContent = "Piscina Libre";
                    badge.className = "bg-emerald-100 text-emerald-800 px-3 py-1 rounded-full text-xs font-black";
                }
                if (ascendingTimerInterval) {
                    clearInterval(ascendingTimerInterval);
                    ascendingTimerInterval = null;
                }
            }
        }

        function updateAscendingStopwatch() {
            if (!poolSessionState.active || !poolSessionState.start_timestamp) return;
            const elapsedSec = Math.max(0, (Date.now() / 1000) - poolSessionState.start_timestamp);
            const mins = Math.floor(elapsedSec / 60);
            const secs = (elapsedSec % 60).toFixed(1);
            const formatted = String(mins).padStart(2, '0') + ":" + String(secs).padStart(4, '0');
            document.getElementById('banner-stopwatch').textContent = formatted;
            const coachTimer = document.getElementById('coach-ascending-timer');
            if (coachTimer) coachTimer.textContent = formatted;
        }

        function publishRoutine() {
            const target = document.getElementById('activity-target-athlete').value;
            const style = document.getElementById('activity-style').value;
            const distance = document.getElementById('activity-distance').value;
            const title = document.getElementById('activity-title').value.trim();
            const desc = document.getElementById('activity-desc').value.trim();

            if (!title || !desc || !target) {
                alert("Completa el título y las indicaciones técnicas de la rutina.");
                return;
            }

            fetch('/api/activities/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    athlete: target,
                    style,
                    distance,
                    title,
                    desc,
                    assigned_by: currentUser ? currentUser.name : "Entrenador"
                })
            }).then(res => res.json()).then(data => {
                if (data.status === 'success') {
                    document.getElementById('activity-title').value = '';
                    document.getElementById('activity-desc').value = '';
                    loadAssignedRoutines(target);
                }
            });
        }

        function loadAssignedRoutines(athleteName) {
            if (!athleteName) return;
            fetch('/api/activities/' + encodeURIComponent(athleteName))
                .then(res => res.json())
                .then(list => {
                    const isCoachOrAdmin = currentUser && (currentUser.role === 'coach' || currentUser.role === 'admin');
                    const container = document.getElementById('activities-list-container');
                    if (list.length === 0) {
                        container.innerHTML = '<div class="text-xs text-slate-400 bg-slate-50 p-4 rounded-xl">No hay rutinas de referencia asignadas para este atleta.</div>';
                        return;
                    }
                    container.innerHTML = list.map(item => {
                        const actionHtml = isCoachOrAdmin ?
                            `<button onclick="openConfirmModalFromRoutine('${athleteName}', '${item.style}', '${item.distance}', '${item.title}')" class="bg-emerald-600 hover:bg-emerald-700 text-white font-black px-3.5 py-1.5 rounded-xl text-xs shadow flex items-center gap-1.5">
                                <i data-lucide="play" class="w-3.5 h-3.5"></i> Iniciar en Piscina desde esta Rutina
                            </button>` :
                            `<span class="bg-slate-200 text-slate-700 px-3 py-1 rounded-full font-bold text-[11px]">📋 Referencia de Entrenamiento (Inicio controlado por el Coach)</span>`;

                        return `
                            <div class="bg-sky-50/70 p-4 rounded-2xl border border-sky-100 text-xs space-y-2">
                                <div class="flex flex-wrap justify-between items-center gap-2">
                                    <span class="font-black text-sky-900 text-sm">${item.title}</span>
                                    <div class="flex gap-2">
                                        <span class="bg-indigo-100 text-indigo-800 px-2.5 py-0.5 rounded-full font-bold">🏊‍♂️ ${item.style}</span>
                                        <span class="bg-emerald-100 text-emerald-800 px-2.5 py-0.5 rounded-full font-bold">📏 ${item.distance}</span>
                                    </div>
                                </div>
                                <p class="text-slate-600">${item.desc}</p>
                                <div class="flex flex-wrap justify-between items-center pt-2 border-t border-sky-100 gap-2">
                                    <span class="text-[10px] text-slate-400">Asignada por: ${item.assigned_by} (${item.date || 'Hoy'})</span>
                                    ${actionHtml}
                                </div>
                            </div>
                        `;
                    }).join('');
                    lucide.createIcons();
                });
        }

        function renderLeaderboard() {
            const style = document.getElementById('rank-filter-style').value;
            const distance = document.getElementById('rank-filter-distance').value;
            const container = document.getElementById('leaderboard-list-container');

            const matching = allSessionsList.filter(s => s.style === style && s.distance === distance);

            const bestByAthlete = {};
            matching.forEach(s => {
                if (!bestByAthlete[s.athlete] || s.time_sec < bestByAthlete[s.athlete].time_sec) {
                    bestByAthlete[s.athlete] = s;
                }
            });

            const ranked = Object.values(bestByAthlete).sort((a, b) => a.time_sec - b.time_sec);

            if (ranked.length === 0) {
                container.innerHTML = `<div class="p-6 text-center text-xs text-slate-400 bg-slate-50 rounded-2xl border">Aún no existen tiempos registrados para <strong>${style} — ${distance}</strong>.</div>`;
                return;
            }

            const badges = ["🥇", "🥈", "🥉"];
            container.innerHTML = ranked.map((item, idx) => `
                <div class="flex items-center justify-between p-3.5 rounded-2xl bg-slate-50 border text-xs">
                    <div class="flex items-center gap-3">
                        <span class="text-base font-black w-6 text-center">${badges[idx] || (idx + 1) + 'º'}</span>
                        <div>
                            <div class="font-black text-slate-900 text-sm">${item.athlete}</div>
                            <div class="text-[10px] text-slate-400 font-semibold">${item.style} • ${item.distance} • Fecha: ${item.date}</div>
                        </div>
                    </div>
                    <div class="text-right">
                        <span class="font-mono text-sky-700 font-black text-sm">${item.time_sec.toFixed(2)} s</span>
                        <span class="block text-[10px] text-emerald-700 font-bold">${item.speed_ms.toFixed(2)} m/s</span>
                    </div>
                </div>
            `).join('');
        }

        function switchAuthMode(mode) {
            authMode = mode;
            document.getElementById('auth-error-box').classList.add('hidden');
            document.getElementById('auth-success-box').classList.add('hidden');

            if (mode === 'welcome') {
                document.getElementById('login-screen-welcome').classList.remove('hidden');
                document.getElementById('login-screen-form').classList.add('hidden');
                return;
            }

            document.getElementById('login-screen-welcome').classList.add('hidden');
            document.getElementById('login-screen-form').classList.remove('hidden');

            if (mode === 'recover') {
                document.getElementById('form-main-title').textContent = "Recuperación de Cuenta";
                document.getElementById('auth-form').classList.add('hidden');
                document.getElementById('recover-form').classList.remove('hidden');
            } else {
                document.getElementById('auth-form').classList.remove('hidden');
                document.getElementById('recover-form').classList.add('hidden');
                if (mode === 'register') {
                    document.getElementById('form-main-title').textContent = "Registro de Nuevo Usuario";
                    document.getElementById('field-name-container').classList.remove('hidden');
                    document.getElementById('forgot-password-link').classList.add('hidden');
                    document.getElementById('auth-submit-btn').textContent = "Validar Correo y Crear Cuenta";
                } else {
                    document.getElementById('form-main-title').textContent = "Iniciar Sesión";
                    document.getElementById('field-name-container').classList.add('hidden');
                    document.getElementById('forgot-password-link').classList.remove('hidden');
                    document.getElementById('auth-submit-btn').textContent = "Entrar";
                }
            }
        }

        async function handleAuthSubmit(event) {
            event.preventDefault();
            const email = document.getElementById('input-email').value.trim();
            const password = document.getElementById('input-password').value.trim();
            const role = document.getElementById('input-role').value;
            const name = document.getElementById('input-name').value.trim();
            const errorBox = document.getElementById('auth-error-box');
            errorBox.classList.add('hidden');

            const endpoint = authMode === 'register' ? '/api/register' : '/api/login';

            try {
                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, email, password, role })
                });
                const result = await response.json();

                if (result.status === 'success') {
                    localStorage.setItem('sw_user_session', JSON.stringify(result.user));
                    location.reload();
                } else {
                    errorBox.textContent = result.message || "Credenciales inválidas.";
                    errorBox.classList.remove('hidden');
                }
            } catch (err) {
                errorBox.textContent = "Error de conexión con el servidor.";
                errorBox.classList.remove('hidden');
            }
        }

        async function handleRecoverSubmit(event) {
            event.preventDefault();
            const email = document.getElementById('recover-email').value.trim();
            const new_password = document.getElementById('recover-new-password').value.trim();
            const errorBox = document.getElementById('auth-error-box');
            const successBox = document.getElementById('auth-success-box');
            errorBox.classList.add('hidden');
            successBox.classList.add('hidden');

            const res = await fetch('/api/recover', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, new_password })
            });
            const data = await res.json();
            if (data.status === 'success') {
                successBox.textContent = data.message;
                successBox.classList.remove('hidden');
            } else {
                errorBox.textContent = data.message;
                errorBox.classList.remove('hidden');
            }
        }

        function applyUserData(user) {
            const roleLabels = { coach: 'Entrenador (Coach)', athlete: 'Atleta / Nadador', admin: 'Administrador' };
            document.getElementById('nav-username').textContent = user.name;
            document.getElementById('nav-userrole').textContent = roleLabels[user.role] || user.role;
            document.getElementById('profile-name').textContent = user.name;
            document.getElementById('profile-email').textContent = user.email;
            document.getElementById('profile-role-text').textContent = roleLabels[user.role] || user.role;

            const initials = user.name.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
            document.getElementById('profile-initials').textContent = initials;

            if (user.role === 'coach' || user.role === 'admin') {
                const selectorContainer = document.getElementById('coach-athlete-selector-container');
                selectorContainer.classList.remove('hidden');
                selectorContainer.classList.add('flex');
                document.getElementById('coach-pool-control-panel').classList.remove('hidden');
                document.getElementById('coach-activity-assignment').classList.remove('hidden');
            } else {
                activeAthlete = user.name;
            }

            if (user.role === 'admin') {
                document.getElementById('admin-management-panel').classList.remove('hidden');
            }
        }

        async function loadAdminOverview() {
            const res = await fetch('/api/admin/users');
            const data = await res.json();
            const container = document.getElementById('admin-users-summary');
            container.innerHTML = `
                <div class="bg-slate-50 p-4 rounded-2xl border">
                    <div class="font-black text-indigo-700 uppercase mb-2">Administradores (${data.admins.length})</div>
                    ${data.admins.map(u => `<div class="py-1 border-b text-slate-700"><strong>${u.name}</strong><br><span class="text-slate-400">${u.email}</span></div>`).join('')}
                </div>
                <div class="bg-slate-50 p-4 rounded-2xl border">
                    <div class="font-black text-sky-700 uppercase mb-2">Coaches (${data.coaches.length})</div>
                    ${data.coaches.map(u => `<div class="py-1 border-b text-slate-700"><strong>${u.name}</strong><br><span class="text-slate-400">${u.email}</span></div>`).join('')}
                </div>
                <div class="bg-slate-50 p-4 rounded-2xl border">
                    <div class="font-black text-emerald-700 uppercase mb-2">Atletas Registrados (${data.athletes.length})</div>
                    ${data.athletes.map(u => `<div class="py-1 border-b text-slate-700"><strong>${u.name}</strong><br><span class="text-slate-400">${u.email}</span></div>`).join('')}
                </div>
            `;
        }

        function switchTab(tab) {
            ['progress', 'smartwatch', 'activities', 'profile', 'leaderboard'].forEach(t => {
                document.getElementById('tab-content-' + t).classList.add('hidden');
                document.getElementById('tab-btn-' + t).classList.remove('active');
            });
            document.getElementById('tab-content-' + tab).classList.remove('hidden');
            document.getElementById('tab-btn-' + tab).classList.add('active');
        }

        function logout() {
            localStorage.removeItem('sw_user_session');
            location.reload();
        }
    </script>
</body>
</html>
"""

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]{2,}$")
VALID_DOMAINS = {
    "gmail.com",
    "hotmail.com",
    "outlook.com",
    "yahoo.com",
    "swiitroom.com",
    "icloud.com",
    "edu.pe",
    "upn.pe",
    "pucp.edu.pe",
    "uni.edu.pe",
    "upc.edu.pe",
}


def is_valid_email_address(email):
  if not EMAIL_REGEX.match(email):
    return False
  domain = email.split("@")[-1].lower()
  return (
      domain in VALID_DOMAINS
      or domain.endswith(".edu.pe")
      or domain.endswith(".com")
      or domain.endswith(".org")
  )


@app.route("/")
def index():
  return render_template_string(HTML_TEMPLATE)


@app.route("/api/athletes", methods=["GET"])
def get_athletes():
  return jsonify(users_db.get("athletes", []))


@app.route("/api/sessions", methods=["GET"])
def get_sessions():
  return jsonify(users_db.get("sessions", []))


@app.route("/api/admin/users", methods=["GET"])
def get_all_users_admin():
  return jsonify({
      "admins": users_db.get("admins", []),
      "coaches": users_db.get("coaches", []),
      "athletes": users_db.get("athletes", []),
  })


@app.route("/api/register", methods=["POST"])
def register_user():
  data = request.json
  name = data.get("name", "").strip()
  email = data.get("email", "").strip().lower()
  password = data.get("password", "").strip()
  role = data.get("role", "athlete")

  if not name or not email or not password:
    return (
        jsonify(
            {"status": "error", "message": "Todos los campos son obligatorios."}
        ),
        400,
    )

  if not is_valid_email_address(email):
    return (
        jsonify({
            "status": "error",
            "message": (
                "El correo ingresado no tiene un formato o dominio válido"
                " existente."
            ),
        }),
        400,
    )

  role_map = {"coach": "coaches", "admin": "admins", "athlete": "athletes"}
  target_key = role_map.get(role, "athletes")

  all_users = (
      users_db.get("admins", [])
      + users_db.get("coaches", [])
      + users_db.get("athletes", [])
  )
  if any(u["email"].lower() == email for u in all_users):
    return (
        jsonify({
            "status": "error",
            "message": "Este correo electrónico ya se encuentra registrado.",
        }),
        400,
    )

  new_user = {"name": name, "email": email, "password": password, "role": role}
  users_db[target_key].append(new_user)
  save_users(users_db)
  return jsonify({"status": "success", "user": new_user})


@app.route("/api/login", methods=["POST"])
def login_user():
  data = request.json
  email = data.get("email", "").strip().lower()
  password = data.get("password", "").strip()
  role = data.get("role", "athlete")

  role_map = {"coach": "coaches", "admin": "admins", "athlete": "athletes"}
  pool = users_db.get(role_map.get(role, "athletes"), [])

  found = next(
      (
          u
          for u in pool
          if u["email"].lower() == email and u["password"] == password
      ),
      None,
  )
  if found:
    return jsonify({"status": "success", "user": found})
  return (
      jsonify({
          "status": "error",
          "message": "Usuario, contraseña, correo o rol incorrectos.",
      }),
      401,
  )


@app.route("/api/recover", methods=["POST"])
def recover_account():
  data = request.json
  email = data.get("email", "").strip().lower()
  new_password = data.get("new_password", "").strip()

  if not email or len(new_password) < 3:
    return (
        jsonify({
            "status": "error",
            "message": (
                "Ingresa un correo válido y una nueva contraseña (mínimo 3"
                " caracteres)."
            ),
        }),
        400,
    )

  for group in ["athletes", "coaches", "admins"]:
    for user in users_db.get(group, []):
      if user["email"].lower() == email:
        user["password"] = new_password
        save_users(users_db)
        return jsonify({
            "status": "success",
            "message": (
                f"Contraseña actualizada correctamente para {user['name']}"
                f" ({user['role']}). Ya puedes iniciar sesión."
            ),
        })

  return (
      jsonify({
          "status": "error",
          "message": (
              "No se encontró ninguna cuenta asociada a ese correo electrónico."
          ),
      }),
      404,
  )


@app.route("/api/session/status", methods=["GET"])
def get_session_status():
  return jsonify(active_pool_session)


@app.route("/api/session/start", methods=["POST"])
def start_pool_session():
  if active_pool_session["active"]:
    return (
        jsonify({
            "status": "error",
            "message": (
                "Ya existe un entrenamiento activo en piscina. Finalízalo antes"
                " de iniciar otro."
            ),
        }),
        400,
    )

  data = request.json
  active_pool_session["active"] = True
  active_pool_session["athlete"] = data.get("athlete")
  active_pool_session["style"] = data.get("style", "Crol / Libre")
  active_pool_session["distance"] = data.get("distance", "50 m")
  active_pool_session["coach"] = data.get("coach", "Pepe Gómez")
  active_pool_session["routine_title"] = data.get(
      "routine_title", "Sesión en Piscina"
  )
  active_pool_session["start_timestamp"] = time.time()
  return jsonify({"status": "success", "session": active_pool_session})


@app.route("/api/session/stop", methods=["POST"])
def stop_pool_session():
  if not active_pool_session["active"]:
    return (
        jsonify(
            {"status": "error", "message": "No hay ninguna sesión en curso."}
        ),
        400,
    )

  elapsed = round(
      max(12.5, time.time() - active_pool_session["start_timestamp"]), 2
  )
  dist_m = parse_distance_meters(active_pool_session["distance"])
  speed_ms = round(dist_m / elapsed, 2)
  split_50 = round(
      elapsed if dist_m <= 50 else (elapsed / (dist_m / 50.0)), 2
  )

  # Si el Smartwatch envió datos recientemente, guardar sus lecturas reales del MPU-9250 en el historial
  sw_active = (time.time() - smartwatch_live_state["last_seen"]) <= 15
  elbow_avg = (
      smartwatch_live_state["elbow_angle"]
      if sw_active and smartwatch_live_state["elbow_angle"] > 0
      else 89
  )
  elbow_min = (
      smartwatch_live_state["elbow_min"]
      if sw_active and smartwatch_live_state["elbow_min"] > 0
      else max(0, elbow_avg - 3)
  )
  elbow_max = (
      smartwatch_live_state["elbow_max"]
      if sw_active and smartwatch_live_state["elbow_max"] > 0
      else min(165, elbow_avg + 3)
  )

  shoulder_avg = (
      smartwatch_live_state["shoulder_angle"]
      if sw_active and smartwatch_live_state["shoulder_angle"] > 0
      else 56
  )
  shoulder_min = (
      smartwatch_live_state["shoulder_min"]
      if sw_active and smartwatch_live_state["shoulder_min"] > 0
      else max(0, shoulder_avg - 3)
  )
  shoulder_max = (
      smartwatch_live_state["shoulder_max"]
      if sw_active and smartwatch_live_state["shoulder_max"] > 0
      else min(120, shoulder_avg + 3)
  )

  f_left = (
      smartwatch_live_state["force_left"]
      if sw_active and smartwatch_live_state["force_left"] > 0
      else 428
  )
  f_right = (
      smartwatch_live_state["force_right"]
      if sw_active and smartwatch_live_state["force_right"] > 0
      else 436
  )

  new_id = f"SES-{len(users_db.get('sessions', [])) + 1:03d}"
  new_session = {
      "id": new_id,
      "athlete": active_pool_session["athlete"],
      "date": datetime.now().strftime("%Y-%m-%d"),
      "style": active_pool_session["style"],
      "distance": active_pool_session["distance"],
      "distance_m": dist_m,
      "time_sec": elapsed,
      "split_50m": split_50,
      "speed_ms": speed_ms,
      "elbow_angle": {
          "avg": elbow_avg,
          "min": elbow_min,
          "max": elbow_max,
          "iqr": round(max(1.5, (elbow_max - elbow_min) * 0.5), 1),
          "phase_entry": (
              smartwatch_live_state["phase_entry"]
              if sw_active and smartwatch_live_state["phase_entry"] > 0
              else 30
          ),
          "phase_pull": elbow_avg,
          "phase_push": (
              smartwatch_live_state["phase_push"]
              if sw_active and smartwatch_live_state["phase_push"] > 0
              else 151
          ),
      },
      "shoulder_angle": {
          "avg": shoulder_avg,
          "min": shoulder_min,
          "max": shoulder_max,
          "iqr": round(max(1.5, (shoulder_max - shoulder_min) * 0.5), 1),
      },
      "force_left": {
          "avg": f_left,
          "min": max(0, f_left - 14),
          "max": f_left + 14,
          "strokes": [
              max(0, f_left - 6),
              f_left + 2,
              max(0, f_left - 3),
              f_left + 8,
              max(0, f_left - 2),
              f_left + 2,
          ],
      },
      "force_right": {
          "avg": f_right,
          "min": max(0, f_right - 14),
          "max": f_right + 14,
          "strokes": [
              max(0, f_right - 5),
              f_right + 3,
              max(0, f_right - 2),
              f_right + 7,
              max(0, f_right - 1),
              f_right + 3,
          ],
      },
  }

  users_db.setdefault("sessions", []).append(new_session)
  save_users(users_db)

  active_pool_session["active"] = False
  active_pool_session["athlete"] = None
  active_pool_session["start_timestamp"] = None

  return jsonify({"status": "success", "session": new_session})


@app.route("/api/activities/<athlete>", methods=["GET"])
def get_activities(athlete):
  return jsonify(users_db.get("routines", {}).get(athlete, []))


@app.route("/api/activities/add", methods=["POST"])
def add_activity():
  data = request.json
  athlete = data.get("athlete")
  style = data.get("style", "Crol / Libre")
  distance = data.get("distance", "100 m")
  title = data.get("title")
  desc = data.get("desc")
  assigned_by = data.get("assigned_by", "Entrenador")

  if athlete and title and desc:
    routines = users_db.setdefault("routines", {})
    routines.setdefault(athlete, []).append({
        "id": f"rut-{int(time.time())}",
        "style": style,
        "distance": distance,
        "title": title,
        "desc": desc,
        "assigned_by": assigned_by,
        "date": datetime.now().strftime("%Y-%m-%d"),
    })
    save_users(users_db)
    return jsonify({"status": "success"})
  return jsonify({"status": "error"}), 400


# RUTAS DE RECEPCIÓN Y ESTADO EN VIVO DEL SMARTWATCH IoT (ESP32 + MPU-9250)
@app.route("/api/smartwatch/telemetry", methods=["POST"])
def receive_smartwatch_telemetry():
  data = request.json or {}
  smartwatch_live_state["connected"] = True
  smartwatch_live_state["hand"] = data.get("hand", "Izquierda (Left)")
  smartwatch_live_state["is_left"] = data.get("is_left", True)
  smartwatch_live_state["battery"] = data.get("battery", 100)
  smartwatch_live_state["uptime_sec"] = data.get("uptime_sec", 0)
  smartwatch_live_state["elbow_angle"] = data.get("elbow_angle", 0)
  smartwatch_live_state["elbow_min"] = data.get("elbow_min", 0)
  smartwatch_live_state["elbow_max"] = data.get("elbow_max", 0)
  smartwatch_live_state["shoulder_angle"] = data.get("shoulder_angle", 0)
  smartwatch_live_state["shoulder_min"] = data.get("shoulder_min", 0)
  smartwatch_live_state["shoulder_max"] = data.get("shoulder_max", 0)
  smartwatch_live_state["phase_entry"] = data.get("phase_entry", 0)
  smartwatch_live_state["phase_pull"] = data.get("phase_pull", 0)
  smartwatch_live_state["phase_push"] = data.get("phase_push", 0)
  smartwatch_live_state["force_n"] = data.get("force_n", 0)
  smartwatch_live_state["force_left"] = data.get("force_left", 0)
  smartwatch_live_state["force_right"] = data.get("force_right", 0)
  smartwatch_live_state["strokes"] = data.get("strokes", 0)
  smartwatch_live_state["last_seen"] = time.time()
  return jsonify(
      {"status": "ok", "active_session": active_pool_session["active"]}
  )


@app.route("/api/smartwatch/status", methods=["GET"])
def get_smartwatch_status():
  if time.time() - smartwatch_live_state["last_seen"] > 8:
    smartwatch_live_state["connected"] = False
  return jsonify(smartwatch_live_state)


@app.route("/stream")
def stream():
  def event_stream():
    while True:
      try:
        line = data_queue.get(timeout=1)
        yield f"data: {line}\n\n"
      except queue.Empty:
        yield "data: \n\n"

  return Response(event_stream(), mimetype="text/event-stream")


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=5001)
