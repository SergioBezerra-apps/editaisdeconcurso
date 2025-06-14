import streamlit as st
import pdfplumber
from openai import OpenAI
import openai
from docx import Document
import tempfile
import tiktoken
import os

# Diretório base do projeto para montar paths relativos
BASE_DIR = os.path.dirname(__file__)

# ──────────────────────────────────────
# Configurações gerais
# ──────────────────────────────────────
MODEL_DEFAULT   = "gpt-4o-mini"    # 128 k
MODEL_FALLBACK  = "gpt-4.1-mini"   # 1  M
TOKEN_THRESHOLD = 120_000          # acima → fallback

# preços (USD / 1M tokens)  – jun/2025
PRICING = {
    "gpt-4o-mini":  {"in": 0.15, "out": 0.60},
    "gpt-4.1-mini": {"in": 0.40, "out": 1.60},
}

# ──────────────────────────────────────
# Funções utilitárias
# ──────────────────────────────────────
def _get_encoding(model):
    """Garantir encoding mesmo se o modelo ainda não constar no tiktoken."""
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")  # fallback genérico

def count_tokens(text: str, model: str = MODEL_DEFAULT) -> int:
    return len(_get_encoding(model).encode(text))

def choose_model(n_tokens: int) -> str:
    return MODEL_DEFAULT if n_tokens <= TOKEN_THRESHOLD else MODEL_FALLBACK

def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pin  = PRICING[model]["in"]  * (prompt_tokens     / 1_000_000)
    pout = PRICING[model]["out"] * (completion_tokens / 1_000_000)
    return round(pin + pout, 4)

def extract_text_from_pdf(file):
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text

def montar_prompt(prompt_base, esfera, edital_ok, edital_texto):
    prompt_usuario = (
        f"O edital a ser analisado é da esfera: {esfera}.\n"
        f"Está legível e completo? {edital_ok}.\n"
        "Segue o texto integral do edital para análise técnica, normativa e "
        "classificatória de riscos conforme o fluxo:\n\n"
        f"{edital_texto}\n"
        "Inicie a análise conforme as instruções detalhadas no prompt-base."
    )
    return prompt_base + "\n\n" + prompt_usuario

def call_openai_stream(prompt: str, model: str, api_key: str):
    client = OpenAI(api_key=api_key)
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        stream=True
    )

    placeholder = st.empty()
    collected_text = ""

    for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        if delta:
            collected_text += delta
            placeholder.markdown(collected_text)

    completion_tokens = count_tokens(collected_text, model=model)
    return collected_text, completion_tokens

def generate_docx_from_template(template_path, output_path, texto):
    doc = Document(template_path)
    for p in doc.paragraphs:
        if "Reproduzir integralmente resultado da etapa" in p.text:
            p.text = texto
    doc.save(output_path)

# ──────────────────────────────────────
# Session state inicial
# ──────────────────────────────────────
defaults = {
    "step": 0, "esfera": None, "edital_ok": None,
    "edital_file": None, "analise_pronta": False,
    "llm_resposta": None, "token_in": 0, "token_out": 0,
    "modelo_usado": None, "output_docx_path": None
}
for k, v in defaults.items():
    st.session_state.setdefault(k, v)

# ──────────────────────────────────────
# UI / Chatbot
# ──────────────────────────────────────
st.title("Editais 3ª CAP/TCE-RJ")
st.info("Bem-vindo(a)! Responda às perguntas abaixo para iniciar a análise do edital.")

# Passo 0 – esfera
if st.session_state.step == 0:
    esfera = st.radio("O edital a ser analisado é Estadual ou Municipal?",
                      ["Estadual", "Municipal"])
    if st.button("Próximo"):
        st.session_state.esfera = esfera
        st.session_state.step = 1
        st.experimental_rerun()

# Passo 1 – legibilidade
elif st.session_state.step == 1:
    edital_ok = st.radio("O edital está legível e completo?", ["Sim", "Não"])
    if st.button("Próximo"):
        st.session_state.edital_ok = edital_ok
        st.session_state.step = 2
        st.experimental_rerun()

# Passo 2 – upload
elif st.session_state.step == 2:
    edital_file = st.file_uploader("Faça upload do edital em PDF", type=["pdf"])
    if edital_file:
        st.session_state.edital_file = edital_file
        if st.button("Iniciar análise"):
            st.session_state.step = 3
            st.experimental_rerun()

# Passo 3 – processamento
elif st.session_state.step == 3 and not st.session_state.analise_pronta:
    with st.spinner("Processando… isso pode levar alguns minutos."):
        prompt_base  = extract_text_from_pdf(
            os.path.join(BASE_DIR, "prompt_edital.pdf")
        )
        edital_texto = extract_text_from_pdf(st.session_state.edital_file)
        prompt_final = montar_prompt(
            prompt_base,
            st.session_state.esfera,
            st.session_state.edital_ok,
            edital_texto
        )

        token_in   = count_tokens(prompt_final)
        modelo_sel = choose_model(token_in)

        st.info(f"Modelo selecionado: **{modelo_sel}** "
                f"(tokens de entrada: {token_in:,})")

        try:
            resposta, token_out = call_openai_stream(
                prompt_final, modelo_sel, st.secrets["openai_api_key"]
            )
        except openai.OpenAIError as e:
            st.error(f"Erro na API OpenAI: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Erro inesperado: {e}")
            st.stop()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
            generate_docx_from_template(
                os.path.join(BASE_DIR, "padrao_instrucao_arq.docx"),
                tmp.name,
                resposta,
            )
            tmp.seek(0)
            st.session_state.output_docx_path = tmp.name

        # Guarda no estado
        st.session_state.llm_resposta   = resposta
        st.session_state.token_in       = token_in
        st.session_state.token_out      = token_out
        st.session_state.modelo_usado   = modelo_sel
        st.session_state.analise_pronta = True
        st.experimental_rerun()

# Passo 4 – resultado
elif st.session_state.step == 3 and st.session_state.analise_pronta:
    cost = estimate_cost(
        st.session_state.modelo_usado,
        st.session_state.token_in,
        st.session_state.token_out
    )

    st.success("✅ Análise concluída!")
    st.markdown(
        f"""**Uso desta execução**  
        • Modelo: `{st.session_state.modelo_usado}`  
        • Prompt tokens: `{st.session_state.token_in}`  
        • Completion tokens: `{st.session_state.token_out}`  
        • **Custo estimado:** **${cost}**"""
    )

    with open(st.session_state.output_docx_path, "rb") as f:
        st.download_button(
            "⬇️ Baixar instrução (.docx)",
            data=f,
            file_name="instrucao_padronizada.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    with st.expander("🔍 Ver texto completo da análise"):
        st.write(st.session_state.llm_resposta)

    if st.button("Nova análise"):
        for k in list(st.session_state.keys()):
            st.session_state.pop(k)
        st.experimental_rerun()
