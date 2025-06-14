# Editais de Concurso

This project contains a Streamlit application that analyzes PDF files of public notices ("editais") using the OpenAI API.

## Installation

1. Create a virtual environment (optional) and activate it.
2. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

Store your OpenAI API key in `.streamlit/secrets.toml` so it is available to the app. The file should look like:

```toml
[general]
openai_api_key = "sk-YOUR_KEY_HERE"
```

The path `.streamlit/secrets.toml` is included in `.gitignore` to avoid accidentally committing secrets.

## Running

Launch the Streamlit app with:

```bash
streamlit run appeditais.py
```

The application will prompt for the required information and display the generated analysis.
