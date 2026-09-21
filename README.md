# Pregunta a la Constitución · tu primer RAG

Un prototipo que funciona entero en tu ordenador: descarga la Constitución del BOE, la trocea por artículos, la convierte en vectores y responde preguntas citando el artículo en que se basa. No necesita nube, ni GPU, ni claves de API.

```
PREPARACIÓN (una vez)                         CADA PREGUNTA
BOE ─► trocear ─► vectores ─► índice          pregunta ─► vector ─► buscar en el índice
       por artículo (bge-m3)   (datos/)                                  │ 4 artículos más parecidos
                                                                         ▼
                                   Qwen3 4B en Ollama ◄── instrucciones + artículos + pregunta
                                           │
                                           ▼
                                   respuesta que cita el artículo
```

| Archivo | Qué hace |
|---|---|
| `rag.py` | El núcleo: convierte texto en vectores, busca, monta el mensaje y pide la respuesta |
| `preparar.py` | Descarga la Constitución, la trocea y crea el índice (se ejecuta una vez) |
| `preguntar.py` | Preguntas desde la terminal |
| `app.py` | La misma idea en una página web local |

---

## Qué necesitas

- Un ordenador con 8 GB de RAM (mejor 16) y unos 6 GB libres en disco. Funciona sin GPU; con una tarjeta NVIDIA o un Mac con chip Apple va mucho más rápido.
- Python 3.10 o superior (`python --version` para comprobarlo).
- Internet solo para instalar y descargar. Después funciona sin conexión.

---

## Paso 1 · Instala Ollama y los dos modelos (15–30 minutos)

Ollama es el programa que ejecuta los modelos en tu ordenador. Aquí hace dos trabajos: convertir textos en vectores y redactar las respuestas.

1. Descarga Ollama de https://ollama.com e instálalo. En Mac y Windows queda funcionando en segundo plano. En Linux:
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```
2. Descarga el modelo de embeddings, el que convierte texto en vectores (unos 1,2 GB):
   ```bash
   ollama pull bge-m3
   ```
3. Descarga el modelo que redacta las respuestas (unos 2,5 GB):
   ```bash
   ollama pull hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M
   ```
4. Comprueba que están los dos:
   ```bash
   ollama list
   ```
5. Haz una prueba sin RAG y guarda la respuesta, porque la compararás luego:
   ```bash
   ollama run hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M "¿Cuántos diputados tiene el Congreso según la Constitución?"
   ```
   Lo más probable es que diga 350. La Constitución no dice eso: fija un mínimo de 300 y un máximo de 400 (el 350 lo pone una ley). Ahí tienes el problema que resuelve el RAG.

## Paso 2 · Prepara Python (5 minutos)

Desde la carpeta del proyecto:

```bash
python -m venv .venv
```

Activa el entorno. En Mac o Linux:

```bash
source .venv/bin/activate
```

En Windows (PowerShell):

```powershell
.venv\Scripts\Activate.ps1
```

Si PowerShell no te deja activarlo, ejecuta una vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y repite.

Instala las librerías (solo son tres):

```bash
pip install -r requirements.txt
```

## Paso 3 · Crea el índice (2–5 minutos)

```bash
python preparar.py
```

Qué hace, en orden:

1. Descarga el texto consolidado de la API de datos abiertos del BOE y lo guarda en `datos/constitucion.xml`.
2. Se queda con la versión vigente de cada artículo, quita las notas editoriales del BOE y anota en qué Título y Capítulo está cada uno.
3. Hace un fragmento por artículo. Los muy largos, como el 149, los parte en varios trozos y repite en cada uno la frase de entrada («El Estado tiene competencia exclusiva sobre las siguientes materias:»), para que ninguno pierda el sentido.
4. Comprueba que hay 169 artículos y que el 49 ya incluye la reforma de 2024 («personas con discapacidad»).
5. Pide a `bge-m3` un vector por fragmento y los guarda en `datos/indice.npz`.

Deberías ver algo así:

```
1/2 Troceando…
  Artículos encontrados: 169 (deberían ser 169)
  ✓ El artículo 49 incluye la reforma de 2024: el texto está actualizado.
  Fragmentos: …
2/2 Calculando los vectores con «bge-m3»…
  Índice: … vectores de 1024 números → datos/indice.npz
```

Abre `datos/constitucion.txt` y échale un vistazo: es exactamente lo que el sistema puede encontrar. Si algo no está ahí, el modelo nunca lo verá.

**Si la descarga falla**, descárgala a mano y usa ese archivo:

```bash
curl -L -H "Accept: application/xml" "https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/BOE-A-1978-31229/texto" -o constitucion.xml
python preparar.py --xml constitucion.xml
```

En Windows escribe `curl.exe` en lugar de `curl`.

## Paso 4 · Haz preguntas desde la terminal

```bash
python preguntar.py "¿Cuánto tiempo me pueden tener detenido sin ver a un juez?"
```

Primero verás los artículos que ha encontrado el buscador, cada uno con su similitud (cuanto más alta, más parecido al significado de tu pregunta). Fíjate más en cómo se ordenan que en el valor exacto. Después, la respuesta se va escribiendo poco a poco.

Otras formas de usarlo:

```bash
python preguntar.py                                        # conversación: varias preguntas seguidas
python preguntar.py --sin-rag "¿Cuántos diputados hay?"    # el mismo modelo, de memoria
python preguntar.py --ver-contexto "¿Qué es el Defensor del Pueblo?"   # lo que recibe el modelo
python preguntar.py --k 8 "¿Cómo se reforma la Constitución?"         # le pasa 8 fragmentos
```

La primera pregunta tarda más porque Ollama carga el modelo en memoria. Sin GPU, cada respuesta puede tardar entre 20 segundos y un minuto; es normal.

## Paso 5 · La versión web

```bash
python app.py
```

Abre en el navegador la dirección que aparece (normalmente http://127.0.0.1:7860). Tienes una casilla para activar o desactivar el RAG, un control para decidir cuántos artículos lee el modelo y un desplegable con los artículos consultados. Para pararla, pulsa Ctrl+C en la terminal.

---

## Paso 6 · Experimentos para entender de verdad cómo funciona

Aquí es donde se aprende. Apunta los resultados en una tabla sencilla (pregunta, con o sin RAG, qué artículos trajo, si acertó): será el germen del examen con el que medirás tus sistemas.

1. **Con y sin RAG.** Haz estas preguntas de las dos maneras (`--sin-rag`):
   - «¿Cuántos diputados tiene el Congreso?» (con RAG debería decir entre 300 y 400, artículo 68).
   - «¿Cuánto tiempo me pueden tener detenido sin ver a un juez?» (72 horas, artículo 17.2).
   - «¿Qué dice la Constitución sobre las personas con discapacidad?» (artículo 49 reformado en 2024; de memoria, el modelo puede citar la versión antigua).
2. **Pregunta por algo que no está.** «¿A qué edad me puedo jubilar?» o «¿Qué dice la Constitución sobre el himno?». ¿Reconoce que no aparece o se lo inventa? Fíjate en que las similitudes suelen ser más bajas cuando nada encaja bien.
3. **Juega con `--k`.** Prueba 1, 4 y 10. Con 1, si el buscador se equivoca no hay margen; con 10, el modelo lee más ruido y tarda más.
4. **Pon a prueba al buscador.** Pregunta con palabras de la calle, con faltas de ortografía o en otro idioma (bge-m3 es multilingüe, prueba en catalán o en inglés). Mira qué artículos trae.
5. **Mira lo que ve el modelo** con `--ver-contexto`. Eso es todo lo que «sabe» en ese momento.
6. **Cambia el troceado.** Edita `MAX_CARACTERES` en `preparar.py` (prueba 500 y 4000), vuelve a ejecutar `python preparar.py` y repite las mismas preguntas.
7. **Cambia el modelo que redacta.** Si tu equipo puede con uno mayor, descárgalo con Ollama y pruébalo con `--modelo nombre-del-modelo`. Compara calidad y velocidad.

---

## Cómo funciona por dentro

Todo el RAG está en `rag.py` y cabe en unas pocas funciones:

- `vectorizar()` envía textos a Ollama (`/api/embed`) y recibe un vector de 1024 números por texto. Los normaliza para que todos midan lo mismo.
- `buscar()` convierte la pregunta en vector y lo multiplica por la matriz de vectores de todos los fragmentos. Con vectores normalizados, eso es la similitud del coseno. Se queda con los `k` más altos. No hace falta base de datos vectorial: con unos 200 fragmentos, esta multiplicación tarda milisegundos.
- `mensajes_con_contexto()` monta lo que recibe el modelo: unas instrucciones («responde solo con estos artículos, cítalos y, si no está, dilo»), los artículos encontrados y la pregunta.
- `responder()` pide la respuesta a Ollama (`/api/chat`) con temperatura 0, para que sea lo más estable posible, y la va devolviendo a medida que se escribe.

Un detalle importante es la **ventana de contexto** (`VENTANA = 8192` en `rag.py`): la cantidad de texto que el modelo puede leer de una vez. Si el mensaje no cabe, Ollama lo recorta sin avisar y el modelo pierde parte de los artículos o de las instrucciones. Si subes mucho `k`, sube también la ventana (a cambio de más memoria).

---

## Problemas frecuentes

| Mensaje o síntoma | Solución |
|---|---|
| «No puedo conectar con Ollama» | Abre la aplicación de Ollama o ejecuta `ollama serve` en otra terminal |
| «Ollama no tiene el modelo…» | Descárgalo con el `ollama pull` que indica el mensaje, con el nombre exacto |
| «El índice se creó con…» | Cambiaste el modelo de embeddings: vuelve a ejecutar `python preparar.py` |
| La descarga del BOE falla | Usa el comando `curl` del paso 3 y luego `python preparar.py --xml constitucion.xml` |
| Va muy lento | Es normal sin GPU. Baja `--k` a 3, cierra programas pesados o prueba un modelo más pequeño (con menos calidad) |
| Se queda sin memoria | Baja `VENTANA` a 4096 en `rag.py` y usa `--k 3` |
| `UnicodeEncodeError` en Windows | Ejecuta antes `$env:PYTHONUTF8=1` (PowerShell) o `set PYTHONUTF8=1` (cmd) |
| Responde sin citar o en inglés | Pasa a veces con modelos pequeños. Prueba otra vez o con un modelo mayor. Es justo lo que mejora un ajuste fino |

---

## Aviso y fuente

Texto: Agencia Estatal Boletín Oficial del Estado (legislación consolidada, BOE-A-1978-31229). Los textos consolidados son informativos y no tienen valor oficial; para fines jurídicos hay que acudir a la publicación oficial. Este proyecto es un prototipo educativo y no ofrece asesoramiento jurídico.

## Siguientes pasos

1. **Mide.** Convierte tu tabla de experimentos en un examen de 100–150 preguntas con su artículo correcto, y cuenta cuántas veces el buscador trae el artículo bueno, cuántas cita bien el modelo y cuántas reconoce lo que no está.
2. **Mejora la búsqueda**, que es donde más se gana: búsqueda híbrida (palabras clave más vectores), un reordenador (reranker) que revise los candidatos o reformular la pregunta antes de buscar.
3. **Solo entonces** plantéate el ajuste fino, si los números demuestran que el modelo, y no el buscador, es el cuello de botella.
