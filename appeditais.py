import streamlit as st
import pdfplumber
from openai import OpenAI
from docx import Document
import tempfile
import os

# Função para extrair texto do PDF
def extract_text_from_pdf(file_path_or_file):
    text = ""
    # Detecta se é caminho de arquivo (string) ou objeto file-like
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

# Função para preparar o prompt final
def montar_prompt(prompt_base, esfera, edital_ok, edital_texto):
    prompt_usuario = (
        f"O edital a ser analisado é da esfera: {esfera}.\n"
        f"Está legível e completo? {edital_ok}.\n"
        f"Segue o texto integral do edital para análise técnica, normativa e classificatória de riscos conforme o fluxo:\n\n"
        f"{edital_texto}\n"
        f"Inicie a análise conforme as instruções detalhadas no prompt-base."
    )
    return prompt_base + "\n\n" + prompt_usuario

# Função para chamar a OpenAI
def analyze_edital_via_openai(prompt, openai_api_key, model="gpt-4o"):
    client = OpenAI(api_key=openai_api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.0,
        max_tokens=4096
    )
    return response.choices[0].message.content

# Função para gerar o DOCX final (adapte para separar etapas se desejar)
def generate_docx_from_template(template_path, output_path, resposta_llm):
    doc = Document(template_path)
    # Substitui os marcadores de etapas pelo texto do relatório completo (ou adapte para separar as etapas)
    for p in doc.paragraphs:
        if "Reproduzir integralmente resultado da etapa" in p.text:
            p.text = resposta_llm
    doc.save(output_path)

# Controle de estado da conversa
if 'step' not in st.session_state:
    st.session_state.step = 0
if 'esfera' not in st.session_state:
    st.session_state.esfera = None
if 'edital_ok' not in st.session_state:
    st.session_state.edital_ok = None
if 'edital_file' not in st.session_state:
    st.session_state.edital_file = None
if 'analise_pronta' not in st.session_state:
    st.session_state.analise_pronta = False
if 'llm_resposta' not in st.session_state:
    st.session_state.llm_resposta = None

st.title("Chatbot Interativo - Análise de Editais 3ª CAP/TCE-RJ")
st.info("Bem-vindo(a)! Responda às perguntas abaixo para iniciar a análise do edital.")

# Passo 1: Perguntar esfera do edital
if st.session_state.step == 0:
    esfera = st.radio("O edital a ser analisado é Estadual ou Municipal?", ["Estadual", "Municipal"])
    if st.button("Próximo"):
        st.session_state.esfera = esfera
        st.session_state.step = 1
        st.experimental_rerun()

# Passo 2: Perguntar se edital está legível e completo
elif st.session_state.step == 1:
    edital_ok = st.radio("O edital está legível e completo?", ["Sim", "Não"])
    if st.button("Próximo"):
        st.session_state.edital_ok = edital_ok
        st.session_state.step = 2
        st.experimental_rerun()

# Passo 3: Upload do edital
elif st.session_state.step == 2:
    edital_file = st.file_uploader("Faça upload do edital em PDF", type=["pdf"])
    if edital_file:
        st.session_state.edital_file = edital_file
        if st.button("Iniciar análise automática"):
            st.session_state.step = 3
            st.experimental_rerun()

# Passo 4: Realiza análise automática e exibe resultado/download
elif st.session_state.step == 3 and not st.session_state.analise_pronta:
    with st.spinner("Extraindo texto do edital e consultando o modelo..."):
        # Lê prompt-base e template diretamente da pasta
        prompt_base = extract_text_from_pdf("prompt_edital.pdf")
        template_path = "padrao_instrucao_arq.docx"
        edital_texto = extract_text_from_pdf(st.session_state.edital_file)

        prompt_final = montar_prompt(
            prompt_base,
            st.session_state.esfera,
            st.session_state.edital_ok,
            edital_texto
        )

        resposta_llm = analyze_edital_via_openai(
            prompt_final,
            st.secrets["openai_api_key"],
            model="gpt-4o"
        )
        st.session_state.llm_resposta = resposta_llm

        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
            generate_docx_from_template(template_path, tmp.name, resposta_llm)
            tmp.seek(0)
            st.session_state.output_docx_path = tmp.name

    st.session_state.analise_pronta = True
    st.experimental_rerun()

elif st.session_state.step == 3 and st.session_state.analise_pronta:
    st.success("Análise concluída! Baixe a instrução padronizada ou visualize o relatório abaixo.")
    with open(st.session_state.output_docx_path, "rb") as f:
        st.download_button(
            label="Baixar instrução padronizada (.docx)",
            data=f,
            file_name="instrução_padronizada.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    with st.expander("Ver texto completo da análise"):
        st.write(st.session_state.llm_resposta)

    if st.button("Nova análise"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.experimental_rerun()
