# -*- coding: utf-8 -*-
import os

import streamlit as st

from agente import LimiteDeUsoError, TaxBot

st.set_page_config(
    page_title="TaxBot — O Agente do Imposto de Renda",
    page_icon="💬",
    layout="centered",
)

EXEMPLOS = [
    "Ganho R$ 6.500 por mês. Quanto vou pagar de IR em 2026?",
    "Como funciona a retenção de 10% sobre dividendos?",
    "Recebo R$ 80 mil por mês de dividendos de uma empresa. Quanto pago de IRPFM?",
    "O que muda para quem ganha até R$ 5 mil?",
]


# =====================  HELPERS  =====================
def escapar_cifrao(s: str) -> str:
    """O Markdown do Streamlit interpreta $...$ como LaTeX; escapa só o cifrão e preserva o resto da formatação."""
    return (s or "").replace("$", "\\$")


def chave_gemini() -> str | None:
    try:
        return st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    except FileNotFoundError:  # sem secrets.toml local
        return os.getenv("GEMINI_API_KEY")


@st.cache_resource(show_spinner="Carregando a base de conhecimento...")
def carregar_agente(api_key: str) -> TaxBot:
    return TaxBot(api_key=api_key)


def mostrar_detalhes(fontes, ferramentas):
    if ferramentas:
        with st.expander("🧮 Cálculos executados"):
            for f in ferramentas:
                st.markdown(f"**`{f['nome']}`**")
                st.json(f["argumentos"], expanded=False)
    if fontes:
        with st.expander("📚 Trechos consultados"):
            for t in fontes:
                selo = " · ✅ oficial" if t.get("oficial") else ""
                st.markdown(f"**{t['fonte']}**, p. {t['pagina']}{selo}")
                st.caption(escapar_cifrao(t["texto"][:400]) + "…")


# =====================  SETUP  =====================
api_key = chave_gemini()
if not api_key:
    st.error(
        "A chave do Gemini não está configurada. Defina `GEMINI_API_KEY` em `.streamlit/secrets.toml` "
        "(local) ou em *Settings → Secrets* no Streamlit Community Cloud."
    )
    st.stop()

try:
    agente = carregar_agente(api_key)
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

if "history" not in st.session_state:
    st.session_state.history = []

with st.sidebar:
    st.markdown("### TaxBot Alpha")
    st.caption("Baseado na Lei 15.270/2025 (reforma do IR, vigente desde 01/2026).")
    if st.button("🗑️ Limpar conversa", use_container_width=True):
        st.session_state.history = []
        st.rerun()

# =====================  HEADER  =====================
st.title("💬 TaxBot")
st.markdown(
    "Pergunte o que quiser sobre a **reforma do Imposto de Renda**. Eu explico as novas regras, "
    "simulo cálculos e comparo o que muda no IRPF."
)

# =====================  HISTÓRICO  =====================
for m in st.session_state.history:
    with st.chat_message(m["role"]):
        st.markdown(escapar_cifrao(m["content"]))
        if m["role"] == "assistant":
            mostrar_detalhes(m.get("fontes"), m.get("ferramentas"))

# =====================  ENTRADA  =====================
pergunta = st.chat_input("Escreva sua pergunta...")

if not st.session_state.history and not pergunta:
    st.markdown("**Experimente:**")
    cols = st.columns(2)
    for i, ex in enumerate(EXEMPLOS):
        if cols[i % 2].button(ex, key=f"ex{i}", use_container_width=True):
            pergunta = ex

if pergunta:
    historico_anterior = [{"role": m["role"], "content": m["content"]} for m in st.session_state.history]
    st.session_state.history.append({"role": "user", "content": pergunta})
    with st.chat_message("user"):
        st.markdown(escapar_cifrao(pergunta))

    with st.chat_message("assistant"):
        fontes, ferramentas = [], []
        with st.spinner("🔎 Consultando os documentos e calculando..."):
            try:
                r = agente.responder(pergunta, historico_anterior)
                texto, fontes, ferramentas = r.texto, r.fontes, r.ferramentas
            except LimiteDeUsoError as e:
                texto = f"⏳ {e}"
            except Exception as e:  # noqa: BLE001 — mostra o erro ao usuário em vez de quebrar a página
                texto = f"⚠️ Erro inesperado: `{e}`"
        st.markdown(escapar_cifrao(texto))
        mostrar_detalhes(fontes, ferramentas)

    st.session_state.history.append(
        {"role": "assistant", "content": texto, "fontes": fontes, "ferramentas": ferramentas}
    )
    if len(st.session_state.history) == 2:
        st.rerun()  # tira os botões de exemplo da tela

st.caption(
    "⚠️ Informação geral: **não** constitui aconselhamento tributário, contábil ou jurídico."
)
