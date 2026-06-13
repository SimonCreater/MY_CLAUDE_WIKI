# LLM Wiki Tool — 하네스 + LLM Wiki + 시각화 도구 통합

객체검출(Object Detection)·XAI 연구 지식을 담은 **markdown LLM Wiki** 를,
**MCP 서버**(AI 에이전트용)와 **웹 뷰어**(사람용)로 함께 제공하고,
**하네스**(RULES + Hook + Skill + Subagent)가 에이전트의 작업 품질을 보증하는 통합 도구입니다.

> 처음 보는 사람도 clone 후 **30분 안에** 자기 자료 1건으로 첫 위키 페이지를 만들고 화면에서 확인할 수 있습니다 — [3절](#3-30분-온보딩--내-자료로-첫-위키-페이지-만들기).

![실사용 화면](demo/demo_screenshot.png)

---

## 1. 구성 요소 (Package)

| 구성 | 위치 | 내용 |
|---|---|---|
| **하네스** | `RULES.md` `CLAUDE.md` `.claude/` | Agent 운영지침 + PostToolUse **Hook**(쓰기 후 자동 스키마 검증) + **Skill**(`/new-wiki-page` 자료 통합 절차) + **Subagent**(`wiki-editor`) |
| **LLM Wiki** | `raw/` `wiki/` | 자료 투입구(raw) · 위키 본체(pages 11 + glossary 3) · 스키마(`wiki/SCHEMA.md`) · 에이전트 안내(`wiki/AGENTS.md`, `llms.txt`) |
| **시각화 도구** | `tools/` | `mcp_server.py`(MCP 6툴, 에이전트 접근) + `app.py`(웹 뷰어·검색·챗봇) + `wiki_core.py`(공유 로직·검증 게이트) + `scholar_search.py`(다중 학술 DB 검색 수집기) |
| **데모** | `demo/` | 실제 지식베이스가 렌더링된 화면 캡처 |
| **문서** | `docs/` | 지식 도메인 정의 · 의사결정 저널 · PRD · 에이전트 SPEC |

```
WikiTool_MCP/
├── RULES.md / CLAUDE.md      ← 하네스: 에이전트 운영지침 + 프로젝트 컨텍스트
├── .claude/                  ← 하네스: settings.json(Hook) · skills/new-wiki-page · agents/wiki-editor
├── .mcp.json                 ← Claude Code 가 자동 인식하는 MCP 서버 등록(프로젝트 스코프)
├── raw/                      ← 자료 투입구 (당신의 PDF·노트를 여기에)
├── wiki/                     ← 위키 본체: pages/ glossary/ _meta/ + SCHEMA.md AGENTS.md llms.txt
├── tools/                    ← wiki_core.py(로직·검증) · mcp_server.py(MCP) · app.py(웹 뷰어) · scholar_search.py(논문 검색 수집)
├── demo/                     ← 실사용 스크린샷
└── docs/                     ← 설계 문서 4종
```

## 2. 설치 (환경 · 의존성)

- **환경**: Python 3.10+ (3.13 검증). Windows 는 `py` 런처 기준, macOS/Linux 는 `py` → `python3` 로 읽으세요.
- **의존성**: `fastmcp`, `flask`, `markdown`, `python-frontmatter` (requirements.txt)

```powershell
git clone <이 저장소 URL>
cd WikiTool_MCP
py -m pip install -r requirements.txt

# 설치 확인 (LLM·네트워크 불필요)
py tools/wiki_core.py              # 통계 + 샘플 검색 출력되면 OK
py tools/wiki_core.py --validate   # "errors=0" + exit 0 이면 OK
```

## 3. 30분 온보딩 — 내 자료로 첫 위키 페이지 만들기

**0–5분 | 위키 화면부터 확인**

```powershell
py tools/app.py
```
브라우저에서 **http://127.0.0.1:5000** → 사이드바에서 페이지 열람, 상단 검색, 우측 챗봇 질의.
(이미 사용 가능한 위키 11페이지가 기본 제공됩니다)

**5–10분 | 내 자료 투입**

자료 1건(논문 PDF, 메모 .md/.txt)을 `raw/` 에 복사합니다. 연습용 예시 파일도 준비되어 있습니다: `raw/example_note.md`

> 💡 **자동 수집(선택)**: 자료가 없으면 주제 검색으로 후보를 모을 수 있습니다 —
> `py tools/scholar_search.py "real-time detection transformer" --save` 가 arXiv·Crossref·OpenAlex 를
> 동시 검색해 중복제거·교차검증 점수를 매긴 노트를 `raw/` 에 저장합니다(메타데이터·OA 링크만, 키 불필요).

**10–25분 | 에이전트에게 통합 요청**

저장소 루트에서 [Claude Code](https://claude.com/claude-code) 를 열고:

```
/new-wiki-page raw/example_note.md
```

또는 자연어로 — `raw에 넣은 example_note.md 위키 페이지로 통합해줘`

에이전트가 Skill 절차(원문 정독 → 중복 검색 → 페이지 생성 → 스키마 검증 → 메타 갱신)를 수행하고
새 페이지의 slug 를 보고합니다. 쓰기 직후 **Hook 이 자동으로 `--validate` 를 실행**해 스키마 위반을 차단합니다.

**25–30분 | 결과 확인 (검증)**

```powershell
py tools/wiki_core.py --validate   # errors=0 확인
py tools/app.py                    # http://127.0.0.1:5000 → 새 페이지가 사이드바·검색에 보이는지 확인
```

## 4. MCP Tool 목록과 동작

`tools/mcp_server.py` 가 MCP 프로토콜(`tools/list`·`tools/call`)로 노출하는 6개 툴:

| 툴 | 기능 | 권한 | 동작 방식 |
|---|---|:---:|---|
| `wiki_search(query, limit)` | 키워드 검색 | read | 제목5/슬러그4/요약3/태그3/본문1 가중치 점수 상위 반환 |
| `wiki_get(slug)` | 페이지 전체 조회 | read | 숫자prefix·alias·glossary 자동 해석 |
| `wiki_list(category, kind)` | 목록/필터 | read | 카테고리·종류별 요약 목록 |
| `wiki_create(slug,title,summary,body,…)` | 새 페이지 | write | 필수필드·slug·중복 검증 → 생성 → 저널 기록 |
| `wiki_update(slug,…)` | 부분 갱신 | write | 지정 필드만 덮어쓰기, `updated` 자동 갱신 → 저널 |
| `wiki_append(slug,text,heading)` | 본문 추가 | write | 말미/지정 섹션에 추가 → 저널 |

리소스: `wiki://stats`. **삭제 툴은 의도적으로 없음**(지식 손실 방지, `status: deprecated` 로 대체).
모든 쓰기는 `wiki/_meta/journal.md` 에 append-only 로 자동 기록됩니다(감사 추적).

### 에이전트 연결 방법

**Claude Code** — 이 저장소를 열면 `.mcp.json`(프로젝트 스코프)이 자동 인식됩니다. 승인만 하면
에이전트가 위 6툴을 바로 호출할 수 있습니다. 수동 등록 시:
```powershell
claude mcp add objdet-wiki -- py tools/mcp_server.py
```

**Claude Desktop** — `claude_desktop_config.json` 에 추가:
```json
{
  "mcpServers": {
    "objdet-wiki": {
      "command": "py",
      "args": ["C:\\절대경로\\WikiTool_MCP\\tools\\mcp_server.py"],
      "env": { "WIKI_ROOT": "C:\\절대경로\\WikiTool_MCP\\wiki" }
    }
  }
}
```

**HTTP 전송** (원격/별도 프로세스): `py tools/mcp_server.py --http` → `http://127.0.0.1:8000/mcp`

## 5. 하네스 — 에이전트 품질 보증 장치

| 장치 | 파일 | 역할 |
|---|---|---|
| 운영지침 | `RULES.md` | 수정 단일 경로(6툴), 삭제 금지, 출처 의무, 저널 append-only, API Key 금지 |
| 컨텍스트 | `CLAUDE.md` | Claude Code 세션에 자동 로드되는 프로젝트 지도 |
| **Hook** | `.claude/settings.json` | Write/Edit 직후 `py tools/wiki_core.py --validate` 자동 실행 — 스키마 위반 시 exit 2 로 차단 (확률적 출력에 결정론적 게이트) |
| **Skill** | `.claude/skills/new-wiki-page/` | 자료 투입 → 페이지 생성 → 검증 → 보고의 고정 절차 |
| **Skill** | `.claude/skills/scholar-search/` | 주제로 다중 학술 DB 검색 → `raw/` 노트 저장 → 위키화 연계 |
| **Subagent** | `.claude/agents/wiki-editor.md` | 대량 통합·메타 정리를 위임받는 편집 전담 에이전트(권한 명세 포함) |

## 6. 검증 방법

```powershell
py tools/wiki_core.py --validate   # ① 스키마 게이트: checked=N errors=0, exit 0
py tools/wiki_core.py              # ② 스모크 테스트: 통계 + 'rt-detr xai' 검색 결과
py tools/app.py                    # ③ 뷰어: http://127.0.0.1:5000 에서 페이지·검색·챗봇 확인
py tools/mcp_server.py             # ④ MCP 서버: 에러 없이 stdio 대기하면 정상 (Ctrl+C 종료)
```

## 7. 설계 노트

- **단일 진실 출처**: markdown + YAML front-matter 가 유일한 데이터. `wiki_core.py` 를
  MCP 서버와 웹 뷰어가 공유하므로 **에이전트가 쓰면 사람 화면에 즉시 반영**됩니다.
- **API Key 없음**: 챗봇은 위키 검색 기반 retrieval 로 동작(재현성). LLM 연동이 필요하면
  MCP 클라이언트(Claude Code/Desktop)나 subprocess 경유로 — 코드에 키를 넣지 않습니다(RULES.md 6절).
- **원문 자료는 git 제외**: `raw/*.pdf` 는 저작권·용량 문제로 커밋되지 않습니다.
  페이지 front-matter 의 `source.ref` 와 `wiki/_meta/source_index.md` 가 출처를 추적합니다.
- 설계 의사결정 이력은 `docs/02_decision_journal.md`(append-only) 참조.
