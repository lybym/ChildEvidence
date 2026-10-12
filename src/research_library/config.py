"""ChildEvidence configuration loading (YAML configs + env vars + paths).

Project layout (independent repo):
    ChildEvidence/
    ├── src/research_library/   <- this package
    ├── config/                 <- YAML configs
    ├── exports/                <- machine-readable exports (tracked)
    ├── docs/research/          <- generated reports (tracked)
    └── data/research-library/  <- runtime data (gitignored, overridable)

The default data directory resolves relative to this file's project root, so
the CLI works from any working directory. Override with CHILDEVIDENCE_DATA_DIR
(RESEARCH_LIBRARY_DATA_DIR kept as a legacy alias from the LumiThink days).
"""

from __future__ import annotations

import os
from pathlib import Path

from .mini_yaml import parse as _parse_yaml

# src/research_library/config.py -> parents[2] == project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"

DEFAULT_CONTACT_EMAIL = "childevidence-research@users.noreply.github.com"

DOMAIN_ORDER = [
    "child_development",
    "learning_sciences",
    "behavior_support",
    "ai_children",
    "china_family",
]

DOMAIN_LABELS_ZH = {
    "child_development": "A. 儿童发展心理学",
    "learning_sciences": "B. 教育心理学与学习科学",
    "behavior_support": "C. 儿童行为与心理支持",
    "ai_children": "D. AI 儿童陪伴与数字心理学",
    "china_family": "E. 中国儿童与家庭教育",
    "cross_domain": "F. 跨领域 / 综合资源",
}


def default_data_dir() -> Path:
    env = (
        os.environ.get("CHILDEVIDENCE_DATA_DIR")
        or os.environ.get("RESEARCH_LIBRARY_DATA_DIR")  # legacy alias
    )
    if env:
        return Path(env)
    return PROJECT_ROOT / "data" / "research-library"


def load_yaml(path: Path):
    return _parse_yaml(path.read_text(encoding="utf-8"))


class Config:
    """Runtime configuration for the research library pipeline."""

    def __init__(self, data_dir: Path | None = None):
        self.project_root = PROJECT_ROOT
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.pdf_dir = self.data_dir / "pdf"
        self.cache_dir = self.data_dir / "cache"
        self.logs_dir = self.data_dir / "logs"
        self.exports_dir = PROJECT_ROOT / "exports"
        self.docs_dir = PROJECT_ROOT / "docs" / "research"

        self.sources = load_yaml(CONFIG_DIR / "sources.yaml")
        self.topics = load_yaml(CONFIG_DIR / "topics.yaml")
        self.seeds = load_yaml(CONFIG_DIR / "seed-papers.yaml")

        fallback = self.sources.get("contact_email_fallback", DEFAULT_CONTACT_EMAIL)
        self.contact_email = (
            os.environ.get("CHILDEVIDENCE_CONTACT_EMAIL")
            or os.environ.get("LUMITHINK_CONTACT_EMAIL")  # legacy alias
            or os.environ.get("UNPAYWALL_EMAIL")
            or fallback
        )
        self.openalex_api_key = os.environ.get("OPENALEX_API_KEY") or None
        self.crossref_mailto = os.environ.get("CROSSREF_MAILTO") or self.contact_email
        self.unpaywall_email = os.environ.get("UNPAYWALL_EMAIL") or self.contact_email

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.pdf_dir, self.cache_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "library.sqlite"

    def user_agent(self) -> str:
        return self.sources.get("user_agent") or (
            "ChildEvidence-ResearchLibrary/0.1 (mailto:%s)" % self.contact_email
        )

    def host_rate_limits(self) -> dict:
        out = {}
        for host, seconds in (self.sources.get("rate_limits") or {}).items():
            out[host] = float(seconds)
        return out
