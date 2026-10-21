> Historical input (2026-10-21): an external review's root-cause analysis and fix list after `v0.3.0` failed on Linux. Part 1 is implemented in 0.3.1; parts 2-4 are tracked in `docs/roadmap-decision-layer.md`. Not maintained.

# Agent Forge — Hướng dẫn fix v0.3.1 và nâng cấp sau v0.3.0

> Tình trạng `origin/main` / `v0.3.0` (kiểm tra trên Ubuntu, 21/10/2026):
> `pin_integrity.py --check` → **12/34 stale**, `agent-forge validate` → **FAILED**, pytest → 3 fail.
> Sau khi áp Phần 1 dưới đây: `validate` → `0 error(s)`, pytest → **336 passed, 3 skipped**.
>
> Phần 1 là bắt buộc trước khi tag v0.3.1 hoặc cho bất kỳ ai cài. Phần 2–4 là nâng cấp theo thứ tự.

---

## Phần 1 · Fix blocker: `sha256_tree` không xác định giữa các OS

### 1.1 Root cause (không phải CRLF)

`src/agent_forge/util.py`:

```python
def sha256_tree(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):          # <-- lỗi ở đây
        ...
```

`sorted()` trên danh sách `Path` so sánh theo quy tắc của OS: `WindowsPath` so sánh **không
phân biệt hoa thường**, `PosixPath` phân biệt. Thư mục nào có file viết hoa (`LICENSE-ECC.txt`,
`SKILL.md`) nằm cạnh file chữ thường (`code-review.md`, `mocking.md`) thì thứ tự duyệt khác
nhau → digest khác nhau. 12 capability lỗi đúng là 12 cái có file viết hoa trong `assets/`.

Bằng chứng: sort lại theo `rel.as_posix().lower()` trên Linux cho ra **chính xác** 12 digest
đang pinned. Digest pinned không khớp LF, không khớp CRLF.

Phạm vi ảnh hưởng rộng hơn registry: `sha256_tree` cũng tính `content_digest` → `registry
digest` trong plan. Plan approve trên Windows sẽ bị từ chối là stale registry trên Linux/macOS.

### 1.2 Sửa code

```python
# src/agent_forge/util.py
def sha256_tree(root: Path) -> str:
    """Deterministic digest of a directory tree (relative paths + file hashes).

    Files are visited in byte order of their POSIX relative path, so the digest is identical
    on every OS and filesystem (Path ordering is case-insensitive on Windows).
    """
    h = hashlib.sha256()
    files = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
    for p in sorted(files, key=lambda q: q.relative_to(root).as_posix()):
        rel = p.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(sha256_file(p).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()
```

Không dùng `.lower()` làm key: hai file chỉ khác hoa/thường trên Linux sẽ va nhau, và digest
cũ vẫn cần re-pin dù chọn cách nào.

### 1.3 Test chặn tái phát

`tests/unit/test_util_hashing.py`:

```python
from pathlib import Path
from agent_forge.util import sha256_tree

def test_sha256_tree_is_independent_of_os_path_ordering(tmp_path: Path) -> None:
    # Uppercase next to lowercase: the case where Windows and POSIX Path ordering differ.
    (tmp_path / "LICENSE.txt").write_text("l", encoding="utf-8")
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "SKILL.md").write_text("s", encoding="utf-8")
    (tmp_path / "sub" / "b.md").write_text("b", encoding="utf-8")
    # Known-good value: compute once on Linux after the fix and paste here.
    assert sha256_tree(tmp_path) == "<paste digest here>"

def test_sha256_tree_changes_when_a_file_is_renamed_by_case(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    before = sha256_tree(tmp_path)
    (tmp_path / "a.md").rename(tmp_path / "A.md")
    assert sha256_tree(tmp_path) != before
```

Test đầu là giá trị cố định, nên chạy trên cả 3 OS trong matrix CI sẽ bắt mọi lệch sau này.

### 1.4 Re-pin và kiểm tra (chạy trên bất kỳ OS nào sau khi sửa code)

```bash
python scripts/pin_integrity.py            # ghi lại 12 pin
python scripts/pin_integrity.py --check    # 34 capabilities, 0 stale/missing
agent-forge validate --no-provenance       # 35 checks, 0 error(s)
pytest -q --ignore=tests/eval              # 336 passed
```

Commit riêng: `fix(util): sha256_tree sorts by posix path, not Path, so digests match across OSes; re-pin registry`.

### 1.5 CI phải bắt được loại lệch này

Job `registry-integrity` hiện chỉ chạy `ubuntu-latest`; lỗi này cần hai OS mới lộ. Sửa
`.github/workflows/ci.yml`:

```yaml
  registry-integrity:
    name: registry integrity (${{ matrix.os }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
```

Giữ nguyên bước kiểm CRLF (vẫn hữu ích), `pin_integrity.py --check`, `validate`.

Thêm vào job `installer` sau khi cài:

```yaml
      - name: Installed registry validates
        run: "$AGENT_FORGE_INSTALL_DIR/bin/agent-forge" validate --no-provenance
        shell: bash
```

Hiện installer chỉ chạy `forge --dry-run`, nên integrity lỗi vẫn pass — đó là lý do v0.2.0 và
v0.3.0 được tag khi đang hỏng.

### 1.6 Release

- [ ] CI xanh ở cả 3 OS **trước** khi tag. Nhìn run thật, không nhìn badge cache.
- [ ] Tag `v0.3.1`; CHANGELOG ghi rõ "v0.2.0–v0.3.0 không cài được trên Linux/macOS, nguyên nhân, đã sửa".
- [ ] Sửa `docs/troubleshooting.md`: mục "assets differ from the reviewed, pinned digest" → bảo user nâng lên ≥ 0.3.1 trước khi làm gì khác.

**Acceptance Phần 1:** clone mới trên Ubuntu + macOS + Windows, cùng `v0.3.1`, cả ba cho
`validate` → `0 error(s)` và cùng một registry digest trong `forge --dry-run --json`.

---

## Phần 2 · Dọn trước khi thêm tính năng (tuần này)

### 2.1 `cli.py` — 2.617 → 3.292 dòng, đi ngược mục tiêu
Tách **trước** khi thêm lệnh tiếp theo, không thì không bao giờ tách.

- [ ] `src/agent_forge/cli/__init__.py` chỉ tạo Typer app + `add_typer` cho từng nhóm.
- [ ] Mỗi nhóm một file: `forge.py` (forge/upgrade/setup), `ops.py` (apply/rollback/status/drift/doctor), `team.py` (check/sync/stats), `registry.py` (catalog/validate/init), `decisions.py` (verify/diff/explain/report/usage), `lint.py`, `_envelope.py`, `_tables.py`.
- [ ] Logic nghiệp vụ còn trong CLI (ví dụ phân loại stale/approval trong `_apply_locked`, lắp decisions vào plan) chuyển về `apply/`, `decisions/`, `planner/`.
- [ ] Mục tiêu: không file nào > 600 dòng; `tests/e2e/test_json_envelope.py` pass không sửa.

### 2.2 Lỗi là code, không phải chuỗi
- [ ] `Problem(code: ProblemCode, op_id, path, message)`; bỏ mọi `"stale" in p` / `"approval" in p`.
- [ ] Envelope JSON và exit code lấy từ `code`.
- [ ] `grep -rn '"stale" in\|"approval" in' src/` → rỗng.

### 2.3 Fixture cho `lint`
`lint examples/python-fastapi/project` ra bảng rỗng vì fixture không có config → không thấy
lint làm gì.
- [ ] `examples/lint-messy/`: `CLAUDE.md` 3.000 chars, hai rule trùng nội dung khác tên, một rule mâu thuẫn `CLAUDE.md`, một hook `curl | sh`, một MCP không dùng.
- [ ] `expected_lint.json`; test khẳng định từng phát hiện và **không** có phát hiện sai.
- [ ] Dùng cùng fixture làm "fixture bẫy" cho golden decisions.

---

## Phần 3 · Hoàn thiện lớp quyết định (2 tuần)

Cái đã có: `models/decision.py`, `decisions/verify.py` (SKIP không chứng minh → ASK, quote
khớp bất kể xuống dòng, số khớp catalog), `diff`, `explain`, `report`, `usage`, policy
`required`/`forbidden`. Việc còn lại là nối nó vào vòng đời và đo.

- [ ] `drift` dùng `covered_by[]`/`contradicts[]` trong decisions: file mất hoặc quote không còn → báo "cơ sở quyết định đã đổi", gợi ý chạy lại skill. (Có `test_evidence_drift_*` cho hàm; cần nối vào lệnh `drift` và `check`.)
- [ ] `check` fail khi: capability `required` thiếu; SKIP trong decisions không qua `verify`; `decisions_digest` trong plan không khớp file.
- [ ] Skill `agent-forge-upgrade` (`assets/claude_code` và `codex`): đã dùng bản rubric chưa? Kiểm tra `grounds` 8 giá trị, verdict REMOVE, trường `scope`. Đo `context_chars` của chính skill trước/sau, ghi vào manifest.
- [ ] Golden decisions: `examples/*/expected_decisions.json` cho 6 fixture + `lint-messy`; `scripts/decision_report.py` chạy skill thật (`claude -p`), so từng ô, in bảng trôi. Chạy khi đổi SKILL.md, đổi model, trước release.
- [ ] Usage log: xác nhận hook chỉ ghi `capability_id + timestamp` (không ghi prompt, không ghi path ngoài project); docs "no telemetry leaves the machine" viết **trước** khi đổi gì ở hook.

**Acceptance Phần 3:** trên 3 pilot nội bộ, mỗi repo có `decisions/<plan>.json` được `verify`
pass, `check` chạy trong CI, và sau 30 ngày `usage` có số thật.

---

## Phần 4 · Thứ tự thực hiện

| Ngày | Việc | Tick khi |
|---|---|---|
| 1 | 1.2 + 1.3 + 1.4 fix `sha256_tree`, test, re-pin | `validate` xanh trên máy local |
| 1 | 1.5 CI 2 OS + installer `validate` | run CI xanh 3 OS |
| 2 | 1.6 tag v0.3.1, CHANGELOG, troubleshooting | clone mới trên macOS cài được |
| 3–5 | 2.1 tách `cli.py` | không file > 600 dòng |
| 5 | 2.2 error code | grep rỗng |
| 6–7 | 2.3 fixture lint-messy | test lint có phát hiện thật |
| tuần 2 | 3.x nối drift/check, golden decisions | 3 pilot có decisions verify pass |

Không thêm lệnh CLI mới, không thêm capability mới, cho tới khi hết Phần 2.

---

## Ghi chú cho người review PR fix

- Diff code của Phần 1 là **một dòng** trong `util.py` + một test file; phần còn lại là 12
  `assets_sha256` thay đổi trong `capability.yaml`. Nếu PR thay đổi nhiều hơn thế, hỏi tại sao.
- Sau fix, digest của mọi capability **có** file viết hoa sẽ đổi; capability chỉ có file chữ
  thường giữ nguyên. Đó là dấu hiệu fix đúng.
- `content_digest` đổi → `registry digest` đổi → mọi plan `approved` đang chờ trong workspace
  của pilot sẽ thành `STALE_REGISTRY`. Đây là đúng, nhưng báo trước cho pilot.
