from fastapi import FastAPI, UploadFile, File
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF
import shutil
import os
from tempfile import NamedTemporaryFile

app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def extract_text_structured(pdf_path):
    doc = fitz.open(pdf_path)
    all_text = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict")["blocks"]
        lines_by_y = {}

        for block in blocks:
            if block["type"] != 0:
                continue

            for line in block["lines"]:
                spans = line["spans"]
                if not spans:
                    continue

                avg_y = round(sum(span["bbox"][1] for span in spans) / len(spans), 1)
                if avg_y not in lines_by_y:
                    lines_by_y[avg_y] = []

                line_parts = []
                for span in spans:
                    text = span["text"].strip()
                    if not text:
                        continue

                    size = span["size"]
                    font = span["font"].lower()
                    is_bold = "bold" in font or "demi" in font

                    line_parts.append({
                        "text": text,
                        "size": size,
                        "is_bold": is_bold
                    })

                lines_by_y[avg_y].append(line_parts)

        page_lines = [f"\n=== Page {page_num + 1} ===\n"]
        for _, lines in sorted(lines_by_y.items()):
            line_texts = []
            sizes = []
            bold_flags = []

            for span_group in lines:
                combined = " ".join([span["text"] for span in span_group])
                line_texts.append(combined)
                sizes += [span["size"] for span in span_group]
                bold_flags += [span["is_bold"] for span in span_group]

            merged_line = " : ".join(line_texts)
            avg_size = sum(sizes) / len(sizes) if sizes else 0
            is_any_bold = any(bold_flags)

            if avg_size >= 16:
                tag = f"\n## {merged_line.upper()}\n"
            elif avg_size >= 13 or is_any_bold:
                tag = f"\n### {merged_line}\n"
            else:
                tag = merged_line

            page_lines.append(tag)

        all_text.append("\n".join(page_lines))

    return "\n\n".join(all_text)

@app.post("/extract", response_class=PlainTextResponse)
async def extract_text(file: UploadFile = File(...)):
    suffix = ".pdf"
    with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        shutil.copyfileobj(file.file, temp_file)
        temp_path = temp_file.name

    try:
        text = extract_text_structured(temp_path)
    finally:
        os.remove(temp_path)

    return text
