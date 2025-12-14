from flask import Flask, request, jsonify
import json
import os
import threading
import time

app = Flask(__name__)

# Variable para almacenar la respuesta configurada
RESPUESTA_BOT = "Hola, soy un bot 🤖\nEscribe 'hola' para comenzar."

# Archivo de configuración
CONFIG_FILE = "config.json"


def cargar_respuesta():
    """Carga la respuesta desde el archivo de configuración"""
    global RESPUESTA_BOT
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                RESPUESTA_BOT = config.get("respuesta_bot", RESPUESTA_BOT)
                print(f"✅ Respuesta cargada: {RESPUESTA_BOT[:50]}...")
    except Exception as e:
        print(f"⚠️ Error cargando configuración: {e}")


def guardar_respuesta(respuesta):
    """Guarda la respuesta en el archivo de configuración"""
    global RESPUESTA_BOT
    try:
        config = {"respuesta_bot": respuesta}
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        RESPUESTA_BOT = respuesta
        print(f"✅ Respuesta guardada: {respuesta[:50]}...")
        return True
    except Exception as e:
        print(f"❌ Error guardando configuración: {e}")
        return False


@app.route("/webhook", methods=["POST"])
def webhook():
    """Endpoint que recibe los mensajes de WhatsApp"""
    try:
        data = request.json
        if not data:
            return jsonify({"reply": "Error: No data received"}), 400

        from_number = data.get("from", "")
        message_text = data.get("message", "").strip().lower()

        print(f"📩 Mensaje recibido de {from_number}: {message_text}")

        # Lógica de respuesta simple
        if "hola" in message_text or "holis" in message_text or "hi" in message_text:
            respuesta = RESPUESTA_BOT
        elif "ayuda" in message_text or "help" in message_text:
            respuesta = "Escribe 'hola' para comenzar la conversación."
        elif "quien" in message_text or "qué eres" in message_text:
            respuesta = "Soy un bot de WhatsApp 🤖 creado para ayudarte."
        else:
            respuesta = RESPUESTA_BOT

        print(f"📤 Respondiendo: {respuesta[:50]}...")
        return jsonify({"reply": respuesta})

    except Exception as e:
        print(f"❌ Error en webhook: {e}")
        return jsonify({"reply": "⚠️ Error interno del servidor"}), 500


@app.route("/status", methods=["GET"])
def status():
    """Endpoint para verificar estado del servidor"""
    return jsonify({
        "status": "online",
        "respuesta_actual": RESPUESTA_BOT[:100] + "..." if len(RESPUESTA_BOT) > 100 else RESPUESTA_BOT,
        "timestamp": time.time()
    })


@app.route("/config", methods=["POST"])
def update_config():
    """Endpoint para actualizar la respuesta del bot (usado por la GUI)"""
    try:
        data = request.json
        nueva_respuesta = data.get("respuesta_bot", "").strip()

        if not nueva_respuesta:
            return jsonify({"error": "La respuesta no puede estar vacía"}), 400

        if guardar_respuesta(nueva_respuesta):
            return jsonify({"success": True, "message": "Respuesta actualizada"})
        else:
            return jsonify({"error": "Error al guardar"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/config", methods=["GET"])
def get_config():
    """Obtiene la configuración actual"""
    return jsonify({"respuesta_bot": RESPUESTA_BOT})


def iniciar_gui():
    """Inicia la interfaz gráfica en un hilo separado"""
    try:
        # Esperar un momento para que Flask se inicialice
        time.sleep(1)

        # Verificar si tkinter está disponible
        import tkinter
        from gui import BotGUI

        print("\n🎨 Iniciando interfaz gráfica...")
        app_gui = BotGUI()
        app_gui.run()

    except ImportError as e:
        print(f"⚠️ No se pudo cargar la GUI: {e}")
        print("💡 Ejecuta: pip install tkinter")
    except Exception as e:
        print(f"❌ Error iniciando GUI: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("🤖 WHATSAPP BOT - VERSIÓN MÍNIMA")
    print("=" * 60)

    # Cargar configuración inicial
    cargar_respuesta()

    print(f"\n💬 Respuesta actual: {RESPUESTA_BOT}")
    print("🌐 Servidor Flask iniciando en http://localhost:5001")
    print("📡 Esperando conexiones de WhatsApp...")
    print("\n📋 Endpoints disponibles:")
    print("   POST /webhook     - Recibe mensajes de WhatsApp")
    print("   GET  /status      - Estado del servidor")
    print("   GET  /config      - Obtiene configuración")
    print("   POST /config      - Actualiza configuración")
    print("\nPresiona CTRL+C para detener\n")

    # Iniciar GUI en hilo separado si no se especifica --no-gui
    import sys

    if "--no-gui" not in sys.argv:
        gui_thread = threading.Thread(target=iniciar_gui, daemon=True)
        gui_thread.start()
    else:
        print("🖥️ Modo: Solo Backend (sin GUI)")

    # Iniciar servidor Flask
    try:
        app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\n\n🛑 Servidor detenido por el usuario")
    except Exception as e:
        print(f"\n❌ Error iniciando servidor: {e}")