# -*- coding: utf-8 -*-
import os, argparse, json, re
from functools import lru_cache
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Optional

from dotenv import load_dotenv
load_dotenv()

# ======================================================================================
# CONFIG VETOR (Mantendo a estrutura original do pergunte_2.py)
# ======================================================================================
from pathlib import Path

# ================= CONFIG VETOR =================
REPO_ROOT   = Path(__file__).resolve().parent
PERSIST_DIR = str((REPO_ROOT / "chroma_taxbot").resolve())
PERSIST_DIR = os.getenv("CHROMA_DIR", PERSIST_DIR)  # opcional, mesmo override do ingestor
COLLECTION  = "taxbot_mem"


from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document

# Embeddings ANTES do loader
emb = OpenAIEmbeddings(model="text-embedding-3-small")
llm = ChatOpenAI(model="gpt-5-mini") # Usaremos o gpt-5 como modelo padrão

# Cache global do Chroma
_VDB = None
def load_vectordb() -> Chroma:
    global _VDB
    if _VDB is None:
        _VDB = Chroma(
            persist_directory=PERSIST_DIR,
            collection_name=COLLECTION,
            embedding_function=emb,
        )
    return _VDB

# =========================
# FORMATADOR EM REAIS
# =========================

def brl(x: Decimal) -> str:
    q = Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s = f"{q:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


# =========================
# IR SOBRE SALÁRIOS / ALUGUÉIS
# =========================

def _irrf_mensal_val(gross: Decimal) -> Decimal:
    """
    IRRF mensal sem considerar NENHUMA dedução (sem INSS, sem dependentes, etc.).
    Regras simplificadas, inspiradas no PL 1.087/2025:
      • Até 5.000 → isento.
      • De 5.001 a 7.350 → faixa de neutralização (fórmula oficial).
      • Acima de 7.350 → aplica 27,5% sobre o valor total do mês.
    Esta função é puramente numérica, para ser usada internamente.
    """
    gross = Decimal(str(gross))

    # Até R$ 5.000 → isento
    if gross <= Decimal("5000.00"):
        return Decimal("0.00")

    # Faixa de neutralização — fórmula do PL (faixa 5.001–7.350)
    if gross <= Decimal("7350.00"):
        neutralizador = Decimal("978.62") - (Decimal("0.133145") * gross)
        ir = max(Decimal("0.00"), neutralizador)
        return ir

    # Acima de 7.350 → alíquota máxima de 27,5%
    return gross * Decimal("0.275")


def irrf_mensal_sem_deducoes(gross: Decimal) -> Dict[str, str]:
    """
    Interface amigável para o IRRF mensal sem deduções.
    Usada quando o usuário informa "recebo X por mês" e não passa INSS/deduções.
    Observação importante:
    - SE o usuário tiver INSS, dependentes ou outras deduções,
      você deve explicar na resposta que o cálculo foi feito sobre o valor bruto
      e que ele pode informar as deduções para refazer a conta.
    """
    gross = Decimal(str(gross))
    ir = _irrf_mensal_val(gross)

    if gross <= Decimal("5000.00"):
        regra = "Isento até R$ 5.000,00/mês."
    elif gross <= Decimal("7350.00"):
        regra = "Faixa de neutralização (fórmula da reforma) entre 5.001 e 7.350."
    else:
        regra = "Faixa superior: aplicada alíquota de 27,5% sobre o valor total do mês."

    return {
        "rendimento_mensal_bruto": brl(gross),
        "irrf_mensal": brl(ir),
        "aliquota_efetiva": f"{(ir / gross * 100):.2f}%" if gross > 0 else "0%",
        "regra_aplicada": regra,
        "observacao": (
            "Cálculo feito sem considerar INSS ou outras deduções. "
            "Se você tiver deduções legais (INSS, dependentes, previdência, etc.), "
            "informe para refazermos o cálculo anual com ajuste e possível restituição."
        ),
    }


def calc_ir_trabalho_anual(
    rendimentos_mensais: List[Decimal],
    deducoes_anuais: Decimal = Decimal("0"),
) -> Dict[str, str]:
    """
    Calculadora anual do IR sobre rendimentos de trabalho / alugueis etc.
    Regras que você pediu:
      1) O imposto é retido mês a mês na fonte, SEM deduções (usa _irrf_mensal_val).
      2) No ajuste anual:
         - Soma todos os rendimentos do ano.
         - Aplica as deduções legais SOMENTE sobre o montante anual (deducoes_anuais).
         - Calcula o imposto devido no ano sobre a renda média mensal após deduções,
           usando a MESMA regra mensal (_irrf_mensal_val) e multiplicando por 12.
         - Compara: imposto devido anual vs. IRRF já retido no ano.
           A diferença é saldo a pagar ou a restituir.
    Entradas:
      - rendimentos_mensais: lista com os valores brutos de cada mês (12 posições idealmente).
      - deducoes_anuais: total anual de deduções legais (INSS, saúde, educação, etc.).
    Observação:
      - Se o usuário não informar deduções, você passa deducoes_anuais = 0
        e deixa claro na resposta que o cálculo é “sem deduções legais”.
    """
    # Normaliza lista
    valores = [Decimal(str(v)) for v in rendimentos_mensais if Decimal(str(v)) > 0]
    if not valores:
        return {
            "renda_total_anual": brl(Decimal("0")),
            "deducoes_anuais": brl(Decimal("0")),
            "base_ajuste_anual": brl(Decimal("0")),
            "media_mensal_ajustada": brl(Decimal("0")),
            "irrf_retido_total": brl(Decimal("0")),
            "ir_ajuste_anual_devido": brl(Decimal("0")),
            "saldo_ajuste": brl(Decimal("0")),
            "situacao": "sem_renda",
            "observacao": "Nenhum rendimento informado para o ano.",
        }

    total_renda = sum(valores)
    meses = len(valores)
    deducoes_anuais = Decimal(str(deducoes_anuais))

    # 1) IRRF efetivamente retido no ano (sem deduções, mês a mês)
    irrf_retido_total = sum(_irrf_mensal_val(v) for v in valores)

    # 2) Ajuste anual: aplica deduções no montante somado
    base_ajuste_anual = max(Decimal("0"), total_renda - deducoes_anuais)
    media_mensal_ajustada = base_ajuste_anual / Decimal(meses)

    # imposto devido no ano = imposto (pela regra mensal) sobre a média ajustada × n_meses
    ir_mensal_ajuste = _irrf_mensal_val(media_mensal_ajustada)
    ir_devido_anual = ir_mensal_ajuste * Decimal(meses)

    saldo = ir_devido_anual - irrf_retido_total
    if saldo > 0:
        situacao = "a_pagar"
    elif saldo < 0:
        situacao = "a_restituir"
    else:
        situacao = "equilibrado"

    return {
        "renda_total_anual": brl(total_renda),
        "deducoes_anuais": brl(deducoes_anuais),
        "base_ajuste_anual": brl(base_ajuste_anual),
        "media_mensal_ajustada": brl(media_mensal_ajustada),
        "irrf_retido_total": brl(irrf_retido_total),
        "ir_ajuste_anual_devido": brl(ir_devido_anual),
        "saldo_ajuste": brl(saldo),
        "situacao": situacao,
        "observacao": (
            "O IRRF foi calculado mês a mês sem deduções. No ajuste anual, "
            "as deduções foram aplicadas sobre o total do ano para refazer o cálculo "
            "e apurar se há imposto a pagar ou restituição."
        ),
    }


# =========================
# IRPFM — DIVIDENDOS
# =========================

def calc_irpfm_dividendos_mensal(
    total_mes: Decimal,
    limite_por_fonte: Decimal = Decimal("50000"),
) -> Dict[str, str]:
    """
    Calculadora simples: quanto é retido NA FONTE em um único mês,
    considerando a regra de 10% sobre dividendos > 50.000 no mês
    (por fonte pagadora).
    Regra:
      - Até 50.000 no mês → isento.
      - Acima de 50.000 no mês → 10% sobre o valor TOTAL do mês.
    """
    total_mes = Decimal(str(total_mes))
    limite = Decimal(str(limite_por_fonte))

    if total_mes <= limite:
        ir_mensal = Decimal("0.00")
        status = "isento"
        obs = (
            "Até R$ 50.000,00 por mês, por fonte pagadora, não há retenção de 10% "
            "sobre lucros/dividendos."
        )
    else:
        ir_mensal = total_mes * Decimal("0.10")
        status = "tributado"
        obs = (
            "Como os dividendos no mês superam R$ 50.000,00, aplica-se retenção de 10% "
            "sobre o valor TOTAL mensal. Esse imposto é abatido do IRPFM anual."
        )

    return {
        "dividendos_mensais": brl(total_mes),
        "status": status,
        "ir_10pct_mensal": brl(ir_mensal),
        "observacao": obs,
    }


def _aliquota_irpfm(base_anual: Decimal) -> Decimal:
    """
    Alíquota da tabela do IRPFM (anual), conforme fórmula progressiva:
      - Até 600.000/ano → 0%
      - Entre 600.000 e 1.200.000 → alíquota = base / 60.000 − 10 (%)
      - Acima de 1.200.000 → 10%
    """
    base_anual = Decimal(str(base_anual))

    if base_anual <= Decimal("600000"):
        return Decimal("0")
    if base_anual < Decimal("1200000"):
        aliq = (base_anual / Decimal("60000")) - Decimal("10")
        return max(aliq, Decimal("0"))
    return Decimal("10")


def calc_irpfm_anual(
    dividendos_mensais: List[Decimal],
    pj_taxa_efetiva: Optional[Decimal] = None,
) -> Dict[str, str]:
    """
    Calculadora anual do IRPFM EXCLUSIVAMENTE sobre dividendos.
    Regras que você pediu:
      1) Aplica retenção de 10% todo mês em que dividendos > 50.000.
      2) Soma os dividendos do ano para obter a base anual.
      3) Aplica a fórmula progressiva do IRPFM anual:
           • até 600k → 0%
           • 600k–1,2M → (base/60.000) − 10
           • acima de 1,2M → 10%
      4) Compara o imposto teórico (tabela IRPFM) com o que foi retido (10%
         mensal). A diferença gera imposto a pagar ou restituição.
      5) Se o usuário informar que a PJ já paga cerca de 34% de tributos
         (pj_taxa_efetiva >= 34), assume neutralização: IRPFM isento sobre
         esses dividendos.
    Observação:
      - Aqui NÃO existe a regra de “se já paga 10% de IRPF então IRPFM é isento”.
        IRPFM é calculado integralmente, exceto se houver neutralização pela PJ.
    """
    valores = [Decimal(str(v)) for v in dividendos_mensais if Decimal(str(v)) > 0]
    notas = []

    if not valores:
        return {
            "dividendos_total_anual": brl(Decimal("0")),
            "irpfm_retido_total": brl(Decimal("0")),
            "aliquota_irpfm_anual": "0%",
            "irpfm_devido_anual": brl(Decimal("0")),
            "saldo_ajuste": brl(Decimal("0")),
            "situacao": "sem_renda",
            "observacao": "Nenhum dividendo informado para o ano.",
        }

    total_dividendos = sum(valores)
    irpfm_retido_total = sum(
        calc_irpfm_dividendos_mensal(v)["ir_10pct_mensal"]
        for v in valores
    )
    irpfm_retido_total = Decimal(irpfm_retido_total.replace("R$ ", "").replace(".", "").replace(",", "."))

    # 5) Neutralização pela PJ
    if pj_taxa_efetiva is not None and pj_taxa_efetiva >= Decimal("34"):
        irpfm_devido_anual = Decimal("0.00")
        aliquota_irpfm_anual = "0%"
        notas.append(
            "Neutralização: IRPFM anual isento, pois a PJ já paga taxa efetiva >= 34%."
        )
    else:
        # 3) Aplica a fórmula progressiva do IRPFM anual
        aliquota_irpfm_anual = _aliquota_irpfm(total_dividendos)
        irpfm_devido_anual = total_dividendos * (aliquota_irpfm_anual / Decimal("100"))
        aliquota_irpfm_anual = f"{aliquota_irpfm_anual:.2f}%"

    # 4) Compara
    saldo = irpfm_devido_anual - irpfm_retido_total
    if saldo > 0:
        situacao = "a_pagar"
    elif saldo < 0:
        situacao = "a_restituir"
    else:
        situacao = "equilibrado"

    return {
        "dividendos_total_anual": brl(total_dividendos),
        "irpfm_retido_total": brl(irpfm_retido_total),
        "aliquota_irpfm_anual": aliquota_irpfm_anual,
        "irpfm_devido_anual": brl(irpfm_devido_anual),
        "saldo_ajuste": brl(saldo),
        "situacao": situacao,
        "observacao": (
            "O IRPFM anual foi calculado sobre o total de dividendos. "
            "O imposto retido mensalmente (10% sobre valores > 50k) é abatido no ajuste anual."
        ) + (" " + " ".join(notas) if notas else ""),
    }


# =========================
# FERRAMENTAS PARA O LLM
# =========================

# Dicionário de ferramentas
TOOLS = {
    "irrf_mensal_sem_deducoes": irrf_mensal_sem_deducoes,
    "calc_ir_trabalho_anual": calc_ir_trabalho_anual,
    "calc_irpfm_dividendos_mensal": calc_irpfm_dividendos_mensal,
    "calc_irpfm_anual": calc_irpfm_anual,
}

# Prompt do sistema
SYSTEM_PROMPT = """
Você é o TaxBot, um assistente especializado em Reforma Tributária e Imposto de Renda, com foco nas regras propostas pelo PL 1.087/2025.
Seu objetivo é responder às perguntas do usuário de forma precisa, clara e didática.

**Instruções de Comportamento:**
1.  **Prioridade:** Use o contexto de busca (Retrieval) para responder a perguntas conceituais e factuais.
2.  **Cálculos:** Se a pergunta envolver um cálculo de imposto (IRRF, IRPFM, etc.), você DEVE usar as ferramentas disponíveis (funções Python) para realizar o cálculo.
3.  **Formato da Resposta:** Sua resposta deve ser sempre em português e em formato Markdown.
    *   Para perguntas conceituais, use o contexto para formular uma resposta completa.
    *   Para cálculos, apresente o resultado da ferramenta de forma clara e explicativa, contextualizando as regras aplicadas.
4.  **Histórico:** O histórico da conversa é fornecido. Use-o para manter o contexto e responder a perguntas de acompanhamento.

**Ferramentas de Cálculo:**
Você tem acesso às seguintes ferramentas para cálculos:
{tools}

**Formato de Chamada de Ferramenta:**
Para chamar uma ferramenta, você DEVE usar o formato JSON, como no exemplo:
```json
{{
  "tool_name": "irrf_mensal_sem_deducoes",
  "tool_input": {{
    "gross": 6000.00
  }}
}}
```
Você só pode chamar UMA ferramenta por vez. Se precisar de múltiplos cálculos, faça-os em chamadas separadas ou use o resultado de uma como entrada para a próxima, se for o caso.

**Contexto de Busca (Retrieval):**
O contexto abaixo foi recuperado de documentos sobre a Reforma Tributária. Use-o para embasar suas respostas conceituais.
---
{context}
---

**Pergunta do Usuário:**
{question}
"""

# =========================
# CADEIA DE EXECUÇÃO
# =========================

def retrieve_with_local_filter(q: str, fonte: str, tipo: str, k: int) -> List[Document]:
    """
    Função que busca documentos no ChromaDB com filtros (se necessário).
    No Streamlit original, o usuário podia filtrar por 'tipo' (texto, tabela, imagem).
    Mantemos a função para compatibilidade, mas o filtro 'tipo' não está implementado
    no código de busca do ChromaDB aqui (apenas na UI do Streamlit).
    """
    vdb = load_vectordb()
    # O filtro de fonte ('all') e tipo ('any') não são usados na busca,
    # mas são mantidos na assinatura para compatibilidade com o app.py original.
    
    # A busca real é feita apenas com a query e o k (número de documentos)
    docs = vdb.similarity_search(q, k=k)
    return docs

def build_chain(retriever_fn):
    """
    Constrói a função principal que executa a cadeia de RAG e Tool Use.
    Retorna a função 'run' que será chamada pelo app.py.
    """
    
    # 1. Formata a descrição das ferramentas para o prompt
    tool_descriptions = "\n".join(
        f"- `{name}`: {func.__doc__.strip()}" for name, func in TOOLS.items()
    )
    
    # 2. Cria o prompt template
    prompt_template = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT.format(tools=tool_descriptions, context="{context}", question="{question}")),
    ])
    
    # 3. Função de formatação do contexto
    def format_docs(docs):
        return "\n\n".join(
            f"**Fonte:** {doc.metadata.get('source', 'Desconhecida')}\n**Conteúdo:** {doc.page_content}"
            for doc in docs
        )

    # 4. Função de execução (Runner)
    def run(q: str, fonte: str, tipo: str, k: int) -> str:
        """
        Função principal que recebe a pergunta e executa a cadeia.
        q: Pergunta do usuário.
        fonte: Fonte de busca (mantido para compatibilidade, mas fixo em 'all').
        tipo: Tipo de conteúdo (mantido para compatibilidade, mas fixo em 'any').
        k: Número de documentos a buscar.
        """
        
        # 4.1. Busca de contexto
        docs = retriever_fn(q, fonte, tipo, k)
        context = format_docs(docs)
        
        # 4.2. Formata o prompt final
        final_prompt = prompt_template.format(context=context, question=q)
        
        # 4.3. Chamada ao LLM
        response = llm.invoke(final_prompt).content
        
        # 4.4. Verifica se o LLM pediu para usar uma ferramenta
        match = re.search(r"```json\n(\{[\s\S]*?\})\n```", response)
        
        if match:
            # 4.5. Executa a ferramenta
            try:
                tool_call = json.loads(match.group(1))
                tool_name = tool_call["tool_name"]
                tool_input = tool_call["tool_input"]
                
                if tool_name in TOOLS:
                    tool_func = TOOLS[tool_name]
                    
                    # Converte entradas numéricas para Decimal, se necessário
                    for key, value in tool_input.items():
                        if isinstance(value, (int, float)):
                            tool_input[key] = Decimal(str(value))
                        elif isinstance(value, list):
                            tool_input[key] = [Decimal(str(v)) if isinstance(v, (int, float)) else v for v in value]
                    
                    tool_result = tool_func(**tool_input)
                    
                    # 4.6. Re-chama o LLM com o resultado da ferramenta
                    tool_result_str = json.dumps(tool_result, indent=2, ensure_ascii=False)
                    
                    # Novo prompt para o LLM interpretar o resultado
                    new_prompt = (
                        f"Você executou a ferramenta `{tool_name}` com os seguintes parâmetros:\n"
                        f"```json\n{match.group(1)}\n```\n"
                        f"O resultado da ferramenta foi:\n"
                        f"```json\n{tool_result_str}\n```\n"
                        f"Agora, use este resultado para responder à pergunta original do usuário de forma clara e didática, em português. "
                        f"Não inclua o JSON de chamada ou o JSON de resultado na sua resposta final, apenas a explicação."
                    )
                    
                    final_response = llm.invoke(new_prompt).content
                    return final_response
                else:
                    return f"⚠️ O LLM solicitou uma ferramenta desconhecida: `{tool_name}`."
            
            except Exception as e:
                # Se a chamada da ferramenta falhar, retorna o erro e a resposta original do LLM
                return f"⚠️ Erro ao executar a ferramenta: `{e}`\n\nResposta original do LLM:\n{response}"
        
        # 4.7. Se não houver chamada de ferramenta, retorna a resposta original do LLM
        return response

    return run

# =========================
# EXECUÇÃO (para testes locais, não usado pelo Gradio)
# =========================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TaxBot - Agente da Reforma Tributária")
    parser.add_argument("q", type=str, help="Pergunta a ser feita ao agente.")
    parser.add_argument("--k", type=int, default=6, help="Número de documentos a buscar.")
    args = parser.parse_args()

    runner = build_chain(retrieve_with_local_filter)
    
    # A função run(q, fonte, tipo, k) não usa chat_ctx
    resposta = runner(args.q, "all", "any", args.k)
    print(resposta)