"""
Resmi Gazete fetcher'ı.
Cumhurbaşkanı Kararları, Kanunlar, Tebliğler arama ve PDF indirme.
"""
import re
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, quote

from .base import BaseFetcher, FetchResult, HTMLFetcherMixin, PDFFetcherMixin
from .pdf_parser import PDFTableParser


class ResmiGazeteFetcher(BaseFetcher, HTMLFetcherMixin, PDFFetcherMixin):
    """
    Resmi Gazete (resmigazete.gov.tr) ve T.C. Resmi Gazete arama motoru fetcher'ı.
    """

    BASE_URL = "https://www.resmigazete.gov.tr"
    SEARCH_URL = "https://www.resmigazete.gov.tr/arayuz/aramasonucu"

    def __init__(self, config: Dict, cache_dir: Optional[Path] = None):
        super().__init__("resmigazete", config, cache_dir)
        self.search_terms = config.get("search_terms", [])
        self.parser_config = config.get("parser", {})
        self.pdf_parser = PDFTableParser(self.parser_config)

    def fetch(self, url: str = None, **kwargs) -> FetchResult:
        """Arama terimlerine göre Resmi Gazete'ten PDF bul ve indir"""
        if url:
            return super().fetch(url, **kwargs)

        all_results = []
        for term in self.search_terms:
            logger.info(f"Searching Resmi Gazete for: {term}")
            results = self._search_and_fetch(term)
            all_results.extend(results)

        # Tüm sonuçları birleştir
        combined_data = {
            "search_terms": self.search_terms,
            "fetched_at": datetime.now().isoformat(),
            "documents": all_results,
        }

        return FetchResult(
            source_name=self.source_name,
            success=len(all_results) > 0,
            data=combined_data,
            metadata={"documents_count": len(all_results)},
        )

    def _search_and_fetch(self, search_term: str) -> List[Dict]:
        """Arama yap ve PDF'leri indir"""
        results = []

        # Arama URL'si oluştur
        search_url = f"{self.SEARCH_URL}?q={quote(search_term)}"
        try:
            response = self.session.get(search_url, timeout=self.timeout)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Search failed for '{search_term}': {e}")
            return results

        # Sonuç sayfasından PDF linklerini bul
        pdf_links = self.find_pdf_links(response.content, self.BASE_URL, [search_term])

        # En güncel 5 PDF'i indir (sayfalama varsa)
        for pdf_url in pdf_links[:5]:
            try:
                doc_data = self._fetch_and_parse_pdf(pdf_url, search_term)
                if doc_data:
                    results.append(doc_data)
            except Exception as e:
                logger.error(f"Failed to process PDF {pdf_url}: {e}")

        return results

    def _fetch_and_parse_pdf(self, pdf_url: str, search_term: str) -> Optional[Dict]:
        """PDF indir, tablo çıkar, JSON'a çevir"""
        # PDF'i indir
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            if not self.download_pdf(self.session, pdf_url, tmp_path):
                return None

            # PDF'ten tabloları çıkar
            tables = self.pdf_parser.extract_tables(tmp_path)

            if not tables:
                logger.warning(f"No tables found in PDF: {pdf_url}")
                return None

            # Tabloları işle
            parsed_data = self._parse_tables(tables, search_term)

            return {
                "pdf_url": pdf_url,
                "search_term": search_term,
                "fetched_at": datetime.now().isoformat(),
                "tables_count": len(tables),
                "data": parsed_data,
            }

        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def _parse_tables(self, tables: List, search_term: str) -> List[Dict]:
        """Çıkarılan tabloları vergi oranı formatına çevir"""
        parsed = []

        for i, table in enumerate(tables):
            if not table or len(table) < 2:
                continue

            # Başlık satırını bul
            headers = [self._normalize_header(h) for h in table[0]]

            # GTIP, Oran, Birim, Açıklama sütunlarını bul
            gtip_col = self._find_column(headers, ["gtip", "tarife", "pozisyon", "kod", "no"])
            rate_col = self._find_column(headers, ["oran", "%", "yüzde", "rate"])
            unit_col = self._find_column(headers, ["birim", "unit", "cins"])
            desc_col = self._find_column(headers, ["açıklama", "mal", "cins", "tanım", "note", "açiklama"])

            if gtip_col is None:
                continue

            for row in table[1:]:
                if len(row) <= max(filter(None, [gtip_col, rate_col, unit_col, desc_col])):
                    continue

                gtip = self._normalize_gtip(row[gtip_col])
                if not gtip:
                    continue

                item = {
                    "gtip": gtip,
                    "source": "resmigazete",
                    "search_term": search_term,
                    "table_index": i,
                }

                if rate_col is not None and rate_col < len(row):
                    item["rate"] = self._parse_rate(row[rate_col])

                if unit_col is not None and unit_col < len(row):
                    item["unit"] = self._normalize_unit(row[unit_col])

                if desc_col is not None and desc_col < len(row):
                    item["note"] = row[desc_col].strip()

                parsed.append(item)

        return parsed

    def _normalize_header(self, header: str) -> str:
        """Başlığı normalize et"""
        return re.sub(r"[^\w]+", "", header.lower().strip())

    def _find_column(self, headers: List[str], keywords: List[str]) -> Optional[int]:
        """Anahtar kelimelerle sütun bul"""
        for i, h in enumerate(headers):
            for kw in keywords:
                if kw in h:
                    return i
        return None

    def _normalize_gtip(self, value: str) -> Optional[str]:
        """GTIP kodunu normalize et"""
        if not value:
            return None
        # Sadece rakamları al
        digits = re.sub(r"[^\d]", "", value)
        if len(digits) in (6, 8, 10):
            return digits
        if len(digits) > 10:
            return digits[:10]
        return None

    def _parse_rate(self, value: str) -> Optional[float]:
        """Oran değerini parse et"""
        if not value:
            return None
        # Virgül, nokta, % temizle
        cleaned = value.replace(",", ".").replace("%", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _normalize_unit(self, value: str) -> str:
        """Birim kodunu normalize et"""
        if not value:
            return ""
        upper = value.upper().strip()
        # Yaygın eşleştirmeler
        unit_map = {
            "KG": "KG", "KGM": "KG", "KILOGRAM": "KG",
            "TON": "TON", "TNE": "TON",
            "M": "M", "MTR": "M", "METRE": "M",
            "M2": "M2", "MTK": "M2", "METREKARE": "M2",
            "M3": "M3", "MTQ": "M3", "METREKUP": "M3",
            "ADET": "ADET", "NPR": "ADET", "SAYI": "ADET",
            "LT": "LT", "LTR": "LT", "LITRE": "LT",
        }
        return unit_map.get(upper, upper)

    def parse(self, content: bytes, url: str) -> Any:
        """BaseFetcher abstract metodu - doğrudan PDF URL verilirse"""
        if url.endswith(".pdf"):
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                tmp_path.write_bytes(content)
                tables = self.pdf_parser.extract_tables(tmp_path)
                return self._parse_tables(tables, "direct_pdf")
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
        return self._parse_tables([], "unknown")


# Test fonksiyonu
async def test_resmigazete():
    """Resmi Gazete fetcher test"""
    import yaml
    with open("updater/config/sources.yaml") as f:
        config = yaml.safe_load(f)

    rg_config = config["sources"]["gv_resmigazete"]
    fetcher = ResmiGazeteFetcher(rg_config)
    result = fetcher.fetch()
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    fetcher.close()


if __name__ == "__main__":
    import asyncio
    import logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_resmigazete())