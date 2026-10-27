# -*- coding: utf-8 -*-
"""
Agente do TaxBot: busca semântica nos documentos (RAG) + Gemini com function calling nativo.

O índice vetorial fica em indice/ (gerado por ingest.py) e é carregado em memória com numpy:
são poucas centenas de trechos, então não é preciso um banco vetorial.
"""
import argparse
import difflib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from calculadoras import FERRAMENTAS

FERRAMENTAS_POR_NOME = {f.__name__: f for f in FERRAMENTAS}

load_dotenv()

# Os aliases "-latest" acompanham a versão mais nova; o Flash-Lite é mais rápido e tem cota gratuita maior.
MODELO = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
# Usados em sequência quando o modelo anterior está sobrecarregado, lento, indisponível ou sem cota.
MODELOS_RESERVA = ["gemini-flash-latest"]
ERROS_TENTAR_PROXIMO = {404, 429, 500, 503, 504}
TIMEOUT_MS = 60_000
MODELO_EMBEDDING = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
DIMENSAO_EMBEDDING = 768
INDICE_DIR = Path(__file__).resolve().parent / "indice"
MAX_MENSAGENS_HISTORICO = 10   # últimas 5 trocas pergunta/resposta
MAX_CHAMADAS_FERRAMENTA = 6

SYSTEM_PROMPT = """
Você é o TaxBot, assistente especializado na reforma do Imposto de Renda da pessoa física no Brasil,
instituída pela Lei 15.270/2025 (originada do PL 1.087/2025), vigente a partir de 1º/01/2026.

Regras:
1. Responda sempre em português do Brasil, em Markdown, de forma clara e didática.
2. Para perguntas conceituais, baseie-se nos TRECHOS RECUPERADOS enviados junto com a pergunta.
   Se os trechos não cobrirem o assunto, diga isso com honestidade em vez de inventar.
3. Para QUALQUER cálculo de imposto, use as ferramentas disponíveis. Nunca faça contas de imposto de cabeça.
   Você pode chamar várias ferramentas em sequência (ex.: retenção mensal de dividendos e depois o IRPFM anual).
4. Se faltar um dado essencial para o cálculo (ex.: valor do rendimento), pergunte ao usuário.
   Dados opcionais (INSS, dependentes, deduções) podem ser assumidos como zero, mas diga que assumiu isso.
5. Ao apresentar um cálculo, mostre os passos principais (base, imposto pela tabela, redução, resultado).
6. Use o histórico da conversa para entender perguntas de acompanhamento ("e se fossem 2 dependentes?").
7. Não use LaTeX nem fórmulas entre cifrões; escreva contas em texto simples (ex.: 30% + 10% = 40%)
   e valores sempre como "R$ 1.234,56".
8. Atenção a duas regras que costumam ser confundidas: a retenção de 10% sobre dividendos incide sobre
   o valor TOTAL pago pela empresa no mês (não só sobre o que excede R$ 50 mil); e a redução da
   Lei 15.270 é um desconto sobre o imposto da tabela progressiva, não o imposto em si.
9. Apresente SOMENTE os valores devolvidos pelas ferramentas. Nunca diga que um redutor, dedução ou
   abatimento foi aplicado se a ferramenta devolveu R$ 0,00 para ele.
10. Lembre, quando pertinente, que a resposta é informativa e não substitui um contador ou advogado.
""".strip()


def criar_client(api_key: Optional[str] = None) -> genai.Client:
    api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Defina GEMINI_API_KEY (no .env ou nos secrets do Streamlit).")
    # Uma única nova tentativa por chamada: em caso de falha é melhor passar ao modelo reserva
    # do que deixar o usuário esperando vários minutos.
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=2)),
    )


# =====================  ÍNDICE VETORIAL  =====================
def embed(client: genai.Client, textos: List[str], task_type: str) -> np.ndarray:
    resp = client.models.embed_content(
        model=MODELO_EMBEDDING,
        contents=textos,
        config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=DIMENSAO_EMBEDDING),
    )
    m = np.array([e.values for e in resp.embeddings], dtype=np.float32)
    return m / np.linalg.norm(m, axis=1, keepdims=True)


class Indice:
    def __init__(self, trechos: List[Dict], vetores: np.ndarray):
        self.trechos = trechos
        self.vetores = vetores

    @classmethod
    def carregar(cls, pasta: Path = INDICE_DIR) -> "Indice":
        trechos_path, vetores_path = pasta / "trechos.json", pasta / "vetores.npy"
        if not trechos_path.exists() or not vetores_path.exists():
            raise FileNotFoundError(
                f"Índice não encontrado em {pasta}. Rode `python ingest.py` para gerá-lo."
            )
        trechos = json.loads(trechos_path.read_text(encoding="utf-8"))
        return cls(trechos, np.load(vetores_path))

    def buscar(self, client: genai.Client, consulta: str, k: int = 6) -> List[Dict]:
        q = embed(client, [consulta], "RETRIEVAL_QUERY")[0]
        scores = self.vetores @ q
        top = np.argsort(-scores)[:k]
        return [{**self.trechos[i], "score": float(scores[i])} for i in top]


# =====================  AGENTE  =====================
@dataclass
class Resposta:
    texto: str
    fontes: List[Dict] = field(default_factory=list)
    ferramentas: List[Dict] = field(default_factory=list)
    modelo: str = ""


class LimiteDeUsoError(RuntimeError):
    """Cota gratuita do Gemini esgotada (HTTP 429)."""


def _formatar_trechos(trechos: List[Dict]) -> str:
    return "\n\n".join(
        f"[{i}] Fonte: {t['fonte']} (p. {t['pagina']})\n{t['texto']}"
        for i, t in enumerate(trechos, start=1)
    )


def _historico_para_contents(historico: List[Dict]) -> List[types.Content]:
    contents = []
    for m in historico[-MAX_MENSAGENS_HISTORICO:]:
        role = "user" if m["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))
    return contents


class TaxBot:
    def __init__(self, api_key: Optional[str] = None, indice: Optional[Indice] = None):
        self.client = criar_client(api_key)
        self.indice = indice or Indice.carregar()
        # As ferramentas são executadas por nós (e não pelo SDK) para tolerar nomes inventados pelo
        # modelo (ex.: "calcular_irpf_mensal") e argumentos inválidos, devolvendo o erro ao modelo.
        self.config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=FERRAMENTAS,
            temperature=0.2,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    @staticmethod
    def _executar_ferramenta(chamada: types.FunctionCall, executadas: List[Dict]) -> types.Part:
        nome = chamada.name
        if nome not in FERRAMENTAS_POR_NOME:
            parecidos = difflib.get_close_matches(nome, FERRAMENTAS_POR_NOME, n=1, cutoff=0.8)
            nome = parecidos[0] if parecidos else nome
        args = dict(chamada.args or {})

        funcao = FERRAMENTAS_POR_NOME.get(nome)
        if funcao is None:
            resultado = {"erro": f"A ferramenta '{chamada.name}' não existe. Use uma destas: "
                                 f"{', '.join(FERRAMENTAS_POR_NOME)}."}
        else:
            try:
                resultado = funcao(**args)
                executadas.append({"nome": nome, "argumentos": args})
            except Exception as e:  # noqa: BLE001 — o modelo recebe o erro e pode corrigir os argumentos
                resultado = {"erro": f"Argumentos inválidos para {nome}: {e}"}
        return types.Part.from_function_response(name=chamada.name, response={"result": resultado})

    def _conversar(self, chat, mensagem: str, executadas: List[Dict]) -> types.GenerateContentResponse:
        resp = chat.send_message(mensagem)
        for _ in range(MAX_CHAMADAS_FERRAMENTA):
            if not resp.function_calls:
                break
            resp = chat.send_message([self._executar_ferramenta(fc, executadas) for fc in resp.function_calls])
        return resp

    def _gerar(self, historico: List[types.Content], mensagem: str):
        """Devolve (resposta, ferramentas executadas com sucesso)."""
        ultimo_erro = None
        for modelo in dict.fromkeys([MODELO, *MODELOS_RESERVA]):
            chat = self.client.chats.create(model=modelo, config=self.config, history=historico)
            executadas: List[Dict] = []
            try:
                return self._conversar(chat, mensagem, executadas), executadas
            except errors.APIError as e:
                if e.code not in ERROS_TENTAR_PROXIMO:
                    raise
                ultimo_erro = e
        if ultimo_erro.code == 429:
            raise LimiteDeUsoError(
                "O limite gratuito do Gemini foi atingido. Tente novamente em alguns minutos."
            ) from ultimo_erro
        raise LimiteDeUsoError(
            "Os servidores do Gemini estão sobrecarregados agora. Tente novamente em alguns minutos."
        ) from ultimo_erro

    def responder(self, pergunta: str, historico: Optional[List[Dict]] = None, k: int = 6) -> Resposta:
        """historico: mensagens anteriores [{"role": "user"|"assistant", "content": str}], sem a pergunta atual."""
        historico = historico or []
        try:
            # Em perguntas de acompanhamento ("e com 2 dependentes?") a pergunta anterior melhora a busca.
            anteriores = [m["content"] for m in historico if m["role"] == "user"][-1:]
            trechos = self.indice.buscar(self.client, "\n".join(anteriores + [pergunta]), k=k)

        except errors.APIError as e:
            if e.code == 429:
                raise LimiteDeUsoError(
                    "O limite gratuito do Gemini foi atingido. Tente novamente em alguns minutos."
                ) from e
            raise

        mensagem = (
            f"TRECHOS RECUPERADOS DOS DOCUMENTOS:\n{_formatar_trechos(trechos)}\n\n"
            f"PERGUNTA DO USUÁRIO:\n{pergunta}"
        )
        resp, ferramentas = self._gerar(_historico_para_contents(historico), mensagem)
        texto = resp.text or "Não consegui gerar uma resposta. Pode reformular a pergunta?"
        return Resposta(texto=texto, fontes=trechos, ferramentas=ferramentas, modelo=resp.model_version or "")


# =====================  CLI (testes locais)  =====================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TaxBot — agente da reforma do IR")
    parser.add_argument("pergunta")
    parser.add_argument("--k", type=int, default=6)
    args = parser.parse_args()

    r = TaxBot().responder(args.pergunta, k=args.k)
    print(r.texto)
    if r.ferramentas:
        print("\nFerramentas usadas:", json.dumps(r.ferramentas, ensure_ascii=False, indent=2))
