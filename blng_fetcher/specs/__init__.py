"""
blng_fetcher/specs
Registry de todas as EntitySpecs conhecidas.
"""
from __future__ import annotations

from .base import EntitySpec, FieldSpec  # noqa: F401 (re-export)
from .core import CORE_SPECS

try:
    from .expansion import EXPANSION_SPECS
except ImportError:  # expansion.py chega na Fase 3
    EXPANSION_SPECS: tuple[EntitySpec, ...] = ()

SPECS: dict[str, EntitySpec] = {
    spec.name: spec for spec in (*CORE_SPECS, *EXPANSION_SPECS)
}

# grupos de conveniencia p/ o CLI
GROUPS: dict[str, tuple[str, ...]] = {
    "all": tuple(name for name, s in SPECS.items() if s.enabled),
    "config": tuple(name for name, s in SPECS.items() if s.enabled and s.small_config),
    "transacional": tuple(
        name for name, s in SPECS.items() if s.enabled and not s.small_config),
}
