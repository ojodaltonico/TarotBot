# TarotBot

Infraestructura conversacional inicial para una tarotista virtual por WhatsApp. Incluye un Tarot Engine independiente y auditable; todavía no incluye IA, memoria, panel administrativo ni pagos.

## Arquitectura

```text
WhatsApp -> Baileys (Node) -> FastAPI -> ConversationService -> Tarot Engine / IA -> SQLite
         <- mensajes ordenados   <- FastAPI
```

El gateway Node recibe mensajes privados, los normaliza y los envía a `POST /internal/whatsapp/inbound`. FastAPI crea o localiza el usuario y su conversación activa, persiste el mensaje y devuelve una respuesta temporal. El gateway la envía a WhatsApp.

## Requisitos

- Windows, Python 3.11+ y Node.js 20+.
- Una cuenta de WhatsApp para vincular mediante QR.

## Instalación

1. Copiá `.env.example` a `.env` si querés cambiar la configuración local. No agregues secretos al repositorio.
2. Ejecutá `install.bat`.
3. Ejecutá `run.bat`: espera `/health`, abre backend y gateway en terminales separadas y luego abre el dashboard privado. También podés ejecutar `start_backend.bat` o `start_gateway.bat` por separado para diagnóstico.

El backend queda disponible en `http://127.0.0.1:5001`; su estado se consulta en `GET /health`.

### Arranque normal en Windows

1. Configurá `.env` localmente.
2. Hacé doble clic en `run.bat`.
3. El script espera que FastAPI responda `/health`, deja backend y gateway visibles en terminales separadas y abre automáticamente `/admin` si está habilitado.

`run.bat` reutiliza un backend saludable y detecta un gateway Node ya activo para evitar duplicar la sesión Baileys. Si necesitás diagnosticar un componente, mantenés disponibles `start_backend.bat` y `start_gateway.bat` por separado.

## Vincular WhatsApp

Al iniciar el gateway se mostrará un QR en la consola si no hay una sesión válida. En WhatsApp, abrí **Dispositivos vinculados** y escanealo. Las credenciales se guardan en `node_backend/whatsapp-sessions/` y nunca deben subirse a Git.

## Datos locales

- SQLite: `data/tarotbot.db` (se crea y migra automáticamente al arrancar FastAPI).
- Sesión de WhatsApp: `node_backend/whatsapp-sessions/`.
- Configuración local: `.env`.

Todos estos elementos están ignorados por Git.

## WhatsApp y flujo conversacional

Por cada mensaje privado de texto (o caption de imagen), el sistema persiste un usuario, una conversación y el mensaje entrante. Devuelve y guarda la respuesta temporal: `Hola. TarotBot está conectado correctamente. 🔮`. El identificador de mensaje de WhatsApp es único: reenviar el mismo ID no produce una segunda respuesta ni duplica datos.

Los grupos se descartan por ahora. El contrato ya admite metadatos de typing/delay e imágenes para fases posteriores, aunque la respuesta temporal actual es solo texto.

El endpoint `POST /internal/whatsapp/inbound` procesa mensajes privados de texto y captions de imágenes con `ConversationService`. Su respuesta contiene `duplicate` y una lista ordenada `messages[]`; en 4A el gateway entrega únicamente acciones `text`. Las cartas y su interpretación se devuelven como texto hasta que se implemente envío de imágenes. Un `message_id` repetido no vuelve a llamar a la IA ni crea otra lectura. Imágenes sin caption y tipos no soportados se ignoran silenciosamente; los grupos siguen excluidos.

Para desarrollo sin red, usá `AI_PROVIDER=fake`: permite recorrer conversación, recomendación, confirmación natural y tirada automática de punta a punta. Typing, demoras e imágenes quedan pendientes.

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

Las variables locales principales son `AI_ENABLED`, `AI_PROVIDER`, `AI_CHAT_MODEL`, `AI_MEMORY_MODEL`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `AI_TIMEOUT_SECONDS`, `AI_TRUST_ENV_PROXY`, `AI_RECENT_MESSAGES`, `AI_MEMORY_UPDATE_INTERVAL` y `AI_STORE_DEBUG_PAYLOADS`. `.env` está ignorado por Git; nunca guardes una key real en el repositorio.

`AI_TRUST_ENV_PROXY=false` (valor por defecto) hace que Gemini conecte directamente y no herede proxies configurados en el entorno. Usá `true` solamente si tu red necesita un proxy; entonces Gemini respetará `HTTP_PROXY`, `HTTPS_PROXY` y `ALL_PROXY`. Esta opción se aplica sólo al cliente HTTP de Gemini, sin cambiar variables del sistema.

El gateway WhatsApp agrupa burbujas consecutivas por JID antes de llamar al backend. `WHATSAPP_MESSAGE_IDLE_MS` (12000) cierra un lote por silencio cuando no hay presencia; `WHATSAPP_TYPING_GRACE_MS` (15000) agrega margen después de que el contacto deja de escribir; y `WHATSAPP_MAX_COLLECTION_MS` (60000) fuerza el cierre para evitar un buffer eterno. Si WhatsApp no informa presencia, se utiliza únicamente idle y máximo.

Para desarrollo sin red usá `AI_PROVIDER=fake`. Para Gemini configurá localmente `AI_PROVIDER=gemini` y `GEMINI_API_KEY=<tu clave local>`. Para Groq usá `AI_PROVIDER=groq`, `AI_CHAT_MODEL=openai/gpt-oss-120b`, `AI_MEMORY_MODEL=openai/gpt-oss-120b` y `GROQ_API_KEY=<tu clave local>`.

Groq usa el SDK oficial de Python `groq`, en vez del cliente compatible con OpenAI. Las decisiones conversacionales y las interpretaciones se solicitan con JSON Schema Mode (`response_format`) y se validan otra vez con Pydantic; las respuestas de memoria permanecen textuales. El cliente desactiva reintentos automáticos para que cada intento quede auditado una sola vez. `python scripts/test_groq_connection.py` hace una única verificación explícita y sanitizada; nunca se ejecuta desde los tests.

Iniciá el backend y luego ejecutá `python scripts/chat_tarot.py` (o `--debug`). La consola admite `/reading [one_card|general_three|relationship_three]`, `/memory`, `/state`, `/refresh-memory`, `/reset`, `/help` y `/quit`.

Para pruebas por WhatsApp, `WHATSAPP_TYPING_CHARS_PER_SECOND` (22 por defecto), `WHATSAPP_MIN_TYPING_MS` (1800) y `WHATSAPP_MAX_TYPING_MS` (18000) calculan el tiempo de escritura por fragmento. `WHATSAPP_INTER_MESSAGE_DELAY_MS_MIN` y `WHATSAPP_INTER_MESSAGE_DELAY_MS_MAX` (600–1800) agregan una pausa acotada entre burbujas. Las respuestas largas se dividen sólo entre párrafos u oraciones completas, hasta cuatro mensajes. Cuando una tirada se interpreta, el backend entrega primero una única imagen renderizada `table_v2` y luego la lectura; si falla la interpretación, puede mostrar las cartas junto con un fallback, sin reintento automático ni cambio de estado a lectura activa.

Las rutas `/internal/lab/...` son sólo para desarrollo local: chat, estado de usuario, lectura explícita, refresh de memoria y reset. El modo debug muestra estado, recomendación, uso y costo, nunca secretos ni payloads completos. Las conversaciones de laboratorio pueden persistirse localmente en SQLite; usá los debug payloads conscientemente y revisá las condiciones del provider y la retención antes de producción.

## Dashboard privado V1

El panel de observación vive dentro del backend: iniciá `start_backend.bat` y abrí [http://127.0.0.1:5001/admin](http://127.0.0.1:5001/admin). Está pensado exclusivamente para uso local y abre directamente, sin usuario ni contraseña. Podés ocultarlo con `ADMIN_ENABLED=false`.

El dashboard es exclusivamente de lectura: permite revisar actividad, conversaciones anonimizadas, timeline, memoria, tiradas, imágenes `table_v2`, llamadas IA y errores. No permite responder, editar prompts, cambiar usuarios ni borrar información. Las páginas usan `no-store` y `noindex`; las imágenes se sirven sólo desde el backend local y se regeneran con el renderer si falta su cache.
