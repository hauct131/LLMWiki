# LLMWiki

**Convert academic papers (PDF) → High-quality Obsidian Wiki using Phi-3.5 (local LLM)**

A robust, intelligent pipeline system optimized for machines with **4GB VRAM**, using **Phi-3.5** via Ollama to transform PDF documents into complete Markdown wiki pages, ready for use in Obsidian.

---

## ✨ Key Features

- **Multi-stage pipeline** with 6 stages + intelligent fallback (FULL_LLM → TEMPLATE → HEURISTIC → RAW_EXCERPT)
- **Optimized for Phi-3.5 (3.8B)** – runs smoothly on laptops with 4GB VRAM
- **Heuristic extraction** + **LLM micro-tasks** (summaries, key points, critical analysis, open questions, concept extraction)
- **Automatic document classification** (Stage 0.5)
- **Validation & Quality Scoring** (0-100) with automatic retry & downgrade
- **Obsidian‑ready output**:
  - Full wiki pages in `vault/_sources/`
  - Concept pages in `vault/_concepts/`
  - Auto‑updated `index.md` + `log.md`
  - Sidecar JSON for debugging & traceability
- **No cloud dependency** – runs completely locally via Ollama

---

## 🛠️ Quick Setup

### 1. Clone the repository

```bash
git clone https://github.com/hauct131/LLMWiki.git
cd LLMWiki
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Install Ollama + Phi-3.5 model
```bash
ollama pull phi3.5:latest
```

---

## 🚀 Usage

```bash
python main.py path/to/your/paper.pdf
```

Example:
```bash
python main.py "papers/Attention_Is_All_You_Need.pdf"
```

After execution you will get:
- Complete wiki page in `./vault/_sources/`
- Extracted concept pages in `./vault/_concepts/`
- Automatically updated log and index

---

## 📁 Project Structure

```text
LLMWiki/
├── config/                  # System configuration
│   ├── profiles.py
│   └── settings.yaml
├── src/
│   ├── __init__.py
│   ├── config.py            # PipelineConfig & ModelProfile
│   ├── state.py             # IngestState (single source of truth)
│   ├── pipeline.py          # Main orchestrator
│   ├── prompt_runner.py
│   ├── llm_router.py
│   ├── stages/              # 6 processing stages
│   └── prompts/             # All prompts isolated
├── vault/                   # Sample Obsidian vault
│   ├── _sources/            # Output wiki pages
│   ├── _concepts/           # Concept pages
│   ├── _sidecars/           # JSON sidecar files
│   ├── index.md
│   └── .obsidian/           # Obsidian configuration
├── tests/                   # Unit tests
├── main.py                  # CLI entry point
├── requirements.txt
└── .gitignore
```

---

## 🔧 Configuration (`config.py`)

The system is extremely easy to customize:

- `model_tier`: "3b" (default), "7b", "13b+"
- `output_dir`: output directory
- `max_retries_per_level`, `temperature`, `quality thresholds`...
- All prompts are in `src/prompts/` → easy to edit without touching code

---

## 📋 Pipeline Stages

| Stage | Name          | Description                                                          |
|-------|---------------|----------------------------------------------------------------------|
| 0     | Preprocess    | Clean text, detect language, chunking                                |
| 0.5   | Classifier    | Classify document type (paper, thesis, report...)                    |
| 1     | Heuristic     | Extract title, sections, metadata, candidate links                  |
| 2     | LLM Micro-tasks | Summaries, key points, critical analysis, open questions, links, concepts |
| 3     | Assembly      | Assemble into complete Markdown template                            |
| 4     | Validation    | Quality check, flag errors                                           |
| 5     | Output        | Write files + update index + sidecar                                 |

---

## 🎯 Project Goal

Build an automatic **Personal Academic Knowledge Base** where every paper you read becomes a structured, interlinked wiki page – easy to search and expand.

---

## 📝 Todo / Roadmap

- [ ] Support more models (Llama 3.2, Gemma 2, Qwen2.5...)
- [ ] Obsidian plugin integration (auto sync)
- [ ] Web UI (Gradio / Streamlit)
- [ ] Batch processing of multiple files
- [ ] RAG for vault (semantic search)
- [ ] Comprehensive tests

---

## 🤝 Contributing

All contributions are welcome! You can:
- Report issues
- Add new stages
- Improve prompts
- Write tests

---

Made with ❤️ for Obsidian + Local LLM  
**Author:** hauct131  
**License:** MIT
```
