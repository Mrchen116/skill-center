---
name: tdd-execution-worker
description: 子 agent 执行面技能。接收主 agent 派发的一个 Milestone，在同一 worktree/分支内完成：一次性拆 Roadpoints（写入 TASKS/PROGRESS）、逐点按 C1/C2/C3 完成、必要时回退重试/交接，最终将 Milestone 整体合并到 main 并更新 dev-tasks.json 状态。
---

# TDD Execution Worker

## 1) 输入契约（必须有，任务单位=Milestone）

开始前检查派发包字段（缺失则先向主 agent 补齐）：
- `milestone_id`
- `title`
- `goal`
- `exit_criteria`
- `execution_mode` (`serial|parallel`)
- `use_worktree` (`true|false`)
- `worktree_dir`（use_worktree=true 时必须提供）
- `branch`（如 `milestone/<milestone_id>`）
- `test_command`
- `allowed_scope` / `forbidden_scope`
- `prevention_rules`
- `dev_tasks_path`（默认 `data/dev-tasks.json`，worktree 内必须指向主仓共享那份）

---

## 2) 启动动作（固定）

1. 先读 `LOGBOOK.md`（主动，拆坑经验库）：把相关坑/规则加入本 Milestone 注意事项  
2. 读 `COMMENTING_GUIDE.md` 并承诺遵守其中的注释/评论规范（后续写代码与写文档均以此为准）  
3. 复述当前处境：
   - Milestone（id/title）
   - execution_mode / 是否 worktree / worktree_dir / branch
   - 测试门禁命令
   - 允许/禁止改动范围
4. 应用 `prevention_rules`（主 agent 注入）  
5. 跑一次 `test_command` 建立基线（若已失败：先向主 agent 说明“失败原因/是否纳入本 Milestone scope”再继续）  
6. 再开始执行

---

## 3) Roadpoint 执行标准（强制三提交）

每个 Roadpoint 必须严格执行：

1. Red：先写测试并用 `test_command`（或该 Roadpoint 的最小子集）确认“失败点=当前缺失能力/bug”  
2. C1：仅提交测试  
3. Green：最小实现让测试通过  
4. Refactor：行为不变重构（如需改行为，先补测试再改代码）  
5. 全绿门禁：在 C2 前必须再次运行 `test_command` 并确认全绿  
6. C2：提交实现/重构  
7. 更新文档：
   - 必更：`TASKS/<milestone_id>-<简述>.md`、`PROGRESS/<milestone_id>-<简述>.md`
   - 选更：仅当你发现“可复用的坑/预防规则/关键经验”时才追加 `LOGBOOK.md`（不要把实现思路/决策流水写进 LOGBOOK；写进 PROGRESS）
8. C3：仅提交文档

提交语义：
- C1: `test(Rx.y): ...（先红）`
- C2: `feat|fix|refactor(Rx.y): ...（全绿）`
- C3: `docs(Rx.y): ...（记录hash/证据/下一步）`

约定：冒号 `:` 后的描述必须用中文，且尽量短、具体、可验收。

---

## 4) 任务生命周期（一个 Milestone 一口气做完）

### 4.1 工作区准备（按 use_worktree）

#### use_worktree=false（串行）
- 在当前仓库新建并切到分支：`<branch>`

#### use_worktree=true（并行/隔离）
0. 先解析主仓根目录：`repo_root=$(git rev-parse --show-toplevel)`
   - 即使当前 shell 已经身处某个 worktree，也必须以 `repo_root` 为锚点；禁止用 `pwd`、相对路径或“当前目录”推导新的 `worktree_dir`
   - 默认约定：`worktree_dir="$repo_root/.worktrees/<milestone_id>"`
   - 禁止在已有 `.claude/worktrees/...`、`.worktrees/...` 或任何其他 worktree 目录内部，再创建新的 agent worktree / milestone worktree
1. 如果 `worktree_dir` 已存在：直接进入复用（用于换人/续跑）  
2. 否则创建 worktree：
   - 先确认 `worktree_dir` 是位于 `repo_root/.worktrees/` 下的绝对路径
   - 再执行 `git -C "$repo_root" worktree add -b <branch> <worktree_dir>`
3. 在 worktree 中确保共享派工板：
   - `data/dev-tasks.json` 必须 symlink 到主仓同一份（避免状态分叉）
   - 锁目录（如 `data/locks/`）也必须共享（symlink 或使用主仓绝对路径）

> 注意：`dev-tasks.json` 是运行态文件，必须 `gitignore`，不得提交到 git；worktree 内的 symlink 也不得提交到 git。

### 4.2 Plan（只做一次）

在同一 worktree/分支中 explore repo 后：
1. 生成 `TASKS/<milestone_id>-<简述>.md`：
   - Roadpoint 列表（R1/R2/…）
   - 每个 Roadpoint 必填：
     - Acceptance（3-5 条）
     - Tests Plan：默认四类 `unit/contract/integration/e2e`，写明本 Roadpoint 选哪些、不选哪些及原因
     - Expected Tests：尽量写到“测试文件/测试名/入口形态”
     - DoD：`test_command` 全绿 + C1/C2/C3 齐全 + PROGRESS 写清决策/证据/哈希
     - 状态（TODO/DOING/DONE/BLOCKED）
2. 生成/更新 `PROGRESS/<milestone_id>-<简述>.md`：
   - 目的：把“当时为什么这么做”的关键决策固化下来，支持：
     - 未来排障/演进时回溯设计意图
     - sub agent 死亡/换人后快速续跑
     - 主 agent 低成本验收（不需要粘贴大段日志）
   - 要求：每个 Roadpoint 完成后必须补齐一条结构化记录（尽量每项 1-3 行）：
     - `Context`：问题/约束/边界（含不做什么）
     - `Decision`：最终方案（关键结构/API/协议点）
     - `Rationale`：为什么这样做（取舍/替代方案一句）
     - `Evidence`：`test_command` 全绿 + 入口验证一句 + 关键约束/边界
     - `Rollback`：若要重做，应回退到哪个稳定 commit（通常 C1 或上一 Roadpoint 的 C3）
     - `Commits`：`C1` / `C2` / `C3`
     - `Next`
     - 模板（直接 copy，保持简短即可）：

       ```md
       ### Rx.y <Roadpoint 标题>
       - Context:
       - Decision:
       - Rationale:
       - Evidence:
         - Tests: <test_command>
         - Entry: <一句入口验证>
       - Rollback:
       - Commits: C1=<...>, C2=<...>, C3=<...>
       - Next:
       ```
3. 提交一次计划提交（不算 Roadpoint 的 C1/C2/C3）
4. 推荐 `git push -u origin <branch>`（保存现场，便于断网/换人恢复）

#### Tests Plan：测试分层（默认四类）

- unit：逻辑与边界，快速定位
- contract：边界结构校验（字段/类型/必填/协议）；优先用项目现有机制（如 Pydantic / JSON Schema / OpenAPI 等）
- integration：关键链路串联（配置 -> 构造 -> 处理 -> 解析 -> 副作用）
- e2e：真实入口验证主流程，防止“单测全过但入口失败”

#### Tests Plan：入口自适应（写进 TASKS 的 Tests Plan 里）

- CLI：用 `subprocess` 跑真实命令行入口，断言退出码/输出/产物
- HTTP：用测试客户端或启动服务发真实请求，断言响应与副作用
- 库/算法：用 public API 跑完整用例，不用“私有函数单测”冒充 e2e

### 4.3 Execute（Roadpoint 循环）

对每个 Roadpoint（同一 sub agent、同一 worktree/分支）：
1. 按第 3 节完成 C1/C2/C3 三提交  
2. 不合并到 main（Milestone 作为整体合并）  
3. 推荐在每个 Roadpoint 完成后：
   - `git push`（保存现场，便于换人/回滚）
   - 视情况 `git fetch origin && git rebase origin/main`（降低最终集成冲突；不是 merge）

### 4.4 Milestone 完成后整体集成到 main

当所有 Roadpoint DONE 且满足 `exit_criteria`：
1. `git fetch origin`
2. `git rebase origin/main`（冲突按第 5 节处理）
3. 运行 `test_command`（必须全绿）
4. 获取合并锁（`data/locks/merge.lock`，目录锁即可），确保同一时刻只合并一个 Milestone  
5. 合并并 push（worktree 内无法 checkout main，必须先回主仓）：
   - `repo_root=$(git rev-parse --show-toplevel)`
   - `cd "$repo_root"`
   - `git checkout main && git pull --rebase origin main`
   - `git merge --no-ff <branch>`
   - `git push origin main`
6. 释放合并锁
7. 用脚本更新 `data/dev-tasks.json`（不要手改），将该 Milestone 更新为 `DONE` 并写入 `result`：

```bash
python3 /Users/czj/.codex/skills/tdd-control-tower/scripts/dev_tasks.py update --path data/dev-tasks.json --milestone-id "<milestone_id>" --status DONE --result-json '{"solution_summary":"...","tests":"...","commits":{"C1":"...","C2":"...","C3":"..."}}'
```

8. 清理（仅当 `use_worktree=true` 且 Milestone 已 `DONE`）：
   - 退出 `worktree_dir`，在主仓执行：
     - `git worktree remove <worktree_dir>`
     - `git branch -d <branch>`（若提示未合并：说明集成未成功，停止并向主 agent 报告）
   - 不要在“交接/释放（回到 READY/BLOCKED）”时清理 worktree；那会导致无法复用续跑。

---

## 5) 冲突处理（rebase 失败）

当 `git rebase origin/main` 失败时：

1. 若是 `unstaged changes`：
   - 先 `git add/commit` 或 `git stash`
2. 若有 merge conflicts：
   - `git status` 查看冲突文件
   - 逐文件理解双方意图并手动解决
   - `git add <resolved-files>`
   - `git rebase --continue`
3. 重复直到 rebase 完成

禁止直接将任务标记失败后放弃。

---

## 6) 测试失败处理

1. 运行 `test_command`  
2. 分析失败原因  
3. 修复  
4. 重跑直到全绿  
5. 提交修复

---

## 7) 回退策略（唯一）

同一 Roadpoint 连续失败 > 6 次：

1. 回退到最近可靠提交（优先该 Roadpoint 的 C1 或更早全绿点）  
2. 在 `PROGRESS/<milestone_id>-<简述>.md` 的该 Roadpoint 条目追加/补齐：
   - 失败现象与根因假设
   - 失败次数
   - 回退目标提交
   - 重拆分方案（新的 Roadpoint 切法/新的测试策略）
   - 若沉淀出可复用“预防规则/坑位”，再追加到 `LOGBOOK.md`
3. Roadpoint 拆小，从 Red 重做

---

## 8) 交接/回传（给主 agent）

主 agent 主要关心：Milestone 是否可继续推进、整体设计思路、以及如何换人续跑。

回传必须包含（简短即可）：
1. Milestone 当前状态：DONE / BLOCKED / 仍在 RUNNING  
2. `TASKS/<milestone_id>-<简述>.md` 中 Roadpoint 完成情况摘要（哪些已完成/剩哪些）  
3. 关键实现设计摘要（可直接引用 `PROGRESS/<milestone_id>-<简述>.md` 的要点）  
4. 是否需要回退：回退到哪个“最近稳定 commit”（通常上一 Roadpoint 的 C3）  
5. 新增的 `prevention_rules`（如有，写入 LOGBOOK 并在回传里列出）  

若你需要停止或交棒：
1. 确保 `TASKS/PROGRESS/LOGBOOK` 已更新并提交到 Milestone 分支  
2. `git push`（保存现场）  
3. 通过工具/脚本将 `data/dev-tasks.json` 中该 Milestone 释放（回到 READY）或标记 BLOCKED（写明原因），并保留 `worktree_dir/branch` 以便新 sub agent 复用

脚本路径：
- `/Users/czj/.codex/skills/tdd-control-tower/scripts/dev_tasks.py`
