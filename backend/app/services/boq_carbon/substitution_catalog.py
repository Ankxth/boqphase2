"""Workstream 08: superseded by the shared app/services/supplier_catalog.py
module -- kept as a thin backward-compatible delegator (same three
function names/signatures as before) so nothing that already imports from
this path breaks. New code should import from app.services.supplier_catalog
directly; this module adds nothing of its own anymore.
"""

from __future__ import annotations

from app.services.supplier_catalog import CATALOG_PATH  # re-exported, unchanged
from app.services.supplier_catalog import get_entry as get_substitution
from app.services.supplier_catalog import list_entries_for_category as list_substitutions_for_category
from app.services.supplier_catalog import load_catalog

__all__ = ["CATALOG_PATH", "load_catalog", "get_substitution", "list_substitutions_for_category"]