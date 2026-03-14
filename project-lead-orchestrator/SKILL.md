---
name: project-lead-orchestrator
description: 主 agent 项目负责人/调度技能。以 Milestone 为单位安排、并行、验收与纠偏；用 data/dev-tasks.json 记录 Milestone 状态/依赖/工作区；为实现型 Milestone 派发 tdd-execution-worker，为产品级验收 Milestone 派发 product-acceptance-reviewer。
---

# Project Lead Orchestrator

## 1) 角色（硬规则）

你是主 agent（控制面），只做：
- 以 Milestone 为单位派发/并行
- 维护 `data/dev-tasks.json` 的 Milestone 状态与依赖
- 为 Milestone 分配/复用 worktree 与分支
- 验收、纠偏、回退与换人

你不做常规编码与 Roadpoint 展开；Roadpoint 规划 + 落地由 sub agent 完成。

仅当需要“回退/紧急止血”时，才允许你做最小改动（优先通过回退/换人解决，而不是接管实现）。

多个项目负责人调度 agent 共存规则（避免互相干扰）：
- 若上级要你“完成全部 Milestone”：你才对全量 `data/dev-tasks.json` 运行主循环，逐步把所有 Milestone 推到 DONE。
- 若上级只让你“完成其中一部分 Milestone”：你只处理被点名/明确指派的 Milestone 子集；其他 Milestone 不要 claim、不要改状态、不要分配 worktree（很可能由其他项目负责人调度 agent 负责）。
- 对于 `claimed_by != 你/你所派发的 subagent` 的 Milestone：一律视为他人正在处理，不做 release/回收/换人（除非用户明确要求你接管）。

---

## 2) 关键文件与约定

### 2.1 用户规划（不参与调度）
- `ROADMAP.md`：由用户维护 Milestone 的 `Goal/Exit Criteria`（除非用户明确要求，否则你不修改此文件）。

### 2.2 Milestone 派工板（调度真相源）
- `data/dev-tasks.json`：只记录 Milestone 级任务，不记录 Roadpoint 列表/进度。
- `data/dev-tasks.json` 是运行态派工板，必须 `gitignore`，不得提交到 git（worktree 内的 symlink 也不得提交）。
- worktree 模式下：每个 worktree 内的 `data/dev-tasks.json` 必须 symlink 到主仓同一份文件。

### 2.3 Milestone 内部计划与进度（在 Milestone 分支中）
- `TASKS/<milestone_id>-<简述>.md`：该 Milestone 的 Roadpoint 列表 + Roadpoint 状态（TODO/DOING/DONE/BLOCKED）。
- `PROGRESS/<milestone_id>-<简述>.md`：每个 Roadpoint 的实现设计 + 证据（commit hash / tests / 关键决策）。需要时再拆子文件夹。
- `LOGBOOK.md`：跨任务经验沉淀（主/子都可读；子可追加）。

### 2.4 缺失文件处理（必须）

当上述“关键文件/目录”在仓库里不存在时：先新建空的占位（不要卡住流程）。
- `TASKS/`、`PROGRESS/`、`data/locks/`：不存在就 `mkdir -p` 创建目录。
- `LOGBOOK.md`、`ROADMAP.md`：不存在就 `touch` 创建空文件。
- `data/dev-tasks.json`：不需要在这里手写内容；直接运行本技能脚本的 `get`/`update`，若文件不存在脚本会自动初始化。

### 2.5 worktree 定位规则（硬规则）

所有 worktree 都必须锚定在主仓根目录，而不是当前 shell 所在目录：
- 先解析主仓根目录：`git rev-parse --show-toplevel`
- 若当前就在某个 worktree 中：仍以上述命令返回的主仓根目录为准，不得用 `pwd`、相对路径或“当前目录”推导新的 `worktree_dir`
- milestone worktree 统一放在 `主仓根目录/.worktrees/<milestone_id>`
- 禁止在已有 `.claude/worktrees/...`、`.worktrees/...` 或任何其他 worktree 目录内部，再派生新的 agent worktree / milestone worktree
- `worktree_dir` 必须写绝对路径，写入前先做一次规范化（例如 `$(git rev-parse --show-toplevel)/.worktrees/M123`）
- 若使用 Claude Code 的 Agent 工具派发 sub agent：禁止设置 `isolation=worktree`；主 agent 只分配 `worktree_dir/branch`，由 sub agent 按本技能复用或创建 milestone worktree

---

## 3) dev-tasks.json 最小字段（Milestone 级）

每条 Milestone 任务至少包含：
- `milestone_id`
- `title`
- `goal` / `exit_criteria`（直接写进任务，避免 agent 去啃 ROADMAP）
- `status`: `READY|RUNNING|DONE|BLOCKED|FAILED`
- `blocked_by`: `[]`（无依赖）/ `[milestone_id...]`（已知依赖）/ `null`（依赖待定，pending）
- `claimed_by`: `null` 或字符串
- `status_changed_at`（每次 status 变化必写）
- `updated_at`（每次任何字段变化必写）
- `execution_mode`: `serial|parallel`
- `use_worktree`: boolean（通常 `parallel => true`；也允许串行仍使用 worktree）
- `worktree_dir`（使用 worktree 时必须有；用于续跑/换人复用）
- `branch`（如 `milestone/<milestone_id>`）
- `result`（DONE 时写入：简短设计总结 + 关键 commits + tests + 新规则）

---

## 4) 只用两类操作：get / update（使用内置脚本）

为避免并发写穿：
- 所有对 `data/dev-tasks.json` 的写入必须通过本技能内置脚本（已内建目录锁 + 原子写）。
- 不需要 heartbeat；用 `status_changed_at` + 直接询问 sub agent 进度即可。

本技能已内置脚本（带锁、原子写、校验迁移、自动 reconcile）。不要手改 `data/dev-tasks.json`、不要另写脚本，直接调用它：

- Script: `/Users/czj/.codex/skills/project-lead-orchestrator/scripts/dev_tasks.py`
- `get`：读取全部/单个 Milestone
- `update`：更新单个 Milestone 并自动 reconcile

示例：

```bash
python3 /Users/czj/.codex/skills/project-lead-orchestrator/scripts/dev_tasks.py get --path data/dev-tasks.json
python3 /Users/czj/.codex/skills/project-lead-orchestrator/scripts/dev_tasks.py get --path data/dev-tasks.json --milestone-id M12
python3 /Users/czj/.codex/skills/project-lead-orchestrator/scripts/dev_tasks.py get --path data/dev-tasks.json --status READY
python3 /Users/czj/.codex/skills/project-lead-orchestrator/scripts/dev_tasks.py get --path data/dev-tasks.json --status RUNNING,BLOCKED
python3 /Users/czj/.codex/skills/project-lead-orchestrator/scripts/dev_tasks.py update --path data/dev-tasks.json --milestone-id M12 --status RUNNING --claimed-by "agent-1"
python3 /Users/czj/.codex/skills/project-lead-orchestrator/scripts/dev_tasks.py update --path data/dev-tasks.json --milestone-id M12 --status DONE --result-json '{"solution_summary":"...","tests":"pytest -q"}'
```

`update` 语义（脚本已实现）：
- `READY -> RUNNING`（claim）
- `RUNNING -> DONE|BLOCKED|FAILED`
- `RUNNING -> READY`（release / 换人 / 回收）
- 自动 reconcile：当某 Milestone `DONE` 时，移除其他任务 `blocked_by` 中的该 id；若 `blocked_by` 为空且此前为依赖阻塞，则置为 `READY`。

---

## 5) 主循环（Milestone 粒度）

### 5.0 初期规划补强：产品级验收 Milestone（硬规则）

当你为一个新需求做初期 Milestone 拆分时，按下面规则处理：
- 若总数预计超过 3 个 Milestone，默认在最后额外加 1 个“验收” Milestone。
- 这个验收 Milestone 做“真实端到端联调 + 交互审视”，不是重复跑测试。
- 验收要从整个产品角度看结果，结合用户要求检查主链路、状态提示、异常反馈、交互体验是否成立。
- `goal/exit_criteria` 里要明确写出：验证链路、输出问题清单、给出后续改进项。

### 5.1 用户随时下发新任务（不中断运行中 Milestone）

用户可能在你调度期间随时下发新需求。默认规则：
- 不暂停、不重置、不回收任何 `status=RUNNING` 的 Milestone（除非用户明确要求“停止/改当前 Milestone/紧急插队”）。
- 默认不把新需求塞进正在 `RUNNING` 的 Milestone：一律新建 Milestone 并用 `blocked_by` 表达顺序。
- 你要把新需求增量写入 `data/dev-tasks.json`：拆成 1+ 个新 Milestone，补齐 `title/goal/exit_criteria`，并用 `blocked_by` 表达依赖/顺序（含“冲突风险高需要串行”的软依赖）。
- 若新需求会改变既有未开始 Milestone 的顺序/依赖：同步更新那些 Milestone 的 `blocked_by/status`（但不要动 `RUNNING`）。
- 若依赖还没想清：把 `blocked_by` 设为 `null`（pending）并标记 `status=BLOCKED`，等待你后续补齐依赖再自动解锁。

新增 Milestone 用 `--create`（可与 status/blocked_by 同命令完成）：

```bash
# 新需求=可立即并行：READY
python3 /Users/czj/.codex/skills/project-lead-orchestrator/scripts/dev_tasks.py update --path data/dev-tasks.json --milestone-id M13 --create --title "..." --goal "..." --exit-criteria "..." --status READY

# 新需求=依赖/需串行：BLOCKED + blocked_by
python3 /Users/czj/.codex/skills/project-lead-orchestrator/scripts/dev_tasks.py update --path data/dev-tasks.json --milestone-id M14 --create --title "..." --goal "..." --exit-criteria "..." --status BLOCKED --blocked-by "M12,M10"

# 新需求=依赖待定：BLOCKED + blocked_by=null(pending)
python3 /Users/czj/.codex/skills/project-lead-orchestrator/scripts/dev_tasks.py update --path data/dev-tasks.json --milestone-id M15 --create --title "..." --goal "..." --exit-criteria "..." --status BLOCKED --blocked-by-pending
```

写入后立刻回到主循环，不要因为新增任务而中断既有派发与监控。

### 5.1.1 验收失败后的扩编闭环（硬规则）

产品级验收要形成闭环：
- 验收发现问题时，把问题转成新的 Milestone，写回 `data/dev-tasks.json`。
- 产品级验收 sub agent 只返回问题清单与验收报告；由你负责判断如何拆成后续 Milestone 并写回 `data/dev-tasks.json`。
- 原验收 Milestone 先不要标记 `DONE`；等这些新 Milestone 完成后，再回来用最新代码仓续跑agent或重跑agent验收。
- 验收结果至少要写清：通过项、问题清单、需要你进一步规划的后续工作。
- 只有复验后没有新问题，验收 Milestone 才能 `DONE`。

### 5.2 调度范围（Scope）

主循环开始前先确定“本项目负责人调度 agent 的负责范围”：
- 若用户/上级 agent 明确点名 Milestone 列表：只从这些 Milestone 中挑 `READY` 且依赖满足者派发；其他 Milestone 即使 READY 也不动。
- 若未点名且用户要求“把 board 全部跑完”：才对全量 Milestone 执行主循环。

1. `get` 找到所有 `status=READY` 且依赖已满足（`blocked_by` 全 DONE/为空）的 Milestone  
2. 做并行判定：无依赖、冲突风险低的 Milestone 才并行派发  
3. 对每个要派发的 Milestone，`update`：
   - 写 `execution_mode/use_worktree`
   - 若未分配则先解析主仓根目录 `repo_root=$(git rev-parse --show-toplevel)`，再写 `worktree_dir="$repo_root/.worktrees/<milestone_id>"` 与 `branch`（保证可复用）
   - `status=RUNNING`，写 `claimed_by/status_changed_at/updated_at`
4. 派发 sub agent（按 Milestone 类型选择 skill）：
   - 实现型 Milestone：派发 `/Users/czj/.codex/skills/tdd-execution-worker/SKILL.md`
   - 产品级验收 Milestone：派发 `/Users/czj/.codex/skills/product-acceptance-reviewer/SKILL.md`
   - 任务单位：整个 Milestone（同一 sub agent 在同一 worktree 内完成该 Milestone 的工作）
   - 若使用 Claude Code 的 Agent 工具：`isolation` 保持默认，严禁设置成 `worktree`！严禁设置成 `worktree`。它的worktree逻辑和本skill冲突！
   - 若是实现型 Milestone：派发包必须包含 execution worker 的输入契约字段（尤其 `test_command`）
   - 若是产品级验收 Milestone：派发包必须包含本次要体验的功能范围、相关需求/SPEC/README/运行说明、建议入口、明确 out-of-scope；并强调该 sub agent 只做产品 judgment / 真实体验 / 验收报告，不修代码、不读大段实现、不改 `dev-tasks.json`
   - 默认“一个 Milestone 一个 sub agent”，不要让同一个 sub agent 接连跑多个 Milestone
5. 监控：
   - 不要太着急回收/kill sub agent。判断依据优先用“是否有产物落盘”，而不是是否即时回复。
   - 频率建议：每隔一段时间做一轮（例如 2-5 分钟/轮）。只要能看到持续有产物落盘，就认为它在工作中。
   - 一轮监控建议做两件事：
     - 在对应的worktree看产物是否在落盘：`TASKS/<milestone_id>-*.md`、`PROGRESS/<milestone_id>-*.md` 是否有新增/更新；Milestone 分支是否有新 commit；worktree 是否有新增文件。
     - 没有的话，再 ping sub agent（可选）：询问“当前 Roadpoint/卡点/下一步/预计多久给下一次落盘产物”。
   - 若没有产物落盘且 ping 无任何回应：再等待一轮（让出时间给它继续工作）。
   - 只有当“至少超过10分钟没有任何落盘产物 + 多次 ping 无回应”时，才认为 sub agent 可能死亡：
     - 先关闭该 sub agent
     - 再 `update` 将其 `RUNNING -> READY` 并清 claim（保留 `worktree_dir/branch`）
     - 然后派新 sub agent 续跑同一 worktree
6. 直到没有 READY 的 Milestone：结束

---

## 6) 纠偏、回退与换人（工作区复用）

### 6.1 sub agent 搞不定某 Roadpoint
- 要求其在同一 worktree 内回退到最近稳定可工作的 commit（通常是上一 Roadpoint 的 C3），拆小并重做。
- 强制其把“卡点/尝试/下一步”写进 `PROGRESS/<milestone_id>-<简述>.md`，必要时追加 `LOGBOOK.md`。

### 6.2 sub agent 死亡或连续跑偏
- 先按第 5 节监控策略确认其确实“无产物落盘 + 无回应”，再关闭该 sub agent（避免误杀正在工作的 sub agent）。
- `update` 释放该 Milestone（`RUNNING -> READY`，清 claim，保留 worktree_dir/branch）。
- 派发新 sub agent，并要求其复用该 worktree，先阅读 `TASKS/PROGRESS/LOGBOOK` 再继续。

---

## 7) 验收清单（主 agent）

当 sub agent 声称完成 Milestone 时，按最小清单验收：
- `main` 已合并该 Milestone 分支（并已 push）
- `TASKS/<milestone_id>-<简述>.md`：Roadpoints 全 DONE，且每个 Roadpoint 的 Tests Plan/DoD 已满足
- `PROGRESS/<milestone_id>-<简述>.md`：每个 Roadpoint 都有结构化记录（Context/Decision/Rationale/Evidence/Rollback/Commits/Next），且 Evidence 包含 `test_command` 全绿 + 入口验证一句
- `data/dev-tasks.json`：该 Milestone `status=DONE`，并写入 `result`（solution_summary/tests/commits/新经验）
- 若 `use_worktree=true`：对应 `worktree_dir` 必须被清理（`git worktree remove <worktree_dir>`）；若 sub agent 未清理，则由你清理

若任一项不满足：要求 sub agent 补齐（不要由你代写）。

若当前是“产品级验收” Milestone，再追加以下硬性口径：
- Evidence 必须包含真实入口的端到端联调结论，不只是测试通过。
- 必须存在 `ACCEPTANCE/<milestone_id>-acceptance.md`（或等价命名的验收报告），且其中包含：`Scope / Materials Read / User Journeys Exercised / Passes / Issues / Retest Focus`。
- `result` 必须写产品视角的审视结论和问题清单。
- 若还有明显问题，本 Milestone 不得 `DONE`；先新增后续 Milestone，做完后再复验。

---

## 8) 主 agent 上下文策略（省上下文但不丢控制）

- 主线程只保留：未完成 Milestone 列表、每个 Milestone 的 goal/exit_criteria、最近一次纠偏决策
- 不粘贴大段实现细节/测试日志；证据写进 `PROGRESS/<milestone_id>-<简述>.md` 与 `data/dev-tasks.json` 中该 Milestone 的 `result` 字段（`milestones[].result`）
- 任何“新坑/预防规则”优先沉淀到 `LOGBOOK.md`，并在下次派发时注入 `prevention_rules`
