from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
import urllib.parse
import urllib.request
import json
import re
import xml.etree.ElementTree as ET


EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


@dataclass
class PubMedArticle:
    pmid: str
    title: str
    abstract: str
    doi: str


class PubMedClient:
    def __init__(self, email: str = "", api_key: str = "", timeout: float = 15.0):
        self.email = email.strip()
        self.api_key = api_key.strip()
        self.timeout = timeout

    def _build_common_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def _fetch_text(self, endpoint: str, params: dict[str, str]) -> str:
        query = urllib.parse.urlencode(params)
        url = f"{EUTILS_BASE}/{endpoint}?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "SiriusMOFA/1.0"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def search_pmids(self, query: str, retmax: int = 8) -> list[str]:
        retmax = max(1, min(int(retmax), 50))
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": str(retmax),
            "retmode": "json",
            **self._build_common_params(),
        }
        raw = self._fetch_text("esearch.fcgi", params)
        data = json.loads(raw)
        return data.get("esearchresult", {}).get("idlist", [])

    def fetch_articles(self, pmids: Iterable[str]) -> list[PubMedArticle]:
        ids = [p for p in pmids if str(p).strip()]
        if not ids:
            return []

        params = {
            "db": "pubmed",
            "id": ",".join(ids),
            "rettype": "abstract",
            "retmode": "xml",
            **self._build_common_params(),
        }
        raw_xml = self._fetch_text("efetch.fcgi", params)
        root = ET.fromstring(raw_xml)

        articles: list[PubMedArticle] = []
        for node in root.findall(".//PubmedArticle"):
            pmid = (node.findtext(".//PMID") or "").strip()
            title = " ".join((node.findtext(".//ArticleTitle") or "").split())

            abstract_parts = []
            for abs_node in node.findall(".//Abstract/AbstractText"):
                txt = " ".join("".join(abs_node.itertext()).split())
                if txt:
                    abstract_parts.append(txt)
            abstract = " ".join(abstract_parts)

            doi = ""
            for aid in node.findall(".//ArticleId"):
                if (aid.attrib.get("IdType") or "").lower() == "doi":
                    doi = " ".join((aid.text or "").split())
                    break

            if pmid:
                articles.append(PubMedArticle(pmid=pmid, title=title, abstract=abstract, doi=doi))

        return articles


_STRUCTURAL_PATTERNS = re.compile(
    r"""
    \bpmid\s*:?\s*\d{6,9}\b
    | \b10\.\d{4,}/\S+
    | \bncbi\.nlm\.nih\.gov\b
    | \bpubmed\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_KEYWORD_WEIGHTS: dict[str, int] = {
    "literature":   3,
    "bibliography": 3,
    "citation":     2,  "citations":  2,
    "reference":    2,  "references": 2,
    "abstract":     2,
    "étude":        1,  "études":     1,
    "etude":        1,  "etudes":     1,
    "paper":        1,  "papers":     1,
    "article":      1,  "articles":   1,
    "evidence":     1,
}

_KEYWORD_THRESHOLD = 3


def looks_like_pubmed_request(text: str) -> bool:
    if _STRUCTURAL_PATTERNS.search(text):
        return True
    t = text.lower()
    score = sum(
        weight
        for keyword, weight in _KEYWORD_WEIGHTS.items()
        if keyword in t
    )
    return score >= _KEYWORD_THRESHOLD


def build_pubmed_context(articles: list[PubMedArticle], max_chars: int = 9000) -> str:
    if not articles:
        return ""

    blocks: list[str] = []
    total = 0
    for i, a in enumerate(articles, start=1):
        abs_short = a.abstract[:900]
        if len(a.abstract) > 900:
            abs_short += " [...]"
        block = (
            f"[{i}] PMID: {a.pmid}\n"
            f"Title: {a.title or '(no title)'}\n"
            f"DOI: {a.doi or '(none)'}\n"
            f"Abstract snippet: {abs_short or '(no abstract)'}"
        )
        total += len(block)
        if total > max_chars:
            break
        blocks.append(block)

    return "\n\n".join(blocks)
