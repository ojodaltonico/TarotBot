# Activos visuales del mazo

`manifest.json` contiene el mapeo inmutable 78/78 entre `card_id` y la colección
[Rider-Waite-Smith tarot deck (Geldard)](https://commons.wikimedia.org/wiki/Category:Rider-Waite-Smith_tarot_deck_(Geldard))
de Wikimedia Commons. Los archivos fueron identificados como obra de **Pamela Colman Smith**, de **1910**, y sus fichas individuales declaran dominio público / **Public Domain Mark 1.0**.

- `cards/<card_id>.webp`: versión runtime normalizada a 700–900 px de alto, con proporción original conservada.
- `table/table_v1.png`: fondo cenital original creado para TarotBot; no incorpora objetos, texto ni símbolos de terceros.
- `manifest.json`: fuente, colección, autoría, año, estado de licencia y el identificador de archivo de Commons para cada carta.

Para obtener o verificar el mazo:

```powershell
backend\.venv\Scripts\python.exe scripts\download_tarot_images.py
backend\.venv\Scripts\python.exe scripts\download_tarot_images.py --validate
```

La descarga usa las miniaturas oficiales de Commons y las convierte localmente a WebP; no almacena los PNG originales de ~11–14 MB. No sobrescribe archivos existentes salvo con `--force`.

Si Commons aplica temporalmente su política anti-robots, el modo explícito `--source tarot-json --force` obtiene en una única descarga el conjunto abierto de 78 scans de [metabismuth/tarot-json](https://github.com/metabismuth/tarot-json), que documenta el mismo RWS como dominio público en EE. UU. Se usa para distribución técnica uniforme; el manifest conserva por carta la ficha de Commons que verifica autoría, año y licencia de la obra original.

`backend/app/tarot/rendering.py` compone exclusivamente una lectura ya persistida. Su versión actual es `table_v2`, guarda el caché regenerable en `data/rendered-readings/reading_<id>.jpg` (ignorado por Git) y usa la semilla derivada de `reading_id` y `audit_metadata`; la misma lectura conserva el mismo layout.

Vista local sin IA:

```powershell
backend\.venv\Scripts\python.exe scripts\render_tarot_reading.py --spread relationship_three --seed 123
```

El resultado tiene contrato de transporte futuro `{ "type": "image", "path": "...", "caption": "..." }`; este bloque no envía nada a WhatsApp.
