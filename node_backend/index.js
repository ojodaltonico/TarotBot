import makeWASocket, {
  DisconnectReason,
  downloadMediaMessage,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from "@whiskeysockets/baileys"
import axios from "axios"
import dotenv from "dotenv"
import qrcode from "qrcode-terminal"
import { resolve } from "path"
import { pathToFileURL } from "url"
import { existsSync } from "fs"

dotenv.config({ path: resolve(process.cwd(), "..", ".env") })

const AUTH_FOLDER = process.env.WHATSAPP_AUTH_FOLDER || "./whatsapp-sessions"
const BACKEND_URL = process.env.WHATSAPP_BACKEND_URL || "http://127.0.0.1:5001"
const INBOUND_URL = `${BACKEND_URL.replace(/\/$/, "")}/internal/whatsapp/inbound`
const TRANSCRIBE_URL = `${BACKEND_URL.replace(/\/$/, "")}/internal/whatsapp/transcribe`
const MAX_RECONNECT_DELAY_MS = 30_000

export function getBackendRequestTimeoutMs(value = process.env.BACKEND_REQUEST_TIMEOUT_MS) {
  const timeout = Number(value)
  return Number.isFinite(timeout) && timeout >= 1_000 ? Math.floor(timeout) : 60_000
}

export function isGatewayTimeout(error) {
  return error?.code === "ECONNABORTED" || /timeout.*exceeded/i.test(String(error?.message || ""))
}

export function getCollectionTimeoutMs(value, fallback) {
  const timeout = Number(value)
  return Number.isFinite(timeout) && timeout >= 1_000 ? Math.floor(timeout) : fallback
}

export function getAudioLimit(value, fallback) {
  const limit = Number(value)
  return Number.isFinite(limit) && limit > 0 ? Math.floor(limit) : fallback
}

const BACKEND_REQUEST_TIMEOUT_MS = getBackendRequestTimeoutMs()

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
  } else if (content.audioMessage) {
    text = ""
    messageType = "audio"
  }

  if (!messageType) return null

  const media = content.audioMessage
  const contextInfo = content.extendedTextMessage?.contextInfo || content.imageMessage?.contextInfo || media?.contextInfo
  const quotedContent = contextInfo?.quotedMessage || {}
  const quotedText = typeof quotedContent.conversation === "string"
    ? quotedContent.conversation
    : typeof quotedContent.extendedTextMessage?.text === "string"
      ? quotedContent.extendedTextMessage.text
      : typeof quotedContent.imageMessage?.caption === "string"
        ? quotedContent.imageMessage.caption
        : typeof quotedContent.audioMessage?.caption === "string"
          ? quotedContent.audioMessage.caption
          : null

  const unixTimestamp = Number(message.messageTimestamp) || Math.floor(Date.now() / 1000)
  return {
    sender: message.key.remoteJid,
    message_id: message.key.id,
    timestamp: new Date(unixTimestamp * 1000).toISOString(),
    message_type: messageType,
    text,
    quoted_text: quotedText,
    quoted_message_id: contextInfo?.stanzaId || null,
    audio_mimetype: media?.mimetype || null,
    audio_duration_seconds: Number.isFinite(Number(media?.seconds)) ? Number(media.seconds) : null,
    audio_ptt: typeof media?.ptt === "boolean" ? media.ptt : null,
    _raw_message: message,
  }
}

export async function transcribeAudioMessage(inbound, sock, {
  request = axios.post,
  downloader = downloadMediaMessage,
  maxBytes = getAudioLimit(process.env.AUDIO_MAX_BYTES, 12_000_000),
  maxSeconds = getAudioLimit(process.env.AUDIO_MAX_SECONDS, 300),
} = {}) {
  if (inbound.message_type !== "audio") return inbound
  if (inbound.audio_duration_seconds !== null && inbound.audio_duration_seconds > maxSeconds) {
    return { ...inbound, transcription_error: "audio_too_long" }
  }
  const declaredSize = Number(inbound._raw_message?.message?.audioMessage?.fileLength)
  if (Number.isFinite(declaredSize) && declaredSize > maxBytes) {
    return { ...inbound, transcription_error: "audio_too_large" }
  }
  let buffer
  try {
    buffer = await downloader(inbound._raw_message, "buffer", {}, { reuploadRequest: sock.updateMediaMessage })
  } catch (_) {
    return { ...inbound, transcription_error: "download_error" }
  }
  if (!Buffer.isBuffer(buffer) || buffer.length === 0) return { ...inbound, transcription_error: "download_error" }
  if (buffer.length > maxBytes) return { ...inbound, transcription_error: "audio_too_large" }
  try {
    const response = await request(TRANSCRIBE_URL, {
      audio_base64: buffer.toString("base64"), mimetype: inbound.audio_mimetype || "audio/ogg",
      duration_seconds: inbound.audio_duration_seconds,
    }, { timeout: BACKEND_REQUEST_TIMEOUT_MS })
    const result = response.data || {}
    return {
      ...inbound, text: typeof result.text === "string" ? result.text : "",
      transcription_provider: result.provider || "unknown", transcription_model: result.model || "unknown",
      transcription_latency_ms: Number(result.latency_ms || 0), transcription_error: result.error_type || null,
    }
  } catch (_) {
    return { ...inbound, transcription_error: "transcription_provider_error" }
  }
}

export class MessageBatcher {
  constructor({ processBatch, onBotPresence = async () => {}, idleMs = 12_000, typingGraceMs = 15_000, maxCollectionMs = 60_000, now = () => Date.now(), setTimer = setTimeout, clearTimer = clearTimeout, log = console }) {
    this.processBatch = processBatch
    this.onBotPresence = onBotPresence
    this.idleMs = idleMs
    this.typingGraceMs = typingGraceMs
    this.maxCollectionMs = maxCollectionMs
    this.now = now
    this.setTimer = setTimer
    this.clearTimer = clearTimer
    this.log = log
    this.chats = new Map()
  }

  enqueue(message) {
    const chat = this._chat(message.sender)
    if (!chat.pending) chat.pending = { messages: [], firstAt: this.now(), lastAt: this.now(), typingEndedAt: null }
    chat.pending.messages.push(message)
    chat.pending.lastAt = this.now()
    this.log.info?.(`whatsapp_batch chat=${message.sender.slice(0, 8)} buffered=${chat.pending.messages.length}`)
    this._schedule(message.sender, chat)
  }

  updatePresence(jid, presence) {
    const chat = this._chat(jid)
    if (presence === "composing") {
      chat.composing = true
    } else if (presence === "paused" || presence === "available" || presence === "unavailable") {
      if (chat.composing) chat.pending && (chat.pending.typingEndedAt = this.now())
      chat.composing = false
    }
    this.log.info?.(`whatsapp_presence chat=${jid.slice(0, 8)} presence=${presence}`)
    this._schedule(jid, chat)
  }

  _chat(jid) {
    if (!this.chats.has(jid)) this.chats.set(jid, { pending: null, composing: false, processing: false, timer: null })
    return this.chats.get(jid)
  }

  _schedule(jid, chat) {
    if (!chat.pending || chat.processing) return
    if (chat.timer) this.clearTimer(chat.timer)
    const now = this.now()
    const elapsed = now - chat.pending.firstAt
    const maxRemaining = Math.max(0, this.maxCollectionMs - elapsed)
    let wait = maxRemaining
    if (!chat.composing) {
      const idleDue = chat.pending.lastAt + this.idleMs
      const graceDue = chat.pending.typingEndedAt ? chat.pending.typingEndedAt + this.typingGraceMs : idleDue
      wait = Math.min(maxRemaining, Math.max(0, idleDue - now, graceDue - now))
    }
    chat.timer = this.setTimer(() => this._close(jid), wait)
  }

  async _close(jid) {
    const chat = this._chat(jid)
    chat.timer = null
    if (!chat.pending || chat.processing) return
    const elapsed = this.now() - chat.pending.firstAt
    if (chat.composing && elapsed < this.maxCollectionMs) return this._schedule(jid, chat)
    const batch = chat.pending
    chat.pending = null
    chat.processing = true
    const reason = elapsed >= this.maxCollectionMs ? "max_collection" : "idle"
    this.log.info?.(`whatsapp_batch chat=${jid.slice(0, 8)} buffered=${batch.messages.length} close=${reason} duration_ms=${elapsed}`)
    try {
      await this.onBotPresence(jid, "composing")
      await this.processBatch(jid, batch.messages)
    } catch (error) {
      this.log.error?.(`whatsapp_batch chat=${jid.slice(0, 8)} result=failed error=${error?.code || "request"}`)
    } finally {
      await this.onBotPresence(jid, "paused")
      chat.processing = false
      this._schedule(jid, chat)
    }
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

export async function sendBackendMessages(sock, recipient, messages, { sleep = (milliseconds) => new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds)), log = console } = {}) {
  for (const message of messages || []) {
    const typingMs = Number(message.typing_ms || 0)
    const delayMs = Number(message.delay_ms || 0)

    if (delayMs > 0) await sleep(delayMs)
    if (typingMs > 0) {
      await sock.sendPresenceUpdate("composing", recipient)
      try {
        await sleep(typingMs)
      } finally {
        await sock.sendPresenceUpdate("paused", recipient)
      }
    }

    if (message.type === "text" && message.text) {
      await sock.sendMessage(recipient, { text: message.text })
    } else if (message.type === "image" && message.image_path) {
      if (!existsSync(message.image_path)) {
        log.warn?.("La imagen de la tirada no está disponible; se omite el envío.")
        continue
      }
      const payload = { image: { url: message.image_path } }
      if (message.caption) payload.caption = message.caption
      await sock.sendMessage(recipient, payload)
    } else {
      console.warn(`El backend solicitó un tipo de mensaje no implementado: ${String(message.type || "desconocido")}.`)
    }
  }
}

export async function dispatchBackendResponse(sock, recipient, response) {
  if (response?.duplicate) return
  await sendBackendMessages(sock, recipient, response?.messages)
}

export function createBatchProcessor(sock, request = axios.post, transcribe = transcribeAudioMessage) {
  return async (sender, messages) => {
    const resolved = []
    for (const message of messages) resolved.push(await transcribe(message, sock, { request }))
    const first = resolved[0]
    const payload = {
      sender,
      message_id: first.message_id,
      timestamp: first.timestamp,
      message_type: first.message_type,
      text: first.text,
      messages: resolved.map(({ message_id, timestamp, message_type, text, quoted_text, quoted_message_id, audio_mimetype, audio_duration_seconds, audio_ptt, transcription_provider, transcription_model, transcription_latency_ms, transcription_error }) => ({ message_id, timestamp, message_type, text, quoted_text, quoted_message_id, audio_mimetype, audio_duration_seconds, audio_ptt, transcription_provider, transcription_model, transcription_latency_ms, transcription_error })),
    }
    const response = await request(INBOUND_URL, payload, { timeout: BACKEND_REQUEST_TIMEOUT_MS })
    await dispatchBackendResponse(sock, sender, response.data)
  }
}

async function handleInboundMessage(batcher, rawMessage) {
  if (!rawMessage.message || rawMessage.key.fromMe) return
  if (isGroupJid(rawMessage.key.remoteJid)) return

  const inbound = extractInboundMessage(rawMessage)
  if (!inbound) return

  batcher.enqueue(inbound)
  return

  console.info(`Mensaje entrante recibido: id=${inbound.message_id} tipo=${inbound.message_type}`)
  try {
    const response = await axios.post(INBOUND_URL, inbound, { timeout: BACKEND_REQUEST_TIMEOUT_MS })
    await dispatchBackendResponse(sock, inbound.sender, response.data)
  } catch (error) {
    const status = error.response?.status
    if (isGatewayTimeout(error)) {
      console.error(`Timeout del gateway para id=${inbound.message_id}; el backend puede seguir procesándolo.`)
      return
    }
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
  const batcher = new MessageBatcher({
    processBatch: createBatchProcessor(sock),
    onBotPresence: (jid, presence) => sock.sendPresenceUpdate(presence, jid),
    idleMs: getCollectionTimeoutMs(process.env.WHATSAPP_MESSAGE_IDLE_MS, 12_000),
    typingGraceMs: getCollectionTimeoutMs(process.env.WHATSAPP_TYPING_GRACE_MS, 15_000),
    maxCollectionMs: getCollectionTimeoutMs(process.env.WHATSAPP_MAX_COLLECTION_MS, 60_000),
  })
  sock.ev.on("presence.update", ({ id, presences }) => {
    if (isGroupJid(id)) return
    for (const presence of Object.values(presences || {})) batcher.updatePresence(id, presence.lastKnownPresence)
  })
  sock.ev.on("messages.upsert", async ({ messages }) => {
    for (const message of messages) await handleInboundMessage(batcher, message)
  })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  startBot().catch((error) => {
    console.error("No se pudo iniciar el gateway:", error.message)
    scheduleReconnect("error inicial")
  })
}
