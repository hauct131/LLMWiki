# main.py
"""
LLMWiki - Main CLI
Hỗ trợ cả xử lý đơn lẻ và batch nhiều bài báo
"""

import sys
from pathlib import Path
import argparse

# Thêm src vào path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.batch_pipeline import BatchIngestPipeline
from src.config import PipelineConfig


def main():
    parser = argparse.ArgumentParser(
        description="LLMWiki - Convert research papers to Obsidian Wiki (Phi-3.5 optimized)"
    )
    parser.add_argument("input", nargs="+",
                        help="Path to PDF/text file or folder containing papers")
    parser.add_argument("--workers", type=int, default=2,
                        help="Number of parallel workers (default: 2, tăng lên nếu máy mạnh)")
    parser.add_argument("--model-tier", default="3b", choices=["3b", "7b", "13b+"],
                        help="Model tier (3b recommended for Phi-3.5 on 4GB VRAM)")

    args = parser.parse_args()

    # Cấu hình tối ưu cho Phi-3.5
    config = PipelineConfig(
        model_tier=args.model_tier,
        api_model_name="phi3.5:latest",   # Đảm bảo bạn đã pull model này
        output_dir="./vault/_sources"
    )

    print("=" * 60)
    print("🚀 LLMWiki Batch Processor (Phi-3.5 optimized)")
    print("=" * 60)

    # Khởi tạo Batch Pipeline
    batch = BatchIngestPipeline(config, max_workers=args.workers)

    # Chạy batch
    batch.run_batch(args.input)

    print("\n" + "=" * 60)
    print("✅ All done! Check your Obsidian vault.")
    print("   Related Papers and concept normalization have been applied.")
    print("=" * 60)


if __name__ == "__main__":
    main()