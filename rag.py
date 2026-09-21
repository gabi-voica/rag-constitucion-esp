"""
Núcleo del RAG: busca los artículos más parecidos a una pregunta y pide al
modelo que responda leyéndolos. Lo usan preguntar.py y app.py.
"""
import json
import os
import re
from pathlib import Path

import numpy as np
import requests

# ---------------------------------------------------------------------------
# Configuración: todo lo que puedes cambiar está aquí
# ---------------------------------------------------------------------------
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODELO_EMBEDDINGS = "bge-m3"
MODELO_LLM = "qwen3:4b-instruct"
K = 4                 # cuántos fragmentos se le pasan al modelo en cada pregunta
VENTANA = 8192        # tokens que el modelo puede leer de una vez (ver README)

CARPETA_DATOS = Path(__file__).resolve().parent / "datos"
RUTA_FRAGMENTOS = CARPETA_DATOS / "fragmentos.jsonl"
RUTA_INDICE = CARPETA_DATOS / "indice.npz"

SISTEMA = (
    "Eres un asistente experto en la Constitución Española. Responde en español, "
    "de forma clara y breve, usando únicamente la información de los artículos "
    "proporcionados. Cita siempre el artículo en el que te basas (por ejemplo, "
    "«artículo 14»). Si los artículos no contienen la respuesta, dilo claramente "
    "y no inventes nada."
)

SISTEMA_SIN_RAG = (
    "Eres un asistente experto en la Constitución Española. Responde en español, "
    "de forma clara y breve, y cita el artículo en el que te basas (por ejemplo, "
    "«artículo 14»). Si la Constitución no regula lo que se pregunta, dilo claramente."
)


class ErrorOllama(RuntimeError):
    pass


def _llamar(ruta, datos, stream=False):
    try:
        r = requests.post(f"{OLLAMA_URL}{ruta}", json=datos, stream=stream, timeout=900)
    except requests.ConnectionError:
        raise ErrorOllama(
            f"No puedo conectar con Ollama en {OLLAMA_URL}. Abre la aplicación de Ollama "
            "o ejecuta «ollama serve» en otra terminal."
        ) from None
    if r.status_code == 404:
        raise ErrorOllama(
            f"Ollama no tiene el modelo «{datos.get('model')}». Descárgalo con: "
            f"ollama pull {datos.get('model')}"
        )
    if r.status_code != 200:
        raise ErrorOllama(f"Ollama respondió con error {r.status_code}: {r.text[:300]}")
    return r


# ---------------------------------------------------------------------------
# 1. Embeddings: texto → vector
# ---------------------------------------------------------------------------

def vectorizar(textos, lote=16, avisar=None):
    """Convierte una lista de textos en una matriz de vectores normalizados."""
    vectores = []
    for i in range(0, len(textos), lote):
        r = _llamar("/api/embed", {"model": MODELO_EMBEDDINGS, "input": textos[i:i + lote]})
        vectores.extend(r.json()["embeddings"])
        if avisar:
            avisar(min(i + lote, len(textos)), len(textos))
    matriz = np.asarray(vectores, dtype=np.float32)
    matriz /= np.linalg.norm(matriz, axis=1, keepdims=True) + 1e-12
    return matriz


def texto_para_indexar(fragmento):
    """Lo que 've' el buscador: etiqueta, ubicación en la Constitución y texto."""
    cabecera = fragmento["etiqueta"]
    if fragmento.get("ruta"):
        cabecera += f" ({fragmento['ruta']})"
    return f"{cabecera}\n{fragmento['texto']}"


# ---------------------------------------------------------------------------
# 2. Búsqueda
# ---------------------------------------------------------------------------

def cargar_indice():
    if not RUTA_INDICE.exists() or not RUTA_FRAGMENTOS.exists():
        raise SystemExit("Todavía no hay índice. Ejecuta antes: python preparar.py")
    fragmentos = [json.loads(l) for l in RUTA_FRAGMENTOS.read_text(encoding="utf-8").splitlines() if l.strip()]
    guardado = np.load(RUTA_INDICE)
    if str(guardado["modelo"]) != MODELO_EMBEDDINGS:
        raise SystemExit(
            f"El índice se creó con «{guardado['modelo']}» y ahora usas «{MODELO_EMBEDDINGS}». "
            "Vuelve a ejecutar: python preparar.py"
        )
    return fragmentos, guardado["matriz"]


def buscar(pregunta, fragmentos, matriz, k=K):
    """Devuelve [(fragmento, similitud), ...] con los k fragmentos más parecidos."""
    vector = vectorizar([pregunta])[0]
    similitudes = matriz @ vector          # similitud del coseno (vectores normalizados)
    mejores = np.argsort(-similitudes)[:k]
    return [(fragmentos[int(i)], float(similitudes[i])) for i in mejores]


# ---------------------------------------------------------------------------
# 3. Construcción del mensaje para el modelo
# ---------------------------------------------------------------------------

def formatear_contexto(fragmentos):
    return "\n\n".join(f"[{f['etiqueta']}]\n{f['texto']}" for f in fragmentos)


def mensajes_con_contexto(pregunta, fragmentos):
    return [
        {"role": "system", "content": SISTEMA},
        {"role": "user", "content": f"Artículos:\n\n{formatear_contexto(fragmentos)}\n\nPregunta: {pregunta}"},
    ]


def mensajes_sin_contexto(pregunta):
    return [
        {"role": "system", "content": SISTEMA_SIN_RAG},
        {"role": "user", "content": pregunta},
    ]


# ---------------------------------------------------------------------------
# 4. Generación de la respuesta
# ---------------------------------------------------------------------------

def responder(mensajes, modelo=MODELO_LLM):
    """Va devolviendo trozos de la respuesta a medida que el modelo la escribe."""
    r = _llamar("/api/chat", {
        "model": modelo,
        "messages": mensajes,
        "stream": True,
        "options": {"temperature": 0, "num_ctx": VENTANA},
    }, stream=True)
    for linea in r.iter_lines():
        if not linea:
            continue
        dato = json.loads(linea)
        if "error" in dato:
            raise ErrorOllama(dato["error"])
        trozo = dato.get("message", {}).get("content", "")
        if trozo:
            yield trozo
        if dato.get("done"):
            break


def texto_visible(texto):
    """Oculta el razonamiento <think>…</think> que escriben algunos modelos."""
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL)
    if "<think>" in texto:
        texto = texto.split("<think>")[0]
    return texto.lstrip()
