# -*- coding: utf-8 -*-
import os
import unicodedata
import streamlit as st
#ola
# Importa as funções necessárias do pergunte_2.py
# A nova versão do pergunte_2.py exporta build_chain e retrieve_with_local_filter
from pergunte_2 import build_chain, retrieve_with_local_filter

# =====================  HELPERS  =====================
def build_chat_ctx(history, max_chars=1200, max_turns=6):
    """Concatena os últimos turnos (user/assistant) e corta em ~max_chars."""
    # A nova versão do pergunte_2.py não usa chat_ctx no prompt, 
    # mas mantemos a função caso o usuário queira reintroduzir a funcionalidade.
    # Por enquanto, esta função não será usada na chamada principal.
    msgs = history[-max_turns:]
    lines = []
    for m in msgs:
        role = "Usuário" if m["role"] == "user" else "Assistente"
        lines.append(f"{role}: {m['content']}")
    s = "\n".join(lines)
    # corta para não estourar contexto
    if len(s) > max_chars:
        s = "… " + s[-max_chars:]
    return s

def normalize_text(s: str) -> str:
    """Evita bugs de formatação no Markdown do Streamlit."""
    if s is None:
        return ""
    # Normaliza primeiro
    s = unicodedata.normalize("NFC", s)
    # Escapes de Markdown/MathJax
    s = s.replace("\\", "\\\\")   # barra invertida primeiro
    s = s.replace("_", "\\_")
    s = s.replace("*", "\\*")
    s = s.replace("$", "\\$")     # ESCAPE DO CIFRÃO
    s = s.replace("|", "\\|")
    return s

# =====================  API KEY (fallback)  =====================
if not os.getenv("OPENAI_API_KEY"):
    with st.sidebar:
        st.info("Defina sua chave da OpenAI (ou use o .env).")
        api_key_input = st.text_input("OPENAI_API_KEY", type="password")
        if api_key_input:
            os.environ["OPENAI_API_KEY"] = api_key_input

# =====================  CONTROLES DA UI  =====================
st.set_page_config(
    page_title="TaxBot — O Agente do Imposto de Renda",
    page_icon="💬",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# A nova versão do pergunte_2.py não usa "modo" (resumido/detalhado) no build_chain.
# Mantemos o controle na UI, mas ele não afeta a cadeia de resposta por enquanto.
modo = st.sidebar.selectbox("🧰 Nível de detalhe", ["resumido", "detalhado"], index=0)

# Opções avançadas
with st.sidebar.expander("⚙️ Opções avançadas", expanded=False):
    tipo = st.selectbox("Tipo de conteúdo", ["any", "texto", "tabela", "imagem"], index=0)
    k = st.slider("Top-k (trechos de contexto)", 3, 12, 6)

# A nova versão do pergunte_2.py não usa build_runner. 
# Usamos diretamente build_chain, que retorna a função 'run'.
if "runner" not in st.session_state or st.session_state.get("k") != k:
    # A função build_chain espera apenas o retriever_fn
    st.session_state.runner = build_chain(retrieve_with_local_filter)
    st.session_state.k = k

# Painel de debug da memória (removido, pois debug_info não existe mais)
# O usuário pode reintroduzir se criar uma função debug_info no pergunte_2.py

# =====================  ESTILO  =====================
st.markdown(
    """
    <style>
    .main .block-container {
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        min-height: 85vh;
        text-align: center;
    }
    [data-testid="stChatInput"] {
        width: 72%;
        margin: 0 auto;
    }
    .intro-text { font-size: 1.2rem; color: #ddd; margin-bottom: 2rem; line-height: 1.5; }
    .title { font-size: 1.8rem; font-weight: 600; color: #fff; margin-bottom: 0.5rem; }
    .disclaimer { opacity: .9; margin-top: 1.25rem; }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown("""
<style>
/* chat sempre alinhado à esquerda */
.stChatMessage, .stChatMessage p, .stChatMessage li, .stChatMessage ul, .stChatMessage ol {
  text-align: left !important;
}
</style>
""", unsafe_allow_html=True)

# =====================  HEADER  =====================
st.markdown(
    """
    <div class="title">💬 TaxBot — O Agente do Imposto de Renda</div>
    <div class="intro-text">
      Pergunte o que quiser sobre a Reforma do Imposto de Renda.
      Eu explico as novas regras, simulo cálculos (quando você pedir) e comparo mudanças no IRPF.
    </div>
    """,
    unsafe_allow_html=True
)
st.caption("Respostas baseadas em documentos oficiais e científicos.")

# =====================  HISTÓRICO  =====================
if "history" not in st.session_state:
    st.session_state.history = []

for m in st.session_state.history:
    with st.chat_message(m["role"]):
        st.markdown(normalize_text(m["content"]), unsafe_allow_html=False)

# =====================  CHAT INPUT  =====================
if prompt := st.chat_input("Escreva sua pergunta..."):
    # Mostra a pergunta
    st.session_state.history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(normalize_text(prompt), unsafe_allow_html=False)

    # Responde usando o runner (fonte fixa 'all')
    with st.chat_message("assistant"):
        with st.spinner("🔎 Consultando memória e calculando quando necessário..."):
            try:
                # A nova função run(q, fonte, tipo, k) não usa chat_ctx
                answer = st.session_state.runner(prompt, "all", tipo, k)
            except Exception as e:
                answer = f"⚠️ Erro: `{e}`"

        st.markdown(normalize_text(answer), unsafe_allow_html=False)
        st.session_state.history.append({"role": "assistant", "content": answer})

# =====================  AVISO FIXO  =====================
st.markdown(
    """
    <div class="disclaimer">
      ⚠️ Isto é informação geral e <u>não</u> constitui aconselhamento tributário, contábil ou jurídico.
    </div>
    """,
    unsafe_allow_html=True
)