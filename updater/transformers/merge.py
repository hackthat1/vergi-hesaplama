"""
Data Merger - Tüm transformer çıktılarını birleştirir, doğrular, kaydeder.
"""
import json
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import defaultdict

from .gtip import GTIPTransformer
from .gv import GVTransformer
from .kdv_otv import KDVOTVTransformer
from .emy_others import EMYOthersTransformer


class DataMerger:
    """
    Tüm transformer'ları koordine eder:
    1. GTIPTransformer → rates.json
    2. GVTransformer → taxes.json (gv)
    3. KDVOTVTransformer → taxes.json (kdv, otv)
    4. EMYOthersTransformer → taxes.json (emy, bandrol, kkdf, damping)
    5. Merge + Validate + Save
    """

    def __init__(self, config_path: str = "updater/config/sources.yaml", mapping_path: str = "updater/config/mapping.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        with open(mapping_path, "r", encoding="utf-8") as f:
            self.mapping_config = yaml.safe_load(f)

        self.outputs = self.config.get("outputs", {})
        self.taxes_path = Path(self.outputs.get("taxes_json", "taxes.json"))
        self.rates_path = Path(self.outputs.get("rates_json", "rates.json"))
        self.changelog_path = Path(self.outputs.get("changelog", "CHANGELOG_RATES.md"))

        # Transformer'ları başlat
        self.gtip_transformer = GTIPTransformer(self.config, self.mapping_config)
        self.gv_transformer = GVTransformer(self.config, self.mapping_config)
        self.kdv_otv_transformer = KDVOTVTransformer(self.config, self.mapping_config)
        self.emy_transformer = EMYOthersTransformer(self.config, self.mapping_config)

        self.all_stats = {}

    def run(self, raw_data: Dict) -> Dict[str, Any]:
        """Tüm pipeline'ı çalıştır"""
        print("=" * 60)
        print("VERGİ ORANLARI GÜNCELLEME PIPELINE'I")
        print("=" * 60)

        # 1. GTIP → rates.json
        print("\n[1/5] GTIP listesi işleniyor (rates.json)...")
        rates_data = self.gtip_transformer.transform(raw_data.get("gtip_tuik", {}))
        self.gtip_transformer.save(rates_data)
        self.all_stats["gtip"] = self.gtip_transformer.stats

        # 2. GV → taxes.json
        print("\n[2/5] Gümrük Vergisi oranları işleniyor...")
        gv_data = self.gv_transformer.transform(raw_data)
        # Henüz kaydetme, birleştirilecek

        # 3. KDV/OTV → taxes.json
        print("\n[3/5] KDV ve ÖTV oranları işleniyor...")
        kdv_otv_data = self.kdv_otv_transformer.transform(raw_data)

        # 4. EMY/Others → taxes.json
        print("\n[4/5] EMY, Bandrol, KKDF, Damping oranları işleniyor...")
        emy_data = self.emy_transformer.transform(raw_data)

        # 5. Birleştir ve kaydet
        print("\n[5/5] Veriler birleştiriliyor ve kaydediliyor...")
        final_taxes = self._merge_tax_data(gv_data, kdv_otv_data, emy_data)
        self._save_taxes(final_taxes)

        # Changelog oluştur
        self._generate_changelog()

        # Özet
        self._print_summary()

        return {
            "taxes_count": len(final_taxes),
            "rates_count": len(rates_data),
            "stats": self.all_stats,
        }

    def _merge_tax_data(self, *data_sources: Dict) -> Dict[str, Dict]:
        """Birden fazla tax data kaynağını birleştir"""
        merged = {}

        for data in data_sources:
            if not isinstance(data, dict):
                continue
            for gtip, entry in data.items():
                if gtip not in merged:
                    merged[gtip] = entry
                else:
                    # Mevcut entry'yi güncelle (None olmayan değerlerle)
                    for key, value in entry.items():
                        if value is not None and value != "" and key != "gtip":
                            merged[gtip][key] = value

        # Manual overrides uygula
        merged = self._apply_manual_overrides(merged)

        # Default değerleri doldur
        merged = self._fill_defaults(merged)

        return merged

    def _apply_manual_overrides(self, taxes: Dict) -> Dict:
        """Mapping.yaml'daki manual_overrides'ları uygula"""
        overrides = self.mapping_config.get("manual_overrides", {})

        for gtip_prefix, override in overrides.items():
            # Prefix eşleşmesi (örn: "8703" -> "870310", "870321", ...)
            for gtip, entry in taxes.items():
                if gtip.startswith(gtip_prefix):
                    for key, value in override.items():
                        entry[key] = value
                        entry[f"{key}_source"] = "manual_override"
                        entry[f"{key}_updated"] = datetime.now().isoformat()

        return taxes

    def _fill_defaults(self, taxes: Dict) -> Dict:
        """Eksik alanları default değerlerle doldur"""
        defaults = self.mapping_config.get("defaults", {})

        for entry in taxes.values():
            for field, default_value in defaults.items():
                if field not in entry or entry[field] is None:
                    entry[field] = default_value

        return taxes

    def _save_taxes(self, taxes: Dict):
        """taxes.json kaydet"""
        tax_list = list(taxes.values())
        tax_list.sort(key=lambda x: x.get("gtip", ""))

        self.taxes_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.taxes_path, "w", encoding="utf-8") as f:
            json.dump(tax_list, f, ensure_ascii=False, indent=2)

        print(f"  ✓ {len(tax_list)} kayıt {self.taxes_path}'e kaydedildi")

    def _generate_changelog(self):
        """CHANGELOG_RATES.md oluştur"""
        changelog = f"""# Vergi Oranları Değişim Kaydı

**Son Güncelleme:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Özet
- **taxes.json**: {self.all_stats.get('gv', {}).get('total_gtip_with_gv', 0) + self.all_stats.get('kdv_otv', {}).get('kdv_updated', 0) + self.all_stats.get('kdv_otv', {}).get('otv_updated', 0) + sum(self.all_stats.get('emy', {}).values())} GTIP güncellendi
- **rates.json**: {self.all_stats.get('gtip', {}).get('new_entries', 0)} yeni GTIP eklendi, {self.all_stats.get('gtip', {}).get('updated_entries', 0)} güncellendi

## Detaylar

### Gümrük Vergisi (GV)
- Güncellenen: {self.all_stats.get('gv', {}).get('updated', 0)}
- Yeni eklenen: {self.all_stats.get('gv', {}).get('new', 0)}

### KDV
- Güncellenen: {self.all_stats.get('kdv_otv', {}).get('kdv_updated', 0)}

### ÖTV
- Güncellenen: {self.all_stats.get('kdv_otv', {}).get('otv_updated', 0)}

### Ek Mali Yükümlülükler
- EMY: {self.all_stats.get('emy', {}).get('emy', 0)}
- Bandrol: {self.all_stats.get('emy', {}).get('bandrol', 0)}
- KKDF: {self.all_stats.get('emy', {}).get('kkdf', 0)}
- Damping: {self.all_stats.get('emy', {}).get('damping', 0)}

## GTIP Bazlı Değişiklikler
<!-- Otomatik doldurulur, manuel düzenleme gerekmez -->

"""

        self.changelog_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.changelog_path, "w", encoding="utf-8") as f:
            f.write(changelog)

        print(f"  ✓ Changelog {self.changelog_path}'e kaydedildi")

    def _print_summary(self):
        """Özet yazdır"""
        print("\n" + "=" * 60)
        print("GÜNCELLEME TAMAMLANDI")
        print("=" * 60)
        print(f"taxes.json: {self.taxes_path}")
        print(f"rates.json: {self.rates_path}")
        print(f"changelog: {self.changelog_path}")
        print("\nİstatistikler:")
        for key, stats in self.all_stats.items():
            print(f"  {key}: {stats}")