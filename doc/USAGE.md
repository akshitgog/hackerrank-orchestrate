# Pipeline Usage Guide

This document explains how to properly run the Orchestrate pipeline, customize configuration, and select different AI providers.

## 1. Running the Pipeline

Before running the main pipeline, ensure that you have populated your API keys in the environment.

1. **Copy the environment template:**
   ```bash
   cp code/env/.env.example code/env/.env
   ```
2. **Add your API Keys to `.env`** (e.g., `AWS_ACCESS_KEY_ID`, `DEEPGRAM_API_KEY`).
3. **Execute the pipeline:**
   Make sure you set your PYTHONPATH so the `code` directory is recognized.
   
   **Windows (PowerShell):**
   ```powershell
   $env:PYTHONPATH = "code"
   python code/main.py
   ```
   
   **macOS/Linux:**
   ```bash
   PYTHONPATH=code python code/main.py
   ```

## 2. Model Configuration (`config.yaml`)

The system relies on [LiteLLM](https://docs.litellm.ai/) which allows you to hot-swap over 100+ AI providers by just changing the model prefix in `code/config/config.yaml`.

```yaml
models:
  llm_model: "bedrock/amazon.nova-micro-v1:0"
  vlm_model: "bedrock/amazon.nova-lite-v1:0"
  stt_model: "deepgram/nova-3"
```

## 3. Image Resizing (Resolution Configuration)

Different VLMs have different optimal input token sizes. 
It is your responsibility to set the `image_long_edge_px` parameter in `code/config/config.yaml` to match your VLM's ideal resolution.

Industry Standards (Recommendations):
* **Amazon Nova:** 1120px 
* **Anthropic Claude:** 1120px
* **Google Gemini:** 1536px
* **OpenAI GPT-4o:** 1024px

By setting this value, you guarantee you don't overspend on tokens while avoiding rate limits or "Payload Too Large" errors (e.g., AWS Bedrock's 5MB cap).
