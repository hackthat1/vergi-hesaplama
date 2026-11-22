"""
Gümrük Vergisi (GV) Transformer.
Resmi Gazete / Cumhurbaşkanı Kararlarından GV oranlarını taxes.json formatına çevirir.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import defaultdict

from .base import BaseTransformer


class GVTransformer(BaseTransformer):
    """GV oranlarını taxes.json formatına dönüştürür"""

    def __init__(self, config: Dict = None, mapping_config: Dict = None):
        super().__init__(config, mapping_config)
        self.output_path = Path(self.config.get("outputs", {}).get("taxes_json", "taxes.json"))

    def transform(self, raw_data: Dict) -> Dict[str, Dict]:
        """Ham GV verisini taxes.json formatına çevir"""
        # Mevcut taxes.json'ı yükle
        existing_taxes = self._load_existing_taxes()

        # Tüm kaynaklardan GV verilerini topla
        gv_by_gtip = defaultdict(list)

        for source_name, source_data in raw_data.items():
            if not isinstance(source_data, dict):
                continue

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

                    # Sadece GV ile ilgili verileri al
                    tax_type = item.get("tax_type", "").upper()
                    search_term = doc.get("search_term", "").upper()

                    is_gv = (
                        tax_type == "GV" or
                        "GUMRUK" in search_term or
                        "GV" in search_term
                    )

                    if not is_gv and "GV" not in source_name.upper():
                        continue

                    gv_by_gtip[gtip].append({
                        "rate": rate,
                        "source": source_name,
                        "note": item.get("note", ""),
                        "unit": item.get("unit", ""),
                        "doc_url": doc.get("pdf_url", ""),
                        "fetched_at": doc.get("fetched_at", ""),
                    })

        # Her GTIP için en güncel/guvenilir oranı seç
        updated_count = 0
        new_count = 0

        for gtip, entries in gv_by_gtip.items():
            # En güncel kaynağı seç (ilk bulunan - kaynaklar sıralı gelmeli)
            best_entry = self._select_best_gv_entry(entries)

            gtip_key = gtip  # 10 hane olarak sakla

            if gtip_key in existing_taxes:
                existing_taxes[gtip_key]["gv"] = best_entry["rate"]
                existing_taxes[gtip_key]["gv_note"] = best_entry.get("note", "")
                existing_taxes[gtip_key]["gv_source"] = best_entry.get("source", "")
                existing_taxes[gtip_key]["gv_updated"] = datetime.now().isoformat()
                updated_count += 1
            else:
                # Yeni entry oluştur (diğer vergiler default)
                new_entry = self._create_default_tax_entry(gtip_key)
                new_entry["gv"] = best_entry["rate"]
                new_entry["gv_note"] = best_entry.get("note", "")
                new_entry["gv_source"] = best_entry.get("source", "")
                new_entry["gv_updated"] = datetime.now().isoformat()
                existing_taxes[gtip_key] = new_entry
                new_count += 1

        self.stats["updated"] = updated_count
        self.stats["new"] = new_count
        self.stats["total_gtip_with_gv"] = len(gv_by_gtip)

        return existing_taxes

    def _select_best_gv_entry(self, entries: List[Dict]) -> Dict:
        """En iyi GV entry'sini seç"""
        # Öncelik: Cumhurbaşkanı Kararı > Resmi Gazete > Diğer
        priority = {
            "cumhurbaskani": 3,
            "resmigazete": 2,
            "gib": 1,
        }

        def get_priority(e):
            source = e.get("source", "").lower()
            for k, v in priority.items():
                if k in source:
                    return v
            return 0

        # Önce priority'ye göre, sonra tarihe göre sırala
        sorted_entries = sorted(entries, key=lambda e: (
            -get_priority(e),
            e.get("fetched_at", ""),
        ), reverse=True)

        return sorted_entries[0] if sorted_entries else {"rate": 0}

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
        """Mevcut taxes.json'ı yükle"""
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
        """taxes.json olarak kaydet (liste formatında)"""
        try:
            # Dict'i listeye çevir
            tax_list = list(data.values())
            # GTIP'e göre sırala
            tax_list.sort(key=lambda x: x.get("gtip", ""))

            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_path, "w", encoding="utf-8") as f:
                json.dump(tax_list, f, ensure_ascii=False, indent=2)

            self.logger.info(f"Saved {len(tax_list)} tax entries to {self.output_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save taxes.json: {e}")
            return False