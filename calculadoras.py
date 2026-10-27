# -*- coding: utf-8 -*-
"""
Calculadoras do TaxBot conforme a Lei 15.270/2025 (reforma do IR, vigente a partir de 01/01/2026).

Toda a aritmética é feita em Decimal. As funções públicas recebem float/int (para que o Gemini
consiga gerar o schema de function calling a partir das anotações) e devolvem dicionários com
valores já formatados em reais.

Referências:
  • Tabelas progressivas mensal e anual de 2026: Receita Federal (Lei 15.191/2025 e Lei 15.270/2025).
  • Redução mensal: art. 3º-A da Lei 9.250/1995, incluído pela Lei 15.270/2025.
  • Redução anual: art. 11-A da Lei 9.250/1995.
  • Retenção de 10% sobre dividendos: art. 6º-A da Lei 9.250/1995.
  • Tributação mínima (IRPFM) e redutor: arts. 16-A e 16-B da Lei 9.250/1995.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Dict

D = Decimal
ZERO = D("0")
CENTAVO = D("0.01")

# =====================  PARÂMETROS LEGAIS  =====================
# (limite superior da faixa, alíquota %, parcela a deduzir)
TABELA_MENSAL = [
    (D("2428.80"), D("0"), D("0")),
    (D("2826.65"), D("7.5"), D("182.16")),
    (D("3751.05"), D("15"), D("394.16")),
    (D("4664.68"), D("22.5"), D("675.49")),
    (None, D("27.5"), D("908.73")),
]
# Tabela anual oficial do ano-calendário 2026 (Receita Federal, "Tributação de 2026").
TABELA_ANUAL = [
    (D("29145.60"), D("0"), D("0")),
    (D("33919.80"), D("7.5"), D("2185.92")),
    (D("45012.60"), D("15"), D("4729.91")),
    (D("55976.16"), D("22.5"), D("8105.85")),
    (None, D("27.5"), D("10904.66")),
]

DEDUCAO_DEPENDENTE_MENSAL = D("189.59")
DEDUCAO_DEPENDENTE_ANUAL = D("2275.08")
DESCONTO_SIMPLIFICADO_MENSAL = D("607.20")
DESCONTO_SIMPLIFICADO_ANUAL_PCT = D("0.20")
DESCONTO_SIMPLIFICADO_ANUAL_TETO = D("17640.00")  # art. 10, X, da Lei 9.250 (redação da Lei 15.270)

# Redução mensal (art. 3º-A)
REDUCAO_MENSAL_LIMITE_ISENCAO = D("5000.00")
REDUCAO_MENSAL_MAX = D("312.89")
REDUCAO_MENSAL_LIMITE = D("7350.00")
REDUCAO_MENSAL_A, REDUCAO_MENSAL_B = D("978.62"), D("0.133145")

# Redução anual (art. 11-A)
REDUCAO_ANUAL_LIMITE_ISENCAO = D("60000.00")
REDUCAO_ANUAL_MAX = D("2694.15")
REDUCAO_ANUAL_LIMITE = D("88200.00")
REDUCAO_ANUAL_A, REDUCAO_ANUAL_B = D("8429.73"), D("0.095575")

# Dividendos e IRPFM
DIVIDENDOS_LIMITE_MENSAL = D("50000.00")
DIVIDENDOS_ALIQUOTA_FONTE = D("0.10")
IRPFM_PISO = D("600000")
IRPFM_TETO = D("1200000")


# =====================  HELPERS  =====================
def _d(x) -> Decimal:
    return D(str(x)) if x is not None else ZERO


def _q(x: Decimal) -> Decimal:
    return D(x).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def brl(x) -> str:
    q = _q(_d(x))
    s = f"{abs(q):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if q < 0 else ''}R$ {s}"


def pct(x) -> str:
    return f"{_q(_d(x))}".replace(".", ",") + "%"


def _imposto_tabela(base: Decimal, tabela) -> Decimal:
    for limite, aliq, parcela in tabela:
        if limite is None or base <= limite:
            return max(ZERO, base * aliq / 100 - parcela)
    return ZERO  # inalcançável


def _situacao(saldo: Decimal) -> str:
    if saldo > 0:
        return "a_pagar"
    if saldo < 0:
        return "a_restituir"
    return "zerado"


# =====================  NÚCLEO NUMÉRICO  =====================
def _irrf_mensal_val(bruto, inss=ZERO, dependentes=0, pensao=ZERO, previdencia=ZERO) -> Dict:
    bruto = _d(bruto)
    deducoes_legais = _d(inss) + DEDUCAO_DEPENDENTE_MENSAL * int(dependentes or 0) + _d(pensao) + _d(previdencia)

    # A fonte pagadora aplica o que for mais vantajoso: deduções legais ou desconto simplificado.
    if deducoes_legais >= DESCONTO_SIMPLIFICADO_MENSAL:
        deducao, metodo = deducoes_legais, "deduções legais"
    else:
        deducao, metodo = DESCONTO_SIMPLIFICADO_MENSAL, "desconto simplificado mensal (R$ 607,20)"
    base = max(ZERO, bruto - deducao)
    imposto_tabela = _imposto_tabela(base, TABELA_MENSAL)

    # Redução da Lei 15.270: calculada sobre o rendimento tributável BRUTO e limitada ao imposto da tabela.
    if bruto <= REDUCAO_MENSAL_LIMITE_ISENCAO:
        reducao = min(REDUCAO_MENSAL_MAX, imposto_tabela)
    elif bruto <= REDUCAO_MENSAL_LIMITE:
        reducao = min(max(ZERO, REDUCAO_MENSAL_A - REDUCAO_MENSAL_B * bruto), imposto_tabela)
    else:
        reducao = ZERO

    return {
        "bruto": bruto, "deducao": deducao, "metodo": metodo, "base": base,
        "imposto_tabela": imposto_tabela, "reducao": reducao,
        "imposto": _q(imposto_tabela - reducao),
    }


def _ir_anual_val(total: Decimal, deducoes_legais: Decimal = ZERO) -> Dict:
    """Imposto devido no ajuste anual: melhor dedução (legais × simplificado), tabela anual e redução."""
    simplificado = min(total * DESCONTO_SIMPLIFICADO_ANUAL_PCT, DESCONTO_SIMPLIFICADO_ANUAL_TETO)
    if deducoes_legais >= simplificado:
        deducao, modelo = deducoes_legais, "completo (deduções legais)"
    else:
        deducao, modelo = simplificado, "simplificado (desconto de 20%)"

    base = max(ZERO, total - deducao)
    imposto_tabela = _imposto_tabela(base, TABELA_ANUAL)

    if total <= REDUCAO_ANUAL_LIMITE_ISENCAO:
        reducao = min(REDUCAO_ANUAL_MAX, imposto_tabela)
    elif total <= REDUCAO_ANUAL_LIMITE:
        reducao = min(max(ZERO, REDUCAO_ANUAL_A - REDUCAO_ANUAL_B * total), imposto_tabela)
    else:
        reducao = ZERO

    return {
        "deducao": deducao, "modelo": modelo, "base": base, "imposto_tabela": imposto_tabela,
        "reducao": reducao, "devido": _q(imposto_tabela - reducao),
    }


# =====================  FERRAMENTAS (expostas ao LLM)  =====================
def calcular_irrf_mensal(
    rendimento_bruto_mensal: float,
    inss: float = 0.0,
    dependentes: int = 0,
    pensao_alimenticia: float = 0.0,
    previdencia_privada: float = 0.0,
) -> dict:
    """Calcula o IR retido na fonte (IRRF) de UM mês sobre salário, pró-labore, aluguel ou outro
    rendimento tributável, já com a redução da Lei 15.270/2025 (isenção efetiva até R$ 5.000 e
    redução decrescente até R$ 7.350). Aplica automaticamente o que for melhor entre as deduções
    legais (INSS, dependentes, pensão, previdência) e o desconto simplificado mensal de R$ 607,20.

    Args:
        rendimento_bruto_mensal: rendimento tributável bruto do mês, em reais.
        inss: contribuição ao INSS descontada no mês (0 se não informado).
        dependentes: número de dependentes.
        pensao_alimenticia: pensão alimentícia judicial paga no mês.
        previdencia_privada: contribuição a previdência oficial complementar/PGBL no mês.
    """
    r = _irrf_mensal_val(rendimento_bruto_mensal, inss, dependentes, pensao_alimenticia, previdencia_privada)
    bruto = r["bruto"]
    return {
        "rendimento_bruto_mensal": brl(bruto),
        "deducao_aplicada": f"{brl(r['deducao'])} ({r['metodo']})",
        "base_de_calculo": brl(r["base"]),
        "imposto_pela_tabela_progressiva": brl(r["imposto_tabela"]),
        "reducao_lei_15270": brl(r["reducao"]),
        "irrf_mensal": brl(r["imposto"]),
        "aliquota_efetiva_sobre_bruto": pct(r["imposto"] / bruto * 100) if bruto > 0 else "0%",
    }


def calcular_ir_ajuste_anual(
    rendimentos_mensais: List[float],
    inss_anual: float = 0.0,
    dependentes: int = 0,
    outras_deducoes_anuais: float = 0.0,
    irrf_retido_total: Optional[float] = None,
) -> dict:
    """Simula a declaração de ajuste anual do IRPF (ano-calendário 2026 em diante) para rendimentos
    tributáveis (salário, aluguel etc.), com a redução anual da Lei 15.270/2025 (isenção efetiva até
    R$ 60.000/ano e redução decrescente até R$ 88.200/ano). Compara deduções legais com o desconto
    simplificado (20%, teto R$ 17.640,00) e escolhe o melhor. Informa se há imposto a pagar ou a restituir.

    Args:
        rendimentos_mensais: rendimentos tributáveis brutos de cada mês do ano (não inclua o 13º).
        inss_anual: total de INSS pago no ano.
        dependentes: número de dependentes.
        outras_deducoes_anuais: soma de saúde, educação (até R$ 3.561,50 por pessoa), PGBL, pensão etc.
        irrf_retido_total: IR retido na fonte no ano; se omitido, é estimado mês a mês.
    """
    valores = [_d(v) for v in rendimentos_mensais if _d(v) > 0]
    if not valores:
        return {"situacao": "sem_renda", "observacao": "Nenhum rendimento informado."}

    n = len(valores)
    total = sum(valores)
    inss_anual = _d(inss_anual)

    if irrf_retido_total is None:
        retido = sum(_irrf_mensal_val(v, inss=inss_anual / n, dependentes=dependentes)["imposto"] for v in valores)
        origem_retido = "estimado mês a mês (INSS distribuído igualmente entre os meses)"
    else:
        retido = _d(irrf_retido_total)
        origem_retido = "informado pelo usuário"

    deducoes_legais = inss_anual + DEDUCAO_DEPENDENTE_ANUAL * int(dependentes or 0) + _d(outras_deducoes_anuais)
    r = _ir_anual_val(total, deducoes_legais)
    devido = r["devido"]
    saldo = _q(devido - retido)
    return {
        "rendimentos_tributaveis_anuais": brl(total),
        "modelo_de_declaracao": r["modelo"],
        "deducao_aplicada": brl(r["deducao"]),
        "base_de_calculo_anual": brl(r["base"]),
        "imposto_pela_tabela_anual": brl(r["imposto_tabela"]),
        "reducao_anual_lei_15270": brl(r["reducao"]),
        "imposto_devido_no_ano": brl(devido),
        "irrf_retido_no_ano": f"{brl(retido)} ({origem_retido})",
        "saldo_do_ajuste": brl(abs(saldo)),
        "situacao": _situacao(saldo),
        "observacao": (
            "Tabela anual oficial do ano-calendário 2026. O 13º salário é tributado exclusivamente "
            "na fonte e não entra no ajuste."
        ),
    }


def calcular_retencao_dividendos_mensal(dividendos_por_empresa: List[float]) -> dict:
    """Calcula a retenção na fonte de 10% sobre lucros e dividendos pagos em UM mês (art. 6º-A,
    Lei 15.270/2025). A regra vale por empresa pagadora: se a mesma empresa pagar mais de R$ 50.000
    no mês à mesma pessoa física, retém-se 10% sobre o valor TOTAL pago por ela no mês. Lucros de
    resultados até 2025 aprovados até 31/12/2025 não sofrem essa retenção.

    Calcula UM único mês. Para o ano todo, chame com os valores de um mês e multiplique pelo número de
    meses iguais (não passe os 12 meses na lista: cada item é uma empresa diferente).

    Args:
        dividendos_por_empresa: valor pago no mês por cada empresa (um item por empresa pagadora).
    """
    detalhes, total_retido = [], ZERO
    for i, v in enumerate(dividendos_por_empresa, start=1):
        v = _d(v)
        retido = _q(v * DIVIDENDOS_ALIQUOTA_FONTE) if v > DIVIDENDOS_LIMITE_MENSAL else ZERO
        total_retido += retido
        detalhes.append({"empresa": i, "dividendos": brl(v), "retencao_10pct": brl(retido)})
    return {
        "por_empresa": detalhes,
        "total_retido_no_mes": brl(total_retido),
        "observacao": "A retenção é antecipação: é abatida do IRPFM no ajuste anual.",
    }


def calcular_irpfm_anual(
    rendimentos_tributaveis_anuais: float,
    dividendos_anuais: float = 0.0,
    outros_rendimentos_isentos_ou_exclusivos: float = 0.0,
    ir_devido_no_ajuste_anual: Optional[float] = None,
    ir_exclusivo_na_fonte: float = 0.0,
    retencao_dividendos_10pct: Optional[float] = None,
    aliquota_efetiva_pj: Optional[float] = None,
    aliquota_nominal_pj: float = 34.0,
) -> dict:
    """Calcula a tributação mínima anual das altas rendas (IRPFM, arts. 16-A e 16-B, Lei 15.270/2025),
    aplicável a quem recebe mais de R$ 600.000 no ano. A alíquota sobe linearmente de 0% (R$ 600 mil)
    a 10% (R$ 1,2 milhão ou mais). Do IRPFM bruto abatem-se o IR do ajuste anual, o IR exclusivo na
    fonte e o redutor (quando PJ + IRPFM superam 34%). Depois abate-se a retenção de 10% sobre dividendos.
    Esta ferramenta é autossuficiente: NÃO é preciso chamar outras antes dela no caso típico.

    NÃO inclua na base: poupança, LCI/LCA/CRI/CRA, FII/Fiagro que cumpram os requisitos, ganhos de capital,
    indenizações, nem lucros de resultados até 2025 aprovados até 31/12/2025.

    Args:
        rendimentos_tributaveis_anuais: salários, pró-labore, aluguéis etc. do ano.
        dividendos_anuais: lucros e dividendos recebidos no ano (sujeitos à nova regra).
        outros_rendimentos_isentos_ou_exclusivos: demais rendimentos isentos ou tributados na fonte que entram na base.
        ir_devido_no_ajuste_anual: DEIXE VAZIO para calcular automaticamente a partir dos rendimentos
            tributáveis (desconto simplificado). Só informe se o usuário deu o valor ou se ele veio de
            calcular_ir_ajuste_anual com deduções. Nunca estime.
        ir_exclusivo_na_fonte: IR já retido de forma definitiva sobre rendimentos incluídos na base.
        retencao_dividendos_10pct: DEIXE VAZIO para calcular automaticamente supondo dividendos iguais todo
            mês de uma única empresa. Informe só se o usuário deu o valor ou se veio de
            calcular_retencao_dividendos_mensal (várias empresas ou meses diferentes).
        aliquota_efetiva_pj: alíquota efetiva (%) de IRPJ+CSLL da empresa que pagou os dividendos, se conhecida.
        aliquota_nominal_pj: alíquota nominal de referência: 34 (geral), 40 (seguradoras etc.) ou 45 (bancos).
    """
    dividendos = _d(dividendos_anuais)
    base = _d(rendimentos_tributaveis_anuais) + dividendos + _d(outros_rendimentos_isentos_ou_exclusivos)

    if base <= IRPFM_PISO:
        aliquota = ZERO
    elif base < IRPFM_TETO:
        aliquota = base / D("60000") - D("10")
    else:
        aliquota = D("10")
    irpfm_bruto = base * aliquota / 100

    # Redutor (art. 16-B): limitado, por prudência, à parcela do IRPFM que recai sobre os dividendos.
    redutor, nota_redutor = ZERO, (
        "REDUTOR NÃO APLICADO: a alíquota efetiva de IRPJ+CSLL da empresa não foi informada. Se a empresa "
        "pagar carga efetiva alta (ex.: lucro real perto de 34%), o IRPFM sobre os dividendos pode cair ou "
        "zerar; pergunte ao usuário essa alíquota."
    )
    if aliquota_efetiva_pj is not None and dividendos > 0 and aliquota > 0:
        soma = _d(aliquota_efetiva_pj) + aliquota
        excesso = soma - _d(aliquota_nominal_pj)
        if excesso > 0:
            redutor = min(dividendos * excesso / 100, dividendos * aliquota / 100)
            nota_redutor = (
                f"PJ ({pct(aliquota_efetiva_pj)}) + IRPFM ({pct(aliquota)}) = {pct(soma)} > "
                f"{pct(aliquota_nominal_pj)}: redutor aplicado."
            )
        else:
            nota_redutor = f"PJ + IRPFM = {pct(soma)}, não supera {pct(aliquota_nominal_pj)}: sem redutor."

    if ir_devido_no_ajuste_anual is None:
        ir_ajuste = _ir_anual_val(_d(rendimentos_tributaveis_anuais))["devido"]
        origem_ir = "calculado (tabela anual 2026, desconto simplificado, sem outras deduções)"
    else:
        ir_ajuste, origem_ir = _d(ir_devido_no_ajuste_anual), "informado"

    if retencao_dividendos_10pct is None:
        mensal = dividendos / 12
        retencao = _q(dividendos * DIVIDENDOS_ALIQUOTA_FONTE) if mensal > DIVIDENDOS_LIMITE_MENSAL else ZERO
        origem_ret = "calculada supondo valores iguais nos 12 meses, de uma única empresa"
    else:
        retencao, origem_ret = _d(retencao_dividendos_10pct), "informada"

    abatimentos = ir_ajuste + _d(ir_exclusivo_na_fonte) + redutor
    irpfm_devido = _q(max(ZERO, irpfm_bruto - abatimentos))
    saldo = _q(irpfm_devido - retencao)

    return {
        "base_irpfm": brl(base),
        "sujeito_ao_irpfm": base > IRPFM_PISO,
        "aliquota_irpfm": pct(aliquota),
        "irpfm_bruto": brl(irpfm_bruto),
        "ir_do_ajuste_anual_abatido": f"{brl(ir_ajuste)} ({origem_ir})",
        "ir_exclusivo_na_fonte_abatido": brl(_d(ir_exclusivo_na_fonte)),
        "redutor_art_16B": brl(redutor),
        "irpfm_devido": brl(irpfm_devido),
        "retencao_10pct_dividendos_abatida": f"{brl(retencao)} ({origem_ret})",
        "saldo": brl(abs(saldo)),
        "situacao": _situacao(saldo),
        "observacao": nota_redutor + " O saldo é somado ao resultado da declaração de ajuste anual.",
    }


FERRAMENTAS = [
    calcular_irrf_mensal,
    calcular_ir_ajuste_anual,
    calcular_retencao_dividendos_mensal,
    calcular_irpfm_anual,
]
