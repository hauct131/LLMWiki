# src/batch_pipeline.py
"""
Batch Pipeline for LLMWiki - Xử lý nhiều bài báo + Vault Linker
"""

import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
import logging
from typing import List

from .config import PipelineConfig
from .pipeline import IngestPipeline
from .state import IngestState
from .vault_linker import run_vault_linker   # Import Vault Linker

logger = logging.getLogger(__name__)

class BatchIngestPipeline:
    """
    Pipeline xử lý hàng loạt bài báo và tự động tạo cross-paper links.
    """

    def __init__(self, config: PipelineConfig = None, max_workers: int = 2):
        self.config = config or PipelineConfig()
        self.max_workers = max_workers
        self.single_pipeline = IngestPipeline(self.config)

    def run_batch(self, input_paths: List[str | Path]):
        """Chạy batch xử lý nhiều paper + chạy Vault Linker ở cuối"""
        all_files = self._collect_files(input_paths)
        print(f"📂 Found {len(all_files)} files to process\n")

        results = []
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_path = {
                executor.submit(self._process_single_file, file_path): file_path
                for file_path in all_files
            }

            for future in tqdm(as_completed(future_to_path), total=len(all_files), desc="Processing"):
                file_path = future_to_path[future]
                try:
                    state: IngestState = future.result()
                    results.append(state)
                except Exception as e:
                    print(f"❌ Error with {file_path.name}: {e}")
                    results.append(self._create_stub_state(file_path))

        # === Tóm tắt kết quả ===
        total = len(results)
        avg_score = sum(r.quality_score for r in results) / total if total > 0 else 0
        good = sum(1 for r in results if r.quality_score >= 50)

        print(f"\n🎉 Batch processing completed!")
        print(f"   Total papers     : {total}")
        print(f"   Good quality     : {good}")
        print(f"   Average score    : {avg_score:.1f}/100")

        # === Chạy Vault Linker để tạo liên kết giữa các bài báo ===
        print("\n🔗 Running Vault Linker (cross-paper linking + concept normalization)...")
        run_vault_linker("vault/_sources")

        return results

    def _collect_files(self, inputs: List[str | Path]) -> List[Path]:
        """Thu thập tất cả file PDF, txt, md"""
        files = []
        for item in inputs:
            p = Path(item)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                for ext in ["*.pdf", "*.txt", "*.md"]:
                    files.extend(p.rglob(ext))
        return sorted(files)

    def _process_single_file(self, file_path: Path) -> IngestState:
        """Xử lý một file duy nhất - cải thiện extract PDF"""
        try:
            if file_path.suffix.lower() == ".pdf":
                text = self._extract_text_from_pdf(file_path)
            else:
                text = file_path.read_text(encoding="utf-8", errors="ignore")

            if not text or len(text.strip()) < 50:
                print(f"⚠️  Empty or too short text from {file_path.name} → using Level 4")
                return self._create_stub_state(file_path)

            state = self.single_pipeline.run(
                raw_text=text,
                source_path=str(file_path)
            )
            return state

        except Exception as e:
            logger.error(f"Failed processing {file_path.name}: {e}")
            return self._create_stub_state(file_path)

    def _extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract text từ PDF dùng PyMuPDF - tốt hơn nhiều"""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(pdf_path)
            text = ""
            for page in doc:
                text += page.get_text("text") + "\n\n"
            doc.close()
            return text.strip()
        except Exception as e:
            print(f"⚠️ PDF extraction failed for {pdf_path.name}: {e}")
            return f"[Failed to extract PDF: {pdf_path.name}]"

    def _create_stub_state(self, file_path: Path) -> IngestState:
        """Tạo state dự phòng khi lỗi"""
        state = IngestState(raw_text="", source_path=str(file_path))
        state.fallback_level = 4
        state.quality_score = 0
        state.page_status = "stub"
        return state