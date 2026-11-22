"""
Transformer'lar - Ham veriyi taxes.json / rates.json formatına dönüştürür.
"""
from .gtip import GTIPTransformer
from .gv import GVTransformer
from .kdv_otv import KDVOTVTransformer
from .emy_others import EMYOthersTransformer
from .merge import DataMerger

__all__ = [
    "GTIPTransformer",
    "GVTransformer",
    "KDVOTVTransformer",
    "EMYOthersTransformer",
    "DataMerger",
]