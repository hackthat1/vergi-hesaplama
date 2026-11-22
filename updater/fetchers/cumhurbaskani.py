"""
Cumhurbaşkanı Kararları fetcher'ı.
tccb.gov.tr üzerinden vergi ile ilgili kararları çeker.
"""
import re
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from .base import BaseFetcher, FetchResult, HTMLFetcherMixin, PDFFetcherMixin
from .pdf_parser import PDFTableParser


class CumhurbaskaniFetcher(BaseFetcher, HTMLFetcherMixin, PDFFetcherMixin):
    """
    Cumhurbaşkanı Kararları (tccb.gov.tr) fetcher'ı.
    Vergi oranları ile ilgili kararları bulur.
    """

    BASE_URL = "https://www.tccb.gov.tr"
    KARARLAR_URL = "https://www.tccb.gov.tr/kurumlar/tccb.gov.tr/ekler/kararlar/"

    def __init__(self, config: Dict, cache_dir: Optional[Path] = None):
        super().__init__("cumhurbaskani", config, cache_dir)
        self.search_terms = config.get("search_terms", [])
        self.parser_config = config.get("parser", {})
        self.pdf_parser = PDFTableParser(self.parser_config)

    def fetch(self, url: str = None, **kwargs) -> FetchResult:
        """Kararlar sayfasından vergi ile ilgili PDF'leri bul"""
        if url:
            return super().fetch(url, **kwargs)

        all_results = []

        # Ana kararlar sayfasını çek
        try:
            response = self.session.get(self.KARARLAR_URL, timeout=self.timeout)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to fetch kararlar page: {e}")
            return FetchResult(
                source_name=self.source_name,
                success=False,
                error=str(e),
            )

        # Yıl bazlı klasör linklerini bul
        year_links = self._find_year_folders(response.content)

        # Son 3 yılı kontrol et (güncel kararlar için)
        for year_url in year_links[:3]:
            year_results = self._fetch_year_page(year_url)
            all_results.extend(year_results)

        combined_data = {
            "fetched_at": datetime.now().isoformat(),
            "search_terms": self.search_terms,
            "documents": all_results,
        }

        return FetchResult(
            source_name=self.source_name,
            success=len(all_results) > 0,
            data=combined_data,
            metadata={"documents_count": len(all_results)},
        )

    def _find_year_folders(self, html: bytes) -> List[str]:
        """Yıl bazlı klasör linklerini bul"""
        links = self.extract_links(html, self.BASE_URL)
        year_links = []

        for link in links:
            # Yıl formatında linkler: /2024/, /2023/, vb.
            match = re.search(r"/(20\d{2})/", link["url"])
            if match:
                year = int(match.group(1))
                if year >= 2022:  # Son 3 yıl
                    year_links.append(link["url"])

        # Yılları sırala (en yeni önce)
        year_links.sort(reverse=True)
        return year_links

    def _fetch_year_page(self, year_url: str) -> List[Dict]:
        """Belirli bir yılın kararlar sayfasını işle"""
        results = []

        try:
            response = self.session.get(year_url, timeout=self.timeout)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to fetch year page {year_url}: {e}")
            return results

        # Sayfadaki PDF linklerini bul
        pdf_links = self.find_pdf_links(response.content, self.BASE_URL, self.search_terms)

        for pdf_url in pdf_links[:5]:  # Yıl başına en fazla 5 PDF
            try:
                doc_data = self._fetch_and_parse_pdf(pdf_url)
                if doc_data:
                    results.append(doc_data)
            except Exception as e:
                logger.error(f"Failed to process PDF {pdf_url}: {e}")

        return results

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

            parsed_data = self._parse_cbk_tables(tables)

            return {
                "pdf_url": pdf_url,
                "fetched_at": datetime.now().isoformat(),
                "tables_count": len(tables),
                "data": parsed_data,
            }

        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def _parse_cbk_tables(self, tables: List) -> List[Dict]:
        """Cumhurbaşkanı Kararı tablolarını parse et"""
        parsed = []

        for i, table in enumerate(tables):
            if not table or len(table) < 2:
                continue

            headers = [self._normalize_header(h) for h in table[0]]

            gtip_col = self._find_column(headers, ["gtip", "tarife", "pozisyon", "kod", "no"])
            rate_col = self._find_column(headers, ["oran", "%", "yuzde", "rate"])
            desc_col = self._find_column(headers, ["aciklama", "mal", "cins", "tanım", "note"])
            unit_col = self._find_column(headers, ["birim", "unit", "cins"])
            tax_type_col = self._find_column(headers, ["vergitur", "tur", "tip", "gumruk", "kdv", "otv"])

            if gtip_col is None:
                continue

            for row in table[1:]:
                max_col = max(filter(lambda x: x is not None, [gtip_col, rate_col, desc_col, unit_col, tax_type_col]))
                if len(row) <= max_col:
                    continue

                gtip = self._normalize_gtip(row[gtip_col])
                if not gtip:
                    continue

                item = {
                    "gtip": gtip,
                    "source": "cumhurbaskani",
                    "table_index": i,
                }

                if rate_col is not None and rate_col < len(row):
                    item["rate"] = self._parse_rate(row[rate_col])

                if desc_col is not None and desc_col < len(row):
                    item["note"] = row[desc_col].strip()

                if unit_col is not None and unit_col < len(row):
                    item["unit"] = self._normalize_unit(row[unit_col])

                if tax_type_col is not None and tax_type_col < len(row):
                    item["tax_type"] = self._normalize_tax_type(row[tax_type_col])

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

    def _normalize_tax_type(self, value: str) -> str:
        if not value:
            return "GV"
        upper = value.upper().strip().replace("İ", "I").replace("Ü", "U").replace("Ğ", "G")
        if "GUMRUK" in upper or "GV" in upper:
            return "GV"
        if "KDV" in upper or "KATMA" in upper:
            return "KDV"
        if "OTV" in upper or "OZEL" in upper:
            return "OTV"
        if "ILAVE" in upper or "IGV" in upper:
            return "IGV"
        if "EMY" in upper or "EK MALI" in upper:
            return "EMY"
        if "BANDROL" in upper:
            return "BANDROL"
        if "KKDF" in upper:
            return "KKDF"
        if "DAMPING" in upper:
            return "DAMPING"
        return "GV"

    def parse(self, content: bytes, url: str) -> Any:
        if url.endswith(".pdf"):
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                tmp_path.write_bytes(content)
                tables = self.pdf_parser.extract_tables(tmp_path)
                return self._parse_cbk_tables(tables)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
        return []


# Test
async def test_cbk():
    import yaml
    with open("updater/config/sources.yaml") as f:
        config = yaml.safe_load(f)

    cbk_config = config["sources"]["cumhurbaskani_kararlari"]
    fetcher = CumhurbaskaniFetcher(cbk_config)
    result = fetcher.fetch()
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    fetcher.close()


if __name__ == "__main__":
    import asyncio
    import logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_cbk())