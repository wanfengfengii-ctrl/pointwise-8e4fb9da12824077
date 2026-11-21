# 海岬夜班退役交班

基础录制有 A=7、B=7。第一次勘误保留 A，以 C=11 替换 B。第二次勘误保留 C，接入 D=7。编目员用第一卷作 R1 的底卷，再用 R1 作 R2 的底卷。载荷单位为牛顿。

夜班先从 R1 领一行 A 并保留原票，质检按 R2 签出 C、D 和合计 18。库管随后退役 R0。回执已落定，但从卷头领取 R2、重新核账 R2、用原票续领 R1 均报缺件。

交班办妥后，R0 停止领取，样例中的目标卷及被替换编码的旧档案文件均已清理，B 的档案载荷随之移除。报送原件、修订和历史报告继续按各自职责保存。R2 应按原序领出 `correction-1/C=11` 和 `correction-2/D=7`，核账为 2 行、0 缺测、18 牛顿。R1 的旧票应只续出 `correction-1/C=11`，随后到卷尾。原回归核对样例退役时 R1 原来分属两帧的 A、C 合为一帧，并在另一进程用原票续领。发生同步发布失败时，原卷、原票和原签报告保持可用，查不到成功退役回执。

从工程根目录运行 `python3 -B incident.py`。脚本办理一次真实退役，输出退役前读值及三个退役后观察项的预期和实际结果。命中事故时返回 1，并印出 `POINTWISE_RETIREMENT_HANDOFF_MISMATCH`。修复后应返回 0，三项结果均与预期一致。

沿用 `.pointwise-runtime.json` 的第 1 版 CLI 运行清单。`setup` 是空的命令列表，`verify` 与 `demo` 是 argv 数组，分别执行 `python3 -B check_project.py` 和 `python3 -B demo.py`。前者运行完整回归，后者演示从报送到退役重开的交班。Python 调用、票和报告格式见 README.md。

## 根因与实测

根因有三处，均在退役链路：

1. `retention/eligibility.py` 的退役范围只查直接引用目标编码的卷。R2 的帧引用的是 R1 的编码而非 R0 的，退役 R0 时 R2 未被重编，R1 旧编码文件清理后 R2 的引用帧悬空，读取和核账报 `missing required encoding 2`。
2. `reading/resume.py` 从不查 `replacement_history`（该表只有发布端写入），R1 旧票绑定的签发编码被替换后无法解析。
3. `retention/publication.py` 在移除物理文件时连同删除了被替换编码的目录行，旧票赖以计算逻辑边界的签发帧布局随之丢失。

修复：退役评估按卷号升序做单趟传递闭包，凡现役编码直接或间接引用将下线编码的保留卷都重编为独立载荷；发布时只物理移除目标及被淘汰编码的文件，目录行保留供旧票定位；续领解析先按票面签发编码的帧布局算出逻辑边界，再沿 `replacement_history` 落到现役编码。票格式、接口与失败回滚路径未变。

实测（修复后）：`python3 -B incident.py` 返回 0，R2 领出 `correction-1/C=11`、`correction-2/D=7`，核账 2 行、0 缺测、18 牛顿，R1 旧票只续出 C 并到卷尾；`python3 -B check_project.py` 23 项回归全过（含新增 `test_retirement_handoff_incident`，该用例在修复前失败）；`python3 -B demo.py` 返回 0。同步发布失败路径仍恢复原卷、原票和原签报告，且无成功回执。
