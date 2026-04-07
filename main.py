import sys
import os
import fitz  # PyMuPDF

# SỬA LẠI ĐÂY: Gọi từ gói 'src'
try:
    from src import IngestPipeline, PipelineConfig
except ImportError:
    # Backup nếu bạn chưa cấu hình __init__.py chuẩn
    from src.pipeline import IngestPipeline
    from src.config import PipelineConfig


def extract_text(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        doc = fitz.open(file_path)
        text = "".join([page.get_text() for page in doc])
        return text
    else:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()


def main():
    if len(sys.argv) < 2:
        print("❌ Usage: python main.py <path_to_paper>")
        return

    input_path = sys.argv[1]
    if not os.path.exists(input_path):
        print(f"❌ File not found: {input_path}")
        return

    # 1. Cấu hình TỐI ƯU CHO PHI-3.5 (4GB VRAM)
    config = PipelineConfig(
        model_tier="3b",                 # Phi-3.5 thuộc phân khúc Mini (3.8B)
        api_model_name="phi3.5:latest",  # Đảm bảo bạn đã chạy 'ollama pull phi3.5'
        output_dir="./vault/_sources"
    )

    print(f"📂 Reading file: {os.path.basename(input_path)}...")
    raw_text = extract_text(input_path)

    if not raw_text.strip():
        print("❌ Error: Could not extract text from PDF.")
        return

    # 2. Khởi chạy hệ thống
    pipeline = IngestPipeline(config)
    print(f"🚀 Processing with LLM Wiki Logic (Model: Phi-3.5)...")

    state = pipeline.run(raw_text, input_path)

    print("-" * 40)
    print(f"✅ SUCCESS: {state.extracted_title}")
    print(f"⭐ Quality Score: {state.quality_score}/100")
    print(f"📝 Status: {state.page_status}")
    print(f"📄 Type: {state.extracted_metadata.get('doc_type', 'Unknown')}")
    print("-" * 40)


if __name__ == "__main__":
    main()