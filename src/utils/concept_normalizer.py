"""
concept_normalizer.py — Chuẩn hóa các thuật ngữ kỹ thuật về tên canonical
dựa trên từ điển đồng nghĩa (DOMAIN_ALIASES).
"""

from typing import Dict, List, Optional

# Từ điển đồng nghĩa (bạn có thể mở rộng)
DOMAIN_ALIASES: Dict[str, Dict[str, List[str]]] = {
    "nlp": {
        # Pre-trained models
        "BERT": ["bert", "bert model", "bidirectional encoder representations from transformers"],
        "Transformer": ["transformer", "transformers", "transformer model", "vanilla transformer"],
        "GPT": ["gpt", "generative pre-trained transformer"],
        "ELMo": ["elmo", "embeddings from language models"],
        "Word2Vec": ["word2vec", "word 2 vec", "cbow", "skip-gram"],
        "GloVe": ["glove", "global vectors", "global log-bilinear regression"],

        # Techniques
        "Attention Mechanism": ["attention", "self-attention", "multi-head attention", "attention weights",
                                "neural attention"],
        "Contrastive Learning": ["contrastive learning", "contrastive loss", "label-based contrastive",
                                 "data-based contrastive"],
        "Graph Attention Network": ["gat", "graph attention network", "bisyn-gat", "bisyn-gat+"],
        "Graph Neural Network": ["gnn", "graph neural network", "graph convolutional network", "gcn"],
        "Long Short-Term Memory": ["lstm", "long short-term memory", "bilstm"],
        "Capsule Network": ["capsnet", "capsule network", "capsnet-bert"],

        # Tasks
        "Named Entity Recognition": ["ner", "named entity recognition", "entity recognition", "entity extraction",
                                     "mner"],
        "Aspect-Based Sentiment Analysis": ["absa", "aspect based sentiment analysis", "aspect-based sentiment",
                                            "aspect level sentiment", "mabsa"],
        "Sentiment Analysis": ["sentiment analysis", "opinion mining", "polarity detection",
                               "sentiment classification"],
        "Dependency Parsing": ["dependency tree", "dependency parsing", "constituent tree", "constituency parsing"],

        # Datasets
        "SemEval": ["semeval", "semeval dataset", "semeval 2014", "semeval-2014"],
        "SentiWordNet": ["sentiwordnet", "sentiment wordnet"],

        # Misc
        "Pre-trained Language Model": ["pre-trained model", "pretrained model", "language model pre-training",
                                       "fine-tuning"],
        "Multimodal Learning": ["multimodal", "multi-modal", "multimodal fusion", "cross-modal", "vision-language"],
    },
    "general": {
        "Deep Learning": ["deep learning", "deep neural network", "neural network"],
        "Transfer Learning": ["transfer learning", "domain adaptation"],
        "Knowledge Graph": ["knowledge graph", "knowledge base", "semantic graph", "concept graph"],
        "Benchmark Dataset": ["benchmark", "benchmark dataset", "evaluation dataset"],
    }
}

# Gom tất cả alias vào một dictionary flat
_ALIAS_TO_CANONICAL: Dict[str, str] = {}
for domain, mapping in DOMAIN_ALIASES.items():
    for canonical, aliases in mapping.items():
        for alias in aliases:
            _ALIAS_TO_CANONICAL[alias.lower()] = canonical
        # Cũng thêm chính canonical vào (để nó map vào chính nó)
        _ALIAS_TO_CANONICAL[canonical.lower()] = canonical


def normalize_concept(term: str) -> str:
    """
    Trả về tên canonical của term dựa trên từ điển đồng nghĩa.
    Nếu không tìm thấy, trả về term gốc (sau khi chuẩn hóa cơ bản).
    """
    term_lower = term.lower().strip()
    # Loại bỏ dấu câu, khoảng trắng thừa
    import re
    term_clean = re.sub(r'[^\w\s]', '', term_lower)
    term_clean = re.sub(r'\s+', ' ', term_clean).strip()

    # Tìm trong alias dict
    if term_clean in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[term_clean]
    # Thử tìm kiếm từng từ (có thể mở rộng)
    # Trả về term gốc nếu không có
    return term