# Smart Fan 设计说明

这份文档描述当前代码中的 `smart_fan` 设计族。它是项目中唯一保留的
Smart Fan 设计说明；历史版本的逐次实验记录不再作为使用文档维护。

## 设计范围

工作流针对 Mac mini M4、120 mm PWM 风扇和控制器电子件生成垂直堆叠的
可拆卸底座，输出参数化 CAD、装配、制造验证和校准试片。当前参考硬件包括：

- Mac mini M4：127 × 127 × 50 mm；
- 120 mm PWM 风扇：120 × 120 × 25 mm；
- ESP32-C3 Super Mini；
- 12 V / 5 V DC-DC 模块；
- MOSFET PWM 驱动器；
- DS18B20 探头和线缆净空。

未提供明确型号、机械图或实测值时，硬件尺寸会标记为估算或参考值，不能
替代卡尺测量。

## 制造策略

制造评估同时考虑几何有效性、构建空间、壁厚、桥接、支撑耗材、打印时间、
拆除可达性和风道污染。默认策略是局部、必要的支撑；不能因为切片器能够
生成支撑就默认开启全局支撑。

主风口、USB 维护口、控制器卡扣、风扇卡钩和 DS18B20 托台优先使用自支撑
拱形、倒角或局部实体托。桥接和配合试片应先于正式生产件打印。解析检查
不能替代实际打印、装配、温升和噪声测试。

## 参数来源与校准

GUI 第三步会根据需求、硬件识别结果和可用模型自动分析材料、公差、壁厚和
层高；每个值仍可手工修改。模型不可用时显示参考值并要求确认。

GUI 生成结果会导出 `calibration_measurement_template.json`。填写试片和
接口测量值后，可在 CLI 下一轮生成时回填：

```bash
ai-cad design \
  --planner rules \
  --calibration-results path/to/calibration_measurement_template.json \
  --request "基于 smices/hw_smart_fan 为 Mac mini M4 设计底部智能散热底座" \
  --output ai_cad_designer/exports/smart_fan_calibrated
```

校准导入支持公差、圆角、电源键、风扇孔位、探头卡扣，以及前后接口的
X/Z 残差。前后接口残差会叠加到当前的
`front_interface_delta_*` / `rear_interface_delta_*` 工程参数，并标记为
`calibration_coupon`。

## 输出与验证

每次设计输出目录至少包含：

- `design_proposal.md`：提案和零件清单；
- `*.step` / `*.stl`：零件、参考件和装配；
- `validation_report.json`：几何、装配、BOM 和制造检查；
- `calibration_measurement_template.json`：下一轮校准输入；
- 开启 `--slice` 时的 OrcaSlicer 报告和 3MF 输出。

生产前重点检查：

1. Mac mini 底脚、风道和接口是否与实物一致；
2. 电源键运动、风扇接头和线缆弯折是否有足够净空；
3. 桥接试片、卡扣试片和 PETG 公差试片；
4. 实际打印机配置下的支撑、温升、噪声和装配寿命。

