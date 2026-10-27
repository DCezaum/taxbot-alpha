# -*- coding: utf-8 -*-
"""
Conjunto de avaliação do TaxBot: perguntas com o que a resposta precisa (e não pode) conter.

Campos de cada caso:
    id, categoria, pergunta
    historico            conversa anterior [{"role", "content"}] (opcional)
    deve_conter          textos que TODOS precisam aparecer na resposta
    deve_conter_algum    lista de grupos; de cada grupo, pelo menos UM texto precisa aparecer
    nao_deve_conter      textos que NÃO podem aparecer
    ferramentas          calculadoras que precisam ter sido chamadas
    sem_ferramentas      True quando o bot deve perguntar/explicar em vez de calcular

A comparação ignora maiúsculas/minúsculas. Os valores de referência dos cálculos vêm das calculadoras,
que por sua vez são validadas pelos exemplos oficiais da Receita em tests/.
"""

IRRF = "calcular_irrf_mensal"
ANUAL = "calcular_ir_ajuste_anual"
DIV = "calcular_retencao_dividendos_mensal"
IRPFM = "calcular_irpfm_anual"

NEGACAO = ["não", "nao "]

CASOS = [
    # ---------------- Cálculo: IR mensal ----------------
    {"id": "irrf-3000", "categoria": "cálculo mensal",
     "pergunta": "Ganho R$ 3.000 por mês de salário. Vou ter IR retido na fonte em 2026?",
     "deve_conter_algum": [["R$ 0,00", "zero", "isento", "não terá", "não haverá"]], "ferramentas": [IRRF]},
    {"id": "irrf-receita-ex4", "categoria": "cálculo mensal",
     "pergunta": "Recebo R$ 6.000 de salário e pago R$ 649,60 de INSS. Quanto de IR é retido por mês em 2026?",
     "deve_conter": ["382,88"], "ferramentas": [IRRF]},
    {"id": "irrf-receita-ex5", "categoria": "cálculo mensal",
     "pergunta": "Meu salário é R$ 7.607,20 e não tenho deduções. Quanto pago de IR na fonte?",
     "deve_conter": ["1.016,27"], "ferramentas": [IRRF]},
    {"id": "irrf-6500", "categoria": "cálculo mensal",
     "pergunta": "Ganho R$ 6.500 por mês. Quanto vou pagar de IR na fonte por mês em 2026?",
     "deve_conter": ["598,61"], "ferramentas": [IRRF]},
    {"id": "irrf-deducoes", "categoria": "cálculo mensal",
     "pergunta": "Salário de R$ 10.000, INSS de R$ 800 e 2 dependentes. Qual o IR retido no mês?",
     "deve_conter": ["1.517,00"], "ferramentas": [IRRF]},
    {"id": "irrf-memoria", "categoria": "memória",
     "historico": [
         {"role": "user", "content": "Ganho R$ 6.000 por mês. Quanto pago de IR na fonte?"},
         {"role": "assistant", "content": "Com R$ 6.000,00 e o desconto simplificado, o IRRF mensal é de R$ 394,54."},
     ],
     "pergunta": "E se eu tiver 2 dependentes e pagar R$ 660 de INSS?",
     "deve_conter": ["275,75"], "ferramentas": [IRRF]},

    # ---------------- Cálculo: ajuste anual ----------------
    {"id": "anual-60mil", "categoria": "cálculo anual",
     "pergunta": "Ganhei R$ 5.000 todos os meses de 2026. Vou ter imposto a pagar na declaração de 2027?",
     "deve_conter_algum": [["R$ 0,00", "zero", "isento", "não terá", "não haverá"]], "ferramentas": [ANUAL]},
    {"id": "anual-saude", "categoria": "cálculo anual",
     "pergunta": "Ganho R$ 8.000 por mês, sem INSS informado, e tive R$ 20.000 de despesas médicas em 2026. "
                 "Como fica meu ajuste anual?",
     "deve_conter": ["9.995,34", "3.496,14"], "deve_conter_algum": [["restitui"]], "ferramentas": [ANUAL]},
    {"id": "anual-simplificado-teto", "categoria": "cálculo anual",
     "pergunta": "Recebo R$ 10.000 por mês e não tenho deduções. Qual o imposto devido no ajuste anual de 2026?",
     "deve_conter": ["17.244,34"], "ferramentas": [ANUAL]},

    # ---------------- Cálculo: dividendos e IRPFM ----------------
    {"id": "div-duas-empresas", "categoria": "dividendos",
     "pergunta": "Neste mês recebi R$ 60 mil de dividendos da empresa A e R$ 30 mil da empresa B. Quanto foi retido?",
     "deve_conter": ["6.000,00"], "ferramentas": [DIV]},
    {"id": "div-50mil", "categoria": "dividendos",
     "pergunta": "Uma empresa me pagou exatamente R$ 50.000 de dividendos este mês. Tem retenção de 10%?",
     "deve_conter_algum": [NEGACAO], "nao_deve_conter": ["R$ 5.000,00 de retenção"]},
    {"id": "irpfm-100k-mes", "categoria": "IRPFM",
     "pergunta": "Recebo R$ 100 mil por mês de dividendos de uma única empresa, o ano todo, e nenhuma outra renda. "
                 "Quanto pago de IRPFM no ajuste?",
     "deve_conter": ["120.000,00"], "deve_conter_algum": [["R$ 0,00", "zero", "nada a pagar", "quitad"]],
     "ferramentas": [IRPFM]},
    {"id": "irpfm-salario-dividendos", "categoria": "IRPFM",
     "pergunta": "Recebo R$ 6.500 por mês de salário e R$ 100 mil por mês de dividendos de uma empresa, sem "
                 "outras rendas nem deduções. Quanto fica o IRPFM a pagar no ajuste?",
     "deve_conter": ["2.519,54"], "ferramentas": [IRPFM]},
    {"id": "irpfm-faixa-intermediaria", "categoria": "IRPFM",
     "pergunta": "No ano tive R$ 300 mil de salário e R$ 600 mil de dividendos (R$ 50 mil por mês de uma empresa). "
                 "O IR devido no meu ajuste foi R$ 20 mil. Quanto devo de IRPFM?",
     "deve_conter": ["25.000,00"], "deve_conter_algum": [["5%", "5,00%", "5,0%"]], "ferramentas": [IRPFM]},
    {"id": "irpfm-redutor-30", "categoria": "IRPFM",
     "pergunta": "Recebo R$ 1,2 milhão por ano de dividendos (R$ 100 mil por mês, com retenção de 10%) de uma "
                 "empresa com alíquota efetiva de IRPJ+CSLL de 30%. Como fica o IRPFM?",
     "deve_conter": ["72.000,00", "48.000,00"], "ferramentas": [IRPFM]},
    {"id": "irpfm-abaixo-600k", "categoria": "IRPFM",
     "pergunta": "Tenho R$ 400 mil de salário e R$ 150 mil de dividendos no ano. Pago IRPFM?",
     "deve_conter_algum": [NEGACAO + ["não está sujeit", "isento"]], "nao_deve_conter": ["alíquota de 10%"]},

    # ---------------- Conceitos (texto da lei) ----------------
    {"id": "conc-isencao", "categoria": "conceito",
     "pergunta": "Até qual salário mensal o IR fica zerado a partir de 2026?",
     "deve_conter": ["5.000"]},
    {"id": "conc-retencao-10", "categoria": "conceito",
     "pergunta": "Como funciona a retenção de 10% sobre dividendos?",
     "deve_conter": ["50.000"], "deve_conter_algum": [["total"]],
     "nao_deve_conter": ["sobre o que exceder", "sobre o excedente", "parcela que exceder"]},
    {"id": "conc-lucros-2025", "categoria": "conceito",
     "pergunta": "Lucros de 2025 aprovados pela empresa até 31/12/2025, mas pagos só em 2027, sofrem a retenção de 10%?",
     "deve_conter_algum": [NEGACAO]},
    {"id": "conc-base-irpfm", "categoria": "conceito",
     "pergunta": "Rendimentos de poupança, LCI e LCA entram na base do IRPFM?",
     "deve_conter_algum": [NEGACAO + ["excluíd", "fora da base"]]},
    {"id": "conc-simplificado", "categoria": "conceito",
     "pergunta": "Qual o limite do desconto simplificado na declaração anual de 2027?",
     "deve_conter": ["17.640"], "nao_deve_conter": ["16.754,34"]},
    {"id": "conc-redutor", "categoria": "conceito",
     "pergunta": "Quais são os limites do redutor do IRPFM para empresas em geral, seguradoras e bancos?",
     "deve_conter": ["34%", "40%", "45%"]},
    {"id": "conc-aliquota-irpfm", "categoria": "conceito",
     "pergunta": "Qual a alíquota máxima do IRPFM e a partir de que renda ela vale?",
     "deve_conter": ["10%"], "deve_conter_algum": [["1.200.000", "1,2 milhão", "1,2 milhões"]]},
    {"id": "conc-dependente", "categoria": "conceito",
     "pergunta": "Qual o valor da dedução mensal por dependente em 2026?",
     "deve_conter": ["189,59"]},
    {"id": "conc-13", "categoria": "conceito",
     "pergunta": "A redução do imposto da Lei 15.270 vale também para o 13º salário?",
     "deve_conter_algum": [["sim", "também se aplica", "aplica-se também", "também é aplicada", "vale também"]]},

    # ---------------- Comportamento ----------------
    {"id": "comp-pede-dados", "categoria": "comportamento",
     "pergunta": "Quanto vou pagar de imposto de renda?",
     "deve_conter": ["?"], "sem_ferramentas": True},
    {"id": "comp-fora-do-escopo", "categoria": "comportamento",
     "pergunta": "Qual a alíquota do ITCMD sobre heranças no estado de São Paulo?",
     "deve_conter_algum": [["não", "fora", "não cobre", "não trata"]],
     # não pode "chutar" alíquotas que não estão nos documentos
     "nao_deve_conter": ["%"], "sem_ferramentas": True},
    {"id": "comp-premissa-errada-7350", "categoria": "comportamento",
     "pergunta": "Como a reforma deixou isento quem ganha até R$ 7.350, quem ganha R$ 7.000 não paga nada, certo?",
     "deve_conter": ["802,69"], "deve_conter_algum": [NEGACAO], "ferramentas": [IRRF]},
    {"id": "comp-premissa-errada-6000", "categoria": "comportamento",
     "pergunta": "Meu chefe disse que com salário de R$ 6.000 vou ficar isento de IR a partir de 2026. É verdade?",
     "deve_conter": ["394,54"], "deve_conter_algum": [NEGACAO], "ferramentas": [IRRF]},
]
