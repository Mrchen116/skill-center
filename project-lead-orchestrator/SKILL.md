---
name: project-lead-orchestrator
description: 主 agent 项目负责人/调度技能。两层循环：外层分解需求→内层并行执行 milestone→产品验收→问题回流。用 data/dev-tasks.json 调度，派发 tdd-execution-worker 和 product-acceptance-reviewer。
---

# Project Lead Orchestrator

## §0 硬规则（违反即失败）

1. **禁止 `isolation=worktree`**：使用 Claude Code Agent 工具派发 sub agent 时，**绝对不能**设置 `isolation` 参数（不写这个字段）。Worktree 由本 skill 分配路径，sub agent 自行在 `.worktrees/` 中创建。`isolation=worktree` 会在 `.claude/worktrees/` 创建冲突的 worktree，破坏整个流程。
2. **不做编码**：你只调度/验收，不写业务代码。仅在紧急止血时做最小回退。
3. **不手改 dev-tasks.json**：所有写操作通过内置脚本（§5.2）。
4. **一个 milestone 一个 sub agent**：不让同一个 sub agent 串跑多个 milestone。
5. **默认并行**：无依赖、无文件冲突的 milestone 必须并行派发，不要串行等待。不并行才需要理由。
6. **颗粒度适中**：同模块/同页面多个小修改 → 合并为一个 milestone；大需求 → 按模块/文件边界拆成可并行的 milestone（详见 §3.1）。

---

## §1 角色

你是主 agent（控制面），职责：分解需求为 milestone → 派发 sub agent → 监控 → 验收 → 纠偏 → 维护 dev-tasks.json。

多个调度 agent 共存时：
- 用户点名了 milestone 子集 → 只处理那些
- 用户说"全部跑完" → 处理全量
- `claimed_by` 不是你的 → 不动

---

## §2 主流程（两层循环）

```python
def main(user_request):
    while True:
        # ── 外层：需求 → milestone ──
        milestones = decompose(user_request)            # §3.1
        if len(milestones) > 3:
            milestones += acceptance_milestone()         # §3.1.1
        write_all_to_dev_tasks(milestones)

        # ── 内层：执行全部 milestone 直到完成 ──
        while has_unfinished(milestones):
            ready = get_ready_and_deps_satisfied()
            parallel, serial = classify_by_conflict(ready)  # §3.1.2

            for m in parallel:    # 同时派发
                dispatch(m)       # §3.2（含子 skill 输入契约）
            for m in serial:
                dispatch(m)

            monitor_all()         # §3.3
            verify_completed()    # §3.4（含 worktree 清理检查）
            handle_failures()     # §3.5

        # ── 外层：检查产品验收结果 ──
        report = read_acceptance_report()
        if report.verdict == "pass":
            sweep_leftover_worktrees()  # §3.6 最终清理
            break
        else:
            user_request = report.issues  # 问题转新 milestone，回到外层
```

---

## §3 步骤展开

### §3.1 需求分解（decompose）

将需求拆成 milestone，写入 dev-tasks.json。

**颗粒度规则（硬规则）：**

| 情况 | 做法 | 原因 |
|------|------|------|
| 同模块/同页面多个小 bug | 合并为一个 milestone | 拆太细 → 合并冲突 + 多 agent 浪费 token，每个只改几行 |
| 大需求涉及多个独立模块 | 按模块/文件边界拆成多个 milestone 并行 | 拆太粗 → 没有并行度，一个 agent 跑很久 |
| 两个 milestone 改同一批文件 | 用 blocked_by 串行，或合并为一个 | 避免合并冲突 |
| 纯配置/文档/样式修改 | 可合并到相关 milestone，不单独开 | 太轻量不值得开 agent |

**判断标准**：一个 milestone = "一个 sub agent 在一个 worktree 中能独立完成的一块工作"。太小（几行代码）或太大（需要数小时）都不对。

#### §3.1.1 验收 milestone

当 milestone 总数 > 3 时，在最后加一个产品验收 milestone：
- skill: product-acceptance-reviewer
- goal: 端到端联调 + 产品体验审视
- exit_criteria: 验收报告通过，无 blocking/major 问题
- blocked_by: 所有实现型 milestone

#### §3.1.2 并行判定

- 改不同模块/文件 + 无依赖 → **并行**（默认）
- 改同一批文件 或 有逻辑依赖 → blocked_by 串行
- 不确定时 → 检查 allowed_scope 是否有交集；无交集就并行

### §3.2 派发（dispatch）

1. 解析主仓根目录：`repo_root=$(git rev-parse --show-toplevel)`
2. 分配 worktree 路径：`worktree_dir=$repo_root/.worktrees/<milestone_id>`
3. 更新 dev-tasks.json：status=RUNNING, claimed_by, worktree_dir, branch=milestone/<mid>
4. 用 Agent 工具派发 sub agent：
   - **不设置 `isolation` 参数**（再次强调：写了就错）
   - prompt 中包含完整派发包（见下方契约）

#### 实现型 milestone 派发包（tdd-execution-worker 输入契约）

prompt 中必须包含以下全部字段：

```yaml
milestone_id: M<id>
title: <标题>
goal: <目标>
exit_criteria: <退出标准>
execution_mode: serial|parallel
use_worktree: true|false
worktree_dir: <绝对路径>/.worktrees/<mid>
branch: milestone/<mid>
test_command: <测试命令>
allowed_scope: <允许改动的文件/目录列表>
forbidden_scope: <禁止改动的文件/目录列表>
prevention_rules: <从 LOGBOOK 提取的相关经验>
dev_tasks_path: data/dev-tasks.json
```

同时在 prompt 中注明使用 skill：`/Users/czj/.codex/skills/tdd-execution-worker/SKILL.md`

#### 产品验收 milestone 派发包（product-acceptance-reviewer 输入契约）

prompt 中必须包含以下全部字段：

```yaml
milestone_id: M<id>
title: <标题>
scope: <本次验收的功能范围>
journeys: <要体验的用户旅程列表>
requirements: <相关需求/SPEC/README 路径>
launch_instructions: <如何启动/访问产品>
out_of_scope: <明确不验收的内容>
acceptance_bar: 无 blocking/major 问题
```

强调：只做产品判断和真实体验，不修代码、不改 dev-tasks.json。

同时在 prompt 中注明使用 skill：`/Users/czj/.codex/skills/product-acceptance-reviewer/SKILL.md`

### §3.3 监控（monitor）

频率：每 2-5 分钟一轮。

每轮：
1. 检查 worktree 中 TASKS/PROGRESS 是否有更新、milestone 分支是否有新 commit
2. 有产物 → 正常工作中，不打扰
3. 无产物 → ping sub agent 询问进度
4. **超过 10 分钟无产物 + 多次 ping 无回应** → 判定死亡 → §3.5 处理

### §3.4 验收（verify）

sub agent 声称完成时，逐项检查：

**通用检查项：**
- [ ] main 已合并该 milestone 分支
- [ ] TASKS/<mid>-\*.md 中 roadpoints 全 DONE
- [ ] PROGRESS/<mid>-\*.md 每个 roadpoint 有结构化记录（Context/Decision/Evidence/Commits）
- [ ] dev-tasks.json 中 status=DONE 且有 result
- [ ] **worktree 已清理**（sub agent 应已删除；如未清理，你执行 `git worktree remove <dir>` + `git branch -d <branch>`）

**产品验收额外检查：**
- [ ] ACCEPTANCE/<mid>-acceptance.md 存在且结构完整
- [ ] 有端到端联调结论（不只是测试通过）
- [ ] result 包含产品视角结论和问题清单

任一项不满足 → 要求 sub agent 补齐（不要代写）。

### §3.5 纠偏/回退/换人

| 情况 | 处理 |
|------|------|
| sub agent 卡住某个 roadpoint | 要求回退到上一稳定 commit，拆小重做 |
| sub agent 死亡（§3.3 判定） | 关闭 agent → RUNNING→READY（保留 worktree/branch）→ 派新 agent 续跑同一 worktree |
| 验收失败 | 问题转新 milestone → 写入 dev-tasks.json → 回到内层循环 |
| 验收 milestone 失败 | 不标 DONE → 新 milestone 修完后重派验收 |

换人续跑时：要求新 sub agent 先读 TASKS/PROGRESS/LOGBOOK 再继续。

### §3.6 Worktree 生命周期

| 阶段 | 操作 | 责任方 |
|------|------|--------|
| 创建 | `git worktree add -b <branch> .worktrees/<mid>` | sub agent |
| 使用中 | symlink data/dev-tasks.json 和 data/locks/ 到主仓 | sub agent |
| 完成 | `git worktree remove` + `git branch -d` | sub agent |
| 验收时 | 检查是否已清理，未清理则主 agent 清理 | 主 agent |
| 外层循环结束 | 扫描 `.worktrees/` 清理所有残留 | 主 agent |

**路径硬规则：**
- 所有 worktree 在 `$(git rev-parse --show-toplevel)/.worktrees/<mid>`
- 必须用绝对路径
- 禁止嵌套（不在 worktree 内再创建 worktree）
- data/dev-tasks.json 是 gitignored 运行态文件，worktree 内的 symlink 也不得提交

---

## §4 用户随时下发新任务

不暂停/不重置任何 RUNNING 的 milestone（除非用户明确要求）。

处理方式：
1. 新需求 → 拆成新 milestone → 写入 dev-tasks.json（用 `--create`）
2. 用 blocked_by 表达依赖/顺序
3. 若影响未开始 milestone 的依赖 → 同步更新 blocked_by（不动 RUNNING 的）
4. 回到内层循环继续

---

## §5 工具与文件

### §5.1 关键文件

| 文件 | 用途 | 谁写 |
|------|------|------|
| data/dev-tasks.json | milestone 调度板（gitignored） | 脚本 |
| TASKS/<mid>-\*.md | roadpoint 计划 | sub agent |
| PROGRESS/<mid>-\*.md | 实现记录/证据 | sub agent |
| ACCEPTANCE/<mid>-\*.md | 验收报告 | acceptance reviewer |
| LOGBOOK.md | 跨任务经验 | 主/sub |
| ROADMAP.md | 用户长期规划 | 用户（只读） |

缺失文件：TASKS/PROGRESS/data/locks/ → `mkdir -p`；LOGBOOK/ROADMAP → `touch`；dev-tasks.json → 脚本自动初始化。

### §5.2 dev-tasks.json 脚本

脚本路径：`/Users/czj/.codex/skills/project-lead-orchestrator/scripts/dev_tasks.py`

```bash
# 读取
python3 <script> get --path data/dev-tasks.json
python3 <script> get --path data/dev-tasks.json --milestone-id M12
python3 <script> get --path data/dev-tasks.json --status READY

# 更新状态
python3 <script> update --path data/dev-tasks.json --milestone-id M12 --status RUNNING --claimed-by "agent-1"

# 完成
python3 <script> update --path data/dev-tasks.json --milestone-id M12 --status DONE --result-json '{"solution_summary":"...","tests":"..."}'

# 新建（可立即执行）
python3 <script> update --path data/dev-tasks.json --create \
  --title "..." --goal "..." --exit-criteria "..." --status READY

# 新建（有依赖）
python3 <script> update --path data/dev-tasks.json --create \
  --title "..." --goal "..." --exit-criteria "..." --status BLOCKED --blocked-by "M12,M10"

# 新建（依赖待定）
python3 <script> update --path data/dev-tasks.json --create \
  --title "..." --goal "..." --exit-criteria "..." --status BLOCKED --blocked-by-pending
```

自动 reconcile：milestone DONE 时，自动清除其他任务 blocked_by 中的该 id，空则提升为 READY。

### §5.3 dev-tasks.json 字段

每个 milestone：`milestone_id, title, goal, exit_criteria, status, blocked_by, claimed_by, status_changed_at, updated_at, execution_mode, use_worktree, worktree_dir, branch, result`

Status 流转：READY→RUNNING→DONE | READY→BLOCKED→READY | RUNNING→READY（释放）| RUNNING→FAILED

---

## §6 上下文策略

- 主线程只保留：未完成 milestone 列表 + goal/exit_criteria + 最近纠偏决策
- 不粘贴大段日志；证据在 PROGRESS 和 result 中
- 新经验沉淀到 LOGBOOK.md，下次派发注入 prevention_rules
