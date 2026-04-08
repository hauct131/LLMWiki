#!/usr/bin/env python3
"""
Batch process multiple PDF/markdown files into wiki pages.

Usage:
    python batch_process.py /path/to/papers [--parallel N] [--recursive] [--ext .pdf,.md]

Options:
    --parallel N    Number of parallel processes (default: 1 = sequential)
    --recursive     Scan subdirectories recursively
    --ext EXT       Comma-separated extensions (default: .pdf,.md)
"""

import argparse
import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm  # pip install tqdm
import time
import re

# Import pipeline components
from src.pipeline import IngestPipeline
from src.config import PipelineConfig
from dotenv import load_dotenv

load_dotenv()


def extract_text_from_file(file_path: str) -> str:
    """
    Extract text from PDF or markdown file.
    For PDF: use PyMuPDF (fitz) if available, else return empty.
    For markdown: read as text.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == '.pdf':
        try:
            import fitz  # PyMuPDF
            text = []
            with fitz.open(path) as doc:
                for page in doc:
                    text.append(page.get_text())
            return "\n".join(text)
        except ImportError:
            print(f"⚠️ PyMuPDF not installed. Cannot extract PDF: {file_path}")
            return ""
        except Exception as e:
            print(f"❌ Failed to extract PDF {file_path}: {e}")
            return ""
    else:  # .md or .txt
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"❌ Failed to read {file_path}: {e}")
            return ""


def process_one_file(file_path: str, config_dict: dict) -> dict:
    """
    Process a single file. Runs in a separate process.
    config_dict is a serialized version of PipelineConfig.
    """
    try:
        # Recreate config from dict
        config = PipelineConfig(**config_dict)
        pipeline = IngestPipeline(config)

        # Extract raw text from file
        raw_text = extract_text_from_file(file_path)
        if not raw_text:
            return {"file": file_path, "status": "failed", "error": "No text extracted"}

        # Run pipeline
        state = pipeline.run(raw_text=raw_text, source_path=file_path)

        # Optionally, you can return some summary info
        return {
            "file": file_path,
            "status": "success",
            "result": f"Score: {state.quality_score}, Status: {state.page_status}",
            "quality": state.quality_score,
        }
    except Exception as e:
        return {"file": file_path, "status": "failed", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Batch process papers into wiki")
    parser.add_argument("input_dir", help="Directory containing PDF/markdown files")
    parser.add_argument("--parallel", type=int, default=1, help="Number of parallel processes (default: 1)")
    parser.add_argument("--recursive", action="store_true", help="Scan subdirectories recursively")
    parser.add_argument("--ext", default=".pdf,.md", help="File extensions to process (comma-separated)")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Seconds to wait between files when sequential (default: 2.0)")
    args = parser.parse_args()

    input_path = Path(args.input_dir)
    if not input_path.exists():
        print(f"❌ Directory not found: {input_path}")
        sys.exit(1)

    # Collect files
    extensions = [ext.strip().lower() for ext in args.ext.split(",")]
    if args.recursive:
        files = [f for f in input_path.rglob("*") if f.suffix.lower() in extensions]
    else:
        files = [f for f in input_path.glob("*") if f.suffix.lower() in extensions]

    if not files:
        print(f"No files with extensions {extensions} found in {input_path}")
        sys.exit(0)

    print(f"📁 Found {len(files)} files to process")

    # Create config and serialize to dict (for parallel processes)
    config = PipelineConfig()
    config_dict = {
        "model_tier": config.model_tier,
        "api_base_url": config.api_base_url,
        "api_model_name": config.api_model_name,
        "api_timeout_secs": config.api_timeout_secs,
        "use_remote_api": config.use_remote_api,
        "remote_api_key": config.remote_api_key,
        "gemini_api_key": config.gemini_api_key,
        "gemini_api_keys": config.gemini_api_keys,
        "gemini_model_name": config.gemini_model_name,
        "output_dir": config.output_dir,
        "concepts_dir": config.concepts_dir,
        "index_path": config.index_path,
        "log_path": config.log_path,
        "sidecar_dir": config.sidecar_dir,
    }

    results = []
    if args.parallel <= 1:
        # Sequential
        for file in tqdm(files, desc="Processing", unit="file"):
            res = process_one_file(str(file), config_dict)
            results.append(res)
            if res["status"] == "failed":
                print(f"⚠️ Failed: {res['file']} - {res.get('error', '')}")
            # Delay between files to avoid rate limiting
            time.sleep(args.delay)
    else:
        # Parallel (not recommended for local Ollama, but can be used with Gemini)
        with ProcessPoolExecutor(max_workers=args.parallel) as executor:
            futures = {executor.submit(process_one_file, str(f), config_dict): f for f in files}
            for future in tqdm(as_completed(futures), total=len(files), desc="Processing", unit="file"):
                res = future.result()
                results.append(res)
                if res["status"] == "failed":
                    print(f"⚠️ Failed: {res['file']} - {res.get('error', '')}")

    # Summary
    success = sum(1 for r in results if r["status"] == "success")
    failed = len(results) - success
    print(f"\n✅ Completed: {success} succeeded, {failed} failed")
    if failed > 0:
        print("⚠️ Check errors above for details.")
    else:
        # Optional: print average quality if available
        qualities = [r.get("quality", 0) for r in results if "quality" in r]
        if qualities:
            avg_q = sum(qualities) / len(qualities)
            print(f"📊 Average quality score: {avg_q:.1f}")


if __name__ == "__main__":
    main()