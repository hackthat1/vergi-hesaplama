"""
KDV ve ÖTV Transformer.
GİB ve Resmi Gazete verilerinden KDV/ÖTV oranlarını taxes.json'a işler.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import defaultdict

from .base import BaseTransformer


class KDVOTVTransformer(BaseTransformer):
    """KDV ve ÖTV oranlarını taxes.json formatına dönüştürür"""

    def __init__(self, config: Dict = None, mapping_config: Dict = None):
        super().__init__(config, mapping_config)
        self.output_path = Path(self.config.get("outputs", {}).get("taxes_json", "taxes.json"))

    def transform(self, raw_data: Dict) -> Dict[str, Dict]:
        """Ham KDV/OTV verisini taxes.json formatına çevir"""
        existing_taxes = self._load_existing_taxes()

        # KDV verilerini topla
        kdv_by_gtip = defaultdict(list)
        otv_by_gtip = defaultdict(list)

        for source_name, source_data in raw_data.items():
            if not isinstance(source_data, dict):
                continue

            law = source_data.get("law", "").lower()
            documents = source_data.get("documents", [])

            for doc in documents:
                data = doc.get("data", [])
                for item in data:
                    gtip = item.get("gtip")
                    if not gtip:
                        continue

                    rate = item.get("rate")
                    if rate is None:
                        continue

                    if "kdv" in law or "katma" in law:
                        kdv_by_gtip[gtip].append({
                            "rate": rate,
                            "source": source_name,
                            "note": item.get("note", ""),
                            "doc_url": doc.get("pdf_url", ""),
                            "fetched_at": doc.get("fetched_at", ""),
                        })
                    elif "otv" in law or "ozel" in law:
                        otv_by_gtip[gtip].append({
                            "rate": rate,
                            "otv_type": item.get("otv_type", "ORANALI"),
                            "source": source_name,
                            "note": item.get("note", ""),
                            "unit": item.get("unit", ""),
                            "doc_url": doc.get("pdf_url", ""),
                            "fetched_at": doc.get("fetched_at", ""),
                        })

        # KDV güncelle
        kdv_updated = 0
        for gtip, entries in kdv_by_gtip.items():
            best = self._select_best_entry(entries)
            gtip_key = gtip

            if gtip_key in existing_taxes:
                existing_taxes[gtip_key]["kdv"] = best["rate"]
                existing_taxes[gtip_key]["kdv_note"] = best.get("note", "")
                existing_taxes[gtip_key]["kdv_source"] = best.get("source", "")
                existing_taxes[gtip_key]["kdv_updated"] = datetime.now().isoformat()
                kdv_updated += 1
            else:
                new_entry = self._create_default_tax_entry(gtip_key)
                new_entry["kdv"] = best["rate"]
                new_entry["kdv_note"] = best.get("note", "")
                new_entry["kdv_source"] = best.get("source", "")
                new_entry["kdv_updated"] = datetime.now().isoformat()
                existing_taxes[gtip_key] = new_entry

        # ÖTV güncelle
        otv_updated = 0
        for gtip, entries in otv_by_gtip.items():
            best = self._select_best_otv_entry(entries)
            gtip_key = gtip

            if gtip_key in existing_taxes:
                existing_taxes[gtip_key]["otv"] = best["rate"]
                existing_taxes[gtip_key]["otv_type"] = best.get("otv_type", "ORANALI")
                existing_taxes[gtip_key]["otv_note"] = best.get("note", "")
                existing_taxes[gtip_key]["otv_source"] = best.get("source", "")
                existing_taxes[gtip_key]["otv_updated"] = datetime.now().isoformat()
                otv_updated += 1
            else:
                new_entry = self._create_default_tax_entry(gtip_key)
                new_entry["otv"] = best["rate"]
                new_entry["otv_type"] = best.get("otv_type", "ORANALI")
                new_entry["otv_note"] = best.get("note", "")
                new_entry["otv_source"] = best.get("source", "")
                new_entry["otv_updated"] = datetime.now().isoformat()
                existing_taxes[gtip_key] = new_entry

        self.stats["kdv_updated"] = kdv_updated
        self.stats["otv_updated"] = otv_updated

        return existing_taxes

    def _select_best_entry(self, entries: List[Dict]) -> Dict:
        """En iyi entry'yi seç (GİB > Resmi Gazete > Diğer)"""
        priority = {"gib": 3, "resmigazete": 2, "cumhurbaskani": 1}

        def get_priority(e):
            source = e.get("source", "").lower()
            for k, v in priority.items():
                if k in source:
                    return v
            return 0

        sorted_entries = sorted(entries, key=lambda e: (
            -get_priority(e),
            e.get("fetched_at", ""),
        ), reverse=True)

        return sorted_entries[0] if sorted_entries else {"rate": 0}

    def _select_best_otv_entry(self, entries: List[Dict]) -> Dict:
        """En iyi ÖTV entry'sini seç"""
        best = self._select_best_entry(entries)
        # OTV türünü de kontrol et
        return best

    def _create_default_tax_entry(self, gtip: str) -> Dict:
        """Default vergi entry'si oluştur"""
        defaults = self.mapping_config.get("defaults", {})
        return {
            "gtip": gtip,
            "gv": defaults.get("gv", 0),
            "kdv": defaults.get("kdv", 20),
            "otv": defaults.get("otv", 0),
            "otv_type": defaults.get("otv_type", "ORANALI"),
            "igv": defaults.get("igv", 0),
            "emy": defaults.get("emy", 0),
            "bandrol": defaults.get("bandrol", 0),
            "kkdf": defaults.get("kkdf", 0),
            "damping": defaults.get("damping", 0),
            "kultur": defaults.get("kultur", 0),
            "note": "",
            "source": "auto_generated",
            "created_at": datetime.now().isoformat(),
        }

    def _load_existing_taxes(self) -> Dict:
        if self.output_path.exists():
            try:
                with open(self.output_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return {item.get("gtip", ""): item for item in data if item.get("gtip")}
                    elif isinstance(data, dict):
                        return data
            except Exception as e:
                self.logger.error(f"Failed to load existing taxes.json: {e}")
        return {}

    def save(self, data: Dict) -> bool:
        try:
            tax_list = list(data.values())
            tax_list.sort(key=lambda x: x.get("gtip", ""))

            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_path, "w", encoding="utf-8") as f:
                json.dump(tax_list, f, ensure_ascii=False, indent=2)

            self.logger.info(f"Saved {len(tax_list)} tax entries to {self.output_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save taxes.json: {e}")
            return False