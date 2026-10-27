# -*- coding: utf-8 -*-
"""
Roda o conjunto de avaliação (evals/casos.py) contra o TaxBot e gera um relatório.

Uso:
    python evals/avaliar.py                      # todos os casos
    python evals/avaliar.py --ids irrf-6500 conc-redutor
    python evals/avaliar.py --pausa 8            # segundos entre perguntas (cota gratuita)
    python evals/avaliar.py --repeticoes 3       # cada caso 3 vezes, para medir a variação do modelo

Relatórios em evals/resultados/AAAA-MM-DD_HHMM.md (+ .json com as respostas completas).
"""
import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from agente import LimiteDeUsoError, TaxBot  # noqa: E402
import calculadoras  # noqa: E402
from calculadoras import brl  # noqa: E402
from evals.casos import CASOS  # noqa: E402

PASTA_RESULTADOS = Path(__file__).resolve().parent / "resultados"
# Valores fixados em lei (faixas, limites, deduções): o modelo pode citá-los mesmo sem estarem nos trechos.
CONSTANTES_LEGAIS = {
    brl(v)[3:] for nome, v in vars(calculadoras).items()
    if nome.isupper() and isinstance(v, Decimal) and v >= 1
} | {brl(x)[3:] for tabela in (calculadoras.TABELA_MENSAL, calculadoras.TABELA_ANUAL)
     for linha in tabela for x in (linha[0], linha[2]) if x}
# Início de faixa ("de R$ 5.000,01 até ...")
CONSTANTES_LEGAIS |= {brl(float(v.replace(".", "").replace(",", ".")) + 0.01)[3:] for v in CONSTANTES_LEGAIS}
RE_REAIS = re.compile(r"R\$\s?(-?\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?)(\s?(?:mil\b|milh[õoãa]o?e?s?\b))?", re.I)
ESCALA = {"mil": 1_000, "milh": 1_000_000}
# Grupo de milhar com 1, 2 ou 4+ dígitos (ou primeiro grupo com 4+ dígitos seguido de ponto)
RE_MALFORMADO = re.compile(r"R\$\s?(?:\d+\.(?:\d{1,2}|\d{4,})(?=[.,\s]|$)|\d{4,}\.\d)[\d.,]*")


# =====================  VERIFICAÇÕES  =====================
def _contem_afirmando(texto: str, termo: str) -> bool:
    """True se o termo aparece sem uma negação logo antes ("e não apenas sobre o que exceder" não conta)."""
    for m in re.finditer(re.escape(termo), texto):
        antes = texto[max(0, m.start() - 25):m.start()]
        if not re.search(r"\bn[ãa]o\b|\bnem\b", antes):
            return True
    return False


def verificar(caso: dict, texto: str, ferramentas: list) -> list:
    t = texto.lower()
    falhas = []
    for s in caso.get("deve_conter", []):
        if s.lower() not in t:
            falhas.append(f"faltou “{s}”")
    for grupo in caso.get("deve_conter_algum", []):
        if not any(s.lower() in t for s in grupo):
            falhas.append(f"faltou um de {grupo}")
    for s in caso.get("nao_deve_conter", []):
        if _contem_afirmando(t, s.lower()):
            falhas.append(f"contém o proibido “{s}”")
    chamadas = {f["nome"] for f in ferramentas}
    for nome in caso.get("ferramentas", []):
        if nome not in chamadas:
            falhas.append(f"não chamou {nome}")
    if caso.get("sem_ferramentas") and chamadas:
        falhas.append(f"calculou sem ter os dados ({', '.join(sorted(chamadas))})")
    return falhas


def extrair_reais(texto: str) -> set:
    """Valores em R$ do texto, normalizados para "1.234,56" ("R$ 50 mil" → "50.000,00")."""
    valores = set()
    for numero, sufixo in RE_REAIS.findall(texto):
        v = float(numero.replace(".", "").replace(",", "."))
        sufixo = sufixo.strip().lower()
        if sufixo:
            v *= ESCALA["mil" if sufixo == "mil" else "milh"]
        valores.add(brl(v).replace("-", "")[3:])
    return valores


def valores_sem_origem(caso: dict, texto: str, ferramentas: list, fontes: list) -> list:
    """Valores em R$ citados na resposta que não aparecem na pergunta, no histórico, nos trechos
    nem nas entradas/saídas das calculadoras (nem como valor anual = 12 × mensal).
    É um diagnóstico de possível invenção, não reprova o caso."""
    origem = [caso["pergunta"], json.dumps(caso.get("historico", []), ensure_ascii=False)]
    origem += [f["texto"] for f in fontes]
    origem += [json.dumps(f.get("resultado", {}), ensure_ascii=False) for f in ferramentas]
    conhecidos = {v for s in origem for v in extrair_reais(s)}
    conhecidos |= CONSTANTES_LEGAIS
    numeros = []
    for f in ferramentas:
        for v in f["argumentos"].values():
            numeros += v if isinstance(v, list) else [v]
    for n in numeros:
        if isinstance(n, (int, float)):
            conhecidos |= {brl(n)[3:], brl(n * 12)[3:]}
    # Contas simples sobre valores conhecidos (somas, diferenças e múltiplos até 12×) não contam como invenção.
    base = {float(v.replace(".", "").replace(",", ".")) for v in conhecidos}
    derivados = {a * k for a in base for k in range(2, 13)}
    derivados |= {a + b for a in base for b in base} | {abs(a - b) for a in base for b in base}
    conhecidos |= {brl(x)[3:] for x in derivados}
    # Números com pontuação impossível (ex.: "R$ 96.0000,00") são sempre suspeitos.
    malformados = {m.group(0) for m in RE_MALFORMADO.finditer(texto)}
    return sorted(extrair_reais(texto) - conhecidos) + sorted(f"formato inválido: {m}" for m in malformados)


# =====================  EXECUÇÃO  =====================
def responder_com_espera(bot: TaxBot, caso: dict):
    for tentativa in range(3):
        try:
            return bot.responder(caso["pergunta"], caso.get("historico", []))
        except LimiteDeUsoError:
            if tentativa == 2:
                raise
            print("    cota/sobrecarga do Gemini, aguardando 65 s...")
            time.sleep(65)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="*", help="rodar só estes casos")
    parser.add_argument("--pausa", type=float, default=5, help="segundos entre perguntas")
    parser.add_argument("--repeticoes", type=int, default=1,
                        help="rodar cada caso N vezes (o modelo varia entre rodadas)")
    args = parser.parse_args()

    selecionados = [c for c in CASOS if not args.ids or c["id"] in args.ids]
    casos = [
        {**c, "id": c["id"] + (f"#{n}" if args.repeticoes > 1 else "")}
        for c in selecionados for n in range(1, args.repeticoes + 1)
    ]
    bot = TaxBot()
    resultados = []
    for i, caso in enumerate(casos, start=1):
        inicio = time.time()
        try:
            r = responder_com_espera(bot, caso)
            texto, ferramentas, fontes, modelo = r.texto, r.ferramentas, r.fontes, r.modelo
            falhas = verificar(caso, texto, ferramentas)
            suspeitos = valores_sem_origem(caso, texto, ferramentas, fontes)
            if suspeitos:  # número que não veio de nenhuma fonte = possível conta errada ou invenção
                falhas.append(f"valores sem origem: {', '.join(suspeitos)}")
        except Exception as e:  # noqa: BLE001 — um erro conta como reprovação, a avaliação continua
            texto, ferramentas, fontes, modelo = f"ERRO: {type(e).__name__}: {e}", [], [], ""
            falhas, suspeitos = [f"erro: {type(e).__name__}"], []
        segundos = time.time() - inicio
        ok = not falhas
        print(f"[{i:2d}/{len(casos)}] {'OK  ' if ok else 'FALHA'} {caso['id']:28s} {segundos:5.1f}s"
              + ("" if ok else f"  → {'; '.join(falhas)}"))
        resultados.append({
            "id": caso["id"], "categoria": caso["categoria"], "pergunta": caso["pergunta"], "ok": ok,
            "falhas": falhas, "valores_sem_origem": suspeitos, "segundos": round(segundos, 1),
            "modelo": modelo, "ferramentas": ferramentas, "resposta": texto,
        })
        if i < len(casos):
            time.sleep(args.pausa)

    salvar_relatorio(resultados)


def salvar_relatorio(resultados: list) -> None:
    PASTA_RESULTADOS.mkdir(exist_ok=True)
    nome = datetime.now().strftime("%Y-%m-%d_%H%M")
    (PASTA_RESULTADOS / f"{nome}.json").write_text(
        json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8")

    total, aprovados = len(resultados), sum(r["ok"] for r in resultados)
    por_cat = defaultdict(lambda: [0, 0])
    for r in resultados:
        por_cat[r["categoria"]][0] += r["ok"]
        por_cat[r["categoria"]][1] += 1
    modelos = sorted({r["modelo"] for r in resultados if r["modelo"]})
    tempo_medio = sum(r["segundos"] for r in resultados) / max(total, 1)

    linhas = [
        f"# Avaliação do TaxBot — {datetime.now():%d/%m/%Y %H:%M}", "",
        f"**Placar: {aprovados}/{total} ({aprovados / max(total, 1):.0%})** · "
        f"tempo médio {tempo_medio:.1f}s · modelo(s): {', '.join(modelos) or '—'}", "",
        "| Categoria | Aprovados |", "|---|---|",
        *[f"| {c} | {a}/{n} |" for c, (a, n) in sorted(por_cat.items())], "",
        "## Reprovações", "",
    ]
    for r in resultados:
        if not r["ok"]:
            linhas += [f"### {r['id']}", f"**Pergunta:** {r['pergunta']}", "",
                       f"**Falhas:** {'; '.join(r['falhas'])}", "",
                       "**Resposta:**", "", "> " + r["resposta"][:1500].replace("\n", "\n> "), ""]
    if aprovados == total:
        linhas.append("Nenhuma.")
    linhas += ["", "## Valores em R$ sem origem identificada", "",
               "Valores citados na resposta que não vieram da pergunta, dos trechos nem das calculadoras (reprovam o caso). "
               "Podem ser contas simples feitas pelo modelo ou invenções.", ""]
    suspeitos = [r for r in resultados if r["valores_sem_origem"]]
    linhas += [f"- **{r['id']}**: {', '.join('R$ ' + v for v in r['valores_sem_origem'])}" for r in suspeitos] or ["Nenhum."]

    caminho = PASTA_RESULTADOS / f"{nome}.md"
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"\nPlacar: {aprovados}/{total} · relatório em {caminho}")


if __name__ == "__main__":
    main()
