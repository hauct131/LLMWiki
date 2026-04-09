"""
src/utils/concept_normalizer.py
Concept Normalizer — maps any LLM-generated variant to the canonical name.

Design:
  - CANONICAL_VOCABULARY: master list of all allowed concept names
  - _ALIAS_TO_CANONICAL: reverse lookup (lowercase variant → canonical)
  - normalize_concept(): returns canonical or best-effort cleaned name
  - get_vocabulary_for_prompt(): used by P6 to constrain LLM output
"""

from typing import Dict, List
import re

# ===================================================================
# CANONICAL VOCABULARY  (source of truth — add new concepts here)
# Format: { "Canonical Name": ["alias1", "alias2", ...] }
# ===================================================================

CANONICAL_VOCABULARY: Dict[str, List[str]] = {

    # ── NLP: Models & Architectures ──────────────────────────────────
    "BERT": [
        "bert", "bert model", "bidirectional encoder representations",
        "bidirectional encoder representations from transformers",
        "bert representations", "bert pretrained",
    ],
    "Transformer": [
        "transformer", "transformers", "transformer model", "transformer architecture",
        "vanilla transformer", "transformer encoder", "transformer decoder",
        "transformer and bert", "transformer and bert methods",
    ],
    "GPT": ["gpt", "generative pre-trained transformer", "gpt model"],
    "ELMo": ["elmo", "embeddings from language models", "elmo and gpt", "elmo and gpt models"],
    "Word2Vec": [
        "word2vec", "word 2 vec", "cbow", "skip-gram", "skipgram",
        "word vector", "word vectors", "word embedding", "word embeddings",
        "distributed representation", "distributed representations",
        "vector space model", "vector representation",
    ],
    "GloVe": [
        "glove", "global vectors", "global log-bilinear regression",
        "global log linear regression", "global log-linear regression model",
        "global log linear regression model for word representations",
    ],
    "Long Short-Term Memory": [
        "lstm", "long short-term memory", "long short term memory", "bilstm",
        "long short term memory networks lstm", "lstm network", "lstm model",
        "recurrent neural network", "rnn",
    ],
    "Capsule Network": [
        "capsnet", "capsule network", "capsule networks", "capsnet-bert",
        "capsnet bert", "capsnet model", "capsnet bert model",
    ],

    # ── NLP: Attention ───────────────────────────────────────────────
    "Attention Mechanism": [
        "attention", "self-attention", "self attention", "multi-head attention",
        "attention weights", "neural attention", "neural attention modeling",
        "attention module", "attention mechanism", "attention layer",
        "cross attention", "cross-attention", "cross attention mechanism",
        "interactive attention", "interactive attention network", "interactive attention networks",
        "multiple attention", "multiple attention mechanisms",
        "attention based", "attention-based", "attention model",
        "feature weighting",   # too vague → normalize to attention
    ],

    # ── NLP: Graph Methods ───────────────────────────────────────────
    "Graph Neural Network": [
        "gnn", "graph neural network", "graph neural networks",
        "graph convolutional network", "gcn", "graph convolution",
        "graph convolution network", "graph convolution networks",
    ],
    "Graph Attention Network": [
        "gat", "graph attention network", "graph attention networks",
        "bisyn-gat", "bisyntaxaware gat", "bisyntax aware gat",
    ],

    # ── NLP: Tasks ───────────────────────────────────────────────────
    "Named Entity Recognition": [
        "ner", "named entity recognition", "entity recognition",
        "entity extraction", "mner", "multi-modal ner",
        "entity boundary detection", "entity boundary",
        "multi modal named entity recognition", "multimodal ner",
        "entity recognition task",
    ],
    "Aspect-Based Sentiment Analysis": [
        "absa", "aspect based sentiment analysis", "aspect-based sentiment analysis",
        "aspect-based sentiment", "aspect level sentiment", "aspect sentiment",
        "mabsa", "multi-modal absa", "absa task", "absa systems",
        "aspect level sentiment classification",
        "feature based sentiment analysis absa",
        "multimodal aspect based sentiment analysis",
        "multimodal absa", "absa systems development",
    ],
    "Aspect Term Extraction": [
        "aspect term extraction", "aspect extraction", "aspect identification",
        "multiple aspect identification", "aspect term",
    ],
    "Sentiment Analysis": [
        "sentiment analysis", "opinion mining", "polarity detection",
        "sentiment classification", "multimodal sentiment analysis",
        "text polarity classification", "text polarity",
        "sentiment classification performance", "sentiment embedding",
        "social media sentiment", "social media sentiments",
        "overall sentiment", "pn polarity", "pn polarity determination",
        "subjectivity analysis", "subjectivity classification",
        "subjective term extraction", "subjective term identification",
        "opinion polarity", "sentiment bias noise",
    ],
    "SentiWordNet": [
        "sentiwordnet", "sentiment wordnet", "sentiwordnet development",
        "sentiwordnet scores", "sentiwordnet scores objs poss negs",
        "committee ternary classifiers", "ternary classifiers", "ternary classifier",
    ],
    "Dependency Parsing": [
        "dependency tree", "dependency parsing", "dependency syntax",
        "syntactic parsing", "constituent tree", "constituency parsing",
        "syntactic word relationships", "dependency tree noise",
    ],
    "Contrastive Learning": [
        "contrastive learning", "contrastive loss",
        "label-based contrastive", "data-based contrastive",
        "label based contrastive", "data based contrastive",
    ],
    "Knowledge Graph": [
        "knowledge graph", "knowledge base", "semantic graph",
        "scene graph", "scene graphs", "scene graph extraction",
    ],
    "Multimodal Learning": [
        "multimodal", "multi-modal", "multimodal fusion", "cross-modal",
        "vision-language", "multiple modality data", "multimodal data",
        "sentence image pair", "sentence image pair inputs",
        "text and image", "text and image alignment", "image text alignment",
        "cross modal semantic graph", "cross-modal semantic graph",
        "cross modal semantic graphs", "image caption integration",
        "image captions", "visual cue", "visual cues extraction",
    ],

    # ── NLP: Benchmarks / Datasets ───────────────────────────────────
    "SemEval": [
        "semeval", "semeval dataset", "semeval 2014", "semeval-2014",
        "semeval tasks", "semeval task",
    ],

    # ── NLP: Misc ────────────────────────────────────────────────────
    "Pre-trained Language Model": [
        "pre-trained model", "pretrained model", "language model pre-training",
        "fine-tuning", "finetuning", "language model pre training",
        "pre trained model", "pre training", "pretraining",
        "pre trained language model",
    ],
    "Encoder-Decoder Framework": [
        "encoder decoder framework", "encoder-decoder framework",
        "encoder decoder", "seq2seq", "sequence to sequence",
    ],
    "Conditional Random Fields": [
        "crf", "conditional random field", "conditional random fields",
    ],
    "Gating Mechanism": [
        "gating mechanism", "gating machine", "gating function",
        "gate mechanism", "gated network",
    ],

    # ── CV: Core Tasks ───────────────────────────────────────────────
    "Single Image Super-Resolution": [
        "sisr", "single image super resolution", "single-image super-resolution",
        "image super resolution", "super resolution", "super-resolution",
        "sr", "image sr", "super resolution sr", "super resolution task",
        "real-world super resolution", "real world super resolution",
        "image restoration", "real-world image restoration",
        "image super resolution sr",
    ],
    "Diffusion Model": [
        "diffusion model", "diffusion models", "denoising diffusion",
        "ddpm", "text-to-image diffusion", "diffusion based",
        "score-based model", "stable diffusion",
        "pre trained text to image diffusion",
    ],

    # ── CV: Architectures ────────────────────────────────────────────
    "Convolutional Neural Network": [
        "cnn", "convnet", "convolutional neural network",
        "convolutional neural networks", "deep cnn", "conv net",
    ],
    "Generative Adversarial Network": [
        "gan", "generative adversarial network", "generative adversarial networks",
        "adversarial training", "discriminator",
    ],
    "Residual Network": [
        "resnet", "residual network", "residual learning",
        "residual connections", "skip connections", "residual block",
        "deep residual network", "low residuals training",
    ],
    "SRCNN": [
        "srcnn", "super resolution convolutional neural network",
        "super-resolution convolutional neural network",
    ],
    "VDSR": ["vdsr", "very deep super resolution"],

    # ── CV: Metrics & Techniques ─────────────────────────────────────
    "PSNR": ["psnr", "peak signal to noise ratio", "peak signal-to-noise ratio"],
    "SSIM": ["ssim", "structural similarity", "structural similarity index"],
    "Upsampling": [
        "upsampling", "up-sampling", "upscaling", "sub-pixel convolution",
        "pixel shuffle", "deconvolution", "transposed convolution",
        "deconvolution layer", "bicubic interpolation", "bicubic",
        "integer scale", "integer scale factors",
    ],
    "High-Resolution Image": [
        "high resolution image", "high resolution images", "high-resolution image",
        "high quality image", "high quality images", "high detailed image",
    ],
    "Low-Resolution Image": [
        "low resolution image", "low resolution images", "low-resolution image",
        "low resolution observation", "low resolution observations",
        "low resoultion observations", "low resoultion observation",  # typo variants
    ],
    "Image Super Supervision": [
        "image supervision", "image supervision issnr", "multiple image supervision",
        "multiple images supervision",
    ],

    # ── General ML ──────────────────────────────────────────────────
    "Deep Learning": [
        "deep learning", "deep neural network", "neural network",
        "deep network", "ann",
    ],
    "Transfer Learning": [
        "transfer learning", "domain adaptation", "cross-domain adaptation",
    ],
    "Data Augmentation": ["data augmentation", "augmentation strategy"],
    "Batch Normalization": ["batch normalization", "batch norm", "bn"],
    "Dropout": ["dropout", "dropout regularization"],
    "Cross-Entropy Loss": [
        "cross entropy", "cross-entropy", "cross entropy loss",
        "cross-entropy loss", "differential sentiment loss",
    ],
    "F1 Score": [
        "f1 score", "f1", "f-measure", "f1-score",
        "precision recall", "precision and recall",
    ],
    "Gradient Clipping": [
        "gradient clipping", "gradient clip", "exploding gradient",
    ],
}


# ===================================================================
# BUILD REVERSE LOOKUP: lowercase alias → canonical name
# ===================================================================
_ALIAS_TO_CANONICAL: Dict[str, str] = {}

for canonical, aliases in CANONICAL_VOCABULARY.items():
    _ALIAS_TO_CANONICAL[canonical.lower()] = canonical
    for alias in aliases:
        _ALIAS_TO_CANONICAL[alias.lower().strip()] = canonical


# ===================================================================
# SINGULARIZER
# ===================================================================
_PLURAL_MAP = {
    "mechanisms": "mechanism", "networks": "network", "models": "model",
    "modules": "module", "methods": "method", "techniques": "technique",
    "approaches": "approach", "losses": "loss", "graphs": "graph",
    "representations": "representation", "embeddings": "embedding",
    "transformers": "transformer", "images": "image",
    "observations": "observation", "vectors": "vector",
    "tasks": "task", "features": "feature", "classifiers": "classifier",
}


def _singularize(word: str) -> str:
    return _PLURAL_MAP.get(word.lower(), word)


def _normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'[:\-\u2013\u2014_.,;()\[\]{}]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ===================================================================
# MAIN NORMALIZE FUNCTION
# ===================================================================
def normalize_concept(term: str, domain: str = "general") -> str:
    """
    Map any LLM-generated concept name to its canonical form.
    Returns canonical name if found, otherwise best-effort Title Case.
    """
    if not term or not str(term).strip():
        return ""

    raw = str(term).strip()

    # 1. Direct lowercase match
    key = _normalize_text(raw)
    if key in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[key]

    # 2. After singularizing each word
    words = key.split()
    key_singular = " ".join(_singularize(w) for w in words)
    if key_singular in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[key_singular]

    # 3. Drop last word (noise: "sr", "task", "based", "approach")
    if len(words) >= 2:
        key_drop = " ".join(words[:-1])
        if key_drop in _ALIAS_TO_CANONICAL:
            return _ALIAS_TO_CANONICAL[key_drop]

    # 4. Partial / substring match (for long compound terms)
    for alias, canonical in _ALIAS_TO_CANONICAL.items():
        if len(alias) >= 8 and alias in key:
            return canonical

    # 5. Best-effort: clean and Title Case
    cleaned = re.sub(r'\s*\([^)]*\)', '', raw)
    cleaned = re.sub(r'[:\-\u2013\u2014_.,;]+', ' ', cleaned)
    cleaned = re.sub(r'[^\w\s]', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if len(cleaned) < 2:
        return ""
    return " ".join(
        w if (w.isupper() and len(w) >= 2) else w.capitalize()
        for w in cleaned.split()
    )


# ===================================================================
# VOCABULARY FOR P6 PROMPT
# ===================================================================
def get_vocabulary_for_prompt() -> str:
    """Formatted canonical vocabulary for injection into P6 prompt."""
    nlp = [
        "BERT", "Transformer", "GPT", "ELMo", "Word2Vec", "GloVe",
        "Long Short-Term Memory", "Attention Mechanism", "Graph Neural Network",
        "Graph Attention Network", "Capsule Network", "Contrastive Learning",
        "Named Entity Recognition", "Aspect-Based Sentiment Analysis",
        "Aspect Term Extraction", "Sentiment Analysis", "SentiWordNet",
        "Dependency Parsing", "Conditional Random Fields", "Gating Mechanism",
        "Pre-trained Language Model", "Encoder-Decoder Framework",
        "Multimodal Learning", "Knowledge Graph", "SemEval",
    ]
    cv = [
        "Single Image Super-Resolution", "Diffusion Model",
        "Convolutional Neural Network", "Generative Adversarial Network",
        "Residual Network", "SRCNN", "VDSR", "PSNR", "SSIM", "Upsampling",
    ]
    ml = [
        "Deep Learning", "Transfer Learning", "Data Augmentation",
        "Batch Normalization", "Dropout", "Cross-Entropy Loss",
        "F1 Score", "Gradient Clipping",
    ]
    lines = [
        "NLP/Text concepts: " + ", ".join(nlp),
        "Computer Vision concepts: " + ", ".join(cv),
        "General ML concepts: " + ", ".join(ml),
    ]
    return "\n".join(lines)


# ===================================================================
# DOMAIN DETECTION
# ===================================================================
_DOMAIN_SIGNALS: Dict[str, List[str]] = {
    "cv": [
        "super resolution", "sisr", "srcnn", "vdsr", "image restoration",
        "cnn", "gan", "diffusion model", "psnr", "ssim", "bicubic",
        "upsampling", "low resolution", "high resolution",
    ],
    "nlp": [
        "bert", "transformer", "attention", "ner", "sentiment analysis",
        "absa", "semeval", "lstm", "aspect", "dependency", "entity",
    ],
}


def detect_domain(text: str) -> str:
    text_lower = text.lower()
    word_count = max(len(text_lower.split()), 1)
    scores: Dict[str, float] = {}
    for domain, signals in _DOMAIN_SIGNALS.items():
        hits = sum(text_lower.count(sig) for sig in signals)
        scores[domain] = hits / (word_count ** 0.5 + 1)
    best = max(scores, key=lambda d: scores[d]) if scores else "general"
    return best if scores.get(best, 0) > 0.02 else "general"