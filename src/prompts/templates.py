P0_DOC_TYPE_TASK = """Analyze the following text and determine its category.
Categories: 
- SCIENTIFIC_PAPER: Has Abstract, Intro, References, and academic affiliations.
- TECHNICAL_DOCUMENTATION: Manuals, API docs, or READMEs.
- NEWS_ARTICLE: Journalistic style, no formal academic structure.
- OTHER: General text.

Format: CATEGORY | CONFIDENCE_SCORE
TEXT: {text_snippet}"""

# P2 - Tóm tắt
P2_SUMMARY_TASK = """Summarize this research in exactly {n_sentences} sentences.
Sentence 1: What problem does it solve?
Sentence 2: What is the core method?
Sentence 3: What is the main result?
TEXT: {text}"""

# P3 - Phương pháp (Cấm lấy tên người)
P3_METHODS_TASK = """You are a Research Assistant. Extract the TECHNICAL methods from the paper.
STRICT RULES:
1. IGNORE author names, emails, affiliations, and locations.
2. If you see "Maria Pontiki" or "Athens University", SKIP THEM.
3. Focus on algorithms (e.g., SVM, CRF, Deep Learning), datasets, and evaluation metrics.
4. If no technical methods are found, return "Heuristic extraction required".

TEXT TO ANALYZE:
{text}"""

# P6 - Thuật ngữ (Cấm lấy tên riêng)
P6_TERMS_TASK = """List {n_terms} technical concepts from this text.
STRICT RULE: DO NOT include names of people, organizations, or locations. 
One per line, no bullets.
TEXT: {text}"""

# P8 - Định nghĩa Concept
P8_CONCEPT_TASK = """Write a wiki entry for: {term}.
DEFINITION: 2-3 sentences.
WHY IT MATTERS: 1 sentence.
CONTEXT: {context_snippet}"""