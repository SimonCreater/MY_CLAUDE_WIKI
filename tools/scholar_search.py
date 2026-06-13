"""
scholar_search.py — 다중 학술 DB 메타데이터 검색 수집기 (위키 자료 투입 보조).

arXiv · Crossref · OpenAlex 의 **공개 REST API** 를 직접 호출해 한 주제를 동시 검색하고,
DOI/제목으로 중복을 합친 뒤 "몇 개 DB에서 동시에 나왔는가"(교차검증)로 점수를 매겨 정렬한다.
결과는 raw/ 에 markdown 노트로 저장할 수 있고, 이어서 `/new-wiki-page` 로 위키 페이지화한다.

설계 메모
- 표준 라이브러리만 사용(urllib/json/xml) — 새 의존성 없음.
- **메타데이터와 오픈액세스 링크만** 수집한다(PDF 무단 수집·유료장벽 우회 없음 → 저작권/ToS 준수).
- 각 소스 호출은 독립적으로 try/except 처리 — 한 곳이 실패해도 나머지 결과는 반환.
- 본 파일은 공개 API 명세를 보고 처음부터 작성한 오리지널 코드다(외부 프로젝트 코드 미사용).
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_UA = "objdet-wiki-scholar-search/1.0 (academic metadata aggregation; stdlib urllib)"
_TIMEOUT = 20


# --------------------------------------------------------------------------- #
# 공통 유틸
# --------------------------------------------------------------------------- #
def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read()


def _norm_title(title: str) -> str:
    """제목 정규화 — 소문자화 + 영숫자만 남겨 중복 판정 키로 사용."""
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def _norm_doi(doi: str) -> str:
    if not doi:
        return ""
    doi = doi.strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi


def _mk(source: str, title: str, authors: list[str], year, doi: str,
        url: str, venue: str = "", oa_pdf: str = "") -> dict:
    return {
        "source": source,
        "title": (title or "").strip(),
        "authors": authors or [],
        "year": str(year) if year else "",
        "doi": _norm_doi(doi),
        "url": url or "",
        "venue": venue or "",
        "oa_pdf": oa_pdf or "",
    }


# --------------------------------------------------------------------------- #
# 소스별 검색
# --------------------------------------------------------------------------- #
def search_arxiv(query: str, limit: int) -> list[dict]:
    """arXiv Atom API. 키 불필요."""
    q = urllib.parse.urlencode({
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": limit,
        "sortBy": "relevance",
    })
    raw = _get(f"http://export.arxiv.org/api/query?{q}")
    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(raw)
    out = []
    for e in root.findall("a:entry", ns):
        title = (e.findtext("a:title", default="", namespaces=ns) or "").strip()
        authors = [a.findtext("a:name", default="", namespaces=ns)
                   for a in e.findall("a:author", ns)]
        published = e.findtext("a:published", default="", namespaces=ns)
        year = published[:4] if published else ""
        doi = e.findtext("arxiv:doi", default="", namespaces=ns)
        abs_url = e.findtext("a:id", default="", namespaces=ns)
        pdf = ""
        for link in e.findall("a:link", ns):
            if link.get("title") == "pdf":
                pdf = link.get("href", "")
        out.append(_mk("arxiv", title, [a for a in authors if a], year, doi,
                       abs_url, venue="arXiv", oa_pdf=pdf))
    return out


def search_crossref(query: str, limit: int) -> list[dict]:
    """Crossref works API. 키 불필요."""
    q = urllib.parse.urlencode({"query": query, "rows": limit})
    raw = _get(f"https://api.crossref.org/works?{q}")
    items = json.loads(raw).get("message", {}).get("items", [])
    out = []
    for it in items:
        title = (it.get("title") or [""])[0]
        authors = [" ".join(filter(None, [a.get("given"), a.get("family")]))
                   for a in it.get("author", [])]
        parts = (it.get("issued", {}).get("date-parts") or [[None]])[0]
        year = parts[0] if parts else ""
        venue = (it.get("container-title") or [""])[0]
        out.append(_mk("crossref", title, authors, year, it.get("DOI", ""),
                       it.get("URL", ""), venue=venue))
    return out


def search_openalex(query: str, limit: int) -> list[dict]:
    """OpenAlex works API. 키 불필요(메일 등록 시 polite pool)."""
    q = urllib.parse.urlencode({"search": query, "per-page": limit})
    raw = _get(f"https://api.openalex.org/works?{q}")
    results = json.loads(raw).get("results", [])
    out = []
    for r in results:
        authors = [a.get("author", {}).get("display_name", "")
                   for a in r.get("authorships", [])]
        loc = r.get("primary_location") or {}
        venue = (loc.get("source") or {}).get("display_name", "") or ""
        oa = (r.get("open_access") or {}).get("oa_url", "") or ""
        out.append(_mk("openalex", r.get("title", ""), authors,
                       r.get("publication_year", ""), r.get("doi", ""),
                       r.get("doi", "") or r.get("id", ""), venue=venue, oa_pdf=oa))
    return out


_SOURCES = {
    "arxiv": search_arxiv,
    "crossref": search_crossref,
    "openalex": search_openalex,
}


# --------------------------------------------------------------------------- #
# 병합 + 랭킹
# --------------------------------------------------------------------------- #
def merge(records: list[dict]) -> list[dict]:
    """DOI(우선) 또는 정규화 제목으로 중복을 합치고 교차검증 점수를 부여."""
    merged: dict[str, dict] = {}
    for rec in records:
        key = rec["doi"] or ("t:" + _norm_title(rec["title"]))
        if not key or key == "t:":
            continue
        if key not in merged:
            merged[key] = {
                **rec,
                "sources": [rec["source"]],
                # 빈 필드는 다른 소스가 채울 수 있게 보관
            }
        else:
            m = merged[key]
            if rec["source"] not in m["sources"]:
                m["sources"].append(rec["source"])
            # 비어 있던 메타데이터를 보강
            for f in ("doi", "year", "venue", "oa_pdf", "url"):
                if not m.get(f) and rec.get(f):
                    m[f] = rec[f]
            if len(rec["authors"]) > len(m["authors"]):
                m["authors"] = rec["authors"]
    out = list(merged.values())
    # 점수: 교차검증된 소스 수(주) → 연도 최신(부)
    out.sort(key=lambda r: (len(r["sources"]),
                            int(r["year"]) if r["year"].isdigit() else 0),
             reverse=True)
    for r in out:
        r["score"] = len(r["sources"])
    return out


def aggregate(query: str, limit: int = 10,
              sources: list[str] | None = None) -> tuple[list[dict], list[str]]:
    """선택한 소스를 검색·병합. 반환: (병합결과, 경고메시지목록)."""
    sources = sources or list(_SOURCES)
    all_recs: list[dict] = []
    warnings: list[str] = []
    for name in sources:
        fn = _SOURCES.get(name)
        if not fn:
            warnings.append(f"알 수 없는 소스: {name}")
            continue
        try:
            recs = fn(query, limit)
            all_recs.extend(recs)
        except Exception as e:  # noqa: BLE001 - 소스 단위 격리
            warnings.append(f"{name} 검색 실패: {e}")
    return merge(all_recs), warnings


# --------------------------------------------------------------------------- #
# raw/ 노트 저장
# --------------------------------------------------------------------------- #
def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "query"


def save_to_raw(query: str, results: list[dict], top: int = 10) -> str:
    """검색 결과를 raw/scholar_<slug>_<date>.md 로 저장하고 경로 반환."""
    from pathlib import Path
    raw_dir = Path(__file__).resolve().parent.parent / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    path = raw_dir / f"scholar_{_slug(query)}_{today}.md"

    lines = [
        f"# (검색 수집) {query}",
        "",
        f"> scholar_search.py 가 arXiv·Crossref·OpenAlex 를 검색해 모은 **메타데이터**입니다.",
        f"> 수집일 {today}. 점수 = 교차검증된 DB 수. `/new-wiki-page` 로 위키화할 후보 자료.",
        "",
    ]
    for i, r in enumerate(results[:top], 1):
        authors = ", ".join(r["authors"][:4]) + (" 외" if len(r["authors"]) > 4 else "")
        lines.append(f"## {i}. {r['title']}  (score {r['score']})")
        meta = [f"**연도** {r['year'] or '?'}", f"**출처DB** {', '.join(r['sources'])}"]
        if r["venue"]:
            meta.append(f"**게재** {r['venue']}")
        if r["doi"]:
            meta.append(f"**DOI** {r['doi']}")
        lines.append(" · ".join(meta))
        if authors:
            lines.append(f"- 저자: {authors}")
        if r["url"]:
            lines.append(f"- 링크: {r['url']}")
        if r["oa_pdf"]:
            lines.append(f"- 오픈액세스 PDF: {r['oa_pdf']}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(
        description="다중 학술 DB(arXiv·Crossref·OpenAlex) 메타데이터 검색 수집기")
    ap.add_argument("query", help="검색 주제 (예: 'real-time detection transformer')")
    ap.add_argument("--limit", type=int, default=10, help="소스당 최대 결과 수 (기본 10)")
    ap.add_argument("--sources", default="arxiv,crossref,openalex",
                    help="쉼표로 구분한 소스 목록")
    ap.add_argument("--save", action="store_true", help="결과를 raw/ 에 .md 노트로 저장")
    args = ap.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    results, warnings = aggregate(args.query, limit=args.limit, sources=sources)

    for w in warnings:
        print(f"[warn] {w}")
    print(f"=== '{args.query}' — 병합 {len(results)}건 (소스: {', '.join(sources)}) ===")
    for i, r in enumerate(results[:args.limit], 1):
        tag = "+".join(r["sources"])
        print(f"[{r['score']}|{tag}] ({r['year'] or '?'}) {r['title'][:90]}")
        if r["doi"]:
            print(f"        doi:{r['doi']}")

    if args.save:
        path = save_to_raw(args.query, results)
        print(f"\n저장됨 → {path}")
        print("다음 단계: Claude Code 에서  /new-wiki-page  로 이 자료를 위키 페이지로 통합하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
