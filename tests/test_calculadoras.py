# -*- coding: utf-8 -*-
"""Casos de referência das calculadoras (valores conferidos à mão com a Lei 15.270/2025)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calculadoras import (  # noqa: E402
    calcular_irrf_mensal,
    calcular_ir_ajuste_anual,
    calcular_retencao_dividendos_mensal,
    calcular_irpfm_anual,
)


# ---------- IRRF mensal ----------
def test_isento_ate_5000():
    assert calcular_irrf_mensal(5000)["irrf_mensal"] == "R$ 0,00"
    assert calcular_irrf_mensal(3000)["irrf_mensal"] == "R$ 0,00"


def test_faixa_de_reducao_6000():
    # base 6.000 − 607,20 = 5.392,80 → 27,5% − 908,73 = 574,29; redução 978,62 − 0,133145×6.000 = 179,75
    r = calcular_irrf_mensal(6000)
    assert r["imposto_pela_tabela_progressiva"] == "R$ 574,29"
    assert r["reducao_lei_15270"] == "R$ 179,75"
    assert r["irrf_mensal"] == "R$ 394,54"


def test_continuidade_em_7350():
    # Sem salto no fim da faixa de redução
    a = calcular_irrf_mensal(7350)["irrf_mensal"]
    b = calcular_irrf_mensal(7350.01)["irrf_mensal"]
    assert a == "R$ 945,54"
    assert b == "R$ 945,54"


def test_acima_de_7350_sem_reducao():
    # base 7.392,80 → 27,5% − 908,73 = 1.124,29
    r = calcular_irrf_mensal(8000)
    assert r["reducao_lei_15270"] == "R$ 0,00"
    assert r["irrf_mensal"] == "R$ 1.124,29"


def test_deducoes_legais_quando_maiores_que_simplificado():
    # INSS 800 + 2 dependentes (379,18) = 1.179,18 > 607,20 → base 8.820,82 → 1.516,9955
    r = calcular_irrf_mensal(10000, inss=800, dependentes=2)
    assert "deduções legais" in r["deducao_aplicada"]
    assert r["irrf_mensal"] == "R$ 1.517,00"


# ---------- Ajuste anual ----------
def test_anual_isento_ate_60000():
    r = calcular_ir_ajuste_anual([5000] * 12)
    assert r["imposto_devido_no_ano"] == "R$ 0,00"
    assert r["situacao"] == "zerado"


def test_anual_com_restituicao_por_deducoes():
    # 8.000/mês, sem deduções na fonte; saúde de 20.000 no ajuste gera restituição
    r = calcular_ir_ajuste_anual([8000] * 12, outras_deducoes_anuais=20000)
    assert r["modelo_de_declaracao"].startswith("completo")
    assert r["situacao"] == "a_restituir"


def test_anual_acima_de_88200_sem_reducao():
    r = calcular_ir_ajuste_anual([10000] * 12, irrf_retido_total=0)
    assert r["reducao_anual_lei_15270"] == "R$ 0,00"
    assert r["situacao"] == "a_pagar"


# ---------- Dividendos ----------
def test_retencao_por_empresa():
    r = calcular_retencao_dividendos_mensal([60000, 30000])
    assert r["por_empresa"][0]["retencao_10pct"] == "R$ 6.000,00"
    assert r["por_empresa"][1]["retencao_10pct"] == "R$ 0,00"
    assert r["total_retido_no_mes"] == "R$ 6.000,00"


def test_exatamente_50000_nao_retem():
    assert calcular_retencao_dividendos_mensal([50000])["total_retido_no_mes"] == "R$ 0,00"


# ---------- IRPFM ----------
def test_irpfm_abaixo_de_600k():
    r = calcular_irpfm_anual(400000, dividendos_anuais=150000)
    assert r["sujeito_ao_irpfm"] is False
    assert r["irpfm_devido"] == "R$ 0,00"


def test_irpfm_10pct_com_retencao():
    # 1,2 mi só de dividendos, 12 × 100 mil (retenção de 10.000/mês = 120.000) → saldo zero
    r = calcular_irpfm_anual(0, dividendos_anuais=1200000, retencao_dividendos_10pct=120000)
    assert r["aliquota_irpfm"] == "10,00%"
    assert r["irpfm_devido"] == "R$ 120.000,00"
    assert r["situacao"] == "zerado"


def test_irpfm_faixa_intermediaria():
    # 900 mil → alíquota 900.000/60.000 − 10 = 5% → 45.000; abate IR do ajuste de 20.000
    r = calcular_irpfm_anual(300000, dividendos_anuais=600000, ir_devido_no_ajuste_anual=20000)
    assert r["aliquota_irpfm"] == "5,00%"
    assert r["irpfm_devido"] == "R$ 25.000,00"


def test_irpfm_redutor_pj_34():
    # PJ com 34% efetivos: redutor anula o IRPFM sobre os dividendos
    r = calcular_irpfm_anual(0, dividendos_anuais=1200000, aliquota_efetiva_pj=34)
    assert r["redutor_art_16B"] == "R$ 120.000,00"
    assert r["irpfm_devido"] == "R$ 0,00"


def test_irpfm_redutor_parcial():
    # PJ 30% + IRPFM 10% = 40% → excesso de 6 p.p. → redutor 72.000 sobre 1,2 mi
    r = calcular_irpfm_anual(0, dividendos_anuais=1200000, aliquota_efetiva_pj=30)
    assert r["redutor_art_16B"] == "R$ 72.000,00"
    assert r["irpfm_devido"] == "R$ 48.000,00"
