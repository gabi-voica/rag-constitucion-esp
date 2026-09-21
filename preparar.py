"""
PREPARACIÓN (se hace una vez): descarga la Constitución del BOE, la trocea
por artículos y crea el índice de vectores.

Uso:
    python preparar.py                     # descarga del BOE y crea el índice
    python preparar.py --xml mi_copia.xml  # usa un XML que ya descargaste

Genera en la carpeta datos/:
    constitucion.xml    lo que devuelve el BOE
    constitucion.txt    versión legible, para que la revises
    fragmentos.jsonl    los trozos (uno por artículo; los largos, en varias partes)
    indice.npz          un vector por fragmento
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import requests

import rag

URL_BOE = ("https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/"
           "BOE-A-1978-31229/texto")
MAX_CARACTERES = 1500   # tamaño máximo aproximado de cada fragmento
TIPOS_CON_TEXTO = {"precepto", "preambulo", "parte_dispositiva", "parte_final"}


def descargar(destino):
    print(f"Descargando la Constitución del BOE…")
    r = requests.get(URL_BOE, timeout=120, headers={
        "Accept": "application/xml",
        "User-Agent": "rag-constitucion/1.0 (proyecto educativo)",
    })
    r.raise_for_status()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(r.content)
    print(f"  Guardada en {destino} ({len(r.content) / 1024:.0f} KB)")


# --- Lectura del XML del BOE ------------------------------------------------

def limpiar(texto):
    return re.sub(r"\s+", " ", texto or "").strip()


def version_vigente(bloque):
    """Cada artículo guarda todas sus versiones; nos quedamos con la más reciente."""
    versiones = bloque.findall("version")
    if not versiones:
        return None
    return max(versiones, key=lambda v: (v.get("fecha_publicacion", ""), v.get("fecha_vigencia", "")))


def parrafos_de(version):
    parrafos = []
    for hijo in version:
        if hijo.tag == "blockquote":          # notas del BOE sobre reformas
            continue
        if hijo.tag == "p":
            if hijo.get("class", "") == "articulo":   # «Artículo 14.» ya va en la etiqueta
                continue
            texto = limpiar("".join(hijo.itertext()))
            if texto:
                parrafos.append(texto)
        elif hijo.tag == "table":
            for fila in hijo.iter("tr"):
                celdas = [limpiar("".join(c.itertext())) for c in fila if c.tag in ("td", "th")]
                if any(celdas):
                    parrafos.append(" | ".join(celdas))
    return parrafos


def actualizar_ruta(ruta, encabezado):
    """Lleva la cuenta de en qué Título / Capítulo / Sección estamos."""
    if not encabezado:
        return
    primera = encabezado.split()[0].upper()
    if primera in ("CAPÍTULO", "CAPITULO"):
        ruta.update(capitulo=encabezado, seccion="")
    elif primera in ("SECCIÓN", "SECCION"):
        ruta.update(seccion=encabezado)
    else:
        ruta.update(titulo=encabezado, capitulo="", seccion="")


def leer_xml(ruta_xml):
    raiz = ET.parse(ruta_xml).getroot()
    codigo = (raiz.findtext("status/code") or "200").strip()
    if codigo != "200":
        sys.exit(f"El BOE respondió con error {codigo}: {raiz.findtext('status/text')}")
    texto = raiz.find(".//texto")
    if texto is None:
        sys.exit("El XML no tiene el nodo <texto>. ¿Es la respuesta de la API /texto del BOE?")

    bloques, ruta = [], {"titulo": "", "capitulo": "", "seccion": ""}
    for bloque in texto.findall("bloque"):
        version = version_vigente(bloque)
        if version is None:
            continue
        parrafos = parrafos_de(version)
        if bloque.get("tipo") == "encabezado":
            actualizar_ruta(ruta, ". ".join(parrafos))
            continue
        if bloque.get("tipo") not in TIPOS_CON_TEXTO or not parrafos:
            continue
        titulo = limpiar(bloque.get("titulo", ""))
        if "preambulo" in titulo.lower() or "preámbulo" in titulo.lower():
            titulo = "Preámbulo"
        m = re.match(r"art[íi]culo\s+(\d+)", titulo, re.IGNORECASE)
        clave = m.group(1) if m else titulo.lower()
        es_articulo = bool(m)
        bloques.append({
            "id": bloque.get("id", ""),
            "etiqueta": titulo or bloque.get("id", ""),
            "articulo": clave,
            "ruta": " > ".join(p for p in ruta.values() if p) if es_articulo else "",
            "parrafos": parrafos,
        })
    return bloques


# --- Troceado ----------------------------------------------------------------

def trocear(bloque):
    """Un fragmento por artículo; los muy largos (como el 149) se parten por
    párrafos, repitiendo la frase de entrada en cada parte para no perder el sentido."""
    parrafos = bloque["parrafos"]
    if len("\n".join(parrafos)) <= MAX_CARACTERES:
        grupos = [parrafos]
    else:
        grupos, grupo, longitud = [], [], 0
        for p in parrafos:
            if grupo and longitud + len(p) > MAX_CARACTERES:
                grupos.append(grupo)
                grupo, longitud = [], 0
            grupo.append(p)
            longitud += len(p) + 1
        grupos.append(grupo)

    entradilla = parrafos[0] if len(parrafos[0]) < 300 else None
    fragmentos = []
    for n, grupo in enumerate(grupos, start=1):
        if n > 1 and entradilla:
            grupo = [entradilla, "[…]"] + grupo
        etiqueta = bloque["etiqueta"] + (f" (parte {n} de {len(grupos)})" if len(grupos) > 1 else "")
        fragmentos.append({
            "id": bloque["id"] if len(grupos) == 1 else f"{bloque['id']}-{n}",
            "articulo": bloque["articulo"],
            "etiqueta": etiqueta,
            "ruta": bloque["ruta"],
            "texto": "\n".join(grupo),
        })
    return fragmentos


def comprobar(bloques):
    articulos = {int(b["articulo"]) for b in bloques if b["articulo"].isdigit()}
    print(f"  Artículos encontrados: {len(articulos)} (deberían ser 169)")
    if len(articulos) != 169:
        faltan = sorted(set(range(1, 170)) - articulos)
        print(f"  ⚠ Faltan artículos: {faltan[:20]}{' …' if len(faltan) > 20 else ''}")
    art49 = next((b for b in bloques if b["articulo"] == "49"), None)
    if art49:
        texto = " ".join(art49["parrafos"]).lower()
        if "discapacidad" in texto:
            print("  ✓ El artículo 49 incluye la reforma de 2024: el texto está actualizado.")
        elif "disminuidos" in texto:
            print("  ⚠ El artículo 49 dice «disminuidos»: es una versión anterior a 2024.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--xml", help="usar un XML ya descargado en vez de descargarlo")
    args = parser.parse_args()

    rag.CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
    ruta_xml = Path(args.xml) if args.xml else rag.CARPETA_DATOS / "constitucion.xml"
    if not args.xml:
        try:
            descargar(ruta_xml)
        except Exception as e:
            print(f"\nNo he podido descargarla: {e}")
            print("Descárgala a mano con este comando y vuelve a ejecutar con --xml constitucion.xml:\n")
            print(f'  curl -L -H "Accept: application/xml" "{URL_BOE}" -o constitucion.xml\n')
            sys.exit(1)

    print("\n1/2 Troceando…")
    bloques = leer_xml(ruta_xml)
    fragmentos = [f for b in bloques for f in trocear(b)]
    comprobar(bloques)
    print(f"  Fragmentos: {len(fragmentos)}")
    with rag.RUTA_FRAGMENTOS.open("w", encoding="utf-8") as f:
        for frag in fragmentos:
            f.write(json.dumps(frag, ensure_ascii=False) + "\n")
    with (rag.CARPETA_DATOS / "constitucion.txt").open("w", encoding="utf-8") as f:
        for frag in fragmentos:
            f.write(f"=== {frag['etiqueta']}   [{frag['ruta']}]\n{frag['texto']}\n\n")

    print(f"\n2/2 Calculando los vectores con «{rag.MODELO_EMBEDDINGS}»…")
    try:
        matriz = rag.vectorizar(
            [rag.texto_para_indexar(f) for f in fragmentos],
            avisar=lambda hechos, total: print(f"  {hechos}/{total}", end="\r", flush=True),
        )
    except rag.ErrorOllama as e:
        sys.exit(f"\n✗ {e}")
    np.savez(rag.RUTA_INDICE, matriz=matriz, modelo=np.array(rag.MODELO_EMBEDDINGS))
    print(f"\n  Índice: {matriz.shape[0]} vectores de {matriz.shape[1]} números → {rag.RUTA_INDICE}")
    print("\nListo. Ahora prueba:  python preguntar.py")


if __name__ == "__main__":
    main()
