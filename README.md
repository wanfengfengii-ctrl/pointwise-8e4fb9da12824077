# 海岬试验记录档案

海岬材料检测中心的记录室把试验机的有序载荷导出冻结为修订和档案卷。编目员可从较早的可用卷复用片段，值班员凭原卷号和续领票交班，质检员以固定卷核账，库管在保留档案可读后退役旧卷。

## 运行

使用 Python 3.11 标准库。无需安装依赖。从项目根目录运行控制台提供的完整回归入口和样例演示。

```sh
python3 -B check_project.py
python3 -B demo.py
```

也可直接运行完整 unittest 套件。

```sh
python3 -B -m unittest discover -s tests -t .
```

演示在测试临时目录执行真实报送、签卷、交班、核账、退役和重开，随后打印一行包含实际值和手算预期的 `POINTWISE_SCENARIO` JSON。命令 `python3 -B demo.py page ROOT VOLUME SIZE [TICKET]` 与 `python3 -B demo.py report ROOT REPORT_ID` 可在独立进程读取已有工作库，业务拒绝时退出码为 1。

## 正常流程

1. 白班按机台导出的行序报送基础录制。来源批和批内行号共同标识每条原行。
2. 编目员把基础修订签成整卷 R0，保存 A=7、B=7 的原序和不同出处。
3. 白班提交针对固定父版的更正。R1 以 C=11 替换 B。R2 在旧区段中沿用 C 并接入 D=7。编目员用各自的底卷签差量卷。
4. 夜班先领 R1 的 A，把续领票交给下一班。
5. 接班人可凭票续出 C，质检对 R2 逐行核账，记录 C、D 的出处和合计 18。
6. 质检可按报告号复领原签结果。
7. 库管通过卷号核查 R0 的保留义务，并准备可独立读取的替代编码。
8. 发布替代卷，实际清理旧编码文件并签退役回执。同步发布失败会恢复旧卷和票。
9. 工作库重开后，接班人仍可凭原 R1 票从 C 开始，质检仍可读原报告。

## Python 接口

`workspace.initialize(root)` 建库并返回 `Path`。重复调用保留来件、修订、卷、票的含义、报告及回执，样例文件由演示显式报送。其余接口的 `root` 是已初始化的本地工作库，卷号、修订号和报告号为正整数。

| 调用 | 结果与业务错误 |
| --- | --- |
| `intake.revisions.ingest(root, batch, rows)` | 接纳初始 `SourceRow` 序列，返回 `SubmissionReceipt`，其中 `revision_id` 可立即签卷。无效输入或已用批号报 `InvalidSubmission`。 |
| `intake.revisions.ingest(root, batch, parent=revision_id, corrections=hunks)` | 对确切父版接纳整单并冻结子修订。目标、锚点、保留项或父版无效时整单拒绝。 |
| `archive.issue.issue(root, revision_id, base_volume=None, *, frame_rows=2)` | 返回固定卷号。底卷必须存在、可读且属于较早的修订。无效签发报 `IssueError`。 |
| `reading.open.read_page(root, volume_id, page_size, ticket=None)` | 返回 `Page`，含原序 `rows` 和 `next_ticket`。卷尾的票为 `None`。页长须为正整数。坏票报 `TicketError`，不可用卷报 `VolumeUnavailable`，必需档案文件有误时报告 `DecodeError`。 |
| `audit.report.reconcile(root, volume_id)` | 整卷成功解码后返回带报告号、计数和逐出现出处的 `SignedReport`。读不完整时不签报告。 |
| `audit.history.get_report(root, report_id)` | 从持久快照复领原签报告，未知号码报 `ReportNotFound`。 |
| `retention.retire.retire(root, volume_id, *, before_commit=None)` | 发布替代编码、移除淘汰文件并返回 `RetirementReceipt`。`retention.receipts.find_retirement_receipt(root, volume_id)` 查询成功回执，尚未成功时返回 `None`。 |

`intake.records` 提供 `RowOrigin(batch, line)`、`SourceRow(origin, value)` 和 `CorrectionHunk(targets, replacement, before=None)`。批和行号为非空文本，值为整数牛顿或 `None`。使用空序列可冻结空录制。非空 `targets` 必须列出父版上连续原行的身份，`replacement` 中的 `RowOrigin` 表示保留区段内该确切原行，`SourceRow` 表示本单的新报原行。空替换删除区段。空目标表示插入，`before` 指向父版行，省略锚点表示追加。所有区段使用同一父版坐标，重叠区段和同一插入位置的冲突整单拒绝。

差量帧按原行身份及值判断复用，目标顺序和源帧内范围都须连续。引用绑定确切发行编码和源帧。解码校验卷文件、帧封签、范围和覆盖。票为库内认证的字符串，绑定固定卷和签发时的帧边界，支持原样重放及跨进程读取。页交付的原行使用零和缺测的原值。核账对每个出现计一次，零参与整数合计，缺测单列，报告中的逻辑行次从 1 起。输入 7、缺测、0 的计数是 3，缺测数是 1，合计是 7。

`catalog.sqlite3` 保存目录和业务记录。工作库 `volumes/` 内的 `.volume` 文件是发行编码的卷文件，`.frame` 文件包含直接载荷或固定引用。退役成功后清理目标和被替换编码的物理文件，保留卷仍按原号交付原序行。报送原件、修订和历史报告各自持久保存。回归用可选 `before_commit` 在同步发布末尾抛出 `PublicationAborted`，验证 SQLite 回滚、帧文件恢复和无成功回执。调用完成后可从另一进程重开工作库。退役操作与其他进程的同时访问、断电恢复和远程归档超出本地运行契约。
