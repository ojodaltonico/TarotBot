import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion
} from "@whiskeysockets/baileys"
import Pino from "pino"
import { Boom } from "@hapi/boom"
import fs from "fs"
import qrcode from "qrcode-terminal"
import axios from "axios"

const AUTH_FOLDER = "./whatsapp-sessions"

async function startBot() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_FOLDER)
  const { version } = await fetchLatestBaileysVersion()

  console.log("✅ Iniciando bot con versión Baileys:", version)

  const sock = makeWASocket({
    version,
    browser: ["Chrome (Linux)", "Chrome", "10.0.0"],
    auth: state,
    logger: Pino({ level: "silent" }),
    markOnlineOnConnect: true,
    syncFullHistory: false,
  })

  // --- QR ---
  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update

    if (qr) {
      console.log("📲 Escaneá este código QR con tu WhatsApp:")
      qrcode.generate(qr, { small: true })
    }

    if (connection === "close") {
      const reason = new Boom(lastDisconnect?.error)?.output?.statusCode
      if (reason === DisconnectReason.loggedOut) {
        console.log("❌ Sesión cerrada, borrando datos y reiniciando...")
        fs.rmSync(AUTH_FOLDER, { recursive: true, force: true })
        startBot()
      } else {
        console.log("⚠️ Conexión cerrada. Reconectando...")
        startBot()
      }
    } else if (connection === "open") {
      console.log("✅ Conectado a WhatsApp Web correctamente.")
      console.log("🤖 Bot listo - vinculado con backend Python.")
    }
  })

  // --- Guardar credenciales ---
  sock.ev.on("creds.update", saveCreds)

  // --- Manejo de mensajes ---
  sock.ev.on("messages.upsert", async ({ messages }) => {
    const msg = messages[0]
    if (!msg.message || msg.key.fromMe) return

    const from = msg.key.remoteJid
    const text = msg.message.conversation || msg.message.extendedTextMessage?.text
    if (!text) return

    console.log(`💬 Mensaje de ${from}: "${text}"`)

    try {
      const webhookData = { from, message: text }
      const response = await axios.post("http://localhost:5001/webhook", webhookData, { timeout: 10000 })

      if (response.data && response.data.reply) {
        await sock.sendMessage(from, { text: response.data.reply })
        console.log("✅ Respuesta enviada al usuario.")
      }
    } catch (error) {
      console.error("❌ Error al manejar mensaje:", error.message)
      try {
        await sock.sendMessage(from, { text: "⚠️ Error del servidor. Intenta nuevamente más tarde." })
      } catch {}
    }
  })
}

// --- Iniciar ---
startBot().catch((err) => console.error("❌ Error general:", err))