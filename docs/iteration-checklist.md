# 迭代执行清单

## 阶段 0：可复现基线（通过）

执行时先确认工作区，再把生成物写入临时目录，不写入受版本控制的
`exports/`：

```bash
git status --short
.venv/bin/python -m pytest

stage0_dir="$(mktemp -d "${TMPDIR:-/tmp}/partpilot-stage0.XXXXXX")"
.venv/bin/python -m ai_cad_designer.cli sensor \
  --planner rules --output "$stage0_dir"

# 将 FREECAD_CMD 指向已安装的 FreeCAD 命令；macOS app bundle 通常为
# /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd。
"$FREECAD_CMD" scripts/freecad_validate_step.py "$stage0_dir/sensor_base.step"
```

本次基线实际已完成规则规划 sensor 输出和 FreeCAD STEP 回读：
启动时 `git status --short` 无输出。`sensor_base.step` 被 FreeCAD 1.1.3
读取为有效的单实体，体积
20,841.100 mm3，边界为 80.000 × 52.400 × 20.000 mm。完整 `pytest`
通过（54 passed、11 warnings、130.28 秒）。

| 证据层级 | 阶段 0 状态 | 已证明 / 未证明 |
| --- | --- | --- |
| 测试替身 | 通过：54 passed | Python/CAD 内核、网格及工作流断言；不等同于外部 CAD 或制造。 |
| 真实 CAD | 通过：FreeCAD 原生 STEP 回读 | 一个导出的 sensor STEP 可被独立 FreeCAD B-Rep 内核读取；不等同于实际打印。 |
| 真实切片 | 未执行 | 未传 `--slice`，因此没有 3MF、G-code 或切片耗材/时间结论。 |
| 真实模型 | 未执行 | 使用 `--planner rules`；没有调用 Codex、API 或视觉模型。 |

Smart Fan 的最小回归集覆盖气流估计、参数/校准、完整装配导出和 LLM
输入约束；本次通过（10 passed、14 deselected、8 warnings、147.48 秒）。
运行命令为：

```bash
.venv/bin/python -m pytest \
  tests/test_airflow.py \
  tests/test_engineering_parameters.py \
  tests/test_workflow.py \
  tests/test_llm_workflow.py \
  -k "smart_fan or airflow"
```

## 阶段 1：可信状态契约

最小范围仅为 schema、workflow、validation、CLI 和 GUI 共享同一状态
契约；不执行真实切片、真实模型调用、实物验证，也不配置 Blender 或外部服务。
每个检查使用 `未执行`、`通过`、`失败` 或 `受阻` 之一，CLI JSON 和 GUI
展示不得把缺失状态推断为通过。

| 范围 | 阶段 1 契约 |
| --- | --- |
| 证据 | 文件存在性、几何有效性、切片产物、实物观察分别记录状态和证据；一类通过不提升其他类状态。 |
| 材料 | 记录材料值及其来源；缺少材料输入或来源时不得宣称制造验证通过。 |
| 规则回退 | 记录请求的 planner、实际 planner 和是否回退；覆盖不可用模型回退 `rules`，以及严格模式拒绝回退。 |
| 空验证 | 未运行是“未执行”，前置条件不可用是“受阻”，已尝试却无检查或证据是“失败”；空对象、`null` 或缺失字段绝不默认为“通过”。 |

阶段 5 才执行真实 OrcaSlicer 切片并保留 3MF、G-code 和切片报告。届时可在
其独立证据下追加 FreeCAD STEP 回读；这些结果不能推断为真实模型调用或实物
打印/装配验证。

## 当前首轮数字验收

| 能力 | 状态 | 当前证据与边界 |
| --- | --- | --- |
| 实测 PCB 输入与外壳 | 通过 | PCB 外形、孔、接口、禁入区及每项来源/确认状态驱动双件外壳；未确认测量会阻止制造通过。 |
| CAD / 视觉审查 | 通过 | 当前运行的 STL 可生成隔离 Blender 等轴图和多零件爆炸图；Blender 缺失时明确为受阻。 |
| 实际切片 | 通过（参考配置） | 已使用 OrcaSlicer 2.4.2、已确认 P1P 0.4 mm / PETG 参考配置；报告绑定 STL SHA-256。该结果不是任意打印机的配置认证。 |
| 有界修复 | 通过 | 仅允许白名单壁厚调整；每轮保留独立目录、问题、参数和停止原因。未确认测量、几何硬错误或切片问题转人工。 |
| GUI 日常流程 | 通过 | 支持 PCB JSON 编辑、异步提交、状态轮询、取消、预览与下载；活动任务 ID 在同一浏览器会话刷新后恢复。取消后的未完成任务不会标为成功。 |
| 交付包 | 通过 | PCB 运行产生包含当前运行文件及 SHA-256 清单的 ZIP。 |
| 实体打印和装配 | 待完成 | 需要实际设备执行试片、测量回填、正式打印、装配/拆卸并把证据回填；数字链路不得表述为实物通过。 |

实体执行者应从当前切片报告复制 STL 文件名和 SHA-256 到
`examples/physical_evidence_template.json`，填写打印后测量与装配结果，再运行：

```bash
.venv/bin/python -m ai_cad_designer.cli physical \
  --planner rules --output "<本次输出目录>" \
  --physical-evidence "<填写后的证据 JSON>"
```

该命令只记录与当前 STL 哈希完全匹配的实物证据；无法替代实际打印或装配。
