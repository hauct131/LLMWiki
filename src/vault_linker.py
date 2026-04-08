# src/vault_linker.py
"""
Vault Linker — Cross-paper linking, concept normalization, typed links
and hub page generation for Obsidian research vaults.

FIXED in this version:
  • Typed links are now actually written to "## Related Papers"
    (e.g. [[uses::PaperA]], [[vs::PaperB]], [[domain::PaperC]])
  • DOMAIN_ALIASES and _DOMAIN_SIGNALS are now cleaner and easier
    to maintain when adding new domains (Medical, RL, Robotics...).
"""

import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

# ---------------------------------------------------------------------------
# DOMAIN SIGNALS & ALIASES (RÚT GỌN - DỄ THÊM DOMAIN MỚI)
# ---------------------------------------------------------------------------
_DOMAIN_SIGNALS: Dict[str, List[str]] = {
    "cv": [
        "super resolution", "sisr", "srcnn", "vdsr",
        "image restoration", "upsampling", "deconvolution",
        "convolutional neural network", "cnn", "resnet", "vgg",
        "generative adversarial", "gan", "diffusion model",
        "psnr", "ssim", "bicubic", "sub pixel", "image patch",
        "low resolution", "high resolution", "scale factor",
        "image enhancement", "pixel shuffle",
    ],
    "nlp": [
        "bert", "transformer", "attention mechanism", "self attention",
        "named entity recognition", "ner", "sentiment analysis", "absa",
        "aspect based sentiment", "word embedding", "word2vec", "glove",
        "language model", "pre training", "fine tuning",
        "text classification", "sequence labeling", "dependency parsing",
        "semeval", "opinion mining", "multimodal sentiment",
        "aspect term", "polarity", "capsule network",
    ],
}

# ---------------------------------------------------------------------------
# Domain alias tables
# Structure: { domain: { canonical_name: [alias, ...] } }
# ---------------------------------------------------------------------------

DOMAIN_ALIASES: Dict[str, Dict[str, List[str]]] = {
    "cv": {
        # Tasks
        "Single Image Super-Resolution": [
            "sisr", "single image super resolution",
            "single-image super-resolution",
            "image super resolution", "image super-resolution",
            "isr", "super resolution", "super-resolution",
            "real-isr", "real isr", "real-world sr",
        ],
        "Real-World Image Restoration": [
            "real world image restoration", "real-world image restoration",
            "real-world super-resolution", "blind super resolution",
        ],
        "Image Reconstruction": [
            "image reconstruction", "image recovery",
            "image enhancement", "image upscaling",
        ],
        # Architectures
        "Convolutional Neural Network": [
            "cnn", "convnet", "convolutional neural network",
            "convolutional neural networks", "deep cnn",
            "deep convolutional network",
        ],
        "Generative Adversarial Network": [
            "gan", "generative adversarial network",
            "generative adversarial networks", "adversarial training",
            "adversarial loss", "discriminator",
        ],
        "Residual Learning": [
            "resnet", "residual network", "residual learning",
            "residual connections", "skip connections",
            "deep residual network", "residual block",
        ],
        "VGG Network": [
            "vgg", "vgg-net", "vggnet", "visual geometry group",
        ],
        "Diffusion Model": [
            "diffusion model", "diffusion models", "denoising diffusion",
            "score-based model", "ddpm", "text-to-image diffusion",
            "iterative denoising", "stable diffusion",
        ],
        "SRCNN": [
            "srcnn", "super resolution convolutional neural network",
            "super-resolution convolutional neural network",
        ],
        "VDSR": ["vdsr", "very deep super resolution"],
        "Residual Channel Attention Network": [
            "rcan", "channel attention", "residual channel attention",
        ],
        # Techniques
        "Upsampling": [
            "upsampling", "up-sampling", "upscaling",
            "sub-pixel convolution", "pixel shuffle",
            "deconvolution", "transposed convolution",
        ],
        "Bicubic Interpolation": [
            "bicubic", "bicubic interpolation", "bicubic upsampling",
        ],
        "Batch Normalization": [
            "batch normalization", "batch norm", "bn",
        ],
        "Target Score Distillation": [
            "score distillation", "target score distillation",
            "tsd", "tsd-sr",
        ],
        "Gradient Clipping": [
            "gradient clipping", "gradient clip", "exploding gradient",
        ],
        "Perceptual Loss": [
            "perceptual loss", "feature loss", "vgg loss",
        ],
        # Metrics
        "PSNR": [
            "psnr", "peak signal to noise ratio",
            "peak signal-to-noise ratio",
        ],
        "SSIM": [
            "ssim", "structural similarity", "structural similarity index",
        ],
        # Data
        "Image Patch": [
            "image patch", "patch extraction",
            "overlapping patches", "patch-based",
        ],
    },

    "nlp": {
        # Pre-trained models
        "BERT": [
            "bert", "bert model",
            "bidirectional encoder representations from transformers",
            "bidirectional encoder representations",
        ],
        "Transformer": [
            "transformer", "transformers", "transformer model",
            "transformer architecture", "vanilla transformer",
        ],
        "GPT": ["gpt", "generative pre-trained transformer"],
        "ELMo": ["elmo", "embeddings from language models"],
        "Word2Vec": [
            "word2vec", "word 2 vec", "word vectors",
            "cbow", "skip-gram", "skipgram",
        ],
        "GloVe": [
            "glove", "global vectors", "global log-bilinear regression",
        ],
        # Techniques
        "Attention Mechanism": [
            "attention", "self-attention", "self attention",
            "multi-head attention", "scaled dot-product attention",
            "attention weights", "neural attention", "attention layer",
        ],
        "Contrastive Learning": [
            "contrastive learning", "contrastive loss",
            "label-based contrastive", "data-based contrastive",
        ],
        "Graph Attention Network": [
            "gat", "graph attention network",
            "graph attention networks", "bisyn-gat", "bisyn-gat+",
        ],
        "Graph Neural Network": [
            "gnn", "graph neural network",
            "graph convolutional network", "gcn", "graph convolution",
        ],
        "Long Short-Term Memory": [
            "lstm", "long short-term memory",
            "long short term memory", "bilstm",
        ],
        "Capsule Network": [
            "capsnet", "capsule network",
            "capsule networks", "capsnet-bert",
        ],
        # Tasks
        "Named Entity Recognition": [
            "ner", "named entity recognition",
            "named entity recognition (ner", "entity recognition",
            "entity extraction", "entity span",
            "multi-modal named entity recognition", "mner",
        ],
        "Aspect-Based Sentiment Analysis": [
            "absa", "aspect based sentiment analysis",
            "aspect-based sentiment analysis",
            "aspect-based sentiment", "aspect level sentiment",
            "aspect sentiment", "mabsa", "multi-modal absa",
        ],
        "Sentiment Analysis": [
            "sentiment analysis", "opinion mining",
            "polarity detection", "polarity classification",
            "sentiment classification", "multimodal sentiment analysis",
        ],
        "Dependency Parsing": [
            "dependency tree", "dependency parsing",
            "dependency syntax", "syntactic parsing",
            "constituent tree", "constituency parsing",
        ],
        # Datasets / tools
        "SemEval": [
            "semeval", "semeval dataset",
            "semeval 2014", "semeval-2014",
        ],
        "SentiWordNet": ["sentiwordnet", "sentiment wordnet"],
        # Misc
        "Pre-trained Language Model": [
            "pre-trained model", "pretrained model",
            "language model pre-training", "pre-training",
            "fine-tuning", "finetuning",
        ],
        "Multimodal Learning": [
            "multimodal", "multi-modal", "multimodal fusion",
            "cross-modal", "vision-language",
        ],
        "Token-Level Fusion": [
            "token-level fusion", "token level fusion",
            "token fusion", "feature fusion",
        ],
        "Cross-Entropy Loss": [
            "cross entropy", "cross-entropy",
            "cross entropy loss", "cross-entropy loss",
        ],
    },

    "general": {
        "Deep Learning": [
            "deep learning", "deep neural network",
            "deep network", "neural network", "ann",
        ],
        "Transfer Learning": [
            "transfer learning", "domain adaptation", "cross-domain",
        ],
        "Knowledge Graph": [
            "knowledge graph", "knowledge base",
            "semantic graph", "concept graph",
        ],
        "Benchmark Dataset": [
            "benchmark", "benchmark dataset",
            "evaluation dataset", "test set",
        ],
        "Data Augmentation": [
            "data augmentation", "augmentation strategy",
        ],
    },
}

# ---------------------------------------------------------------------------
# Typed-link relation signals
# Maps relation type → sentence-level phrases that indicate it.
# "uses" is the default and needs no signals.
# ---------------------------------------------------------------------------

_RELATION_SIGNALS: Dict[str, List[str]] = {
    "vs": [
        "outperform", "outperforms", "compared to", "better than",
        "versus", "vs.", "surpass", "surpasses", "over existing",
        "against", "prior method", "previous method", "baseline",
        "previous work", "state-of-the-art method", "existing approach",
        "improve over", "improvement over", "exceed",
    ],
    "domain": [
        "applied to", "application in", "task of", "for the task",
        "in the domain", "field of", "area of", "problem of",
        "we address", "this paper tackles", "our approach for",
    ],
}

class TypedLink(NamedTuple):
    relation: str   # "uses" | "vs" | "domain"
    concept: str

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[-_]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def _build_reverse_maps() -> Dict[str, Dict[str, str]]:
    result: Dict[str, Dict[str, str]] = {}
    for domain, canonical_map in DOMAIN_ALIASES.items():
        rev: Dict[str, str] = {}
        for canonical, aliases in canonical_map.items():
            rev[canonical.lower()] = canonical
            for alias in aliases:
                rev[alias.lower().strip()] = canonical
        result[domain] = rev
    return result

_REVERSE: Dict[str, Dict[str, str]] = _build_reverse_maps()

def detect_domain(text: str) -> str:
    normalized = _normalize_text(text)
    word_count = max(len(normalized.split()), 1)
    scores = {}
    for domain, signals in _DOMAIN_SIGNALS.items():
        hits = sum(normalized.count(sig) for sig in signals)
        scores[domain] = hits / (word_count ** 0.5)
    best_domain = max(scores, key=lambda d: scores[d])
    if scores[best_domain] < 0.02:
        return "general"
    return best_domain

def normalize_concept(concept: str, domain: str = "general") -> str:
    if not concept or not concept.strip():
        return ""
    if "::" in concept:
        concept = concept.split("::", 1)[1]
    raw = concept.strip()
    key = _normalize_text(raw)

    canonical = _REVERSE.get(domain, {}).get(key)
    if canonical:
        return canonical
    for d, rev in _REVERSE.items():
        if d == domain:
            continue
        canonical = rev.get(key)
        if canonical:
            return canonical

    cleaned = re.sub(r'\s*\([^)]*\)', '', raw)
    cleaned = re.sub(r'[:\-–—_.,;]+', ' ', cleaned)
    cleaned = re.sub(r'[^\w\s]', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if not cleaned or len(cleaned) < 3:
        return ""
    words = cleaned.split()
    return " ".join(w if (w.isupper() and len(w) >= 2) else w.capitalize() for w in words)

# ---------------------------------------------------------------------------
# TYPED LINKS
# ---------------------------------------------------------------------------
def _classify_relation(sentence: str) -> str:
    sentence_lower = sentence.lower()
    for relation, signals in _RELATION_SIGNALS.items():
        if any(sig in sentence_lower for sig in signals):
            return relation
    return "uses"

def extract_typed_links(content: str, domain: str) -> List[TypedLink]:
    typed: List[TypedLink] = []
    seen: set[str] = set()
    for match in re.finditer(r'\[\[([^\]|#]+?)(?:\|[^\]]*)?\]\]', content):
        raw = match.group(1).strip()
        norm = normalize_concept(raw, domain=domain)
        if not norm or len(norm) < 3 or norm in seen:
            continue
        seen.add(norm)
        left = max(0, match.start() - 200)
        right = min(len(content), match.end() + 200)
        sentence = content[left:right]
        relation = _classify_relation(sentence)
        typed.append(TypedLink(relation=relation, concept=norm))
    return typed

# ---------------------------------------------------------------------------
# INJECT RELATED PAPERS (ĐÃ SỬA - DÙNG TYPED LINKS)
# ---------------------------------------------------------------------------
def _build_typed_related_section(related_typed: List[Tuple[str, str]]) -> str:
    lines = [f"- [[{rel}::{paper}]]" for rel, paper in related_typed]
    return f"## Related Papers\n\n" + "\n".join(lines) + "\n"

def inject_related_papers(
    sources_dir: Path,
    concept_index: Dict[str, List[str]],
    domain: Optional[str] = None,
    min_shared: int = 2,
) -> None:
    updated = 0
    for md_file in sorted(sources_dir.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
            file_domain = domain or detect_domain(content)
            typed_links = extract_typed_links(content, file_domain)

            paper_hits: Dict[str, List[str]] = defaultdict(list)
            for tl in typed_links:
                for other_paper in concept_index.get(tl.concept, []):
                    if other_paper != md_file.stem:
                        paper_hits[other_paper].append(tl.relation)

            related_typed = []
            priority = {"vs": 3, "domain": 2, "uses": 1}
            for paper, relations in paper_hits.items():
                if len(relations) >= min_shared:
                    best_rel = max(relations, key=lambda r: priority.get(r, 0))
                    related_typed.append((best_rel, paper))

            if not related_typed:
                continue

            related_typed.sort(key=lambda x: -priority.get(x[0], 0))
            new_section = _build_typed_related_section(related_typed)

            backup = md_file.with_suffix(".md.bak")
            if not backup.exists():
                shutil.copy2(md_file, backup)

            if "## Related Papers" in content:
                content = re.sub(
                    r'## Related Papers\n[\s\S]*?(?=\n## |\Z)',
                    new_section,
                    content,
                    flags=re.MULTILINE,
                )
            else:
                content = content.rstrip() + "\n\n" + new_section

            md_file.write_text(content, encoding="utf-8")
            updated += 1
            print(f" [OK] {md_file.name} → {len(related_typed)} typed related papers")

        except Exception as e:
            print(f" [ERROR] {md_file.name}: {e}")

    print(f"\n Papers updated with typed links: {updated}")

# ---------------------------------------------------------------------------
# PHẦN CÒN LẠI (GIỮ NGUYÊN TỪ CODE CŨ CỦA BẠN)
# ---------------------------------------------------------------------------
def build_concept_index(
    sources_dir: Path,
    domain: Optional[str] = None,
) -> Dict[str, List[str]]:
    index: Dict[str, List[str]] = defaultdict(list)
    for md_file in sorted(sources_dir.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception as e:
            print(f" [WARN] Cannot read {md_file.name}: {e}")
            continue
        file_domain = domain or detect_domain(content)
        raw_links = re.findall(r'\[\[([^\]|#]+?)(?:\|[^\]]*)?\]\]', content)
        for raw in raw_links:
            norm = normalize_concept(raw.strip(), domain=file_domain)
            if norm and len(norm) > 2:
                index[norm].append(md_file.stem)
    return {
        concept: list(dict.fromkeys(papers))
        for concept, papers in index.items()
    }

_HUB_TEMPLATE = """\
---
title: "{title}"
type: concept
domain: "{domain}"
paper_count: {paper_count}
created_date: {created_date}
updated_date: {updated_date}
tags: [concept, auto-generated]
---
## Definition
> Stub — add a concise definition for **{title}** here.
## Papers Using This Concept
{paper_links}
---
*Auto-generated by Vault Linker. Verify before publishing.*
"""

def create_concept_hub_pages(
    concepts_dir: Path,
    concept_index: Dict[str, List[str]],
    domain: str = "general",
    min_papers: int = 2,
) -> None:
    concepts_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    created = updated = skipped = 0
    for concept, papers in sorted(concept_index.items()):
        if len(papers) < min_papers:
            continue
        slug = re.sub(r'[^\w\s-]', '', concept.lower())
        slug = re.sub(r'[\s_]+', '-', slug).strip('-')[:60]
        hub_path = concepts_dir / f"{slug}.md"
        if hub_path.exists():
            existing = hub_path.read_text(encoding="utf-8")
            created_date = re.search(r'^created_date:\s*(\S+)', existing, re.MULTILINE)
            created_date = created_date.group(1) if created_date else today
            existing_papers = set(re.findall(r'\[\[([^\]]+)\]\]', existing))
            if set(papers) == existing_papers:
                skipped += 1
                continue
            new_content = _HUB_TEMPLATE.format(
                title=concept, domain=domain, paper_count=len(papers),
                created_date=created_date, updated_date=today,
                paper_links="\n".join(f"- [[{p}]]" for p in sorted(papers))
            )
            hub_path.write_text(new_content, encoding="utf-8")
            updated += 1
            print(f" [UPDATED] {hub_path.name} ({len(papers)} papers)")
        else:
            new_content = _HUB_TEMPLATE.format(
                title=concept, domain=domain, paper_count=len(papers),
                created_date=today, updated_date=today,
                paper_links="\n".join(f"- [[{p}]]" for p in sorted(papers))
            )
            hub_path.write_text(new_content, encoding="utf-8")
            created += 1
            print(f" [NEW] {hub_path.name} ({len(papers)} papers)")
    print(f"\n Hub pages -> created: {created} | updated: {updated} | unchanged: {skipped}")

def run_vault_linker(
    sources_dir: str = "vault/_sources",
    concepts_dir: str = "vault/_concepts",
    domain: Optional[str] = None,
    min_shared: int = 2,
    min_hub_papers: int = 2,
) -> None:
    src = Path(sources_dir)
    cpts = Path(concepts_dir)
    if not src.exists():
        print(f"[ERROR] Sources directory not found: {src.resolve()}")
        return
    md_files = list(src.glob("*.md"))
    if not md_files:
        print(f"[ERROR] No .md files found in: {src.resolve()}")
        return

    if domain is None:
        freq: Dict[str, int] = defaultdict(int)
        for f in md_files:
            try:
                freq[detect_domain(f.read_text(encoding="utf-8"))] += 1
            except Exception:
                freq["general"] += 1
        dominant = max(freq, key=lambda d: freq[d])
        domain_label = ", ".join(f"{d}={n}" for d, n in sorted(freq.items()))
        print(f"\n Auto-detected domains : {domain_label}")
        print(f" Hub page domain label : {dominant}")
        effective = dominant
    else:
        effective = domain
        print(f"\n Forced domain: {effective}")

    print(f"\n{'='*60}")
    print(f" Vault Linker | {len(md_files)} papers | domain={effective!r}")
    print(f"{'='*60}")

    print("\n[1/3] Building concept index...")
    index = build_concept_index(src, domain=domain)

    print(f"\n[2/3] Injecting typed related-paper links...")
    inject_related_papers(src, index, domain=domain, min_shared=min_shared)

    print(f"\n[3/3] Creating/updating concept hub pages...")
    create_concept_hub_pages(cpts, index, domain=effective, min_papers=min_hub_papers)

    print(f"\n{'='*60}")
    print(" ✅ Vault Linker completed.")
    print(f"{'='*60}\n")