> Historical input (2026-10-21): the owner's upgrade checklist that produced ADR-0007 / ADR-0008 and `docs/roadmap-decision-layer.md` (the tracked version). Kept verbatim; statuses here are not maintained.

# Agent Forge — Checklist nâng cấp (bản final)

> **Định vị sản phẩm** (chốt sau thảo luận): Agent Forge không phải bộ sưu tập lớn nhất. Nó là
> bộ sưu tập **nhỏ nhất đã được đo**, cộng với một agent đọc từng dự án và đưa ra **đánh giá
> độc lập, có bằng chứng kiểm chứng được**, để developer chạy `/agent-forge-upgrade` quyết định.
> Mọi quyết định được lưu lại, tái lập được khi dự án không đổi, và gỡ được.
>
> Bốn lớp giá trị: (1) engine cài/gỡ an toàn, (2) lớp quyết định có bằng chứng, (3) vòng phản hồi từ
> phiên làm việc thật (config nào được dùng, rule nào mâu thuẫn), (4) dữ liệu toàn công ty để catalog tự co lại.
>
> Thứ tự: cái làm mất uy tín nếu người ngoài thử → trước. Cái chứng minh giá trị → trước khi mở
> rộng. Tính năng mới → sau cùng. Mỗi mục có **Acceptance**; không tick khi chưa chạy lệnh kiểm chứng.

---

## P0 · Blocker — xanh trước khi ai khác chạy `install.sh` (tuần 1)

### 0.1 Registry integrity hỏng trên Linux/macOS
Đã tái hiện trên Ubuntu, cả `main` và `v0.2.0`: 12–13/33 capability mismatch, gồm entry skill
`forge.skill.agent-forge-upgrade`. `agent-forge validate` → FAILED, 20/204 test fail. Nguyên nhân:
digest pin từ working copy CRLF.

- [ ] Trên máy Windows: `git add --renormalize . && git checkout -- registry`; `git ls-files --eol registry | grep crlf` → rỗng.
- [ ] `python scripts/pin_integrity.py` re-pin **toàn bộ**, commit một lần.
- [ ] Pre-commit hook chặn CRLF trong `registry/`; ghi `core.autocrlf=false` vào `docs/contributing-capabilities.md`.
- [ ] Job CI riêng `registry-integrity`: `pin_integrity.py --check` trên ubuntu, độc lập với test suite.
- [ ] Tag `v0.2.1` ngay khi xanh.

**Acceptance:** `agent-forge validate --no-provenance` → `0 error(s)`, `pytest -q` → `0 failed` trên ubuntu + macos trong CI; link run dán vào CHANGELOG.

### 0.2 CI phản ánh đúng sự thật
- [ ] Job `installer` thêm bước `agent-forge validate` sau khi cài (hiện chỉ `forge --dry-run`, integrity lỗi vẫn pass).
- [ ] `release.yml` chặn release nếu `validate` fail; build từ checkout LF.
- [ ] Kiểm tra badge CI trong README phản ánh đúng trạng thái.

**Acceptance:** sửa 1 byte trong `registry/capabilities/*/assets/` → CI đỏ ở cả 3 OS.

### 0.3 Installer an toàn mặc định
- [ ] Không bao giờ fallback về `main` khi không resolve được release; dừng với lỗi rõ + hướng dẫn `AGENT_FORGE_VERSION`.
- [ ] Verify sha256 archive trước khi giải nén; Sigstore khi có `cosign`, cảnh báo khi không.
- [ ] `~/.agent-forge/VERSION`; `doctor` so với latest release.
- [ ] README: dòng pin version đặt ngay cạnh lệnh `curl | bash`.

**Acceptance:** chặn `api.github.com` → installer exit ≠ 0, không cài gì.

---

## P1 · Tin cậy kỹ thuật + lớp quyết định (tuần 2–5)

### 1.1 Tách `cli.py` (2.617 dòng)
- [ ] `cli/forge.py`, `cli/ops.py`, `cli/team.py`, `cli/registry.py`, `cli/decisions.py`, `cli/_envelope.py`; `cli.py` < 200 dòng.
- [ ] Logic nghiệp vụ ra khỏi CLI; CLI chỉ format + exit code.

**Acceptance:** không file nào trong `cli/` > 600 dòng; `test_json_envelope.py` pass không sửa.

### 1.2 Lỗi là dữ liệu, không phải chuỗi
Hiện `_apply_locked` phân loại bằng `"stale" in p` / `"approval" in p`.
- [ ] `Problem(code, op_id, path, message)` với enum code; exit code và envelope dùng `code`.
- [ ] Bảng code → exit code → hành động trong `cli-reference.md`.

**Acceptance:** `grep -rn '"stale" in\|"approval" in' src/` → rỗng.

### 1.3 Property / crash test cho phần ghi
- [ ] Hypothesis: `apply` + `rollback` trên `sections` và `jsonmerge` → byte-identical, idempotent, giữ key của user.
- [ ] Kill giữa `apply` (mock exception sau op k) → `doctor` báo `needs recovery`, `rollback --partial` khôi phục đúng.

**Acceptance:** ≥ 3 property test, ≥ 200 examples mỗi cái, chạy trong CI.

### 1.4 Lock & multi-process
- [ ] 2 `apply` song song cùng target → một chờ, không interleave.
- [ ] Lock có TTL + pid; `doctor` dọn lock mồ côi thay vì bảo user xoá tay.

### 1.5 Audit log có schema
- [ ] JSONL, một dòng/command: command, plan_id, tx_id, exit code, duration, token/time của bước LLM (nếu có). Redact path ngoài target.
- [ ] `stats`: project managed, capability phổ biến, drift rate, rollback rate.

**Acceptance:** full lifecycle → `jq` parse được; test grep không thấy secret.

### 1.6 Decision record — lớp quyết định của LLM thành artifact ⭐
Cốt lõi của định vị sản phẩm. Không có mục này, "LLM phân tích" không kiểm toán được.
- [ ] Schema `decisions.schema.json`: một object/capability với `verdict`, `grounds[]` (enum: `covered`, `conflicts`, `security`, `context_cost`, `stack_mismatch`, `evidence_worse`, `duplicate_tool`), `confidence`, `covered_by[]`, `contradicts[]`, `gap`, `context_chars`, `always_on`, `risk[]`, `evidence`, `reason`, `assessed_by`, `assessed_at`.
- [ ] Skill ghi `.agent-forge/decisions/<plan-id>.json`; planner gắn `decisions_digest` vào plan.
- [ ] `agent-forge decisions verify <plan-id>`: path tồn tại, quote là substring thật, số khớp catalog, `grounds` hợp lệ. **SKIP không qua verify → hạ thành ASK** và báo user "skill muốn bỏ X nhưng không chứng minh được".
- [ ] `status` in lý do vì sao capability vắng mặt; `drift` phát hiện bằng chứng biến mất (file được quote đã xoá/đổi) → gợi ý review lại.
- [ ] Plan mới diff với decisions cũ: chỉ hiện quyết định **thay đổi**, kèm lý do cũ/mới. Model đổi ý khi project không đổi → không tự áp dụng.

**Acceptance:** fixture có decision SKIP với quote giả → `verify` fail, `forge` hiển thị ASK. Xoá file được quote → `drift` báo đúng capability.

### 1.7 Golden decisions — đo độ trôi của LLM
- [ ] `examples/*/expected_decisions.json` (6 fixture) do người review.
- [ ] `scripts/decision_report.py`: chạy skill thật (`claude -p` / `codex exec`) trên fixture, so từng ô với golden, in bảng trôi.
- [ ] Chạy khi: đổi prompt skill, đổi model mặc định, release. Kết quả commit vào `docs/evaluation/decisions/`.

**Acceptance:** đổi một dòng trong SKILL.md → report chỉ ra quyết định nào đổi trên fixture nào.

### 1.8 Skill `agent-forge-upgrade` theo rubric phủ định-trước
Dùng bản `SKILL-section-3-4-rubric.md` đã có.
- [ ] Thay section 3–4; đo `context_chars` của skill trước/sau, cắt nếu vượt ngưỡng tự đặt.
- [ ] Chạy skill cũ vs mới trên 6 fixture: số ADD, số quyết định có path, số SKIP không qua verify.
- [ ] Đồng bộ bản Codex (`assets/codex/`).

**Acceptance:** bản mới có ≥ 90% quyết định kèm path/quote thật; không SKIP nào rơi vào "không có căn cứ".

### 1.9 Policy ba mức
- [ ] `required` / `recommended` (mặc định) / `forbidden`. LLM không được SKIP `required`, không thấy `forbidden`; developer thắng tuyệt đối ở `recommended`.
- [ ] Muốn bỏ `required` → sửa policy qua PR, không qua skill.

**Acceptance:** fixture với policy `required: [forge.hook.guard-secrets-python]` → skill không thể loại; `check` fail nếu thiếu.

---

## P2 · Vận hành nội bộ — pilot thật (tuần 4–10)

### 2.1 Ba repo pilot, ba stack
- [ ] Điền `docs/pilots/<repo>.md` **trước** khi cài: onboarding time, hand-edit `CLAUDE.md` 30 ngày, `scan --json`.
- [ ] Owner không phải bạn; họ cài theo README, không hỏi bạn; ghi mọi chỗ vấp.
- [ ] Tuần 1–2 chỉ skill + rule; hook/MCP từ tuần 3.
- [ ] Lưu `decisions.json` của mỗi pilot → đây là dữ liệu thật đầu tiên để đánh giá rubric.

**Acceptance:** 3 pilot có baseline thật; ≥ 5 issue từ owner khác; ≥ 3 decision record thật được review.

### 2.2 Policy công ty + CI gate
- [ ] Layer registry riêng cho công ty; `company.yaml` với `required`/`forbidden`, `max_context_chars` (khởi điểm 6–8k, đo rồi chỉnh).
- [ ] `agent-forge check .` trong CI từng pilot.
- [ ] Một trang quy trình ai sửa policy, review thế nào.

**Acceptance:** sửa tay `.claude/rules/*.md` → CI đỏ, message chỉ đúng file + lệnh fix.

### 2.3 Context budget ở nơi quyết định
- [ ] `forge --dry-run` in tổng context always-on trước → sau, % so budget, dòng đầu.
- [ ] `status` cảnh báo khi vượt budget do rule user tự thêm.

### 2.4 Vòng upgrade thật
- [ ] `upgrade .`: so version, diff từng capability, tôn trọng drift.
- [ ] Deprecation/revocation hiện trong `check` (CI), không chỉ `status`.
- [ ] Nâng một capability trong registry → 3 pilot nhận thông báo và upgrade sạch.

**Acceptance:** một vòng trên 3 pilot, zero rollback bắt buộc, ghi vào pilot file.

### 2.5 Capability nội bộ
- [ ] ≥ 3 capability `<company>.*` (convention, review process, template ADR/PR). Đây là lý do thật để team dùng.
- [ ] Mỗi cái có `review.owner`, `reviewed_at`, lý do tồn tại 2 câu; nằm ở layer nội bộ, không vào repo public.

---

## P3 · Chứng minh giá trị — cổng trước khi public (tháng 2–3)

### 3.1 Tiêu chí vào catalog mặc định — ADR-0007 ⭐
Văn bản định nghĩa sản phẩm, quan trọng hơn mọi tính năng.
- [ ] Vào default chỉ khi: eval `improved` trên ≥ 1 fixture cùng stack; `context_chars` < ngưỡng; không `conflicts` với capability khác cùng profile; có owner review; có `grounds` nào có thể phủ định nó được liệt kê sẵn.
- [ ] `no_evidence` sau 2 lần đo → `experimental`, không vào plan mặc định.
- [ ] Mục tiêu catalog mặc định **≤ 15 capability**.

**Acceptance:** ADR-0007 merge; `validate` cảnh báo capability `status: curated` không đạt tiêu chí.

### 3.2 Chạy eval harness thật
`docs/evaluation/README.md` đang "none yet".
- [ ] 5 capability lõi (gợi ý: `ecc.security-review`, `mattpocock.tdd`, `ecc.error-handling`, `karpathy.principles`, 1 nội bộ); ≥ 5 run/arm; `--tool claude`.
- [ ] Commit report `.json` + `.md`, kể cả `worse`/`no_evidence`; ghi `review.evidence`; `catalog show` hiển thị.
- [ ] Ước chi phí trước (~250 lần `claude -p`), script tổng hợp token/USD từ report.

**Acceptance:** bảng evaluation ≥ 5 dòng thật với interval và chi phí.

### 3.3 Eval theo lịch
- [ ] Workflow hàng tháng hoặc khi model mặc định đổi: chạy lại eval + golden decisions; capability mất bằng chứng tự rớt default.

### 3.4 KPI pilot và go/no-go
- [ ] Onboarding time, hand-edit, rollback, `needs recovery`, số user tắt tool — trước/sau, 3 pilot.
- [ ] Tỷ lệ decision SKIP bị `verify` hạ xuống ASK (đo độ bịa của model).
- [ ] Tỷ lệ capability đã cài có ≥ 1 lần gọi trong 30 ngày (từ 5.2). Dưới 50% → catalog mặc định đang quá rộng.

**Acceptance:** ≥ 2/3 pilot không muốn giữ → **không public**, quay lại P2.

---

## P4 · Public (tháng 3–4, chỉ khi P3 go)

### 4.1 Bề mặt tin cậy
- [ ] README: 2 câu + 1 gif `agent-forge lint .` trên repo lạ (thứ người ta thử đầu tiên) + 1 gif `/agent-forge-upgrade` với **bảng đánh giá** + bảng evidence rút gọn → rồi mới Install.
- [ ] Một ví dụ công khai mà kết luận là "repo này không cần cài gì". Tool dám nói không sẽ được tin.
- [ ] `SECURITY.md` có threat model ngắn; trang "What Agent Forge does NOT do"; CHANGELOG có mục Breaking.

### 4.2 Bus factor
- [ ] Maintainer thứ hai có quyền merge + release; release build từ CI, ký OIDC.
- [ ] Đăng PyPI để `pipx install` không cần git URL.

### 4.3 Supply chain registry
- [ ] 100% capability curated có upstream SHA + reviewer + ngày.
- [ ] `docs-watch` mở issue → re-review 1 tuần, quá hạn tự `stale`.
- [ ] Content-safety thêm rule: prompt-injection ("ignore previous instructions"), network call ẩn trong script, base64 blob.
- [ ] CODEOWNERS bắt buộc 2 reviewer cho `registry/`.

### 4.4 Người dùng mới
- [ ] Người ngoài công ty cài theo README trên macOS + Linux, quay màn hình, bạn không trả lời; sửa mọi chỗ vấp.
- [ ] `doctor` chẩn đoán 10 lỗi phổ biến nhất và in lệnh fix; `--non-interactive` cho mọi lệnh.

### 4.5 Phạm vi
- [ ] Claude Code + Codex first-class; Cursor/Copilot/Gemini gắn `beta` tới khi có conformance trên tool thật.
- [ ] GitHub Discussions với thread "what we measured" và "roadmap".

---

## P5 · Ý tưởng khác biệt — xếp theo giá trị, không theo độ dễ

Chỉ mục **5.1** và **5.2** vào roadmap ngay (song song P2); phần còn lại cần 1.6 ổn trước.

### 5.1 `agent-forge lint .` — chấm config hiện có, không cài gì ⭐ (làm cùng P2)
Cửa vào không ma sát; người ngoài tin tool trước khi tool đề xuất gì. Logic gần như đã có trong bước 2 của skill.
- [ ] Đọc `CLAUDE.md`/`AGENTS.md`, `.claude/rules`, `.cursor/rules`, `.github/instructions`, hooks, MCP — read-only, không cần workspace.
- [ ] Báo: tổng context always-on; rule trùng lặp (cosine/ngram giữa các file); rule mâu thuẫn (dùng rubric `conflicts`, phần này cần LLM → `--deep`); secret lộ; hook chạy lệnh nguy hiểm (content-safety rules); MCP không dùng.
- [ ] Output người đọc 30 giây + `--json`; exit code để làm CI gate nhẹ (`--max-context`).
- [ ] Không đề xuất cài capability nào trong lint. Tách biệt hoàn toàn với `forge`.

**Acceptance:** chạy trên 5 repo thật ngoài công ty (public), mỗi repo ra ≥ 1 phát hiện đúng và 0 phát hiện sai; thời gian < 3 giây không `--deep`.

### 5.2 Config chết — vòng phản hồi từ phiên làm việc thật ⭐ (làm cùng P2)
Biến "fewer is better" thành số đo; bằng chứng giá trị rẻ nhất, có trước eval harness.
- [ ] Capability `forge.hook.usage-log`: hook `PostToolUse`/`SessionEnd` của Claude Code (và log Codex) ghi skill/agent được gọi vào `.agent-forge/usage.jsonl`, **opt-in, local, không gửi đi đâu**, nội dung chỉ là id + timestamp.
- [ ] `agent-forge usage .`: số lần gọi mỗi capability trong cửa sổ N ngày.
- [ ] `status` gợi ý: "cài 42 ngày, 0 lần gọi — gỡ?"; skill có ground `unused` và verdict REMOVE (đã thêm vào rubric).
- [ ] `.gitignore` mặc định cho `usage.jsonl`; docs nói rõ không có telemetry ra ngoài.

**Acceptance:** sau 30 ngày pilot, ít nhất một capability bị đề xuất gỡ vì `unused`, và owner pilot đồng ý gỡ.

### 5.3 `agent-forge import .` — đưa config viết tay vào quản lý
Xoá rào cản "tool sẽ ghi đè cái tôi đã làm".
- [ ] LLM chưng cất `CLAUDE.md`/rules hiện có thành capability `<project>.local` (manifest + assets), không đổi nội dung, chỉ thêm quản lý.
- [ ] Đi qua đúng vòng đời: hash, drift, `context_chars`, rollback; không bao giờ ghi đè khi chưa approve.
- [ ] `lint` và skill dùng `<project>.local` như nguồn `covered` chính thức.

**Acceptance:** repo có `CLAUDE.md` 200 dòng → import → `status` hiện `<project>.local` với context_chars; `git diff` nội dung = 0.

### 5.4 Học từ quyết định toàn công ty (cần 1.6)
- [ ] `agent-forge decisions report --org DIR`: gom `decisions.json` của mọi repo; bảng capability × ground.
- [ ] Quy tắc gợi ý: SKIP `covered` ở ≥ 70% repo → đề xuất bỏ khỏi catalog mặc định; ADD ở ≥ 90% repo cùng stack → ứng viên `required`.
- [ ] Report là đầu vào cho review ADR-0007 hàng quý; catalog co lại theo dữ liệu, không theo ý kiến.

### 5.5 Probe hành vi sau khi cài (cần P3 harness)
- [ ] Mỗi capability lõi kèm 1–2 probe: prompt + điều kiện pass (vd `tdd`: "thêm hàm X" → có test trước code?).
- [ ] `apply` xong tuỳ chọn `--probe`: chạy trong chính repo, báo "rule này có đổi hành vi ở đây không". Không phải thống kê, là smoke test.
- [ ] Probe fail 2 lần → gợi ý REMOVE với ground mới `ineffective_here` (thêm vào enum khi làm).

### 5.6 Canary theo vòng (quy mô công ty, sau P2)
- [ ] Policy có `rollout: canary | all`; registry nâng version → chỉ repo canary thấy `upgrade` trong 7 ngày.
- [ ] Điều kiện lên `all`: không rollback, không drift bất thường, probe pass (nếu có).
- [ ] `check` ở repo không canary không đỏ vì version mới trong giai đoạn canary.

### Các ý nhỏ hơn (giữ từ bản trước)
- [ ] `agent-forge explain <id>`: lý do có/không capability này trong repo, từ decisions.
- [ ] GitHub Action post bảng đánh giá vào PR khi `.agent-forge/` đổi.
- [ ] Fixture "bẫy": rule mâu thuẫn, file trùng tên khác nội dung → vào golden decisions.
- [ ] Skill `agent-forge-upgrade` tự tuân `context_chars` budget như mọi capability.
- [ ] `--thorough`: lượt đối nghịch "tìm căn cứ phủ định cho từng ADD", hiển thị cả hai.
- [ ] Tách repo registry khỏi engine trước khi public.

---

## Giữ repo không "AI hoá" quá đà (xuyên suốt)

- [ ] Một PR một mục tiêu; commit nói việc, không "phase N complete".
- [ ] Tính năng mới phải trả lời: pilot nào cần, số nào cải thiện. Không có → `docs/ideas.md`.
- [ ] Docs chỉ mô tả cái đã chạy; cái chưa làm ở roadmap với trạng thái rõ.
- [ ] Người thật review `apply/`, `rollback/`, `registry/`, `install.*`, và từ giờ thêm `decisions/`.

---

## 2 tuần tới (nếu chỉ làm được 8 việc)

1. 0.1 — fix integrity, tag v0.2.1
2. 0.2 — CI installer gọi `validate`
3. 0.3 — installer không fallback `main`
4. 1.8 — thay section 3–4 của skill, chạy thử 6 fixture
5. 1.6 — schema `decisions.json` + `verify` (bản tối thiểu: path exists + quote substring)
6. 2.1 — chọn 3 pilot, điền baseline
7. 5.2 — hook usage-log opt-in bật ngay trên 3 pilot (dữ liệu cần 30 ngày, nên bật sớm)
8. 1.9 — policy `required`

Tuần 3–4: 5.1 `lint` — đây là thứ đầu tiên cho người ngoài công ty thử.

Sau 2 tuần mở lại file này, tick/sửa, rồi chọn đợt tiếp.
