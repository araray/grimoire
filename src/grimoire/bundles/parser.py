# src/grimoire/bundles/parser.py
"""
Bundle file parser.

Parses ``*.bundle.yaml`` files into :class:`~grimoire.models.Bundle` instances.

Bundle YAML format::

    id: bundles/engineering/rca_with_tools
    name: RCA with Engineering Tools
    version: 1.0.0
    base_template: engineering/root_cause_analysis
    overlays:
      - persona/principal_swe
    inject:
      system_prepend:
        - safety/base_engineering
      system_append:
        - tool_policy/low_risk
    tools:
      diagnostic_tools:
        - devtools/git
        - semantiscan/query
    variants:
      - id: anthropic_concise
        when:
          provider: anthropic
        inject:
          system_append:
            - style/concise
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from grimoire.exceptions import BundleParseError
from grimoire.models import Bundle, BundleInject, BundleVariant

logger = logging.getLogger(__name__)


def parse_bundle(data: dict[str, Any], source_path: str | Path | None = None) -> Bundle:
    """
    Parse a bundle from a pre-loaded dict.

    Args:
        data: Dict from YAML / in-memory construction.
        source_path: Optional path for error messages.

    Returns:
        Validated ``Bundle`` instance.

    Raises:
        BundleParseError: If required fields are missing or invalid.
    """
    loc = str(source_path) if source_path else "<dict>"
    try:
        # Normalise inject sub-dict
        inject_raw = data.get("inject")
        inject = BundleInject(**inject_raw) if isinstance(inject_raw, dict) else None

        # Normalise variants list
        variants_raw = data.get("variants", [])
        variants: list[BundleVariant] = []
        for v in variants_raw:
            if not isinstance(v, dict):
                raise BundleParseError(f"Each variant must be a mapping, got {type(v)}")
            v_inject_raw = v.get("inject")
            v_inject = BundleInject(**v_inject_raw) if isinstance(v_inject_raw, dict) else None
            variants.append(
                BundleVariant(
                    id=v["id"],
                    when=v.get("when", {}),
                    inject=v_inject,
                    variable_overrides=v.get("variable_overrides", {}),
                )
            )

        bundle = Bundle(
            id=data["id"],
            name=data["name"],
            version=data.get("version", "1.0.0"),
            description=data.get("description"),
            tags=data.get("tags", []),
            base_template=data["base_template"],
            overlays=data.get("overlays", []),
            inject=inject,
            tools=data.get("tools", {}),
            variants=variants,
            source_path=str(source_path) if source_path else None,
        )
        return bundle
    except BundleParseError:
        raise
    except KeyError as e:
        raise BundleParseError(f"Missing required field {e} in bundle at {loc}") from e
    except Exception as e:
        raise BundleParseError(f"Failed to parse bundle at {loc}: {e}") from e


def parse_bundle_file(path: str | Path) -> Bundle:
    """
    Parse a ``*.bundle.yaml`` file.

    Args:
        path: Path to the bundle file.

    Returns:
        Validated ``Bundle`` instance.

    Raises:
        BundleParseError: If the file cannot be read or parsed.
    """
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise BundleParseError(f"Invalid YAML in bundle {p}: {e}") from e
    except OSError as e:
        raise BundleParseError(f"Cannot read bundle file {p}: {e}") from e

    if not isinstance(raw, dict):
        raise BundleParseError(f"Bundle file {p} must be a YAML mapping")

    return parse_bundle(raw, source_path=p)
