"""
PDF tablo çıkarma yardımcı sınıfı.
pdfplumber kullanarak PDF'lerden tabloları çıkarır.
"""
import pdfplumber
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class PDFTableParser:
    """
    PDF dosyalarından tablo verilerini çıkaran parser.
    pdfplumber kütüphanesini kullanır.
    """

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.table_settings = self.config.get("table_settings", {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "edge_min_length": 3,
            "min_words_vertical": 3,
            "min_words_horizontal": 1,
            "keep_blank_chars": False,
            "text_tolerance": 3,
            "text_x_tolerance": 3,
            "text_y_tolerance": 3,
        })

    def extract_tables(self, pdf_path: Path) -> List[List[List[str]]]:
        """
        PDF'den tüm tabloları çıkarır.
        Returns: List of tables, each table is List[List[str]] (rows x cols)
        """
        all_tables = []

        try:
            with pdfplumber.open(pdf_path) as pdf:
                logger.info(f"PDF opened: {pdf_path}, pages: {len(pdf.pages)}")

                for page_num, page in enumerate(pdf.pages):
                    try:
                        tables = page.extract_tables(self.table_settings)

                        if tables:
                            for table_idx, table in enumerate(tables):
                                if table and len(table) > 0:
                                    # Temizle
                                    cleaned = self._clean_table(table)
                                    if cleaned and len(cleaned) > 1:  # En az header + 1 satır
                                        all_tables.append(cleaned)
                                        logger.debug(f"Page {page_num+1}, Table {table_idx+1}: {len(cleaned)} rows x {len(cleaned[0])} cols")

                    except Exception as e:
                        logger.warning(f"Failed to extract tables from page {page_num+1}: {e}")

        except Exception as e:
            logger.error(f"Failed to open PDF {pdf_path}: {e}")

        return all_tables

    def _clean_table(self, table: List[List[Any]]) -> List[List[str]]:
        """Tabloyu temizle: None'ları boş string yap, hücreleri strip et"""
        cleaned = []
        for row in table:
            cleaned_row = []
            for cell in row:
                if cell is None:
                    cleaned_row.append("")
                else:
                    # Çoklu satırları tek satır yap
                    text = str(cell).replace("\n", " ").replace("\r", " ")
                    # Fazla boşlukları temizle
                    text = " ".join(text.split())
                    cleaned_row.append(text.strip())
            # Tamamen boş satırları atla
            if any(cell for cell in cleaned_row):
                cleaned.append(cleaned_row)
        return cleaned

    def extract_text(self, pdf_path: Path) -> str:
        """PDF'den ham metin çıkar"""
        text_parts = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
        except Exception as e:
            logger.error(f"Failed to extract text from PDF {pdf_path}: {e}")
        return "\n".join(text_parts)

    def find_tables_with_keywords(self, pdf_path: Path, keywords: List[str]) -> List[List[List[str]]]:
        """Anahtar kelime içeren tabloları bul"""
        matching_tables = []
        all_tables = self.extract_tables(pdf_path)

        for table in all_tables:
            if self._table_contains_keywords(table, keywords):
                matching_tables.append(table)

        return matching_tables

    def _table_contains_keywords(self, table: List[List[str]], keywords: List[str]) -> bool:
        """Tablo anahtar kelimelerden birini içeriyor mu?"""
        if not table:
            return False

        # İlk 3 satırda (header + 2 data) ara
        search_rows = table[:min(3, len(table))]
        text = " ".join(" ".join(row) for row in search_rows).lower()

        for kw in keywords:
            if kw.lower() in text:
                return True

        return False


# Test fonksiyonu
def test_pdf_parser(pdf_path: str):
    """PDF parser test"""
    import logging
    logging.basicConfig(level=logging.INFO)

    parser = PDFTableParser()
    tables = parser.extract_tables(Path(pdf_path))

    print(f"Found {len(tables)} tables")
    for i, table in enumerate(tables[:3]):
        print(f"\n--- Table {i+1} ({len(table)} rows x {len(table[0]) if table else 0} cols) ---")
        for row in table[:5]:
            print(row)
        if len(table) > 5:
            print(f"... and {len(table) - 5} more rows")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        test_pdf_parser(sys.argv[1])
    else:
        print("Usage: python pdf_parser.py <pdf_file>")