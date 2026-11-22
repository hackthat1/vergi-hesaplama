"""
TÜİK (Türkiye İstatistik Kurumu) fetcher'ı.
GTIP (Tarife Pozisyonları) listesi için açık veri portalı.
"""
import re
import json
import csv
import io
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from .base import BaseFetcher, FetchResult, HTMLFetcherMixin
from .pdf_parser import PDFTableParser


class TUİKFetcher(BaseFetcher, HTMLFetcherMixin):
    """
    TÜİK açık veri portalından GTIP tarife pozisyonlarını çeker.
    Class name uses ASCII: TUIKFetcher
    """

    BASE_URL = "https://data.tuik.gov.tr"
    GTIP_DATASET_URL = "https://data.tuik.gov.tr/Bulten/Index?p=Dis-Ticaret-Istatistikleri"

    def __init__(self, config: Dict, cache_dir: Optional[Path] = None):
        super().__init__("tuik", config, cache_dir)
        self.parser_config = config.get("parser", {})

    def fetch(self, url: str = None, **kwargs) -> FetchResult:
        """TÜİK'ten GTIP verisi çek"""
        if url:
            return super().fetch(url, **kwargs)

        all_data = []

        for target_url in self.config.get("urls", []):
            logger.info(f"Fetching TÜİK: {target_url}")
            data = self._fetch_dataset(target_url)
            all_data.extend(data)

        # Mevcut rates.json'dan da GTIP kodlarını al (merge için)
        existing_rates = self._load_existing_rates()

        combined_data = {
            "fetched_at": datetime.now().isoformat(),
            "source": "tuik",
            "records_count": len(all_data),
            "gtip_list": all_data,
            "existing_rates_count": len(existing_rates),
        }

        return FetchResult(
            source_name=self.source_name,
            success=len(all_data) > 0,
            data=combined_data,
            metadata={"records": len(all_data)},
        )

    def _fetch_dataset(self, url: str) -> List[Dict]:
        """TÜİK veri setini çek - HTML sayfasından CSV/Excel linki bul"""
        results = []

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to fetch TÜİK page: {e}")
            return results

        # Sayfadan indirme linklerini bul (CSV, Excel, JSON)
        download_links = self._find_download_links(response.content)

        for link in download_links:
            try:
                data = self._download_and_parse(link)
                if data:
                    results.extend(data)
                    break  # İlk başarılı link yeterli
            except Exception as e:
                logger.error(f"Failed to process {link}: {e}")

        # Eğer doğrudan indirme linki bulunamazsa, sayfadaki tabloyu parse et
        if not results:
            results = self._parse_html_table(response.content)

        return results

    def _find_download_links(self, html: bytes) -> List[str]:
        """Sayfadan CSV/Excel/JSON indirme linklerini bul"""
        links = self.extract_links(html, self.BASE_URL)
        download_links = []

        for link in links:
            url = link["url"].lower()
            text = (link["text"] + " " + link.get("title", "")).lower()
            if any(ext in url for ext in [".csv", ".xlsx", ".xls", ".json"]) or \
               any(kw in text for kw in ["indir", "download", "csv", "excel", "açık veri", "veri seti"]):
                download_links.append(link["url"])

        return download_links

    def _download_and_parse(self, url: str) -> List[Dict]:
        """Dosyayı indir ve parse et"""
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            content = response.content

            if url.endswith(".csv"):
                return self._parse_csv(content)
            elif url.endswith((".xlsx", ".xls")):
                return self._parse_excel(content)
            elif url.endswith(".json"):
                return self._parse_json(content)
        except Exception as e:
            logger.error(f"Download/parse failed for {url}: {e}")

        return []

    def _parse_csv(self, content: bytes) -> List[Dict]:
        """CSV parse et"""
        text = content.decode("utf-8-sig")  # BOM desteği
        reader = csv.DictReader(io.StringIO(text))
        results = []

        for row in reader:
            # Sütun adlarını normalize et
            normalized = {k.lower().strip(): v for k, v in row.items()}

            # GTIP kodunu bul
            gtip = None
            for key in ["gtip", "tarife", "pozisyon", "kod", "tarife_no", "tarife_kodu"]:
                if key in normalized and normalized[key]:
                    gtip = self._normalize_gtip(normalized[key])
                    break

            if not gtip:
                continue

            # Açıklamayı bul
            desc = ""
            for key in ["aciklama", "mal_cinsi", "cins", "tanım", "mal_adi", "description"]:
                if key in normalized and normalized[key]:
                    desc = normalized[key].strip()
                    break

            # Birimi bul
            unit = ""
            for key in ["birim", "unit", "cins_birimi", "olcu_birimi"]:
                if key in normalized and normalized[key]:
                    unit = self._normalize_unit(normalized[key])
                    break

            results.append({
                "gtip": gtip,
                "note": desc,
                "unit": unit,
                "source": "tuik_csv",
            })

        return results

    def _parse_excel(self, content: bytes) -> List[Dict]:
        """Excel parse et (openpyxl)"""
        try:
            import openpyxl
            from io import BytesIO

            wb = openpyxl.load_workbook(BytesIO(content), read_only=True)
            ws = wb.active

            results = []
            headers = None

            for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
                if row_idx == 0:
                    headers = [str(c).lower().strip() if c else "" for c in row]
                    continue

                if not headers:
                    continue

                row_dict = dict(zip(headers, row))

                # GTIP bul
                gtip = None
                for key in headers:
                    if any(kw in key for kw in ["gtip", "tarife", "pozisyon", "kod"]):
                        if row_dict.get(key):
                            gtip = self._normalize_gtip(str(row_dict[key]))
                            break

                if not gtip:
                    continue

                # Diğer alanlar
                desc = ""
                for key in headers:
                    if any(kw in key for kw in ["aciklama", "mal", "cins", "tanım", "adi"]):
                        if row_dict.get(key):
                            desc = str(row_dict[key]).strip()
                            break

                unit = ""
                for key in headers:
                    if any(kw in key for kw in ["birim", "unit", "cins"]):
                        if row_dict.get(key):
                            unit = self._normalize_unit(str(row_dict[key]))
                            break

                results.append({
                    "gtip": gtip,
                    "note": desc,
                    "unit": unit,
                    "source": "tuik_excel",
                })

            return results

        except Exception as e:
            logger.error(f"Excel parse failed: {e}")
            return []

    def _parse_json(self, content: bytes) -> List[Dict]:
        """JSON parse et"""
        try:
            data = json.loads(content.decode("utf-8"))
            # JSON yapısına göre uyarlanmalı
            if isinstance(data, list):
                return self._normalize_json_records(data)
            elif isinstance(data, dict) and "data" in data:
                return self._normalize_json_records(data["data"])
        except Exception as e:
            logger.error(f"JSON parse failed: {e}")
        return []

    def _normalize_json_records(self, records: List[Dict]) -> List[Dict]:
        """JSON kayıtlarını normalize et"""
        results = []
        for rec in records:
            gtip = None
            for key in ["gtip", "tarife", "pozisyon", "kod", "tarife_no"]:
                if key in rec and rec[key]:
                    gtip = self._normalize_gtip(str(rec[key]))
                    break

            if not gtip:
                continue

            desc = rec.get("aciklama") or rec.get("mal_cinsi") or rec.get("cins") or ""
            unit = rec.get("birim") or rec.get("unit") or ""

            results.append({
                "gtip": gtip,
                "note": str(desc).strip() if desc else "",
                "unit": self._normalize_unit(str(unit)) if unit else "",
                "source": "tuik_json",
            })
        return results

    def _parse_html_table(self, html: bytes) -> List[Dict]:
        """HTML sayfasındaki tabloyu parse et"""
        tables = self.extract_tables(html)
        results = []

        for table in tables:
            if len(table) < 2:
                continue

            headers = [self._normalize_header(h) for h in table[0]]
            gtip_col = self._find_column(headers, ["gtip", "tarife", "pozisyon", "kod"])
            desc_col = self._find_column(headers, ["aciklama", "mal", "cins", "tanım", "adi"])
            unit_col = self._find_column(headers, ["birim", "unit", "cins"])

            if gtip_col is None:
                continue

            for row in table[1:]:
                max_col = max(filter(lambda x: x is not None, [gtip_col, desc_col, unit_col]))
                if len(row) <= max_col:
                    continue

                gtip = self._normalize_gtip(row[gtip_col])
                if not gtip:
                    continue

                item = {"gtip": gtip, "source": "tuik_html"}
                if desc_col is not None and desc_col < len(row):
                    item["note"] = row[desc_col].strip()
                if unit_col is not None and unit_col < len(row):
                    item["unit"] = self._normalize_unit(row[unit_col])

                results.append(item)

        return results

    def _load_existing_rates(self) -> Dict:
        """Mevcut rates.json'ı yükle"""
        rates_path = Path("rates.json")
        if rates_path.exists():
            try:
                with open(rates_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return {item.get("gtip", ""): item for item in data if item.get("gtip")}
                    elif isinstance(data, dict):
                        return data
            except Exception as e:
                logger.error(f"Failed to load existing rates.json: {e}")
        return {}

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
        if url.endswith(".csv"):
            return self._parse_csv(content)
        elif url.endswith((".xlsx", ".xls")):
            return self._parse_excel(content)
        elif url.endswith(".json"):
            return self._parse_json(content)
        return self._parse_html_table(content)


# Test
async def test_tuik():
    import yaml
    with open("updater/config/sources.yaml") as f:
        config = yaml.safe_load(f)

    tuik_config = config["sources"]["gtip_tuik"]
    fetcher = TUİKFetcher(tuik_config)
    result = fetcher.fetch()
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    fetcher.close()


if __name__ == "__main__":
    import asyncio
    import logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_tuik())