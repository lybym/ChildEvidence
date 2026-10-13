"""Parsing pipeline configuration: config/parsing.yaml + environment overrides.

The parse feature is OPTIONAL: the defaults work with the zero-dependency core
(docling/pdfplumber only load inside their adapters). All paths stay inside the
configurable data directory unless explicitly overridden via environment.

Environment overrides (highest precedence):
    CHILDEVIDENCE_PARSING_MODELS_DIR   Docling weights cache (offline-first)
    CHILDEVIDENCE_PARSING_OUTPUT_DIR   parse artifact root (default: <data>/parse-output)
    CHILDEVIDENCE_PARSING_TIMEOUT_SEC  per-document timeout
    CHILDEVIDENCE_PARSING_EXECUTION    "subprocess" | "inprocess"
    CHILDEVIDENCE_PARSING_OFFLINE      "1" forbids any network at parse time
"""

from __future__ import annotations

import os
from pathlib import Path

from ..config import Config
from ..mini_yaml import parse as _parse_yaml

DEFAULT_CONFIG_FILE = Path(__file__).resolve().parents[3] / "config" / "parsing.yaml"


class ParsingConfig:
    """Runtime configuration for the parsing pipeline."""

    def __init__(self, base: Config | None = None, config_file: Path | None = None,
                 data_dir: Path | None = None):
        self.base = base or Config(data_dir=data_dir)
        path = Path(config_file) if config_file else DEFAULT_CONFIG_FILE
        self.config_path: Path | None = path if path.exists() else None
        raw: dict = {}
        if self.config_path:
            raw = _parse_yaml(self.config_path.read_text(encoding="utf-8")) or {}

        parser_cfg = raw.get("parser") or {}
        self.primary_parser: str = parser_cfg.get("primary", "docling")
        self.fallback_parser: str | None = parser_cfg.get("fallback", "pdfplumber")
        self.fallback_enabled: bool = bool(parser_cfg.get("fallback_enabled", True))
        self.cross_check: bool = bool(parser_cfg.get("cross_check", False))
        self.timeout_sec: float = float(parser_cfg.get("timeout_sec", 600))
        self.max_memory_mb: int | None = parser_cfg.get("max_memory_mb", None)
        self.concurrency: int = int(parser_cfg.get("concurrency", 1))
        self.execution: str = parser_cfg.get("execution", "subprocess")

        offline_cfg = raw.get("offline") or {}
        self.offline: bool = bool(offline_cfg.get("mode", True))
        models_dir = offline_cfg.get("artifacts_dir")
        self.models_dir: Path | None = Path(models_dir) if models_dir else None

        out_cfg = raw.get("output") or {}
        self.output_dirname: str = out_cfg.get("dirname", "parse-output")
        self.corrections_dirname: str = out_cfg.get("corrections_dirname", "parse-corrections")
        self.review_dirname: str = out_cfg.get("review_dirname", "parse-review-queue")

        doc_cfg = raw.get("docling") or {}
        self.ocr_enabled: bool = bool(doc_cfg.get("ocr_enabled", False))
        self.table_mode: str = doc_cfg.get("table_mode", "accurate")
        self.num_threads: int = int(doc_cfg.get("num_threads", 1))

        # ---- environment overrides ------------------------------------
        env = os.environ
        if env.get("CHILDEVIDENCE_PARSING_PRIMARY"):
            self.primary_parser = env["CHILDEVIDENCE_PARSING_PRIMARY"]
        if env.get("CHILDEVIDENCE_PARSING_FALLBACK"):
            self.fallback_parser = env["CHILDEVIDENCE_PARSING_FALLBACK"]
        if env.get("CHILDEVIDENCE_PARSING_FALLBACK_ENABLED") is not None:
            self.fallback_enabled = env["CHILDEVIDENCE_PARSING_FALLBACK_ENABLED"] \
                not in ("0", "false", "False")
        if env.get("CHILDEVIDENCE_PARSING_MODELS_DIR"):
            self.models_dir = Path(env["CHILDEVIDENCE_PARSING_MODELS_DIR"])
        if env.get("CHILDEVIDENCE_PARSING_TIMEOUT_SEC"):
            self.timeout_sec = float(env["CHILDEVIDENCE_PARSING_TIMEOUT_SEC"])
        if env.get("CHILDEVIDENCE_PARSING_EXECUTION"):
            self.execution = env["CHILDEVIDENCE_PARSING_EXECUTION"]
        if env.get("CHILDEVIDENCE_PARSING_OFFLINE") is not None:
            self.offline = env["CHILDEVIDENCE_PARSING_OFFLINE"] not in ("0", "false", "False")
        if self.max_memory_mb is not None and env.get("CHILDEVIDENCE_PARSING_MAX_MEM_MB"):
            self.max_memory_mb = int(env["CHILDEVIDENCE_PARSING_MAX_MEM_MB"])

        if self.execution not in ("subprocess", "inprocess"):
            raise ValueError(f"parser.execution must be subprocess|inprocess, got {self.execution!r}")
        if self.concurrency != 1:
            # issue #3: limit concurrency; parallel parsing is out of scope v1
            raise ValueError("parser.concurrency must be 1 in this version")

    # ------------------------------------------------------------------
    _output_root_override: Path | None = None
    _corrections_dir_override: Path | None = None

    @property
    def output_root(self) -> Path:
        if self._output_root_override is not None:
            return self._output_root_override
        env = os.environ.get("CHILDEVIDENCE_PARSING_OUTPUT_DIR")
        if env:
            return Path(env)
        return self.base.data_dir / self.output_dirname

    @output_root.setter
    def output_root(self, value: Path) -> None:
        self._output_root_override = Path(value)

    @property
    def corrections_dir(self) -> Path:
        if self._corrections_dir_override is not None:
            return self._corrections_dir_override
        return self.base.data_dir / self.corrections_dirname

    @corrections_dir.setter
    def corrections_dir(self, value: Path) -> None:
        self._corrections_dir_override = Path(value)

    @property
    def review_queue_dir(self) -> Path:
        return self.output_root / self.review_dirname

    def effective_options(self) -> dict:
        """The options that affect parser output (part of the artifact identity)."""
        return {
            "primary_parser": self.primary_parser,
            "ocr_enabled": self.ocr_enabled,
            "table_mode": self.table_mode,
            "num_threads": self.num_threads,
            "schema_version": 1,
        }
