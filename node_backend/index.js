import makeWASocket, {
  DisconnectReason,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from "@whiskeysockets/baileys"
import axios from "axios"
import dotenv from "dotenv"
import qrcode from "qrcode-terminal"
import { resolve } from "path"
import { pathToFileURL } from "url"

dotenv.config({ path: resolve(process.cwd(), "..", ".env") })

const AUTH_FOLDER = process.env.WHATSAPP_AUTH_FOLDER || "./whatsapp-sessions"
const BACKEND_URL = process.env.WHATSAPP_BACKEND_URL || "http://127.0.0.1:5001"
const INBOUND_URL = `${BACKEND_URL.replace(/\/$/, "")}/internal/whatsapp/inbound`
const MAX_RECONNECT_DELAY_MS = 30_000

let reconnectAttempts = 0
let reconnectScheduled = false

export function isGroupJid(jid) {
  return typeof jid === "string" && jid.endsWith("@g.us")
}

export function extractInboundMessage(message) {
  const content = message.message
  if (!content || !message.key?.remoteJid || !message.key?.id) return null

  let text = null
  let messageType = null

  if (typeof content.conversation === "string") {
    text = content.conversation
    messageType = "text"
  } else if (typeof content.extendedTextMessage?.text === "string") {
    text = content.extendedTextMessage.text
    messageType = "text"
  } else if (content.imageMessage) {
    text = content.imageMessage.caption || ""
    messageType = "image"
  }

  if (!messageType) return null

  const unixTimestamp = Number(message.messageTimestamp) || Math.floor(Date.now() / 1000)
  return {
    sender: message.key.remoteJid,
    message_id: message.key.id,
    timestamp: new Date(unixTimestamp * 1000).toISOString(),
    message_type: messageType,
    text,
  }
}

function scheduleReconnect(reason) {
  if (reconnectScheduled) return

  reconnectScheduled = true
  const delay = Math.min(1_000 * 2 ** reconnectAttempts, MAX_RECONNECT_DELAY_MS)
  reconnectAttempts += 1
  console.warn(`WhatsApp se desconectó (${reason}). Reintento en ${delay / 1000}s.`)

  setTimeout(() => {
    reconnectScheduled = false
    startBot().catch((error) => {
      console.error("No se pudo reiniciar el gateway:", error.message)
      scheduleReconnect("fallo al iniciar")
    })
  }, delay)
}

async function sendBackendMessages(sock, recipient, messages) {
  for (const message of messages || []) {
    const typingMs = Number(message.typing_ms || 0)
    const delayMs = Number(message.delay_ms || 0)

    if (typingMs > 0 || delayMs > 0) {
      await sock.sendPresenceUpdate("composing", recipient)
      await new Promise((resolveDelay) => setTimeout(resolveDelay, Math.min(Math.max(typingMs, delayMs), 10_000)))
      await sock.sendPresenceUpdate("paused", recipient)
    }

    if (message.type === "text" && message.text) {
      await sock.sendMessage(recipient, { text: message.text })
    } else if (message.type === "image") {
      console.warn("El backend solicitó una imagen, formato aún no implementado.")
    }
  }
}

async function handleInboundMessage(sock, rawMessage) {
  if (!rawMessage.message || rawMessage.key.fromMe) return
  if (isGroupJid(rawMessage.key.remoteJid)) return

  const inbound = extractInboundMessage(rawMessage)
  if (!inbound) return

  console.info(`Mensaje entrante recibido: id=${inbound.message_id} tipo=${inbound.message_type}`)
  try {
    const response = await axios.post(INBOUND_URL, inbound, { timeout: 10_000 })
    await sendBackendMessages(sock, inbound.sender, response.data?.messages)
  } catch (error) {
    const status = error.response?.status
    console.error(`Error procesando id=${inbound.message_id}${status ? ` status=${status}` : ""}:`, error.message)
    try {
      await sock.sendMessage(inbound.sender, {
        text: "No pude procesar tu mensaje en este momento. Intentá nuevamente en unos instantes.",
      })
    } catch (sendError) {
      console.error(`No se pudo enviar el aviso para id=${inbound.message_id}:`, sendError.message)
    }
  }
}

async function startBot() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_FOLDER)
  const { version } = await fetchLatestBaileysVersion()
  const sock = makeWASocket({
    version,
    browser: ["TarotBot", "Chrome", "1.0.0"],
    auth: state,
    markOnlineOnConnect: false,
    syncFullHistory: false,
  })

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update
    if (qr) {
      console.log("Escaneá este código QR con WhatsApp:")
      qrcode.generate(qr, { small: true })
    }
    if (connection === "open") {
      reconnectAttempts = 0
      console.log("Gateway conectado a WhatsApp.")
    }
    if (connection === "close") {
      const statusCode = lastDisconnect?.error?.output?.statusCode
      if (statusCode === DisconnectReason.loggedOut) {
        console.error("La sesión fue cerrada. Las credenciales locales se preservaron; vinculá nuevamente si hace falta.")
      }
      scheduleReconnect(statusCode || "desconocido")
    }
  })

  sock.ev.on("creds.update", saveCreds)
  sock.ev.on("messages.upsert", async ({ messages }) => {
    for (const message of messages) await handleInboundMessage(sock, message)
  })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  startBot().catch((error) => {
    console.error("No se pudo iniciar el gateway:", error.message)
    scheduleReconnect("error inicial")
  })
}
