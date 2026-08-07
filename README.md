# TarotBot

Infraestructura conversacional inicial para una tarotista virtual por WhatsApp. Incluye un Tarot Engine independiente y auditable; todavía no incluye IA, memoria, panel administrativo ni pagos.

## Arquitectura

```text
WhatsApp -> Baileys (Node) -> FastAPI (127.0.0.1:5001) -> SQLite
         <- mensajes temporales  <- FastAPI
```

El gateway Node recibe mensajes privados, los normaliza y los envía a `POST /internal/whatsapp/inbound`. FastAPI crea o localiza el usuario y su conversación activa, persiste el mensaje y devuelve una respuesta temporal. El gateway la envía a WhatsApp.

## Requisitos

- Windows, Python 3.11+ y Node.js 20+.
- Una cuenta de WhatsApp para vincular mediante QR.

## Instalación

1. Copiá `.env.example` a `.env` si querés cambiar la configuración local. No agregues secretos al repositorio.
2. Ejecutá `install.bat`.
3. Ejecutá `run.bat` para abrir el backend y el gateway, o `start_backend.bat` / `start_gateway.bat` por separado.

El backend queda disponible en `http://127.0.0.1:5001`; su estado se consulta en `GET /health`.

## Vincular WhatsApp

Al iniciar el gateway se mostrará un QR en la consola si no hay una sesión válida. En WhatsApp, abrí **Dispositivos vinculados** y escanealo. Las credenciales se guardan en `node_backend/whatsapp-sessions/` y nunca deben subirse a Git.

## Datos locales

- SQLite: `data/tarotbot.db` (se crea y migra automáticamente al arrancar FastAPI).
- Sesión de WhatsApp: `node_backend/whatsapp-sessions/`.
- Configuración local: `.env`.

Todos estos elementos están ignorados por Git.

## Estado del MVP

Por cada mensaje privado de texto (o caption de imagen), el sistema persiste un usuario, una conversación y el mensaje entrante. Devuelve y guarda la respuesta temporal: `Hola. TarotBot está conectado correctamente. 🔮`. El identificador de mensaje de WhatsApp es único: reenviar el mismo ID no produce una segunda respuesta ni duplica datos.

Los grupos se descartan por ahora. El contrato ya admite metadatos de typing/delay e imágenes para fases posteriores, aunque la respuesta temporal actual es solo texto.

## Tarot Engine

El catálogo Rider-Waite-Smith contiene 78 cartas estructuradas en `backend/app/tarot/data/deck.json`: 22 arcanos mayores y 56 menores (14 por palo). El motor Python selecciona cartas sin repetición, controla la probabilidad de invertidas y admite una semilla opcional para reproducir una tirada. No interviene ningún modelo de IA.

Spreads disponibles: `one_card`, `general_three` y `relationship_three`. Las tiradas persistidas guardan posición, orientación, metadatos de auditoría y un snapshot de la carta; por eso no se reescriben si el catálogo cambia después.

Para probar un sorteo puro, sin WhatsApp ni persistencia:

```bat
backend\.venv\Scripts\python.exe scripts\test_tarot.py relationship_three --seed ejemplo-1
```

Las rutas de imágenes futuras están documentadas en [`assets/tarot-cards/README.md`](assets/tarot-cards/README.md). No se incluye arte de cartas en este repositorio todavía.

## Tests

Con las dependencias instaladas:

```bat
backend\.venv\Scripts\python.exe -m pytest backend\tests
npm.cmd --prefix node_backend test
```

## Estado actual del proyecto

TarotBot incluye el gateway WhatsApp/Baileys, FastAPI con SQLite, un Tarot Engine Rider-Waite-Smith de 78 cartas y los spreads `one_card`, `general_three` y `relationship_three`. También dispone de motor conversacional, memoria resumida, provider Gemini, provider Fake, interpretaciones persistidas y laboratorio local. WhatsApp todavía **no está conectado a la IA**.

## Configuración IA y laboratorio

Las variables locales principales son `AI_ENABLED`, `AI_PROVIDER`, `AI_CHAT_MODEL`, `AI_MEMORY_MODEL`, `GEMINI_API_KEY`, `AI_TIMEOUT_SECONDS`, `AI_RECENT_MESSAGES`, `AI_MEMORY_UPDATE_INTERVAL` y `AI_STORE_DEBUG_PAYLOADS`. `.env` está ignorado por Git; nunca guardes una key real en el repositorio.

Para desarrollo sin red usá `AI_PROVIDER=fake`. Para Gemini configurá localmente `AI_PROVIDER=gemini` y `GEMINI_API_KEY=<tu clave local>`. Iniciá el backend y luego ejecutá `python scripts/chat_tarot.py` (o `--debug`). La consola admite `/reading [one_card|general_three|relationship_three]`, `/memory`, `/state`, `/refresh-memory`, `/reset`, `/help` y `/quit`.

Las rutas `/internal/lab/...` son sólo para desarrollo local: chat, estado de usuario, lectura explícita, refresh de memoria y reset. El modo debug muestra estado, recomendación, uso y costo, nunca secretos ni payloads completos. Las conversaciones de laboratorio pueden persistirse localmente en SQLite; usá los debug payloads conscientemente y revisá las condiciones del provider y la retención antes de producción.
