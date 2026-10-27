# -*- coding: utf-8 -*-
"""
Gera o índice vetorial do TaxBot (indice/trechos.json + indice/vetores.npy) com embeddings do Gemini.

Uso:
    python ingest.py                                # lê ../Memória TaxBot Alpha e ./documentos
    python ingest.py "C:/caminho/para/pdfs" outra/pasta

Aceita .pdf, .md e .txt. Rode de novo sempre que adicionar ou trocar documentos.
"""
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

import numpy as np
from google.genai import errors
from pypdf import PdfReader

from agente import INDICE_DIR, criar_client, embed

RAIZ = Path(__file__).resolve().parent
PASTAS_PADRAO = [RAIZ.parent / "Memória TaxBot Alpha", RAIZ / "documentos"]
TAMANHO_TRECHO = 1500
SOBREPOSICAO = 200
LOTE = 50


def dividir(texto: str) -> List[str]:
    """Divide em trechos de ~TAMANHO_TRECHO caracteres, cortando preferencialmente em fim de parágrafo/frase."""
    texto = " ".join(texto.split())
    trechos, inicio = [], 0
    while inicio < len(texto):
        fim = min(inicio + TAMANHO_TRECHO, len(texto))
        if fim < len(texto):
            corte = max(texto.rfind(". ", inicio, fim), texto.rfind("; ", inicio, fim))
            if corte > inicio + TAMANHO_TRECHO // 2:
                fim = corte + 1
        trechos.append(texto[inicio:fim].strip())
        if fim >= len(texto):
            break
        inicio = fim - SOBREPOSICAO
    return [t for t in trechos if len(t) > 80]


def ler_documento(caminho: Path) -> List[Dict]:
    if caminho.suffix.lower() == ".pdf":
        paginas = [(i + 1, p.extract_text() or "") for i, p in enumerate(PdfReader(caminho).pages)]
    else:
        paginas = [(1, caminho.read_text(encoding="utf-8"))]
    return [
        {"fonte": caminho.name, "pagina": n, "texto": t}
        for n, texto in paginas
        for t in dividir(texto)
    ]


def embed_com_retry(client, textos: List[str]) -> np.ndarray:
    for tentativa in range(5):
        try:
            return embed(client, textos, "RETRIEVAL_DOCUMENT")
        except errors.APIError as e:
            if e.code != 429 or tentativa == 4:
                raise
            print("  limite de requisições atingido, aguardando 60 s...")
            time.sleep(60)


def main(pastas: List[Path]) -> None:
    arquivos = sorted(
        a for p in pastas if p.exists() for a in p.iterdir()
        if a.suffix.lower() in {".pdf", ".md", ".txt"}
    )
    if not arquivos:
        sys.exit(f"Nenhum documento encontrado em: {', '.join(map(str, pastas))}")

    trechos = []
    for a in arquivos:
        doc = ler_documento(a)
        print(f"{len(doc):4d} trechos  {a.name}")
        trechos.extend(doc)

    client = criar_client()

    vetores = []
    for i in range(0, len(trechos), LOTE):
        lote = trechos[i:i + LOTE]
        vetores.append(embed_com_retry(client, [t["texto"] for t in lote]))
        print(f"  embeddings: {min(i + LOTE, len(trechos))}/{len(trechos)}")

    INDICE_DIR.mkdir(exist_ok=True)
    (INDICE_DIR / "trechos.json").write_text(json.dumps(trechos, ensure_ascii=False, indent=1), encoding="utf-8")
    np.save(INDICE_DIR / "vetores.npy", np.vstack(vetores))
    print(f"\nÍndice salvo em {INDICE_DIR} ({len(trechos)} trechos de {len(arquivos)} documentos).")


if __name__ == "__main__":
    main([Path(p) for p in sys.argv[1:]] or PASTAS_PADRAO)
