import test from "node:test"
import assert from "node:assert/strict"
import { extractInboundMessage, isGroupJid } from "../index.js"

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
