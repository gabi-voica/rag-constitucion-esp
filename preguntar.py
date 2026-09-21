"""
Haz preguntas a la Constitución desde la terminal.

Uso:
    python preguntar.py                                   # modo conversación
    python preguntar.py "¿Cuánto dura la legislatura?"    # una sola pregunta
    python preguntar.py --sin-rag "¿Cuántos diputados hay?"   # el mismo modelo, de memoria
    python preguntar.py --ver-contexto "…"                # enseña lo que recibe el modelo
    python preguntar.py --k 8 "…"                         # cambia cuántos artículos se usan
"""
import argparse
import sys

import rag


def contestar(pregunta, fragmentos, matriz, args):
    if args.sin_rag:
        print("\n(Sin RAG: el modelo responde de memoria, sin consultar nada)")
        mensajes = rag.mensajes_sin_contexto(pregunta)
    else:
        encontrados = rag.buscar(pregunta, fragmentos, matriz, k=args.k)
        print("\nArtículos encontrados (similitud: 1 = idéntico, 0 = nada que ver):")
        for fragmento, similitud in encontrados:
            print(f"  {similitud:.3f}  {fragmento['etiqueta']}")
        mensajes = rag.mensajes_con_contexto(pregunta, [f for f, _ in encontrados])
        if args.ver_contexto:
            print("\n----- Esto es exactamente lo que recibe el modelo -----")
            print(f"[instrucciones] {mensajes[0]['content']}\n")
            print(mensajes[1]["content"])
            print("--------------------------------------------------------")

    print("\nRespuesta:\n")
    texto, mostrado = "", 0
    for trozo in rag.responder(mensajes, modelo=args.modelo):
        texto += trozo
        visible = rag.texto_visible(texto)
        print(visible[mostrado:], end="", flush=True)
        mostrado = len(visible)
    print("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pregunta", nargs="*", help="la pregunta (si no la pones, entra en modo conversación)")
    parser.add_argument("--k", type=int, default=rag.K, help="cuántos fragmentos se pasan al modelo")
    parser.add_argument("--modelo", default=rag.MODELO_LLM, help="modelo de Ollama que redacta")
    parser.add_argument("--sin-rag", action="store_true", help="pregunta sin buscar artículos, para comparar")
    parser.add_argument("--ver-contexto", action="store_true", help="muestra el texto completo que recibe el modelo")
    args = parser.parse_args()

    fragmentos, matriz = (None, None) if args.sin_rag else rag.cargar_indice()
    try:
        if args.pregunta:
            contestar(" ".join(args.pregunta), fragmentos, matriz, args)
            return
        print("Pregunta lo que quieras sobre la Constitución. Pulsa Enter sin escribir nada para salir.")
        while True:
            pregunta = input("\nPregunta: ").strip()
            if not pregunta:
                break
            contestar(pregunta, fragmentos, matriz, args)
    except rag.ErrorOllama as e:
        sys.exit(f"\n✗ {e}")
    except (KeyboardInterrupt, EOFError):
        print()


if __name__ == "__main__":
    main()
