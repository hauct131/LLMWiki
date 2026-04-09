# 📚 LLMWiki

**Convert Academic Papers (PDF) → Structured Obsidian Wiki using Phi-3.5**

A production-ready pipeline that intelligently transforms PDF documents and text files into complete, interconnected Markdown wiki pages optimized for Obsidian. Purpose-built for machines with **4GB VRAM** using **Phi-3.5** via Ollama.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Language: Python](https://img.shields.io/badge/Language-Python-blue.svg)](#)

---

## ✨ Key Features

### 🔄 Multi-Level Pipeline (6 Stages + Fallback)
- **Stage 0**: Text preprocessing, cleaning, language detection
- **Stage 0.5**: Document classification (Scientific Paper, Benchmark, News, etc.)
- **Stage 1**: Heuristic extraction (title, sections, metadata, candidate links)
- **Stage 2**: LLM micro-tasks (8 parallel subtasks: P0-P8)
- **Stage 3**: Template assembly → Markdown wiki page
- **Stage 4**: Quality validation (0-100 scoring)
- **Stage 5**: File output + vault index management

**Automatic fallback mechanism**: If quality drops below threshold → downgrades to next level (LLM → Heuristic → Raw Excerpt)

### 8 LLM Micro-Tasks (P0-P8)
- **P0**: Extract title
- **P0.5**: Classify document type (SCIENTIFIC_PAPER, BENCHMARK_PAPER, etc.)
- **P1**: Extract authors and publication year
- **P2**: Generate 3-sentence summary
- **P3**: List key methods/techniques
- **P4**: Critical analysis (strengths, weaknesses)
- **P5**: Identify open research questions
- **P6**: Extract and normalize technical concepts
- **P7**: Rate research importance (1-5 scale)
- **P8**: Generate concept wiki stubs

Each task is **fully isolated** — one failure never blocks others. If LLM fails, heuristic fallback fills the gap.

### 💻 Optimized for Resource-Constrained Machines
- **Runs smoothly on 4GB VRAM** with Phi-3.5 (3.8B)
- Model profiles for 3B, 7B, and 13B+ models
- Automatic context window overflow detection (35k chars default)
- Temperature reduction on retry for better stability

### 🎯 Intelligent Routing
- **Multi-backend LLM support**:
  - Priority 1: Gemini API (with key rotation + rate limiting)
  - Priority 2: OpenAI-compatible remote APIs
  - Priority 3: Ollama (local fallback)
- HTTP-based with timeout protection — no hung processes

### 🔗 Cross-Paper Intelligence
- **Automatic vault linking** (via Vault Linker):
  - Typed relationships: `[[uses::Paper A]]`, `[[vs::Paper B]]`, `[[domain::Paper C]]`
  - Concept normalization across papers
  - Hub pages for recurring concepts
  - Domain detection (CV, NLP, General)

### 🧠 Constrained Vocabulary System
- All concepts normalized to **canonical vocabulary**
- Prevents 120 unique "Sentiment Analysis" variants
- Guarantees cross-paper linking by construction

### 📊 Batch Processing + Parallel Execution
- Process **multiple PDF/text files** in one run
- Configurable parallel workers (default: 2)
- Progress bar with tqdm
- Smart error recovery for each file

### 🗂️ Obsidian-Ready Output
- `vault/_sources/`: Complete wiki pages (one per paper)
- `vault/_concepts/`: Auto-generated concept hubs
- `vault/index.md`: Auto-updated central index
- `vault/log.md`: Processing history with timestamps
- Sidecar JSON files: Full execution state for debugging

### ✅ Quality Assurance
- **Quality scoring** (0-100 scale):
  - `≥70`: "processed" status
  - 30-70: "needs-review" status
  - `<30`: "stub" status
- **Validation flags**: Tracks missing/incomplete sections
- **Never fails**: Even worst-case produces Level 4 stub page

---

## 🛠️ Quick Start

### Prerequisites
- **Python 3.8+**
- **Ollama** ([download](https://ollama.ai))
- **4GB VRAM minimum** (8GB+ for faster processing)

### Installation

```bash
# 1. Clone repository
git clone https://github.com/hauct131/LLMWiki.git
cd LLMWiki

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Ollama and Phi-3.5 model
ollama pull phi3.5:latest

# 4. Start Ollama server (if not running as daemon)
ollama serve &
```

### Usage

#### Single File
```bash
python main.py path/to/paper.pdf
```

#### Batch Processing
```bash
# Process entire directory
python main.py papers/

# Process with custom workers
python main.py papers/ --workers 4

# Change model tier
python main.py papers/ --model-tier 7b
```

#### Output
- ✅ Wiki pages: `./vault/_sources/`
- ✅ Concepts: `./vault/_concepts/`
- ✅ Index: `./vault/index.md`
- ✅ Log: `./vault/log.md`

---

## 📋 Pipeline Stages Explained

### Stage 0: Preprocessing
- Strips HTML tags, fixes encoding issues (smart quotes, ligatures)
- Removes academic noise (references, headers, page numbers)
- Detects language, normalizes whitespace
- **Output**: `cleaned_text`, `detected_language`, `source_char_count`

### Stage 0.5: Document Classification
- Determines document type via LLM
- Categories: SCIENTIFIC_PAPER, BENCHMARK_PAPER, TECHNICAL_DOCUMENTATION, NEWS_ARTICLE, OTHER
- **Output**: `extracted_metadata["category"]`

### Stage 1: Heuristic Extraction
- **No LLM** — pure regex/rule-based
- Extracts: title, 7 standard sections (abstract, intro, methodology, experiments, conclusion, related work, limitations), metadata, candidate links
- Falls back to filename/first line if no title found
- **Output**: `extracted_title`, `extracted_sections`, `extracted_metadata`, `candidate_links`

### Stage 2: LLM Micro-Tasks
- Runs **8 independent prompts** (P0-P8)
- Each task has its own validation contract
- On failure: uses heuristic fallback immediately
- **Output**: `summary`, `key_points`, `critical_analysis`, `open_questions`, `confirmed_links`, `concept_pages`

### Stage 3: Assembly
- Combines all extracted/LLM data into structured Markdown template
- Includes YAML frontmatter with metadata
- **Output**: `structured_page`

### Stage 4: Validation
- Checks completeness: title, summary length, sections presence
- Computes quality score (0-100)
- Sets page status: "processed" / "needs-review" / "stub"
- **Output**: `quality_score`, `validation_status`, `page_status`

### Stage 5: Output
- Writes Markdown to `vault/_sources/`
- Creates concept hub pages in `vault/_concepts/`
- Updates `index.md` and `log.md`
- Saves sidecar JSON with full state
- **Output**: `files_written`, `sidecar_path`

---

## ⚙️ Configuration

### Model Profiles

```python
# 3B (Default - 4GB VRAM)
ModelProfile(
    max_input_chars=4000,
    max_output_tokens=1024,
    summary_sentences=3,
    key_methods_count=4,
    terms_count=10,
    temperature=0.1,
    fallback_threshold="normal"
)

# 7B (8GB VRAM)
ModelProfile(
    max_input_chars=1500,
    max_output_tokens=300,
    temperature=0.2,
    fallback_threshold="normal"
)

# 13B+ (16GB+ VRAM)
ModelProfile(
    max_input_chars=3000,
    max_output_tokens=600,
    temperature=0.3,
    fallback_threshold="relaxed"
)
```

### Runtime Config (src/config.py)

```python
from src.config import PipelineConfig

config = PipelineConfig(
    # LLM backend
    model_tier="3b",                          # "3b" | "7b" | "13b+"
    api_base_url="http://localhost:11434",   # Ollama endpoint
    api_model_name="phi3.5:latest",          # Model name
    api_timeout_secs=60,
    
    # Gemini API (optional)
    gemini_api_keys=["key1", "key2"],        # Key rotation
    gemini_model_name="gemini-2.0-flash",
    
    # Output paths
    output_dir="./vault/_sources",
    concepts_dir="./vault/_concepts",
    index_path="./vault/index.md",
    log_path="./vault/log.md",
    sidecar_dir="./vault/_sidecars",
    
    # Quality gates
    min_score_processed=60,      # ≥60 → "processed"
    min_score_needs_review=30,   # 30-60 → "needs-review"
    
    # Context & retry
    context_window_chars=35_000,
    max_retries_per_level=1,
    retry_temperature_delta=-0.05,
)
```

---

## 📁 Project Structure

```
LLMWiki/
├── main.py                      # CLI entry point
├── requirements.txt
├── src/
│   ├── config.py               # PipelineConfig & ModelProfile
│   ├── state.py                # IngestState (single source of truth)
│   ├── pipeline.py             # Main orchestrator with fallback logic
│   ├── prompt_runner.py        # Executes prompt contracts
│   ├── llm_router.py           # Multi-backend LLM routing + rate limiting
│   ├── batch_pipeline.py       # Batch processing + parallel execution
│   ├── vault_linker.py         # Cross-paper linking & concept normalization
│   ├── stages/
│   │   ├── s0_preprocess.py
│   │   ├── s0_5_classifier.py
│   │   ├── s1_heuristic.py
│   │   ├── s2_llm_tasks.py
│   │   ├── s3_assembly.py
│   │   ├── s4_validator.py
│   │   └── s5_output.py
│   ├── prompts/
│   │   ├── contracts.py        # 8 prompt contracts (P0-P8)
│   │   └── templates.py
│   └── utils/
│       ├── clean_terms.py      # Term deduplication
│       └── concept_normalizer.py  # Vocabulary mapping
├── vault/
│   ├── _sources/              # Output wiki pages
│   ├── _concepts/             # Concept hubs
│   ├── _sidecars/             # JSON state files
│   ├── index.md
│   └── log.md
└── tests/

```

---

## 🔍 Data Flow

```
PDF/Text Input
    ↓
[S0] Preprocess
    ├─ Clean text
    ├─ Detect language
    └─ Check context window
    ↓
[S0.5] Classify
    └─ Document type detection
    ↓
[S1] Heuristic (ALWAYS)
    ├─ Extract title, sections
    ├─ Extract metadata
    └─ Candidate links (regex)
    ↓
[S2] LLM Tasks (P0-P8)
    ├─ P0: Title (LLM)
    ├─ P1: Authors + Date
    ├─ P2: Summary
    ├─ P3: Key Methods
    ├─ P4: Strengths/Weaknesses
    ├─ P5: Open Questions
    ├─ P6: Technical Terms (constrained vocab)
    ├─ P7: Importance
    └─ P8: Concept Stubs
    
    [Quality check]
    ├─ Score ≥ 40? → Continue
    └─ Score < 40? → Retry or Downgrade
    ↓
[S3] Assembly → Markdown template
    ↓
[S4] Validation → Quality score
    ↓
    ├─ Status PASSED?
    └─ Status FAILED? → Downgrade & retry
    ↓
[S5] Output
    ├─ Write wiki page
    ├─ Write concepts
    └─ Update index + log
```

---

## 🌐 LLM Routing & Multi-Backend Support

### Backend Priority

```python
# llm_router.py routing logic:

1. Gemini API (if gemini_api_keys set)
   ├─ Key rotation (cycle through keys)
   ├─ Rate limiting (2 req/sec, 15 req/min)
   ├─ 429 handling (automatic key skip)
   └─ Exponential backoff on exhaustion

2. OpenAI-compatible (if use_remote_api=True)
   └─ Standard /v1/chat/completions endpoint

3. Ollama (always available)
   └─ Local inference, no API calls
```

### Rate Limiting

```python
# Gemini API key rotation
config.gemini_api_keys = ["key1", "key2", "key3"]  # Read from env: GEMINI_API_KEYS

# Rate limiting automatically applied:
# - Min 0.5s between requests
# - 15 requests/minute max
# - 429 errors trigger automatic key switch
```

---

## 🔗 Vault Linker: Cross-Paper Intelligence

### Typed Links

Links between papers use semantic relations:

```markdown
## Related Papers

- [[uses::BERT]]           # This paper uses BERT
- [[vs::GPT-2]]           # Compares against GPT-2
- [[domain::NLP]]         # Related to NLP domain
```

### Concept Hub Pages

Auto-generated pages for recurring concepts:

```markdown
---
title: "Attention Mechanism"
type: concept
domain: nlp
paper_count: 7
created_date: 2024-01-01
updated_date: 2024-01-15
---

## Definition
> Neural mechanism that weights different input features...

## Papers Using This Concept
- [[BERT|Bidirectional Encoders...]]
- [[Transformer|Attention Is All You Need]]
- [[T5|Text-to-Text Transfer Transformer]]

---
*Auto-generated by Vault Linker*
```

### Domain-Specific Concept Mapping

```python
# Automatic domain detection:
# - CV (Computer Vision): SISR, CNN, GAN, ResNet, PSNR, SSIM, ...
# - NLP: BERT, Transformer, Attention, Sentiment Analysis, NER, SemEval, ...
# - General: Deep Learning, Transfer Learning, Knowledge Graph, ...

# Example normalization:
"sisr"  → "Single Image Super-Resolution"
"bert"  → "BERT"
"sentiment analysis" → "Sentiment Analysis"
"GAN"   → "Generative Adversarial Network"
```

---

## 📊 Quality Metrics

### Quality Score Calculation

```python
# Computed in s4_validator.py
quality_score = 0

# Presence checks (binary)
+ 20 if summary exists and > 20 words
+ 15 if extracted_title exists
+ 15 if key_points count ≥ 2
+ 15 if critical_analysis has strengths + weaknesses
+ 10 if open_questions ≥ 2
+ 10 if confirmed_links ≥ 3
+ 15 if metadata complete (author, year, etc.)
```

### Page Status Decision

```python
quality_score ≥ 70  → status = "processed"     (ready for use)
30 ≤ score < 70     → status = "needs-review"  (manual editing recommended)
score < 30          → status = "stub"          (placeholder, incomplete)
```

---

## 🚀 Advanced Usage

### Custom Model Backend

```bash
# Use 7B model
python main.py paper.pdf --model-tier 7b

# Use remote OpenAI-compatible API
# Set env vars:
export OPENAI_API_KEY="sk-..."
export OPENAI_API_BASE="https://api.openai.com/v1"

# Then modify config.py:
config.use_remote_api = True
config.remote_api_key = os.getenv("OPENAI_API_KEY")
config.api_base_url = os.getenv("OPENAI_API_BASE")
```

### Using Gemini API

```bash
# Set API keys (supports rotation)
export GEMINI_API_KEYS="key1,key2,key3"

# Or single key:
export GEMINI_API_KEY="AIzaSy..."

# Auto-selects Gemini if keys are set
python main.py papers/
```

### Custom Output Directory

```bash
python main.py papers/ \
  --output-dir /custom/vault/_sources \
  --concepts-dir /custom/vault/_concepts
```

### Debugging with Sidecar JSON

```bash
# Check full execution state
cat vault/_sidecars/paper_name.json | jq '.stages'

# See quality score reasoning
cat vault/_sidecars/paper_name.json | jq '.validation_flags'

# Check LLM outputs for each task
cat vault/_sidecars/paper_name.json | jq '.llm_results'
```

---

## 🔧 Troubleshooting

### "Connection refused" (Ollama not running)
```bash
# Start Ollama server
ollama serve

# In another terminal:
python main.py paper.pdf
```

### "Out of memory" errors
```bash
# Use smaller model
python main.py paper.pdf --model-tier 3b

# Or increase system swap
# Linux: sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
```

### PDF extraction produces garbage
```bash
# Check if PDF is text-based (not scanned image)
# PDF scanning requires OCR (not implemented yet)
# Workaround: convert to PDF/A via online tool first
```

### Quality scores consistently low
- Increase `context_window_chars` in config if document is long
- Reduce `temperature` for more conservative outputs
- Check if PDF cleaning is removing too much content (Stage 0)

### Cross-paper linking not working
```bash
# Manually run Vault Linker after batch processing
python -c "from src.vault_linker import run_vault_linker; run_vault_linker('vault/_sources')"
```

---

## 📚 Use Cases

### Personal Research Library
- Index all papers you read
- Auto-generate concept maps
- Find cross-paper connections

### Literature Reviews
- Batch process all papers in a domain
- Auto-extract key findings per paper
- Generate concept hubs for systematic mapping

### Knowledge Base Building
- Papers → structured wiki
- Concepts → linked hub pages
- Ready for Obsidian Graph View

---

## 🤝 Contributing

Issues and PRs welcome! Areas for contribution:

- Better PDF text extraction
- OCR support for scanned papers
- Additional model backends
- Prompt optimization
- Test coverage
- Documentation

---

## 📄 License

MIT — See LICENSE file

---

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/hauct131/LLMWiki/issues)
- **Author**: [@hauct131](https://github.com/hauct131)

---

**Made with ❤️ for Obsidian + Local LLM**

Last updated: April 2026
