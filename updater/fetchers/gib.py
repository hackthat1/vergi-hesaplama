"""
GİB (Gelir İdaresi Başkanlığı) fetcher'ı.
KDV, ÖTV, Diğer vergiler için mevzuat sayfaları ve PDF'ler.
"""
import re
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from .base import BaseFetcher, FetchResult, HTMLFetcherMixin, PDFFetcherMixin
from .pdf_parser import PDFTableParser


class GIBFetcher(BaseFetcher, HTMLFetcherMixin, PDFFetcherMixin):
    """
    GİB (https://www.gib.gov.tr) fetcher'ı.
    KDV Kanunu, ÖTV Kanunu, mevzuat sayfalarından oranları çeker.
    """

    BASE_URL = "https://www.gib.gov.tr"

    def __init__(self, config: Dict, cache_dir: Optional[Path] = None):
        super().__init__("gib", config, cache_dir)
        self.parser_config = config.get("parser", {})
        self.pdf_parser = PDFTableParser(self.parser_config)
        self.target_law = config.get("target_law", "")  # "kdv" or "otv"

    def fetch(self, url: str = None, **kwargs) -> FetchResult:
        """GİB sayfasından PDF linklerini bul ve işle"""
        if url:
            return super().fetch(url, **kwargs)

        all_results = []
        for target_url in self.config.get("urls", []):
            logger.info(f"Fetching GIB page: {target_url}")
            results = self._fetch_page(target_url)
            all_results.extend(results)

        combined_data = {
            "target_law": self.target_law,
            "fetched_at": datetime.now().isoformat(),
            "documents": all_results,
        }

        return FetchResult(
            source_name=self.source_name,
            success=len(all_results) > 0,
            data=combined_data,
            metadata={"documents_count": len(all_results), "law": self.target_law},
        )

    def _fetch_page(self, url: str) -> List[Dict]:
        """Tek bir GİB sayfasını işle"""
        results = []

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return results

        # PDF linklerini bul
        pdf_links = self.find_pdf_links(response.content, self.BASE_URL)

        # İlgili PDF'leri filtrele (KDV/ÖTV oranları içeren)
        relevant_pdfs = self._filter_relevant_pdfs(pdf_links, response.content)

        for pdf_url in relevant_pdfs[:3]:  # En fazla 3 PDF
            try:
                doc_data = self._fetch_and_parse_pdf(pdf_url)
                if doc_data:
                    results.append(doc_data)
            except Exception as e:
                logger.error(f"Failed to process PDF {pdf_url}: {e}")

        return results

    def _filter_relevant_pdfs(self, pdf_links: List[str], page_html: bytes) -> List[str]:
        """Sayfa içeriğine göre ilgili PDF'leri filtrele"""
        # Sayfa metninden bağlam al
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(page_html, "lxml")
        page_text = soup.get_text().lower()

        # KDV/ÖTV anahtar kelimeleri
        keywords = []
        if "kdv" in self.target_law.lower() or "katma" in page_text:
            keywords.extend(["kdv", "katma deger", "oranlar", "liste"])
        if "otv" in self.target_law.lower() or "ozel tuketim" in page_text:
            keywords.extend(["otv", "ozel tuketim", "oranlar", "liste"])

        # Link metinlerini de kontrol et
        relevant = []
        for pdf_url in pdf_links:
            # URL'de anahtar kelime var mı?
            url_lower = pdf_url.lower()
            if any(kw in url_lower for kw in ["oran", "liste", "tarife", "kdv", "otv"]):
                relevant.append(pdf_url)
                continue

            # Sayfa metninde bu PDF'e referans var mı?
            pdf_name = pdf_url.split("/")[-1].lower()
            if any(kw in pdf_name for kw in keywords):
                relevant.append(pdf_url)

        return relevant if relevant else pdf_links[:3]

    def _fetch_and_parse_pdf(self, pdf_url: str) -> Optional[Dict]:
        """PDF indir ve parse et"""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            if not self.download_pdf(self.session, pdf_url, tmp_path):
                return None

            tables = self.pdf_parser.extract_tables(tmp_path)

            if not tables:
                return None

            parsed_data = self._parse_gib_tables(tables)

            return {
                "pdf_url": pdf_url,
                "law": self.target_law,
                "fetched_at": datetime.now().isoformat(),
                "tables_count": len(tables),
                "data": parsed_data,
            }

        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def _parse_gib_tables(self, tables: List) -> List[Dict]:
        """GİB PDF tablolarını parse et"""
        parsed = []

        for i, table in enumerate(tables):
            if not table or len(table) < 2:
                continue

            headers = [self._normalize_header(h) for h in table[0]]

            # Sütun indeksleri
            gtip_col = self._find_column(headers, ["gtip", "tarife", "pozisyon", "kod", "no", "tarifen"])
            desc_col = self._find_column(headers, ["mal", "cins", "tanım", "aciklama", "note", "adi"])
            rate_col = self._find_column(headers, ["oran", "%", "yuzde", "rate", "vergiorani"])

            # ÖTV için ek sütunlar
            otv_type_col = self._find_column(headers, ["tur", "tip", "cins", "sekil", "muktessep", "oranli"])
            unit_col = self._find_column(headers, ["birim", "unit", "cins"])

            if gtip_col is None:
                continue

            for row in table[1:]:
                max_col = max(filter(lambda x: x is not None, [gtip_col, desc_col, rate_col, otv_type_col, unit_col]))
                if len(row) <= max_col:
                    continue

                gtip = self._normalize_gtip(row[gtip_col])
                if not gtip:
                    continue

                item = {
                    "gtip": gtip,
                    "source": "gib",
                    "law": self.target_law,
                    "table_index": i,
                }

                if desc_col is not None and desc_col < len(row):
                    item["note"] = row[desc_col].strip()

                if rate_col is not None and rate_col < len(row):
                    item["rate"] = self._parse_rate(row[rate_col])

                if otv_type_col is not None and otv_type_col < len(row):
                    item["otv_type"] = self._normalize_otv_type(row[otv_type_col])

                if unit_col is not None and unit_col < len(row):
                    item["unit"] = self._normalize_unit(row[unit_col])

                parsed.append(item)

        return parsed

    def _normalize_header(self, header: str) -> str:
        return re.sub(r"[^\w]+", "", header.lower().strip().replace("ı", "i").replace("ğ", "g").replace("ü", "u").replace("ş", "s").replace("ö", "o").replace("ç", "c"))

    def _find_column(self, headers: List[str], keywords: List[str]) -> Optional[int]:
        for i, h in enumerate(headers):
            for kw in keywords:
                if kw in h:
                    return i
        return None

    def _normalize_gtip(self, value: str) -> Optional[str]:
        if not value:
            return None
        digits = re.sub(r"[^\d]", "", value)
        if len(digits) in (6, 8, 10):
            return digits
        if len(digits) > 10:
            return digits[:10]
        return None

    def _parse_rate(self, value: str) -> Optional[float]:
        if not value:
            return None
        cleaned = value.replace(",", ".").replace("%", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _normalize_otv_type(self, value: str) -> str:
        if not value:
            return "ORANALI"
        upper = value.upper().strip().replace("İ", "I").replace("Ü", "U")
        if "MUKT" in upper or "MÜKT" in upper or "SPECIFIC" in upper:
            return "MUKTESEP"
        if "KARMA" in upper or "MIXED" in upper:
            return "KARMA"
        return "ORANALI"

    def _normalize_unit(self, value: str) -> str:
        if not value:
            return ""
        upper = value.upper().strip()
        unit_map = {
            "KG": "KG", "KGM": "KG", "KILOGRAM": "KG",
            "TON": "TON", "TNE": "TON",
            "M": "M", "MTR": "M", "METRE": "M",
            "M2": "M2", "MTK": "M2",
            "M3": "M3", "MTQ": "M3",
            "ADET": "ADET", "NPR": "ADET", "SAYI": "ADET",
            "LT": "LT", "LTR": "LT", "LITRE": "LT",
        }
        return unit_map.get(upper, upper)

    def parse(self, content: bytes, url: str) -> Any:
        if url.endswith(".pdf"):
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                tmp_path.write_bytes(content)
                tables = self.pdf_parser.extract_tables(tmp_path)
                return self._parse_gib_tables(tables)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
        return []


# Test
async def test_gib():
    import yaml
    with open("updater/config/sources.yaml") as f:
        config = yaml.safe_load(f)

    for key in ["kdv_gib", "otv_gib"]:
        gib_config = config["sources"][key]
        fetcher = GIBFetcher(gib_config)
        result = fetcher.fetch()
        print(f"\n=== {key} ===")
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        fetcher.close()


if __name__ == "__main__":
    import asyncio
    import logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_gib())