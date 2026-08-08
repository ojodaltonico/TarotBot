import test from "node:test"
import assert from "node:assert/strict"
import { resolve } from "node:path"
import { dispatchBackendResponse, extractInboundMessage, getBackendRequestTimeoutMs, getCollectionTimeoutMs, isGatewayTimeout, isGroupJid, MessageBatcher, sendBackendMessages } from "../index.js"

function fakeClock() {
  let now = 0
  let nextId = 0
  const timers = new Map()
  return {
    now: () => now,
    setTimer: (callback, delay) => { const id = ++nextId; timers.set(id, { due: now + delay, callback }); return id },
    clearTimer: (id) => timers.delete(id),
    async advance(milliseconds) {
      const target = now + milliseconds
      while (true) {
        const due = [...timers.entries()].filter(([, timer]) => timer.due <= target).sort((a, b) => a[1].due - b[1].due)[0]
        if (!due) break
        timers.delete(due[0]); now = due[1].due; await due[1].callback()
      }
      now = target
    },
  }
}

function inbound(sender, id, text = "x") {
  return { sender, message_id: id, timestamp: new Date(0).toISOString(), message_type: "text", text }
}

function batcherHarness(processBatch) {
  const clock = fakeClock()
  const presences = []
  const batcher = new MessageBatcher({ processBatch, onBotPresence: async (...args) => presences.push(args), now: clock.now, setTimer: clock.setTimer, clearTimer: clock.clearTimer, log: { info() {}, error() {} } })
  return { clock, batcher, presences }
}

test("detecta JID de grupo", () => {
  assert.equal(isGroupJid("12345-67890@g.us"), true)
  assert.equal(isGroupJid("5491100000000@s.whatsapp.net"), false)
})

test("extrae texto y metadatos de un mensaje privado", () => {
  const payload = extractInboundMessage({
    key: { remoteJid: "5491100000000@s.whatsapp.net", id: "ABC" },
    messageTimestamp: 1_700_000_000,
    message: { extendedTextMessage: { text: "Hola" } },
  })
  assert.equal(payload.sender, "5491100000000@s.whatsapp.net")
  assert.equal(payload.message_id, "ABC")
  assert.equal(payload.message_type, "text")
  assert.equal(payload.text, "Hola")
})

test("envía textos del backend en orden e ignora tipos futuros", async () => {
  const sent = []
  const sock = {
    sendMessage: async (_recipient, payload) => sent.push(payload.text),
    sendPresenceUpdate: async () => {},
  }
  await sendBackendMessages(sock, "5491100000000@s.whatsapp.net", [
    { type: "text", text: "primero" },
    { type: "tarot_card", card_id: "major-00" },
    { type: "text", text: "segundo" },
  ])
  assert.deepEqual(sent, ["primero", "segundo"])
})

test("no reenvía una respuesta marcada como duplicada", async () => {
  const sent = []
  const sock = {
    sendMessage: async (_recipient, payload) => sent.push(payload),
    sendPresenceUpdate: async () => {},
  }
  await dispatchBackendResponse(sock, "5491100000000@s.whatsapp.net", {
    duplicate: true,
    messages: [{ type: "text", text: "no enviar" }],
  })
  assert.deepEqual(sent, [])
})

test("el timeout del backend es configurable y por defecto cubre una respuesta lenta", () => {
  assert.equal(getBackendRequestTimeoutMs(undefined), 60_000)
  assert.equal(getBackendRequestTimeoutMs("75000"), 75_000)
  assert.equal(getBackendRequestTimeoutMs("invalido"), 60_000)
  assert.equal(getBackendRequestTimeoutMs("999"), 60_000)
})

test("identifica timeout del gateway para no enviar un segundo mensaje", () => {
  assert.equal(isGatewayTimeout({ code: "ECONNABORTED", message: "timeout of 10000ms exceeded" }), true)
  assert.equal(isGatewayTimeout({ message: "backend returned 500" }), false)
})

test("agrupa un mensaje por idle y activa composing del bot solo al procesar", async () => {
  const batches = []; const { clock, batcher, presences } = batcherHarness(async (_jid, messages) => batches.push(messages))
  batcher.enqueue(inbound("a@s.whatsapp.net", "a1"))
  assert.deepEqual(presences, [])
  await clock.advance(11_999); assert.equal(batches.length, 0)
  await clock.advance(1); assert.equal(batches.length, 1)
  assert.deepEqual(batches[0].map((item) => item.message_id), ["a1"])
  assert.deepEqual(presences.map((item) => item[1]), ["composing", "paused"])
})

test("presence composing retiene el lote hasta pause/grace o máximo", async () => {
  const batches = []; const { clock, batcher } = batcherHarness(async (_jid, messages) => batches.push(messages))
  batcher.enqueue(inbound("a@s.whatsapp.net", "a1")); batcher.updatePresence("a@s.whatsapp.net", "composing")
  await clock.advance(30_000); assert.equal(batches.length, 0)
  batcher.updatePresence("a@s.whatsapp.net", "paused"); batcher.enqueue(inbound("a@s.whatsapp.net", "a2"))
  await clock.advance(14_999); assert.equal(batches.length, 0)
  await clock.advance(1); assert.deepEqual(batches[0].map((item) => item.message_id), ["a1", "a2"])
})

test("varios mensajes, máximo y usuarios distintos mantienen buffers separados", async () => {
  const batches = []; const { clock, batcher } = batcherHarness(async (jid, messages) => batches.push([jid, messages]))
  batcher.enqueue(inbound("a@s.whatsapp.net", "a1")); batcher.enqueue(inbound("b@s.whatsapp.net", "b1"))
  await clock.advance(8_000); batcher.enqueue(inbound("a@s.whatsapp.net", "a2"))
  await clock.advance(4_000); assert.equal(batches.length, 1)
  await clock.advance(8_000); assert.equal(batches.length, 2)
  assert.deepEqual(batches.map(([jid, messages]) => [jid, messages.length]), [["b@s.whatsapp.net", 1], ["a@s.whatsapp.net", 2]])
  batcher.enqueue(inbound("a@s.whatsapp.net", "a3")); batcher.updatePresence("a@s.whatsapp.net", "composing")
  await clock.advance(60_000); assert.equal(batches[2][1].length, 1)
})

test("mantiene un segundo lote detrás del procesamiento y se recupera de fallo", async () => {
  const batches = []; let release
  const processing = new Promise((resolve) => { release = resolve })
  const { clock, batcher } = batcherHarness(async (_jid, messages) => { batches.push(messages); if (batches.length === 1) await processing; if (batches.length === 3) throw new Error("fail") })
  batcher.enqueue(inbound("a@s.whatsapp.net", "a1")); const firstClose = clock.advance(12_000); await Promise.resolve()
  batcher.enqueue(inbound("a@s.whatsapp.net", "a2")); release(); await firstClose; await clock.advance(12_000)
  assert.deepEqual(batches.slice(0, 2).map((messages) => messages[0].message_id), ["a1", "a2"])
  batcher.enqueue(inbound("a@s.whatsapp.net", "a3")); await clock.advance(12_000)
  batcher.enqueue(inbound("a@s.whatsapp.net", "a4")); await clock.advance(12_000)
  assert.deepEqual(batches.map((messages) => messages[0].message_id), ["a1", "a2", "a3", "a4"])
})

test("normaliza configuración de ventana humana", () => {
  assert.equal(getCollectionTimeoutMs("20000", 12_000), 20_000)
  assert.equal(getCollectionTimeoutMs("bad", 12_000), 12_000)
})

test("envía una imagen antes de los fragmentos con typing y pausas por burbuja", async () => {
  const events = []
  const sock = {
    sendPresenceUpdate: async (presence) => events.push(`presence:${presence}`),
    sendMessage: async (_recipient, payload) => events.push(payload.image ? "image" : `text:${payload.text}`),
  }
  const table = resolve(process.cwd(), "..", "assets", "tarot-cards", "table", "table_v1.png")
  await sendBackendMessages(sock, "a@s.whatsapp.net", [
    { type: "image", image_path: table, caption: "Cartas", typing_ms: 100 },
    { type: "text", text: "Primera idea.", typing_ms: 200, delay_ms: 50 },
    { type: "text", text: "Segunda idea.", typing_ms: 300, delay_ms: 75 },
  ], { sleep: async (milliseconds) => events.push(`sleep:${milliseconds}`) })
  assert.deepEqual(events, [
    "presence:composing", "sleep:100", "presence:paused", "image",
    "sleep:50", "presence:composing", "sleep:200", "presence:paused", "text:Primera idea.",
    "sleep:75", "presence:composing", "sleep:300", "presence:paused", "text:Segunda idea.",
  ])
})

test("omite una imagen inexistente sin detener los textos posteriores", async () => {
  const sent = []; const warnings = []
  const sock = { sendPresenceUpdate: async () => {}, sendMessage: async (_recipient, payload) => sent.push(payload) }
  await sendBackendMessages(sock, "a@s.whatsapp.net", [
    { type: "image", image_path: "Z:/missing-reading.jpg" },
    { type: "text", text: "Seguimos con la lectura." },
  ], { sleep: async () => {}, log: { warn: (message) => warnings.push(message) } })
  assert.equal(warnings.length, 1)
  assert.deepEqual(sent, [{ text: "Seguimos con la lectura." }])
})

test("un fallo durante el typing siempre pausa la presencia", async () => {
  const presences = []
  const sock = { sendPresenceUpdate: async (presence) => presences.push(presence), sendMessage: async () => {} }
  await assert.rejects(
    sendBackendMessages(sock, "a@s.whatsapp.net", [{ type: "text", text: "Hola", typing_ms: 10 }], { sleep: async () => { throw new Error("timer failed") } }),
    /timer failed/,
  )
  assert.deepEqual(presences, ["composing", "paused"])
})
