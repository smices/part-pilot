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

## 阶段 1：最小增量

在不新增或配置外部模型、服务或 Blender 的前提下，选定一个已验证的本地
OrcaSlicer 打印机/材料配置，对一个 Smart Fan 请求运行一次 `--planner rules
--slice`。保留该次 3MF、G-code 和切片报告，并继续以 FreeCAD 回读其 STEP。
结果只能标记为“真实切片”，不能推断为真实模型调用或实物打印/装配验证。
