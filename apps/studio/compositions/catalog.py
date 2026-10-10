"""Import every composition module so each registers itself (see compositions.composition)."""
import importlib
import pkgutil
from pathlib import Path

for _module in pkgutil.iter_modules([str(Path(__file__).resolve().parent)]):
    if _module.name not in ('catalog',):
        importlib.import_module(f'{__package__}.{_module.name}')
