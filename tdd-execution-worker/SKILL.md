---
name: tdd-execution-worker
description: 用于作为 subagent 执行单个 Milestone 的编码实现。触发条件：被 project-lead-orchestrator 派发一个含 milestone_id/goal/exit_criteria/test_command 的派发包，需要在 worktree 中完成 TDD 三提交循环（C1测试/C2实现/C3文档）并合并到 main。不要用于：调度多个 milestone（用 orchestrator）、不需要 TDD 流程的简单修改。
---

# TDD Execution Worker

## §0 硬规则（违反即失败）

### 编码原则

1. **遵循 SPEC 和项目架构**：先读相关 SPEC 文档和现有代码结构，在项目既有架构内实现。不要"哪能跑就在哪写"，不要为了最小改动而放错位置。正确的做法是最符合框架设计意图的做法，不是改动行数最少的做法。
2. **禁止兜底/降级/防御性编程**：Avoid degradation handling, fallback, hacks, heuristics, local stabilizations, or post-processing bandages that are not faithful general algorithms. 兜底代码不只是屎山——它会造成数据静默错误而你完全不知道。错误应该大声失败（raise/assert），不要静默吞掉。
3. **禁止超范围改动**：只改 `allowed_scope` 内的文件；`forbidden_scope` 内的文件不得修改。

### 测试原则

4. **测试必须证明产品能用，不是证明代码能跑**：单元测试全绿 ≠ 产品能用。历史教训：M250 每个组件的单元测试都过了，但 send_message 在真实系统中根本不能用；M248 单元测试全绿，但 session 在 gateway 重启后实际丢失。原因都是测试只 mock 了内部函数，没有走真实入口。
5. **新功能必须有真实入口测试**：至少一个测试走真实产品入口（浏览器/CLI/HTTP endpoint），证明用户真的能用。不接受"全是 mock 的单元测试全绿"作为完成依据。
6. **Bug 修复 / 重构：补足现有测试，不要新建一堆**：优先修改现有测试文件，补充缺失的断言或场景。不要为每个小修改都新建测试文件。
7. **不要为了测试而测试**：每个测试必须证明现有测试没覆盖的东西。重复/无用的测试该删就删。测试数量不是目标，覆盖真实行为才是。

### 流程规则

8. **强制三提交**：每个 Roadpoint 必须 C1（测试）→ C2（实现）→ C3（文档），不得合并或跳过。
9. **测试门禁**：C2 提交前必须 `test_command` 全绿。
10. **不手改 dev-tasks.json**：所有写操作通过内置脚本。
11. **Worktree 路径锚定主仓**：`$(git rev-parse --show-toplevel)/.worktrees/<mid>`，禁止用相对路径、禁止嵌套 worktree。

---

## §1 输入契约

开始前检查派发包（缺失字段向主 agent 补齐）：

```yaml
milestone_id: M<id>
title: <标题>
goal: <目标>
exit_criteria: <退出标准>
execution_mode: serial|parallel
use_worktree: true|false
worktree_dir: <绝对路径>    # use_worktree=true 时必须
branch: milestone/<mid>
test_command: <测试命令>
allowed_scope: <允许改动的文件/目录>
forbidden_scope: <禁止改动的文件/目录>
prevention_rules: <LOGBOOK 中的相关经验>
dev_tasks_path: data/dev-tasks.json
```

---

## §2 主流程

```python
def execute_milestone(dispatch):
    # ── 启动 ──
    setup_worktree(dispatch)                    # §3.1
    read_spec_and_logbook()                     # §3.1
    run_test_baseline(dispatch.test_command)     # §3.1

    # ── 规划 ──
    roadpoints = plan(dispatch)                 # §3.2
    write_tasks_and_progress()
    commit_and_push("plan")

    # ── 执行 ──
    for rp in roadpoints:                       # §3.3
        write_test(rp)                          # Red
        commit("C1: test")
        implement(rp)                           # Green + Refactor
        assert test_command() == ALL_GREEN
        commit("C2: impl")
        update_tasks_and_progress(rp)
        commit("C3: docs")
        push()

    # ── 集成 ──
    rebase_on_main()                            # §3.4
    assert test_command() == ALL_GREEN
    acquire_merge_lock()
    merge_to_main_and_push()
    release_merge_lock()
    update_dev_tasks(status=DONE)

    # ── 清理 ──
    remove_worktree()                           # §3.5
    report_to_orchestrator()
```

---

## §3 步骤展开

### §3.1 启动

**工作区准备：**

- `use_worktree=false`：在当前仓库切到 `<branch>`
- `use_worktree=true`：
  1. `repo_root=$(git rev-parse --show-toplevel)`
  2. `worktree_dir` 已存在 → 直接进入复用（换人/续跑）
  3. 不存在 → `git -C "$repo_root" worktree add -b <branch> <worktree_dir>`
  4. 确保 `data/dev-tasks.json` symlink 到主仓（避免状态分叉）
  5. 确保 `data/locks/` symlink 到主仓

> dev-tasks.json 是 gitignored 运行态文件，worktree 内的 symlink 也不得提交。

**读取上下文：**

1. 读 `LOGBOOK.md`，提取相关经验加入注意事项
2. 读 `COMMENTING_GUIDE.md`（如存在），遵守注释规范
3. **读相关 SPEC 文档**：查找 `docs/`、`specs/` 或项目中与本 milestone 相关的设计文档，理解架构意图和接口约定
4. 读现有代码结构，理解模块边界和职责划分
5. **读现有测试结构**：了解项目已有哪些测试、测试文件的组织方式、已有的 fixture/helper，避免重复造轮子
6. 跑一次 `test_command` 建立基线（若已失败 → 先向主 agent 说明原因再继续）

### §3.2 规划（Plan，只做一次）

Explore repo 后生成：

**TASKS/\<mid\>-\<简述\>.md**：Roadpoint 列表，每个 Roadpoint 必填：
- Acceptance（3-5 条验收标准）
- Tests Plan（见下方 §3.2.1）
- DoD：`test_command` 全绿 + C1/C2/C3 齐全 + PROGRESS 记录完整
- 状态：TODO/DOING/DONE/BLOCKED

**PROGRESS/\<mid\>-\<简述\>.md**：初始化文件，后续每个 Roadpoint 完成后补齐记录。

提交一次计划提交 + `git push -u origin <branch>`。

#### §3.2.1 Tests Plan（核心：测试必须证明产品能用）

规划测试时，按以下顺序思考：

**第一步：确定"怎么证明这个功能对用户真的能用"**

- 这个改动最终影响用户的入口是什么？（浏览器页面？CLI 命令？HTTP API？）
- 用户会怎么触发这个功能？
- 如果我是用户，我怎么验证它 work 了？

**第二步：选择测试策略**

| 场景 | 策略 |
|------|------|
| 新功能（后端/API） | **必须**至少一个真实入口测试（HTTP 请求/CLI 命令），证明用户真的能调通 |
| 新功能（前端 UI） | **必须**至少一个组件交互测试：模拟用户操作（点击/输入/选择）→ 断言页面可见结果（文字/元素出现/消失/变化）。不接受只测内部 state 变化 |
| Bug 修复 | 优先在现有测试文件中补充能复现该 bug 的用例。不要新建文件除非现有文件确实不合适 |
| 重构 | 现有测试应该不改就能通过（行为不变）。如果需要改测试，说明行为变了，要重新审视 |
| 纯内部改动（不影响用户入口） | 单元测试/集成测试即可，但要确认确实不影响入口 |

**第三步：避免常见陷阱**

- ❌ 每个内部函数都写单元测试 → 测试爆炸，重构时全部要改
- ❌ mock 掉所有依赖 → 测试通过但真实链路断了
- ❌ 为了凑测试数量新建大量小文件 → 维护噩梦
- ✅ 一个测试覆盖完整链路 > 五个测试各 mock 一段
- ✅ 修改现有测试文件 > 新建测试文件
- ✅ 删除被新测试覆盖的旧测试

### §3.3 执行（C1/C2/C3 循环）

每个 Roadpoint 严格执行：

| 步骤 | 做什么 | 提交 |
|------|--------|------|
| Red | 写测试，确认失败点=当前缺失能力 | C1: `test(Rx.y): <描述>` |
| Green | 最小实现让测试通过 | — |
| Refactor | 行为不变的重构（改行为需先补测试） | — |
| 门禁 | `test_command` 全绿 | — |
| Commit | 提交实现 | C2: `feat\|fix\|refactor(Rx.y): <描述>` |
| 文档 | 更新 TASKS（状态→DONE）+ PROGRESS（补齐记录） | C3: `docs(Rx.y): <描述>` |
| Push | `git push` 保存现场 | — |

冒号后描述用中文，简短具体。

**PROGRESS 记录模板**（每个 Roadpoint 完成后补齐）：

```md
### Rx.y <标题>
- Context: <问题/约束/边界>
- Decision: <最终方案>
- Rationale: <为什么这样做>
- Evidence:
  - Tests: <test_command 结果>
  - Entry: <真实入口验证结果，不是"单元测试通过">
- Rollback: <回退到哪个 commit>
- Commits: C1=<...>, C2=<...>, C3=<...>
- Next: <下一步>
```

可复用的经验/坑才写 LOGBOOK.md，实现思路写 PROGRESS。

### §3.4 集成到 main

所有 Roadpoint DONE 且满足 `exit_criteria` 后：

```bash
git fetch origin
git rebase origin/main          # 冲突处理见 §4.1
test_command                    # 必须全绿

# 获取合并锁
mkdir data/locks/merge.lock     # 目录锁

# 合并（worktree 内无法 checkout main，回主仓）
repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"
git checkout main && git pull --rebase origin main
git merge --no-ff <branch>
git push origin main

# 释放合并锁
rmdir data/locks/merge.lock

# 更新状态
python3 <script> update --path data/dev-tasks.json \
  --milestone-id "<mid>" --status DONE \
  --result-json '{"solution_summary":"...","tests":"...","commits":{...}}'
```

### §3.5 清理与交接

**正常完成（DONE）：**
1. 退出 worktree_dir，在主仓执行：
   - `git worktree remove <worktree_dir>`
   - `git branch -d <branch>`（提示未合并 → 集成未成功，停止并报告）
2. 向主 agent 回传：状态、Roadpoint 完成情况、关键设计摘要、新 prevention_rules

**需要交棒（未完成）：**
1. 更新 TASKS/PROGRESS/LOGBOOK 并提交 + push
2. 用脚本释放 milestone（→READY 或→BLOCKED），**保留 worktree/branch** 以便续跑
3. 向主 agent 回传：当前状态、卡点、回退目标 commit

---

## §4 异常处理

### §4.1 Rebase 冲突

```
git status → 查看冲突文件 → 逐文件理解双方意图 → 手动解决
git add <resolved> → git rebase --continue → 重复直到完成
```

禁止直接放弃或标记失败。

### §4.2 测试失败

分析原因 → 修复 → 重跑 → 全绿 → 提交修复。

### §4.3 连续失败回退

同一 Roadpoint 连续失败 > 6 次：
1. 回退到上一稳定 commit（该 Roadpoint 的 C1 或上一 Roadpoint 的 C3）
2. 在 PROGRESS 中记录：失败现象、根因、回退目标、重拆方案
3. Roadpoint 拆小，从 Red 重做

---

## §5 工具

脚本路径：`/Users/czj/.codex/skills/project-lead-orchestrator/scripts/dev_tasks.py`

```bash
# 更新状态
python3 <script> update --path data/dev-tasks.json --milestone-id "<mid>" --status RUNNING --claimed-by "agent-x"

# 完成
python3 <script> update --path data/dev-tasks.json --milestone-id "<mid>" --status DONE --result-json '{"solution_summary":"...","tests":"...","commits":{...}}'

# 释放（交棒）
python3 <script> update --path data/dev-tasks.json --milestone-id "<mid>" --status READY
```
