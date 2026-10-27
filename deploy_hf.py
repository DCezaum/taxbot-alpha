# -*- coding: utf-8 -*-
"""
Publica o TaxBot no Hugging Face Space (SDK Streamlit nativo).

Pré-requisitos:
    pip install huggingface_hub
    hf auth login            # token com permissão de escrita
    Chave do Gemini em: Space → Settings → Variables and secrets → New secret → GEMINI_API_KEY

Uso:
    python deploy_hf.py
"""
import shutil
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

SPACE = "DCezaum/TaxBot_Alpha"
RAIZ = Path(__file__).resolve().parent
ARQUIVOS = ["app.py", "agente.py", "calculadoras.py", "ingest.py", "requirements.txt", ".streamlit/config.toml"]
PASTAS = ["indice"]
# Arquivos da versão anterior (OpenAI + Chroma) que devem sumir do Space
APAGAR = ["chroma_taxbot/*", "chroma_taxbot/**", "pergunte_2.py", "runtime.txt"]

CABECALHO = """---
title: TaxBot - Alpha
emoji: 💬
colorFrom: yellow
colorTo: gray
sdk: streamlit
sdk_version: 1.51.0
python_version: "3.12"
app_file: app.py
pinned: false
short_description: Agente de IA da reforma do Imposto de Renda (Lei 15.270)
---

"""


def main() -> None:
    if not (RAIZ / "indice" / "vetores.npy").exists():
        raise SystemExit("Índice não encontrado. Rode `python ingest.py` antes do deploy.")

    with tempfile.TemporaryDirectory() as tmp:
        destino = Path(tmp)
        for arq in ARQUIVOS:
            (destino / arq).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(RAIZ / arq, destino / arq)
        for pasta in PASTAS:
            shutil.copytree(RAIZ / pasta, destino / pasta)
        readme = (RAIZ / "README.md").read_text(encoding="utf-8")
        (destino / "README.md").write_text(CABECALHO + readme, encoding="utf-8")

        HfApi().upload_folder(
            repo_id=SPACE,
            repo_type="space",
            folder_path=destino,
            delete_patterns=APAGAR,
            commit_message="TaxBot: Lei 15.270, Gemini com function calling e memória",
        )
    print(f"Publicado: https://huggingface.co/spaces/{SPACE}")


if __name__ == "__main__":
    main()
