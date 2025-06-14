import streamlit as st
import pdfplumber
from openai import OpenAI, AsyncOpenAI
from docx import Document
import tempfile
import os
import tiktoken

# ────────────────────────────────────────────────────────────
# CONFIGURAÇÕES GERAIS
# ────────────────────────────────────────────────────────────
MODEL_DEFAULT = "gpt-4o-mini"      # até 128k  tokens
MODEL_FALLBACK = "gpt-4.1-mini"    # até 1M    tokens
TOKEN_THRESHOLD = 120_000          # se ultrapassar → usa fallback

# preços (USD por 1M tokens) – jun/2025
PRICING = {
    "gpt-4o-mini":   {"in": 0.15, "out": 0.60},
    "gpt-4.1-mini":  {"in": 0.40, "out": 1.60},
}

# ────────────────────────────────────────────────────────────
# FUNÇÕES AUXILIARES
# ────────────────────────────────────────────────────────────
def extract_text_from_pdf(file_path_or_file):
    text = ""
    if isinstance(file_path_or_file, str):
        pdf_source = open(file_path_or_file, 'rb')
    else:
        pdf_source = file_path_or_file
    with pdfplumber.open(pdf_source) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    if isinstance(file_path_or_file, str):
        pdf_source.close()
    return text

def montar_prompt(prompt_base, esfera, edital_ok, edital_texto):
    prompt_usuario = (
        f"O edital a ser analisado é da esfera: {esfera}.\n"
        f"Está legível e completo? {edital_ok}.\n"
        f"Segue o texto integral do edital para análise técnica, normativa e classificatória de riscos conforme o fluxo:\n\n"
        f"{edital_texto}\n"
        f"Inicie a análise conforme as instruções detalhadas no prompt-base."
    )
    return prompt_base + "\n\n" + prompt_usuario

def count_tokens(text, model="gpt-4o-mini"):
    enc = tiktoken.encoding_for_model(model)
    return len(enc.encode(text))

def choose_model(n_tokens):
    return MODEL_DEFAULT if n_tokens <= TOKEN_THRESHOLD else MODEL_FALLBACK

def estimate_cost(model, prompt_tokens, completion_tokens):
    price_in  = PRICING[model]["in"]  * (prompt_tokens     / 1_000_000)
    price_out = PRICING[model]["out"] * (completion_tokens / 1_000_000)
    return round(price_in + price_out, 4)

# │ OpenAI chamada síncrona, com stream=True para latência percebida menor
def call_openai_stream(prompt, model, api_key):
    client = OpenAI(api_key=api_key)
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        stream=True          # ← STREAMING
    )
    collected_chunks = []
    collected_text = ""
    for chunk in stream:
        chunk_text = chunk.choices[0].delta.content or ""
        collected_text += chunk_text
        collected_chunks.append(chunk)
        # imprime enquanto recebe
        st.write(chunk_text, end="")  # mostra incrementalmente
    # usage só aparece no último chunk
    usage = collected_chunks[-1].usage
    return collected_text, usage

def generate_docx_from_template(template_path, output_path, resposta_llm):
    doc = Document(template_path)
    for p in doc.paragraphs:
        if "Reproduzir integralmente resultado da etapa" in p.text:
            p.text = resposta_llm
    doc.save(output_path)

# ────────────────────────────────────────────────────────────
# ESTADO DA CONVERSA
# ────────────────────────────────────────────────────────────
for key, default in {
    "step": 0, "esfera": None, "edital_ok": None,
    "edital_file": None, "analise_pronta": False,
    "llm_resposta": None, "usage": None, "modelo_usado": None
}.items():
    st.session_state.setdefault(key, default)

st.title("Chatbot Interativo – Análise de Editais (3ª CAP / TCE-RJ)")

# ────────────────────────────────────────────────────────────
# ETAPAS DO CHATBOT
# ────────────────────────────────────────────────────────────
if st.session_state.step == 0:
    esfera = st.radio("O edital a ser analisado é:", ["Estadual", "Municipal"])
    if st.button("Próximo"):
        st.session_state.esfera = esfera
        st.session_state.step = 1
        st.experimental_rerun()

elif st.session_state.step == 1:
    edital_ok = st.radio("O edital está legível e completo?", ["Sim", "Não"])
    if st.button("Próximo"):
        st.session_state.edital_ok = edital_ok
        st.session_state.step = 2
        st.experimental_rerun()

elif st.session_state.step == 2:
    edital_file = st.file_uploader("Faça upload do edital em PDF", type=["pdf"])
    if edital_file:
        st.session_state.edital_file = edital_file
        if st.button("Iniciar análise"):
            st.session_state.step = 3
            st.experimental_rerun()

# ── Passo 3: processamento
elif st.session_state.step == 3 and not st.session_state.analise_pronta:
    with st.spinner("Processando… isso pode levar alguns minutos."):
        prompt_base  = extract_text_from_pdf("prompt_edital.pdf")
        template_doc = "padrao_instrucao_arq.docx"
        edital_texto = extract_text_from_pdf(st.session_state.edital_file)

        prompt_final = montar_prompt(
            prompt_base,
            st.session_state.esfera,
            st.session_state.edital_ok,
            edital_texto
        )

        n_tokens = count_tokens(prompt_final, model=MODEL_DEFAULT)
        modelo   = choose_model(n_tokens)

        st.info(f"Modelo selecionado: **{modelo}**  •  Tokens de entrada estimados: **{n_tokens:,}**")

        resposta, usage = call_openai_stream(
            prompt=prompt_final,
            model=modelo,
            api_key=st.secrets["openai_api_key"]
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
            generate_docx_from_template(template_doc, tmp.name, resposta)
            tmp.seek(0)
            st.session_state.output_docx_path = tmp.name

        st.session_state.llm_resposta = resposta
        st.session_state.usage = usage
        st.session_state.modelo_usado = modelo
        st.session_state.analise_pronta = True
        st.experimental_rerun()

# ── Passo 4: resultados
elif st.session_state.step == 3 and st.session_state.analise_pronta:
    usage = st.session_state.usage
    modelo = st.session_state.modelo_usado
    cost_est = estimate_cost(
        modelo,
        usage.prompt_tokens,
        usage.completion_tokens
    )

    st.success("✅ Análise concluída!")
    st.markdown(
        f"""**Resumo de uso**  
        • Modelo: `{modelo}`  
        • Prompt tokens: `{usage.prompt_tokens}`  
        • Completion tokens: `{usage.completion_tokens}`  
        • **Custo estimado:** **${cost_est}**"""
    )

    with open(st.session_state.output_docx_path, "rb") as f:
        st.download_button(
            label="⬇️ Baixar instrução (.docx)",
            data=f,
            file_name="instrucao_padronizada.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    with st.expander("📝 Ver texto completo da análise"):
        st.write(st.session_state.llm_resposta)

    if st.button("Nova análise"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.experimental_rerun()
