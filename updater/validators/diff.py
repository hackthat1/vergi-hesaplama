"""
Diff Reporter - Yeni ve eski veriler arasındaki farkları raporlar.
"""
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import defaultdict


class DiffReporter:
    """İki veri seti arasındaki farkları hesaplar ve raporlar"""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.max_change_percent = config.get("validation", {}).get("max_rate_change_percent", 50)

    def compare_taxes(self, old_data: List[Dict], new_data: List[Dict]) -> Dict[str, Any]:
        """taxes.json karşılaştırması"""
        old_by_gtip = {item["gtip"]: item for item in old_data if item.get("gtip")}
        new_by_gtip = {item["gtip"]: item for item in new_data if item.get("gtip")}

        all_gtips = set(old_by_gtip.keys()) | set(new_by_gtip.keys())

        added = []
        removed = []
        changed = []
        unchanged = 0

        for gtip in sorted(all_gtips):
            old = old_by_gtip.get(gtip)
            new = new_by_gtip.get(gtip)

            if old is None:
                added.append({"gtip": gtip, "data": new})
            elif new is None:
                removed.append({"gtip": gtip, "data": old})
            else:
                diff = self._diff_tax_entry(old, new)
                if diff:
                    changed.append({"gtip": gtip, "changes": diff})
                else:
                    unchanged += 1

        # Şüpheli büyük değişiklikleri işaretle
        suspicious = []
        for change in changed:
            for field, values in change["changes"].items():
                old_val = values["old"]
                new_val = values["new"]
                if old_val != 0 and new_val != 0:
                    pct_change = abs((new_val - old_val) / old_val * 100)
                    if pct_change > self.max_change_percent:
                        suspicious.append({
                            "gtip": change["gtip"],
                            "field": field,
                            "old": old_val,
                            "new": new_val,
                            "pct_change": round(pct_change, 1),
                        })

        return {
            "summary": {
                "total_old": len(old_data),
                "total_new": len(new_data),
                "added": len(added),
                "removed": len(removed),
                "changed": len(changed),
                "unchanged": unchanged,
                "suspicious_count": len(suspicious),
            },
            "added": added,
            "removed": removed,
            "changed": changed,
            "suspicious": suspicious,
        }

    def compare_rates(self, old_data: List[Dict], new_data: List[Dict]) -> Dict[str, Any]:
        """rates.json karşılaştırması"""
        old_by_gtip = {item["gtip"]: item for item in old_data if item.get("gtip")}
        new_by_gtip = {item["gtip"]: item for item in new_data if item.get("gtip")}

        all_gtips = set(old_by_gtip.keys()) | set(new_by_gtip.keys())

        added = []
        removed = []
        changed = []
        unchanged = 0

        for gtip in sorted(all_gtips):
            old = old_by_gtip.get(gtip)
            new = new_by_gtip.get(gtip)

            if old is None:
                added.append({"gtip": gtip, "data": new})
            elif new is None:
                removed.append({"gtip": gtip, "data": old})
            else:
                diff = self._diff_rate_entry(old, new)
                if diff:
                    changed.append({"gtip": gtip, "changes": diff})
                else:
                    unchanged += 1

        return {
            "summary": {
                "total_old": len(old_data),
                "total_new": len(new_data),
                "added": len(added),
                "removed": len(removed),
                "changed": len(changed),
                "unchanged": unchanged,
            },
            "added": added,
            "removed": removed,
            "changed": changed,
        }

    def _diff_tax_entry(self, old: Dict, new: Dict) -> List[Dict]:
        """Tek bir tax entry'si için diff"""
        changes = []
        fields = ["gv", "kdv", "otv", "otv_type", "igv", "emy", "bandrol", "kkdf", "damping", "kultur"]

        for field in fields:
            old_val = old.get(field)
            new_val = new.get(field)

            if old_val != new_val:
                changes.append({
                    "field": field,
                    "old": old_val,
                    "new": new_val,
                })

        return changes

    def _diff_rate_entry(self, old: Dict, new: Dict) -> List[Dict]:
        """Tek bir rate entry'si için diff"""
        changes = []
        fields = ["rate", "unit", "note"]

        for field in fields:
            old_val = old.get(field)
            new_val = new.get(field)

            if old_val != new_val:
                changes.append({
                    "field": field,
                    "old": old_val,
                    "new": new_val,
                })

        return changes

    def generate_markdown_report(self, taxes_diff: Dict, rates_diff: Dict) -> str:
        """Markdown formatında diff raporu oluştur"""
        lines = [
            "# Vergi Oranları Değişim Raporu",
            f"**Tarih:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Özet",
            "",
            "| Metrik | Taxes | Rates |",
            "|--------|-------|-------|",
            f"| Eski kayıt | {taxes_diff['summary']['total_old']} | {rates_diff['summary']['total_old']} |",
            f"| Yeni kayıt | {taxes_diff['summary']['total_new']} | {rates_diff['summary']['total_new']} |",
            f"| Eklenen | {taxes_diff['summary']['added']} | {rates_diff['summary']['added']} |",
            f"| Silinen | {taxes_diff['summary']['removed']} | {rates_diff['summary']['removed']} |",
            f"| Değişen | {taxes_diff['summary']['changed']} | {rates_diff['summary']['changed']} |",
            f"| Değişmeyen | {taxes_diff['summary']['unchanged']} | {rates_diff['summary']['unchanged']} |",
            "",
        ]

        # Şüpheli değişiklikler
        if taxes_diff["suspicious"]:
            lines.extend([
                "## ⚠️ Şüpheli Büyük Değişiklikler (>%50)",
                "",
                "| GTIP | Alan | Eski | Yeni | Değişim % |",
                "|------|------|------|------|-----------|",
            ])
            for s in taxes_diff["suspicious"]:
                lines.append(f"| {s['gtip']} | {s['field']} | {s['old']} | {s['new']} | {s['pct_change']}% |")
            lines.append("")

        # Eklenen GTIP'ler
        if taxes_diff["added"]:
            lines.extend([
                "## Yeni Eklenen GTIP'ler (taxes.json)",
                "",
                "| GTIP | GV | KDV | ÖTV | Kaynak |",
                "|------|----|-----|-----|--------|",
            ])
            for a in taxes_diff["added"][:20]:  # İlk 20
                d = a["data"]
                lines.append(f"| {a['gtip']} | {d.get('gv',0)} | {d.get('kdv',0)} | {d.get('otv',0)} | {d.get('source','')} |")
            if len(taxes_diff["added"]) > 20:
                lines.append(f"\n... ve {len(taxes_diff['added']) - 20} kayıt daha")
            lines.append("")

        # Değişen oranlar
        if taxes_diff["changed"]:
            lines.extend([
                "## Değişen Oranlar (taxes.json)",
                "",
                "| GTIP | Alan | Eski | Yeni |",
                "|------|------|------|------|",
            ])
            for c in taxes_diff["changed"][:30]:
                for ch in c["changes"]:
                    lines.append(f"| {c['gtip']} | {ch['field']} | {ch['old']} | {ch['new']} |")
            if len(taxes_diff["changed"]) > 30:
                lines.append(f"\n... ve {len(taxes_diff['changed']) - 30} kayıt daha")
            lines.append("")

        return "\n".join(lines)

    def save_report(self, taxes_diff: Dict, rates_diff: Dict, output_path: str = "updater/output/diff_report.md"):
        """Raporu dosyaya kaydet"""
        report = self.generate_markdown_report(taxes_diff, rates_diff)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        return output_path


def load_json_safe(path: str) -> List[Dict]:
    """JSON dosyasını güvenli yükle"""
    p = Path(path)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


if __name__ == "__main__":
    import sys
    import yaml

    # Config yükle
    with open("updater/config/sources.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    reporter = DiffReporter(config)

    # Mevcut dosyaları yükle
    old_taxes = load_json_safe("taxes.json.backup") if Path("taxes.json.backup").exists() else load_json_safe("taxes.json")
    new_taxes = load_json_safe("taxes.json")
    old_rates = load_json_safe("rates.json.backup") if Path("rates.json.backup").exists() else load_json_safe("rates.json")
    new_rates = load_json_safe("rates.json")

    # Karşılaştır
    taxes_diff = reporter.compare_taxes(old_taxes, new_taxes)
    rates_diff = reporter.compare_rates(old_rates, new_rates)

    # Rapor kaydet
    report_path = reporter.save_report(taxes_diff, rates_diff)
    print(f"Diff raporu kaydedildi: {report_path}")

    # Özet yazdır
    print(json.dumps({
        "taxes_summary": taxes_diff["summary"],
        "rates_summary": rates_diff["summary"],
    }, indent=2, ensure_ascii=False))