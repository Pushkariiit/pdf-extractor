from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from dotenv import load_dotenv
import os
import fitz  # PyMuPDF
import shutil
from tempfile import NamedTemporaryFile

# Load env
load_dotenv()
DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")

# SQLAlchemy setup
DATABASE_URL = f"mysql+pymysql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# FastAPI app
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database model
class PDFExtractedText(Base):
    __tablename__ = "pdf_extracted_text"
    id = Column(Integer, primary_key=True, index=True)
    class_id = Column(Integer)
    subject_id = Column(Integer)
    course_id = Column(Integer)
    module_id = Column(Integer)
    extracted_text = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Create table
Base.metadata.create_all(bind=engine)

# PDF text extraction
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

# Endpoint
@app.post("/extract", response_class=PlainTextResponse)
async def extract_text(
    file: UploadFile = File(...),
    class_id: int = Form(...),
    subject_id: int = Form(...),
    course_id: int = Form(...),
    module_id: int = Form(...)
):
    suffix = ".pdf"
    with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        shutil.copyfileobj(file.file, temp_file)
        temp_path = temp_file.name

    try:
        text = extract_text_structured(temp_path)

        db = SessionLocal()
        existing_entry = db.query(PDFExtractedText).filter_by(
            class_id=class_id,
            subject_id=subject_id,
            course_id=course_id,
            module_id=module_id
        ).first()

        if existing_entry:
            existing_entry.extracted_text = text
            existing_entry.updated_at = datetime.utcnow()
            db.commit()
            message = "🔁 Updated existing entry."
        else:
            new_entry = PDFExtractedText(
                class_id=class_id,
                subject_id=subject_id,
                course_id=course_id,
                module_id=module_id,
                extracted_text=text,
            )
            db.add(new_entry)
            db.commit()
            message = "✅ Inserted new entry."

    except Exception as e:
        print("❌ DB Error:", e)
        message = "❌ Failed to save to database."
    finally:
        db.close()
        os.remove(temp_path)

    return message + "\n\n" + text
