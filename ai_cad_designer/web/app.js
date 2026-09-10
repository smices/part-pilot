const state = { files: [], vision: null, busy: false, step: 1, jobId: null };

const elements = {
  request: document.querySelector("#request"),
  pcbMode: document.querySelector("#pcbMode"),
  pcbFields: document.querySelector("#pcbFields"),
  pcbInput: document.querySelector("#pcbInput"),
  printConfiguration: document.querySelector("#printConfiguration"),
  planner: document.querySelector("#planner"),
  model: document.querySelector("#model"),
  sourceKind: document.querySelector("#sourceKind"),
  material: document.querySelector("#material"),
  tolerance: document.querySelector("#tolerance"),
  wallThickness: document.querySelector("#wallThickness"),
  layerHeight: document.querySelector("#layerHeight"),
  fanAirflow: document.querySelector("#fanAirflow"),
  fanStaticPressure: document.querySelector("#fanStaticPressure"),
  thermalLoad: document.querySelector("#thermalLoad"),
  allowedAirRise: document.querySelector("#allowedAirRise"),
  fanThickness: document.querySelector("#fanThickness"),
  screwless: document.querySelector("#screwless"),
  removable: document.querySelector("#removable"),
  minimalSupports: document.querySelector("#minimalSupports"),
  sliceManufacturing: document.querySelector("#sliceManufacturing"),
  blenderPreview: document.querySelector("#blenderPreview"),
  analyzeConstraints: document.querySelector("#analyzeConstraints"),
  constraintStatus: document.querySelector("#constraintStatus"),
  saveProfile: document.querySelector("#saveProfile"),
  loadProfile: document.querySelector("#loadProfile"),
  profileStatus: document.querySelector("#profileStatus"),
  wizardSteps: document.querySelector(".wizard-steps"),
  loadDemo: document.querySelector("#loadDemo"),
  fileInput: document.querySelector("#fileInput"),
  dropzone: document.querySelector("#dropzone"),
  previews: document.querySelector("#previews"),
  imageCount: document.querySelector("#imageCount"),
  visionButton: document.querySelector("#visionButton"),
  designButton: document.querySelector("#designButton"),
  cancelJob: document.querySelector("#cancelJob"),
  errorBox: document.querySelector("#errorBox"),
  statusDot: document.querySelector("#statusDot"),
  statusText: document.querySelector("#statusText"),
  runState: document.querySelector("#runState"),
  emptyState: document.querySelector("#emptyState"),
  progressState: document.querySelector("#progressState"),
  progressTitle: document.querySelector("#progressTitle"),
  progressSteps: document.querySelector("#progressSteps"),
  resultState: document.querySelector("#resultState"),
  visionSection: document.querySelector("#visionSection"),
  visionCount: document.querySelector("#visionCount"),
  componentCards: document.querySelector("#componentCards"),
  confirmations: document.querySelector("#confirmations"),
  proposalSection: document.querySelector("#proposalSection"),
  plannerLabel: document.querySelector("#plannerLabel"),
  metrics: document.querySelector("#metrics"),
  partsList: document.querySelector("#partsList"),
  bomSection: document.querySelector("#bomSection"),
  bomSummary: document.querySelector("#bomSummary"),
  bomPolicy: document.querySelector("#bomPolicy"),
  bomList: document.querySelector("#bomList"),
  previewSection: document.querySelector("#previewSection"),
  modelCanvas: document.querySelector("#modelCanvas"),
  modelStats: document.querySelector("#modelStats"),
  modelTabs: document.querySelector("#modelTabs"),
  modelError: document.querySelector("#modelError"),
  resetView: document.querySelector("#resetView"),
  topView: document.querySelector("#topView"),
  bottomView: document.querySelector("#bottomView"),
  frontView: document.querySelector("#frontView"),
  rearView: document.querySelector("#rearView"),
  leftView: document.querySelector("#leftView"),
  rightView: document.querySelector("#rightView"),
  dimensionX: document.querySelector("#dimensionX"),
  dimensionY: document.querySelector("#dimensionY"),
  dimensionZ: document.querySelector("#dimensionZ"),
  assemblyInspector: document.querySelector("#assemblyInspector"),
  inspectorTitle: document.querySelector("#inspectorTitle"),
  inspectorSummary: document.querySelector("#inspectorSummary"),
  serviceSequence: document.querySelector("#serviceSequence"),
  inspectorList: document.querySelector("#inspectorList"),
  showAllItems: document.querySelector("#showAllItems"),
  validationSection: document.querySelector("#validationSection"),
  validationSummary: document.querySelector("#validationSummary"),
  validationList: document.querySelector("#validationList"),
  airflowSection: document.querySelector("#airflowSection"),
  airflowSummary: document.querySelector("#airflowSummary"),
  airflowMetrics: document.querySelector("#airflowMetrics"),
  airflowNote: document.querySelector("#airflowNote"),
  airflowChecks: document.querySelector("#airflowChecks"),
  structureSection: document.querySelector("#structureSection"),
  structureSummary: document.querySelector("#structureSummary"),
  structureMetrics: document.querySelector("#structureMetrics"),
  structureNote: document.querySelector("#structureNote"),
  structureChecks: document.querySelector("#structureChecks"),
  manufacturingSection: document.querySelector("#manufacturingSection"),
  manufacturingSummary: document.querySelector("#manufacturingSummary"),
  manufacturingList: document.querySelector("#manufacturingList"),
  calibrationSection: document.querySelector("#calibrationSection"),
  calibrationSummary: document.querySelector("#calibrationSummary"),
  calibrationSequence: document.querySelector("#calibrationSequence"),
  calibrationList: document.querySelector("#calibrationList"),
  calibratedTolerance: document.querySelector("#calibratedTolerance"),
  calibratedCornerRadius: document.querySelector("#calibratedCornerRadius"),
  buttonDeltaX: document.querySelector("#buttonDeltaX"),
  buttonDeltaY: document.querySelector("#buttonDeltaY"),
  frontInterfaceDeltaX: document.querySelector("#frontInterfaceDeltaX"),
  frontInterfaceDeltaZ: document.querySelector("#frontInterfaceDeltaZ"),
  rearInterfaceDeltaX: document.querySelector("#rearInterfaceDeltaX"),
  rearInterfaceDeltaZ: document.querySelector("#rearInterfaceDeltaZ"),
  calibratedFanSpacing: document.querySelector("#calibratedFanSpacing"),
  calibratedFanHole: document.querySelector("#calibratedFanHole"),
  calibratedProbeDiameter: document.querySelector("#calibratedProbeDiameter"),
  calibratedProbeInterference: document.querySelector("#calibratedProbeInterference"),
  calibratedMainBridgeSag: document.querySelector("#calibratedMainBridgeSag"),
  calibratedUsbBridgeSag: document.querySelector("#calibratedUsbBridgeSag"),
  bridgeCouponResult: document.querySelector("#bridgeCouponResult"),
  bridgeCouponNotes: document.querySelector("#bridgeCouponNotes"),
  applyCalibration: document.querySelector("#applyCalibration"),
  calibrationFeedbackStatus: document.querySelector("#calibrationFeedbackStatus"),
  filesSection: document.querySelector("#filesSection"),
  runId: document.querySelector("#runId"),
  filesList: document.querySelector("#filesList"),
};

const SMART_FAN_DEMO = {
  source_kind: "schematic",
  components: [
    {
      name: "Mac mini M4",
      category: "other",
      dimensions_mm: [127, 127, 50],
      confidence: 1,
      evidence: "Apple technical specification: 12.7 × 12.7 × 5.0 cm",
      dimension_source: "datasheet_reference",
    },
    {
      name: "12V 120mm PWM fan",
      category: "fan",
      dimensions_mm: [120, 120, 25],
      confidence: 0.98,
      evidence: "hw_smart_fan README specifies a standard 12V 120mm 2/4-wire fan",
      dimension_source: "known_reference",
    },
    {
      name: "ESP32-C3 Super Mini",
      category: "esp32_board",
      dimensions_mm: [25, 22, 6],
      confidence: 0.78,
      evidence: "Named by the repository; board variants must be measured before printing",
      dimension_source: "estimated",
    },
    {
      name: "12V DC-DC module",
      category: "power_supply",
      dimensions_mm: [45, 25, 15],
      confidence: 0.45,
      evidence: "Electrical block exists in the wiring diagram but no module model is specified",
      dimension_source: "estimated",
    },
    {
      name: "5V DC-DC module",
      category: "power_supply",
      dimensions_mm: [45, 25, 15],
      confidence: 0.45,
      evidence: "Electrical block exists in the wiring diagram but no module model is specified",
      dimension_source: "estimated",
    },
    {
      name: "MOSFET PWM driver",
      category: "power_supply",
      dimensions_mm: [25, 15, 8],
      confidence: 0.45,
      evidence: "The fan PWM switching block is present; the selected module must be measured",
      dimension_source: "estimated",
    },
    {
      name: "DS18B20 metal probe and lead clearance",
      category: "sensor",
      dimensions_mm: [30, 6, 6],
      confidence: 0.55,
      evidence: "20 mm metal capsule plus 10 mm lead bend clearance; measure the selected probe",
      dimension_source: "estimated",
    },
  ],
  scene_notes: [
    "Source: github.com/smices/hw_smart_fan wiring diagram and README.",
    "Reserve airflow, cable exits, fan service access, and separated power/control routing.",
  ],
  requires_user_confirmation: [
    "Measure the exact ESP32-C3 board including USB-C protrusion.",
    "Measure both selected DC-DC modules and their terminal access zones.",
    "Confirm fan thickness, cable exit direction, connector sizes, and DS18B20 cable gland.",
  ],
};

const CAD_PROFILE_KEY = "forge.aiCadProfile.v1";

function parameterInput(name) {
  return document.querySelector(`[data-engineering-parameter="${name}"]`);
}

function markParameterSource(input, source) {
  input.dataset.source = source;
  input.classList.toggle("confirmed", source !== "default_reference");
}

function saveLocalProfile(status = "本机 CAD 记忆已保存") {
  const parameterInputs = [
    ...document.querySelectorAll(
      "[data-engineering-parameter], [data-manufacturing-parameter]",
    ),
  ];
  const profile = {
    version: 1,
    saved_at: new Date().toISOString(),
    request: elements.request.value,
    source_kind: elements.sourceKind.value,
    thermal: {
      fan_airflow_cfm: elements.fanAirflow.value,
      fan_static_pressure_pa: elements.fanStaticPressure.value,
      thermal_load_w: elements.thermalLoad.value,
      allowed_air_rise_c: elements.allowedAirRise.value,
    },
    requirements: {
      screwless: elements.screwless.checked,
      removable: elements.removable.checked,
      minimal_supports: elements.minimalSupports.checked,
      slice_manufacturing: elements.sliceManufacturing.checked,
    },
    bridge_validation: {
      main_portal_crown_sag_mm: elements.calibratedMainBridgeSag?.value || "",
      usb_port_crown_sag_mm: elements.calibratedUsbBridgeSag?.value || "",
      result: elements.bridgeCouponResult?.value || "not_tested",
      notes: elements.bridgeCouponNotes?.value || "",
    },
    parameters: Object.fromEntries(parameterInputs.map((input) => [
      input.dataset.engineeringParameter
        || input.dataset.manufacturingParameter,
      {
        value: input.value,
        source: input.dataset.source || "default_reference",
        kind: input.dataset.engineeringParameter
          ? "engineering"
          : "manufacturing",
      },
    ])),
  };
  localStorage.setItem(CAD_PROFILE_KEY, JSON.stringify(profile));
  elements.profileStatus.textContent = `${status} · ${new Date().toLocaleTimeString()}`;
  return profile;
}

function loadLocalProfile() {
  const raw = localStorage.getItem(CAD_PROFILE_KEY);
  if (!raw) {
    elements.profileStatus.textContent = "没有已保存的本机 CAD 记忆";
    return false;
  }
  try {
    const profile = JSON.parse(raw);
    if (profile.version !== 1 || !profile.parameters) {
      throw new Error("unsupported profile");
    }
    elements.request.value = profile.request || elements.request.value;
    elements.sourceKind.value = profile.source_kind || elements.sourceKind.value;
    const thermal = profile.thermal || {};
    elements.fanAirflow.value = thermal.fan_airflow_cfm ?? elements.fanAirflow.value;
    elements.fanStaticPressure.value = thermal.fan_static_pressure_pa
      ?? elements.fanStaticPressure.value;
    elements.thermalLoad.value = thermal.thermal_load_w ?? elements.thermalLoad.value;
    elements.allowedAirRise.value = thermal.allowed_air_rise_c
      ?? elements.allowedAirRise.value;
    const requirements = profile.requirements || {};
    elements.screwless.checked = requirements.screwless ?? elements.screwless.checked;
    elements.removable.checked = requirements.removable ?? elements.removable.checked;
    elements.minimalSupports.checked = requirements.minimal_supports
      ?? elements.minimalSupports.checked;
    elements.sliceManufacturing.checked = requirements.slice_manufacturing
      ?? elements.sliceManufacturing.checked;
    const bridgeValidation = profile.bridge_validation || {};
    if (elements.calibratedMainBridgeSag) {
      elements.calibratedMainBridgeSag.value =
        bridgeValidation.main_portal_crown_sag_mm || "";
      elements.calibratedUsbBridgeSag.value =
        bridgeValidation.usb_port_crown_sag_mm || "";
      elements.bridgeCouponResult.value =
        bridgeValidation.result || "not_tested";
      elements.bridgeCouponNotes.value = bridgeValidation.notes || "";
    }
    Object.entries(profile.parameters).forEach(([name, parameter]) => {
      const input = parameter.kind === "engineering"
        ? parameterInput(name)
        : document.querySelector(`[data-manufacturing-parameter="${name}"]`);
      if (!input) return;
      input.value = parameter.value;
      markParameterSource(input, parameter.source || "user_supplied");
    });
    elements.profileStatus.textContent = `已恢复 · ${new Date(profile.saved_at).toLocaleString()}`;
    return true;
  } catch {
    elements.profileStatus.textContent = "本机 CAD 记忆格式无效";
    return false;
  }
}

let modelViewer;
try {
  modelViewer = new window.STLViewer(elements.modelCanvas, {
    onStatus: (message) => { elements.modelStats.textContent = message; },
    onDimensions: (dimensions) => {
      [elements.dimensionX, elements.dimensionY, elements.dimensionZ]
        .forEach((element, index) => {
          element.textContent = `${dimensions[index]} mm`;
        });
    },
  });
} catch (error) {
  elements.modelError.textContent = error.message;
  elements.modelError.hidden = false;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({ error: "服务器返回了无效响应" }));
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

async function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({ name: file.name, data_url: reader.result });
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function imagePayload() {
  return Promise.all(state.files.map(fileToDataUrl));
}

function addFiles(fileList) {
  const accepted = [...fileList].filter((file) =>
    ["image/png", "image/jpeg", "image/webp", "application/pdf"].includes(file.type)
  );
  const valid = accepted.filter((file) => file.size <= 20 * 1024 * 1024);
  state.files = [...state.files, ...valid].slice(0, 6);
  state.vision = null;
  setWizardStep(state.files.length ? 2 : 1);
  renderPreviews();
}

function renderPreviews() {
  elements.previews.innerHTML = "";
  state.files.forEach((file, index) => {
    const item = document.createElement("div");
    item.className = "preview";
    const visual = file.type === "application/pdf"
      ? document.createElement("div")
      : document.createElement("img");
    if (file.type === "application/pdf") {
      visual.className = "pdf-thumb";
      visual.innerHTML = `<b>PDF</b><span>${escapeHtml(file.name)}</span>`;
    } else {
      visual.alt = file.name;
      visual.src = URL.createObjectURL(file);
      visual.onload = () => URL.revokeObjectURL(visual.src);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `移除 ${file.name}`);
    remove.addEventListener("click", () => {
      state.files.splice(index, 1);
      state.vision = null;
      setWizardStep(state.files.length ? 2 : 1);
      renderPreviews();
    });
    item.append(visual, remove);
    elements.previews.append(item);
  });
  elements.imageCount.textContent = `${state.files.length} / 6`;
  elements.visionButton.disabled =
    state.busy || state.files.length === 0 || elements.planner.value === "rules";
  elements.designButton.disabled =
    state.busy || (state.files.length > 0 && !state.vision);
}

function requestPayload() {
  const sourceHint = elements.sourceKind.value === "auto"
    ? "由视觉模型自动判断"
    : elements.sourceKind.options[elements.sourceKind.selectedIndex].text;
  const confirmedComponents = (state.vision?.components || []).map((component) =>
    `${component.name}: ${component.dimensions_mm.join(" × ")} mm`
  );
  const engineeringConstraints = [
    "",
    "CONFIRMED USER SETTINGS:",
    `Input source: ${sourceHint}`,
    `Material: ${elements.material.value}`,
    `Assembly tolerance: ${elements.tolerance.value} mm`,
    `Wall thickness: ${elements.wallThickness.value} mm`,
    `Layer height: ${elements.layerHeight.value} mm`,
    `Fan free-air flow: ${elements.fanAirflow.value} CFM`,
    `Maximum static pressure: ${elements.fanStaticPressure.value} Pa`,
    `Thermal load: ${elements.thermalLoad.value} W`,
    `Allowed air temperature rise: ${elements.allowedAirRise.value} C`,
    `Screwless: ${elements.screwless.checked ? "required" : "not required"}`,
    `Removable/serviceable: ${elements.removable.checked ? "required" : "not required"}`,
    `Supports: ${elements.minimalSupports.checked ? "minimal" : "allowed"}`,
  ];
  if (confirmedComponents.length) {
    engineeringConstraints.push("Confirmed component envelopes:", ...confirmedComponents);
  }
  const engineeringParameters = Object.fromEntries(
    [...document.querySelectorAll("[data-engineering-parameter]")].map(
      (input) => [
        input.dataset.engineeringParameter,
        {
          value: Number(input.value),
          source: input.dataset.source || "default_reference",
        },
      ],
    ),
  );
  const manufacturingParameters = Object.fromEntries(
    [...document.querySelectorAll("[data-manufacturing-parameter]")]
      .filter((input) => input.value !== "")
      .map((input) => [
        input.dataset.manufacturingParameter,
        {
          value: input.dataset.manufacturingParameter === "material"
            ? input.value
            : Number(input.value),
          source: input.dataset.source || "default_reference",
        },
      ]),
  );
  Object.entries(engineeringParameters).forEach(([name, parameter]) => {
    const input = parameterInput(name);
    const unit = input?.dataset.unit || "mm";
    engineeringConstraints.push(
      `${name}: ${parameter.value} ${unit} (${parameter.source})`,
    );
  });
  return {
    request: `${elements.request.value.trim()}\n${engineeringConstraints.join("\n")}`,
    planner: elements.planner.value,
    model: elements.model.value.trim(),
    slice_manufacturing: elements.sliceManufacturing.checked,
    blender_preview: elements.blenderPreview.checked,
    engineering_parameters: engineeringParameters,
    manufacturing_parameters: manufacturingParameters,
  };
}

function setWizardStep(step) {
  state.step = Math.max(1, Math.min(4, step));
  [...elements.wizardSteps.children].forEach((item) => {
    const itemStep = Number(item.dataset.step);
    item.classList.toggle("active", itemStep === state.step);
    item.classList.toggle("complete", itemStep < state.step);
  });
}

function loadSmartFanDemo() {
  elements.request.value = `基于 smices/hw_smart_fan 为 Mac mini M4 设计一个底部智能散热底座。
内部包含 ESP32-C3 Super Mini、12V 与 5V DC-DC 模块、MOSFET 驱动、DS18B20 探头接线和 120mm 四线 PWM 风扇。
Mac mini M4 尺寸为 127 × 127 × 50mm，所有通风经过底部脚座。
要求：提供明确卡放位置、前后接口无遮挡、中央底部风道贯通、不用螺丝、可拆卸维护、PETG、0.25mm 装配公差、最少支撑。
配件盒子不要侧向扩展，使用上下堆叠；同时画出 Mac mini、120 × 120 × 25mm 风扇和全部被装配物，在装配图里用半透明物件表示。
外观优先整体化、连续圆滑，结构开孔不得切断上边框，不要出现城墙垛口式豁牙或无必要的断层断点。`;
  elements.sourceKind.value = "schematic";
  elements.material.value = "PETG";
  elements.tolerance.value = "0.25";
  elements.wallThickness.value = "2.5";
  elements.layerHeight.value = "0.2";
  elements.fanAirflow.value = "45";
  elements.fanStaticPressure.value = "12";
  elements.thermalLoad.value = "65";
  elements.allowedAirRise.value = "8";
  document.querySelectorAll("[data-engineering-parameter]").forEach((input) => {
    input.value = input.defaultValue;
    input.dataset.source = "default_reference";
    input.classList.remove("confirmed");
  });
  document.querySelectorAll("[data-manufacturing-parameter]").forEach((input) => {
    input.value = input.defaultValue || input.value;
    markParameterSource(input, "default_reference");
  });
  elements.sliceManufacturing.checked = true;
  state.files = [];
  state.vision = structuredClone(SMART_FAN_DEMO);
  elements.emptyState.hidden = true;
  elements.progressState.hidden = true;
  elements.resultState.hidden = false;
  elements.runState.textContent = "待确认尺寸";
  elements.runState.className = "run-state done";
  renderVision(state.vision);
  renderPreviews();
  void analyzeConstraints();
  elements.visionSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

function setBusy(mode) {
  state.busy = Boolean(mode);
  [
    elements.visionSection,
    elements.proposalSection,
    elements.bomSection,
    elements.previewSection,
    elements.validationSection,
    elements.airflowSection,
    elements.structureSection,
    elements.manufacturingSection,
    elements.calibrationSection,
    elements.filesSection,
  ].forEach((section) => { section.hidden = true; });
  elements.emptyState.hidden = Boolean(mode);
  elements.resultState.hidden = Boolean(mode);
  elements.progressState.hidden = !mode;
  elements.progressTitle.textContent =
    mode === "vision" ? "正在识别硬件" : "正在生成参数化 CAD";
  [...elements.progressSteps.children].forEach((item, index) => {
    item.classList.toggle("active", mode === "vision" ? index === 0 : index <= 2);
  });
  elements.runState.textContent = mode ? "运行中" : "等待任务";
  elements.runState.className = `run-state ${mode ? "running" : "idle"}`;
  elements.designButton.disabled = Boolean(mode);
  elements.cancelJob.hidden = !mode || mode === "vision";
  if (mode === "vision") setWizardStep(2);
  if (mode === "design") setWizardStep(4);
  renderPreviews();
  elements.errorBox.hidden = true;
}

function showError(error) {
  state.busy = false;
  state.jobId = null;
  elements.progressState.hidden = true;
  elements.resultState.hidden = !state.vision;
  elements.emptyState.hidden = Boolean(state.vision);
  elements.runState.textContent = error.cancelled ? "任务已取消" : "任务失败";
  elements.runState.className = `run-state ${error.cancelled ? "idle" : "failed"}`;
  elements.errorBox.textContent = error.message || String(error);
  elements.errorBox.hidden = false;
  elements.designButton.disabled = false;
  elements.cancelJob.hidden = true;
  elements.cancelJob.hidden = true;
  setWizardStep(state.vision ? 3 : Math.min(state.step, 2));
  renderPreviews();
}

function renderVision(vision) {
  state.vision = vision;
  if (!vision) {
    elements.visionSection.hidden = true;
    return;
  }
  const components = vision?.components || [];
  elements.visionSection.hidden = false;
  const sourceLabels = {
    photo: "PHOTO",
    schematic: "SCHEMATIC",
    mixed: "MIXED",
  };
  elements.visionCount.textContent =
    `${sourceLabels[vision.source_kind] || "SOURCE"} · ${components.length} COMPONENTS`;
  elements.componentCards.innerHTML = components.map((component, componentIndex) => `
    <article class="component-card">
      <header>
        <h4>${escapeHtml(component.name)}</h4>
        <span class="confidence">${Math.round(component.confidence * 100)}%</span>
      </header>
      <p>${escapeHtml(component.evidence)}</p>
      <div class="dimension-editor" aria-label="${escapeHtml(component.name)} 外包络尺寸">
        ${["长 L", "宽 W", "高 H"].map((label, axis) => `
          <label>${label} (mm)
            <input type="number" min="0.1" max="1000" step="0.1"
              value="${Number(component.dimensions_mm[axis])}"
              data-component="${componentIndex}" data-axis="${axis}">
          </label>
        `).join("")}
      </div>
      <footer>
        <span>${escapeHtml(component.category)}</span>
        <span>${escapeHtml(component.dimension_source)}</span>
      </footer>
    </article>
  `).join("");
  elements.componentCards.querySelectorAll("input[data-component]").forEach((input) => {
    input.addEventListener("change", () => {
      const component = state.vision.components[Number(input.dataset.component)];
      const value = Number(input.value);
      if (Number.isFinite(value) && value > 0) {
        component.dimensions_mm[Number(input.dataset.axis)] = value;
        component.dimension_source = "user_supplied";
        input.classList.add("confirmed");
        if (
          component.name.toLowerCase().includes("fan")
          && Number(input.dataset.axis) === 2
        ) {
          elements.fanThickness.value = String(value);
          elements.fanThickness.dataset.source = "user_supplied";
          elements.fanThickness.classList.add("confirmed");
        }
      }
    });
  });
  const confirmations = vision?.requires_user_confirmation || [];
  elements.confirmations.hidden = confirmations.length === 0;
  elements.confirmations.innerHTML = confirmations.length
    ? `<b>需实测确认：</b> ${confirmations.map(escapeHtml).join("；")}`
    : "";
  setWizardStep(3);
}

async function analyzeConstraints() {
  if (!elements.request.value.trim()) {
    elements.constraintStatus.textContent = "请先填写工程需求，再进行自动分析；也可以手工填写。";
    return;
  }
  elements.analyzeConstraints.disabled = true;
  elements.constraintStatus.textContent = "正在分析制造约束…";
  try {
    const result = await api("/api/constraints", {
      request: elements.request.value.trim(),
      planner: elements.planner.value,
      model: elements.model.value.trim(),
      vision_report: state.vision,
    });
    Object.entries(result.parameters || {}).forEach(([name, parameter]) => {
      const input = document.querySelector(`[data-manufacturing-parameter="${name}"]`);
      if (!input || parameter.value === undefined || parameter.value === null) return;
      input.value = parameter.value;
      markParameterSource(input, parameter.source || "auto_analyzed");
    });
    const mode = result.analyzed ? `已自动载入（${result.planner}）` : "无法自动分析，已载入参考值，请手工确认";
    elements.constraintStatus.textContent = `${mode}${result.notes?.length ? ` · ${result.notes[0]}` : ""}`;
    setWizardStep(3);
  } catch (error) {
    elements.constraintStatus.textContent = `自动分析失败：${error.message}；请手工填写。`;
    setWizardStep(3);
  } finally {
    elements.analyzeConstraints.disabled = false;
  }
}

function renderProposal(proposal) {
  elements.proposalSection.hidden = false;
  elements.plannerLabel.textContent = String(proposal.planner || "rules").toUpperCase();
  const brief = proposal.brief;
  const metricValues = [
    ["材料", brief.material],
    ["壁厚", `${brief.wall_thickness_mm} mm`],
    ["公差", `${brief.tolerance_mm} mm`],
    ["层高", `${brief.layer_height_mm} mm`],
  ];
  elements.metrics.innerHTML = metricValues.map(([label, value]) => `
    <div class="metric"><span>${label}</span><b>${escapeHtml(value)}</b></div>
  `).join("");
  elements.partsList.innerHTML = proposal.parts.map((part, index) => `
    <div class="part-row">
      <b>${String(index + 1).padStart(2, "0")} · ${escapeHtml(part.name)}</b>
      <span>${escapeHtml(part.purpose)}</span>
      <code>${escapeHtml(part.assembly_method)}</code>
    </div>
  `).join("");
}

function renderBom(bom) {
  elements.bomSection.hidden = !bom;
  if (!bom) return;
  const matched = Number(bom.matched_hardware_count || 0);
  const total = Number(bom.active_hardware_count || 0);
  elements.bomSummary.textContent = bom.passed
    ? `${matched}/${total} CAD-MATCHED`
    : `${matched}/${total} CHECK REQUIRED`;
  elements.bomPolicy.textContent = (
    "提案 BOM、导出参考 CAD 与完整装配必须共用同一尺寸来源；"
    + "禁止退回通用风扇或 ESP32 占位尺寸。"
  );
  const sourceLabel = (source) => {
    const normalized = [...new Set(
      String(source || "").split("/").map((value) => value.trim()).filter(Boolean),
    )].join(" / ");
    return ({
      default_reference: "默认参考规格",
      "hw_smart_fan reference envelope": "hw_smart_fan 参考包络",
      user_supplied: "用户实测",
      calibration_coupon: "校准试片实测",
    }[normalized] || normalized || "未标记");
  };
  const hardwareRows = (bom.items || []).map((item) => {
    const dimensions = item.reference_dimensions_mm || [];
    const size = dimensions.length === 3
      ? dimensions.map((value) => Number(value).toFixed(1)).join(" × ")
      : "—";
    return `
      <div class="validation-row">
        <span><b>${escapeHtml(item.name)}</b> · ${escapeHtml(size)} mm · 来源：${escapeHtml(sourceLabel(item.dimension_source))}</span>
        <b class="${item.passed ? "" : "fail"}">${item.passed ? "CAD + ASSEMBLY" : "MISMATCH"}</b>
      </div>
    `;
  }).join("");
  const consumableRows = (bom.consumables || []).map((item) => `
    <div class="validation-row">
      <span>${escapeHtml(item.name)} · 设计数量 ${Number(item.quantity || 0)} · 装配引用 ${Number(item.installed_reference_count || 0)}</span>
      <b class="${Number(item.quantity || 0) === Number(item.installed_reference_count || 0) ? "" : "fail"}">CONSUMABLE</b>
    </div>
  `).join("");
  elements.bomList.innerHTML = hardwareRows + consumableRows;
}

function evidenceLabel(evidence) {
  const labels = {
    not_run: "NOT RUN",
    passed: "PASSED",
    failed: "FAILED",
    blocked: "BLOCKED",
  };
  return labels[evidence?.status] || "UNKNOWN";
}

function renderValidation(validation, evidence, planner, visual) {
  elements.validationSection.hidden = false;
  const entries = Object.entries(validation || {});
  const geometry = evidence?.geometry;
  elements.validationSummary.textContent = `GEOMETRY ${evidenceLabel(geometry)}`;
  const evidenceRows = Object.entries(evidence || {}).map(([name, record]) => `
    <div class="validation-row">
      <span>${escapeHtml(name)} · ${escapeHtml(record.summary || "")}</span>
      <b class="${record.status === "failed" || record.status === "blocked" ? "fail" : ""}">${evidenceLabel(record)}</b>
    </div>
  `).join("");
  const fallback = planner?.fallback;
  const plannerRow = planner ? `
    <div class="validation-row">
      <span>planner · ${escapeHtml(planner.requested || "rules")} → ${escapeHtml(planner.actual || "rules")}</span>
      <b class="${fallback?.status === "failed" || fallback?.status === "blocked" ? "fail" : ""}">${evidenceLabel(fallback)}</b>
    </div>
  ` : "";
  const visualRow = visual ? `
    <div class="validation-row">
      <span>Blender preview · ${escapeHtml(visual.summary || "")}</span>
      <b class="${visual.status === "failed" || visual.status === "blocked" ? "fail" : ""}">${evidenceLabel(visual)}</b>
    </div>
  ` : "";
  const geometryRows = entries.map(([name, report]) => `
    <div class="validation-row">
      <span>${escapeHtml(name)} · OCP / mesh / build volume</span>
      <b class="${report.printable ? "" : "fail"}">${report.printable ? "PRINTABLE" : "FAILED"}</b>
    </div>
  `).join("");
  elements.validationList.innerHTML = evidenceRows + plannerRow + visualRow + geometryRows;
}

function renderManufacturing(manufacturing, evidence) {
  const slicing = evidence?.slicing;
  elements.manufacturingSection.hidden = false;
  if (!manufacturing) {
    elements.manufacturingSummary.textContent = `SLICING ${evidenceLabel(slicing)}`;
    elements.manufacturingList.innerHTML = `
      <div class="validation-row">
        <span>${escapeHtml(slicing?.summary || "Real slicing was not requested.")}</span>
        <b>${evidenceLabel(slicing)}</b>
      </div>
    `;
    return;
  }
  const parts = Object.values(manufacturing.parts || {});
  const totals = manufacturing.totals || {};
  const support = manufacturing.support_analysis || {};
  const thresholdSweep = manufacturing.support_threshold_sweep || {};
  const localizedSupportPlan = manufacturing.localized_support_plan || {};
  const supportRemoval = localizedSupportPlan.support_removal_accessibility || {};
  const supportOptimization = localizedSupportPlan.support_parameter_optimization || {};
  const openingEconomy = manufacturing.opening_support_economy || {};
  const minutes = Math.round(Number(totals.estimated_seconds || 0) / 60);
  const supportMaterialPercent = (
    Number(support.additional_filament_ratio || 0) * 100
  ).toFixed(1);
  const supportTimePercent = (
    Number(support.additional_time_ratio || 0) * 100
  ).toFixed(1);
  elements.manufacturingSummary.textContent = slicing?.status === "passed"
    ? `${minutes} MIN · ${Number(totals.filament_weight_g || 0).toFixed(1)} G PETG`
    : `SLICING ${evidenceLabel(slicing)}`;
  const supportRow = support.method ? `
    <div class="validation-row">
      <span>自动支撑对照 · +${Number(support.additional_filament_weight_g || 0).toFixed(1)} g PETG（+${supportMaterialPercent}%）· +${Math.round(Number(support.additional_time_seconds || 0) / 60)} min（+${supportTimePercent}%）· 同方向双切片</span>
      <b class="${support.passed ? "" : "fail"}">${support.support_required ? "SUPPORT REQUIRED" : support.auto_support_generated ? "AVOIDABLE SUPPORT" : "SELF-SUPPORTING"}</b>
    </div>
    <div class="validation-row">
      <span>制造策略 · 允许必要支撑；按额外耗材、打印时间、拆除可达性与风道残留联合最小化，禁止默认全局支撑</span>
      <b>MINIMUM SUPPORT</b>
    </div>
  ` : "";
  const supportPartRows = Object.entries(support.parts || {})
    .filter(([, part]) =>
      Number(part.additional_filament_weight_g || 0) >= 0.05
      || Number(part.additional_time_seconds || 0) >= 60
    )
    .map(([name, part]) => {
      const envelope = part.support_toolpath_envelope || {};
      const footprint = envelope.footprint_mm || [];
      const envelopeText = footprint.length === 2
        ? ` · 支撑包络 ${Number(footprint[0]).toFixed(0)}×${Number(footprint[1]).toFixed(0)}×${Number(envelope.height_mm || 0).toFixed(1)} mm`
        : "";
      const bands = envelope.z_bands || [];
      const hotspot = bands.length
        ? bands.reduce((best, band) =>
          Number(band.extrusion_move_count || 0)
            > Number(best.extrusion_move_count || 0)
            ? band
            : best, bands[0])
        : null;
      const hotspotText = hotspot
        ? ` · 热点 Z${Number(hotspot.actual_z_range_mm?.[0] || 0).toFixed(1)}–${Number(hotspot.actual_z_range_mm?.[1] || 0).toFixed(1)} mm（${(Number(hotspot.move_ratio || 0) * 100).toFixed(1)}% 路径 · ${Number(hotspot.feature_move_counts?.support_interface || 0)} 条接触层）`
        : "";
      const ratios = ` · 材料 +${Math.round(Number(part.additional_filament_ratio || 0) * 100)}% / 时间 +${Math.round(Number(part.additional_time_ratio || 0) * 100)}%`;
      return `
      <div class="validation-row">
        <span>${escapeHtml(name)} 自动支撑代价 · +${Number(part.additional_filament_weight_g || 0).toFixed(2)} g · +${Math.round(Number(part.additional_time_seconds || 0) / 60)} min${envelopeText}${hotspotText}${ratios}</span>
        <b class="${support.support_required ? "fail" : ""}">${support.support_required ? "必须评估" : "建议关闭"}</b>
      </div>
    `;
    }).join("");
  const thresholdRows = thresholdSweep.passed ? `
    <div class="validation-row">
      <span>支撑阈值敏感性 · 同一 ${escapeHtml(thresholdSweep.part || "零件")} / 方向 / PETG 配置，仅改变阈值角度</span>
      <b>MEASURED SWEEP</b>
    </div>
    ${(thresholdSweep.trials || []).map((trial) => `
      <div class="validation-row">
        <span>${Number(trial.threshold_angle_deg || 0).toFixed(0)}° 阈值 · +${Number(trial.additional_filament_weight_g || 0).toFixed(2)} g · +${Math.round(Number(trial.additional_time_seconds || 0) / 60)} min · ${Number(trial.support_extrusion_move_count || 0).toLocaleString()} 条支撑路径 · ${Number(trial.support_interface_move_count || 0).toLocaleString()} 条接触路径</span>
        <b>${trial.support_generated ? "AUTO SUPPORT" : "NO SUPPORT"}</b>
      </div>
    `).join("")}
    <div class="validation-row">
      <span>决策 · 先打印桥接试片；通过后关闭支撑，失败时只在失败拱冠下绘制局部支撑。阈值越高会把更多平滑外壳判定为需要支撑。</span>
      <b>LOCAL ONLY</b>
    </div>
  ` : "";
  const localizedSupportRows = localizedSupportPlan.passed ? `
    <div class="validation-row">
      <span>局部支撑决策 · ${Number(localizedSupportPlan.total_support_interface_move_count || 0).toLocaleString()} 条接触路径已按高度和结构分区，默认关闭全局支撑</span>
      <b>3 REGIONS</b>
    </div>
    ${(localizedSupportPlan.regions || []).map((region) => `
      <div class="validation-row">
        <span>${escapeHtml(region.label || region.id)} · Z${Number(region.actual_z_range_mm?.[0] || region.nominal_z_range_mm?.[0] || 0).toFixed(1)}–${Number(region.actual_z_range_mm?.[1] || region.nominal_z_range_mm?.[1] || 0).toFixed(1)} mm · ${Number(region.support_extrusion_move_count || 0).toLocaleString()} 条路径 · ${Number(region.support_interface_move_count || 0).toLocaleString()} 条接触层</span>
        <b>COUPON → LOCAL</b>
      </div>
    `).join("")}
    ${(localizedSupportPlan.support_enforcer_projects || []).map((project) => {
      const measured = project.measured_slice || {};
      if (project.integral_support_used) {
        return `
        <div class="validation-row">
          <span>${escapeHtml(project.label || project.region_id)} · 四个 0.2 mm 一体可撕桥接膜 · +${Number(measured.additional_filament_weight_g || 0).toFixed(4)} g / +${Math.round(Number(measured.additional_time_seconds || 0) / 60)} min · 无外部切片器支撑 · 装配前从四个开放侧面取出</span>
          <b class="${project.passed ? "" : "fail"}">${project.passed ? "INTEGRAL BREAKAWAY" : "REJECTED"}</b>
        </div>
      `;
      }
      if (!project.project_file) {
        return `
        <div class="validation-row">
          <span>${escapeHtml(project.label || project.region_id)} · 实切未产生支撑接触，不输出空白或误导性的 3MF 支撑工程</span>
          <b class="${project.passed ? "" : "fail"}">${project.passed ? "NO EXTERNAL SUPPORT" : "REJECTED"}</b>
        </div>
      `;
      }
      return `
      <div class="validation-row">
        <span>${escapeHtml(project.label || project.region_id)} · 可直接打开 ${escapeHtml(project.project_file || "")} · +${Number(measured.additional_filament_weight_g || 0).toFixed(2)} g / +${Math.round(Number(measured.additional_time_seconds || 0) / 60)} min · ${Number(measured.support_interface_move_count || 0).toLocaleString()} 条界面路径 · 目标区 ${(Number(measured.target_interface_move_ratio || 0) * 100).toFixed(0)}%</span>
        <b class="${project.passed ? "" : "fail"}">${project.passed ? "3MF ENFORCER" : "REJECTED"}</b>
      </div>
    `;
    }).join("")}
    ${localizedSupportPlan.support_strategy_comparison?.passed ? `
      <div class="validation-row">
        <span>支撑拓扑选择 · 已实切比较 tree(manual) 与 normal(manual)；普通柱状支撑虽然更省料，但会在下层非目标表面生成致密界面，因此不采用。</span>
        <b>CONTACT FIRST</b>
      </div>
    ` : ""}
    ${supportRemoval.passed ? `
      <div class="validation-row">
        <span>拆支撑路径 · 装配硬件前从底部沿 −Z 取出树状支撑；界面必须 ≥98% 连通打印平台，永久中央风道不得残留支撑路径。</span>
        <b>REMOVAL READY</b>
      </div>
      ${(supportRemoval.regions || []).map((region) => {
        const access = region.support_removal_access || {};
        return `
        <div class="validation-row">
          <span>${escapeHtml(region.label || region.region_id)} · 底部连通 ${(Number(access.build_plate_connected_interface_ratio || 0) * 100).toFixed(1)}% · 游离界面 ${(Number(access.detached_interface_move_ratio || 0) * 100).toFixed(1)}% / ${Number(access.detached_interface_component_count || 0)} 组且${access.all_detached_interfaces_side_pickable ? "可侧取" : "不可侧取"} · 可达侧面 ${escapeHtml((region.observed_interface_sides || []).join(" / "))} · 永久风道 ${Number(access.permanent_airway_support_move_count || 0).toLocaleString()} 条</span>
          <b class="${region.passed ? "" : "fail"}">${region.passed ? "AIRWAY CLEAR" : "TRAPPED"}</b>
        </div>
      `;
      }).join("")}
    ` : ""}
    ${supportOptimization.passed ? `
      <div class="validation-row">
        <span>树状支撑参数搜索 · 同一模型、方向和 PETG 配置实切 30% / 25% / 20% 顶部接触率；合计节省 ${Number(supportOptimization.total_filament_reduction_g || 0).toFixed(2)} g / ${Number(supportOptimization.total_time_reduction_seconds || 0).toLocaleString()} s，且保留 ≥90% 基线界面覆盖。</span>
        <b>PARAMETER SEARCH</b>
      </div>
      ${(supportOptimization.regions || []).map((region) => `
        <div class="validation-row">
          <span>${escapeHtml(region.label || region.region_id)} · ${escapeHtml(region.selected_candidate_id || "")} / 顶部接触率 ${escapeHtml(region.selected_support_settings?.tree_support_top_rate || "30% 默认")} · ${Number(region.baseline_additional_filament_weight_g || 0).toFixed(2)}→${Number(region.selected_additional_filament_weight_g || 0).toFixed(2)} g · ${Number(region.baseline_additional_time_seconds || 0).toLocaleString()}→${Number(region.selected_additional_time_seconds || 0).toLocaleString()} s · 界面保留 ${(Number(region.selected_interface_coverage_ratio || 0) * 100).toFixed(1)}%</span>
          <b class="${region.passed ? "" : "fail"}">${region.passed ? "LEAN + SAFE" : "REJECTED"}</b>
        </div>
      `).join("")}
    ` : ""}
    <div class="validation-row">
      <span>阈值护栏 · 全局阈值不高于 ${Number(localizedSupportPlan.threshold_guardrail?.maximum_global_threshold_deg || 30).toFixed(0)}°；禁止用 35°/45° 全局支撑替代局部绘制</span>
      <b>≤ 30°</b>
    </div>
  ` : "";
  const openingEconomyRow = openingEconomy.method ? `
    <div class="validation-row">
      <span>主风口镂空 A/B · 实际件 ${Number(openingEconomy.support_free_comparison?.production_weight_g || 0).toFixed(2)} g / ${Math.round(Number(openingEconomy.support_free_comparison?.production_time_seconds || 0) / 60)} min，对照封闭墙 ${Number(openingEconomy.support_free_comparison?.sealed_control_weight_g || 0).toFixed(2)} g / ${Math.round(Number(openingEconomy.support_free_comparison?.sealed_control_time_seconds || 0) / 60)} min；镂空净省 ${Number(openingEconomy.support_free_comparison?.material_saved_g || 0).toFixed(2)} g / ${Math.round(Number(openingEconomy.support_free_comparison?.time_saved_seconds || 0) / 60)} min。若误开自动支撑，材料净优势 ${Number(openingEconomy.if_auto_support_is_enabled?.net_material_advantage_vs_sealed_g || 0).toFixed(2)} g。</span>
      <b class="${openingEconomy.passed ? "" : "fail"}">${openingEconomy.passed ? "VOID EARNS ITS KEEP" : "REDESIGN VOID"}</b>
    </div>
  ` : "";
  const openingLabels = {
    main_air_portals: "四面主风口",
    controller_air_and_service_arches: "控制仓通风 / 维护拱口",
    controller_usb_service_arch: "USB 维护拱口",
    cradle_central_airway: "托架中央贯通风道",
    rear_connector_service_relief: "后部接口圆角让位",
  };
  const openingDescriptions = {
    main_air_portals: {
      purpose: "风扇侧向进排气",
      evidence: "实际风口 / 封闭墙双切片 + 正式件免支撑切片",
    },
    controller_air_and_service_arches: {
      purpose: "控制仓横向通风、走线和卡扣释放",
      evidence: "OpenCascade 开口几何 + 完整机架免支撑切片",
    },
    controller_usb_service_arch: {
      purpose: "USB 插拔与控制板维护",
      evidence: "OpenCascade 插头通道 + 完整机架免支撑切片",
    },
    cradle_central_airway: {
      purpose: "Mac mini 底部贯通进风",
      evidence: "OpenCascade 贯穿孔 + 托架免支撑切片",
    },
    rear_connector_service_relief: {
      purpose: "电源与网口插头让位",
      evidence: "OpenCascade 顶部开放让位 + 托架免支撑切片",
    },
  };
  const openingDecisionRows = (openingEconomy.opening_decisions || [])
    .map((opening) => {
      const description = openingDescriptions[opening.opening_id] || {};
      return `
      <div class="validation-row">
        <span>${escapeHtml(openingLabels[opening.opening_id] || opening.opening_id)} × ${Number(opening.count || 0)} · ${escapeHtml(description.purpose || opening.purpose || "")} · 最大桥接 ${Number(opening.maximum_bridge_span_mm || 0).toFixed(1)} mm · 最小顶面斜率 ${Number(opening.minimum_roof_slope_deg || 0).toFixed(1)}° · ${escapeHtml(description.evidence || opening.evidence || "")}</span>
        <b class="${opening.accepted && !opening.support_required ? "" : "fail"}">${opening.accepted && !opening.support_required ? "FUNCTIONAL · NO SUPPORT" : "REDESIGN"}</b>
      </div>
    `;
    }).join("");
  elements.manufacturingList.innerHTML = parts.map((part) => `
    <div class="validation-row">
      <span>${escapeHtml(part.part)} · ${part.layers} 层 · ${Math.round(part.estimated_seconds / 60)} min · ${Number(part.filament_weight_g).toFixed(1)} g · 最大桥接 ${Number(part.max_bridge_span_mm).toFixed(1)} mm</span>
      <b class="${part.printable ? "" : "fail"}">${part.support_used ? "SUPPORT" : "NO SUPPORT"}</b>
    </div>
  `).join("") + supportRow + supportPartRows + thresholdRows
    + localizedSupportRows + openingEconomyRow + openingDecisionRows;
}

function renderCalibration(calibration) {
  elements.calibrationSection.hidden = !calibration;
  if (!calibration) return;
  const parts = Object.entries(calibration.parts || {});
  const totals = calibration.manufacturing?.totals || {};
  elements.calibrationSummary.textContent = calibration.passed
    ? `${parts.length}/${parts.length} · ${Number(totals.filament_weight_g || 0).toFixed(1)} G`
    : "FIT CHECK REQUIRED";
  elements.calibrationSequence.innerHTML = `
    <b>建议顺序</b><br>
    ${(calibration.recommended_sequence || [])
      .map((step, index) => `${index + 1}. ${escapeHtml(step)}`)
      .join("<br>")}
  `;
  elements.calibrationList.innerHTML = parts.map(([name, part]) => {
    const slice = calibration.manufacturing?.parts?.[name] || {};
    const print = slice.estimated_seconds
      ? ` · ${Math.round(Number(slice.estimated_seconds) / 60)} min · ${Number(slice.filament_weight_g || 0).toFixed(1)} g`
      : "";
    return `
      <div class="validation-row">
        <span>${escapeHtml(part.display_name || name)} · ${escapeHtml(part.calibration_kind)}${print}<br><small>${escapeHtml(part.test_method)}</small></span>
        <b>${slice.support_used ? "SUPPORT" : "NO SUPPORT"}</b>
      </div>
    `;
  }).join("");
  elements.calibratedTolerance.value = elements.tolerance.value;
  elements.calibratedCornerRadius.value =
    parameterInput("mac_corner_radius_mm")?.value || "9";
  elements.calibratedFanSpacing.value =
    parameterInput("fan_mount_spacing_mm")?.value || "105";
  elements.calibratedFanHole.value =
    parameterInput("fan_mount_hole_diameter_mm")?.value || "4.6";
  elements.calibratedProbeDiameter.value =
    parameterInput("ds18b20_probe_diameter_mm")?.value || "6";
  elements.calibratedProbeInterference.value =
    parameterInput("ds18b20_snap_interference_per_side_mm")?.value || "0.1";
  elements.buttonDeltaX.value = "0";
  elements.buttonDeltaY.value = "0";
  elements.frontInterfaceDeltaX.value = "0";
  elements.frontInterfaceDeltaZ.value = "0";
  elements.rearInterfaceDeltaX.value = "0";
  elements.rearInterfaceDeltaZ.value = "0";
  elements.calibrationFeedbackStatus.textContent =
    "先打印桥接试片；两个拱冠均不超过 0.5 mm 且无分层，才建议打印完整机架。";
}

function applyCalibrationFeedback() {
  const bridgeResult = elements.bridgeCouponResult.value;
  const mainBridgeSag = Number(elements.calibratedMainBridgeSag.value);
  const usbBridgeSag = Number(elements.calibratedUsbBridgeSag.value);
  if (
    bridgeResult !== "not_tested"
    && (
      elements.calibratedMainBridgeSag.value === ""
      || elements.calibratedUsbBridgeSag.value === ""
      || !Number.isFinite(mainBridgeSag)
      || !Number.isFinite(usbBridgeSag)
    )
  ) {
    elements.calibrationFeedbackStatus.textContent =
      "请填写两个拱冠的实测下垂值，再保存桥接结论。";
    return;
  }
  if (
    bridgeResult === "passed"
    && (mainBridgeSag > 0.5 || usbBridgeSag > 0.5)
  ) {
    elements.calibrationFeedbackStatus.textContent =
      "实测下垂超过 0.5 mm，不能标记通过；请选择失败并先调桥接参数或添加局部支撑。";
    return;
  }
  const updates = [
    [elements.tolerance, Number(elements.calibratedTolerance.value)],
    [
      parameterInput("mac_corner_radius_mm"),
      Number(elements.calibratedCornerRadius.value),
    ],
    [
      parameterInput("fan_mount_spacing_mm"),
      Number(elements.calibratedFanSpacing.value),
    ],
    [
      parameterInput("fan_mount_hole_diameter_mm"),
      Number(elements.calibratedFanHole.value),
    ],
    [
      parameterInput("ds18b20_probe_diameter_mm"),
      Number(elements.calibratedProbeDiameter.value),
    ],
    [
      parameterInput("ds18b20_snap_interference_per_side_mm"),
      Number(elements.calibratedProbeInterference.value),
    ],
  ];
  const buttonX = parameterInput("power_button_x_mm");
  const buttonY = parameterInput("power_button_y_mm");
  const frontInterfaceX = parameterInput(
    "front_interface_delta_x_mm",
  );
  const frontInterfaceZ = parameterInput(
    "front_interface_delta_z_mm",
  );
  const rearInterfaceX = parameterInput(
    "rear_interface_delta_x_mm",
  );
  const rearInterfaceZ = parameterInput(
    "rear_interface_delta_z_mm",
  );
  updates.push(
    [
      buttonX,
      Number(buttonX.value) + Number(elements.buttonDeltaX.value),
    ],
    [
      buttonY,
      Number(buttonY.value) + Number(elements.buttonDeltaY.value),
    ],
    [
      frontInterfaceX,
      Number(frontInterfaceX.value)
        + Number(elements.frontInterfaceDeltaX.value),
    ],
    [
      frontInterfaceZ,
      Number(frontInterfaceZ.value)
        + Number(elements.frontInterfaceDeltaZ.value),
    ],
    [
      rearInterfaceX,
      Number(rearInterfaceX.value)
        + Number(elements.rearInterfaceDeltaX.value),
    ],
    [
      rearInterfaceZ,
      Number(rearInterfaceZ.value)
        + Number(elements.rearInterfaceDeltaZ.value),
    ],
  );
  if (updates.some(([input, value]) => !input || !Number.isFinite(value))) {
    elements.calibrationFeedbackStatus.textContent = "校准值无效，未应用。";
    return;
  }
  updates.forEach(([input, value]) => {
    input.value = String(Number(value.toFixed(3)));
    markParameterSource(input, "calibration_coupon");
  });
  elements.buttonDeltaX.value = "0";
  elements.buttonDeltaY.value = "0";
  elements.frontInterfaceDeltaX.value = "0";
  elements.frontInterfaceDeltaZ.value = "0";
  elements.rearInterfaceDeltaX.value = "0";
  elements.rearInterfaceDeltaZ.value = "0";
  saveLocalProfile("校准结果已应用并保存");
  elements.calibrationFeedbackStatus.textContent = bridgeResult === "passed"
    ? "配合参数已回填；桥接试片通过，可按同一 PETG/层高/桥接设置打印完整机架。"
    : bridgeResult === "failed"
      ? "结果已保存；暂缓打印完整机架，先调整桥接流量、速度、冷却，或只在失败拱冠下添加局部支撑。"
      : "配合参数已回填，但桥接试片尚未验证；打印完整机架前仍需完成该步骤。";
  document.querySelector(".engineering-fields").scrollIntoView({
    behavior: "smooth",
    block: "start",
  });
}

function renderAirflow(airflow) {
  elements.airflowSection.hidden = !airflow;
  if (!airflow) return;
  const point = airflow.operating_point || {};
  const checks = Object.entries(airflow.checks || {});
  const sources = airflow.inputs?.sources || {};
  const defaultCount = Object.values(sources).filter(
    (source) => source === "conservative_default",
  ).length;
  elements.airflowSummary.textContent = airflow.passed
    ? `${Number(point.effective_airflow_cfm).toFixed(1)} CFM · ΔT ${Number(point.bulk_air_temperature_rise_c).toFixed(1)} °C`
    : "PHYSICAL CHECK REQUIRED";
  const metrics = [
    ["有效风量", `${Number(point.effective_airflow_cfm).toFixed(1)} CFM`],
    ["估算压降", `${Number(point.estimated_pressure_drop_pa).toFixed(1)} Pa`],
    ["喉部流速", `${Number(point.throat_velocity_m_s).toFixed(2)} m/s`],
    ["热能力", `${Number(point.thermal_capacity_at_allowed_rise_w).toFixed(0)} W`],
  ];
  elements.airflowMetrics.innerHTML = metrics.map(([label, value]) => `
    <div class="metric"><span>${label}</span><b>${escapeHtml(value)}</b></div>
  `).join("");
  elements.airflowNote.innerHTML = `
    <b>${escapeHtml(airflow.confidence)}</b><br>
    ${defaultCount
      ? `${defaultCount} 项采用保守默认值；打印前请用所选风扇数据表覆盖。`
      : "全部风扇与热负载输入来自本次用户设置。"}
    该模型估算整体空气温升，不代表芯片结温，也不能替代实机测试。
  `;
  elements.airflowChecks.innerHTML = checks.map(([name, check]) => `
    <div class="validation-row">
      <span>${escapeHtml(name.replaceAll("_", " "))}</span>
      <b class="${check.passed ? "" : "fail"}">${check.passed ? "PASSED" : "CHECK"}</b>
    </div>
  `).join("");
}

function renderStructure(structure) {
  elements.structureSection.hidden = !structure;
  if (!structure) return;
  const checks = structure.checks || {};
  const pressure = checks.four_point_contact_pressure || {};
  const deflection = checks.annular_shelf_deflection || {};
  const strength = checks.petg_bending_strength || {};
  const tipping = checks.whole_assembly_tipping || {};
  elements.structureSummary.textContent = structure.passed
    ? "3g LOAD PATH PASSED"
    : "PHYSICAL CHECK REQUIRED";
  const metrics = [
    ["每点 3g 载荷", `${Number(structure.load_path?.force_per_pad_at_3g_n || 0).toFixed(2)} N`],
    ["接触压强", `${Number(pressure["3g_pressure_mpa"] || 0).toFixed(3)} MPa`],
    ["组合位移", `${Number(deflection.combined_worst_displacement_mm || 0).toFixed(3)} mm`],
    ["倾覆安全系数", Number(tipping.safety_factor || 0).toFixed(2)],
  ];
  elements.structureMetrics.innerHTML = metrics.map(([label, value]) => `
    <div class="metric"><span>${label}</span><b>${escapeHtml(value)}</b></div>
  `).join("");
  elements.structureNote.innerHTML = `
    <b>${escapeHtml(structure.confidence || "")}</b><br>
    设计质量 ${Number(structure.inputs?.mac_design_mass_kg || 0).toFixed(2)} kg
    （${escapeHtml(structure.inputs?.mac_design_mass_source || "unknown")}）；
    PETG 弯曲安全系数 ${Number(strength.safety_factor || 0).toFixed(2)}。
    这是打印前解析筛查，不代替实体 PETG 挠度、摇晃和风扇振动测试。
  `;
  elements.structureChecks.innerHTML = Object.entries(checks).map(
    ([name, check]) => `
      <div class="validation-row">
        <span>${escapeHtml(name.replaceAll("_", " "))}</span>
        <b class="${check.passed ? "" : "fail"}">${check.passed ? "PASSED" : "CHECK"}</b>
      </div>
    `,
  ).join("");
}

function renderFiles(downloads, runId) {
  elements.filesSection.hidden = false;
  elements.runId.textContent = runId || "EXPORT";
  elements.filesList.innerHTML = (downloads || []).map((file) => {
    const extension = file.name.split(".").pop().toUpperCase();
    return `
      <a class="file-row" href="${encodeURI(file.url)}" download>
        <span>${escapeHtml(file.name)}</span>
        <span class="file-type">${escapeHtml(extension)} ↓</span>
      </a>`;
  }).join("");
}

function renderModels(downloads, preview) {
  const stlFiles = (downloads || []).filter((file) =>
    file.name.toLowerCase().endsWith(".stl")
  );
  const urls = Object.fromEntries(stlFiles.map((file) => [file.name, file.url]));
  const scenes = [];
  const serviceAccessItems = (preview?.service_access?.items || []).map(
    (item) => ({ ...item }),
  );
  const macInterfaceItems = (
    preview?.mac_interface_access?.items || []
  ).map((item) => ({ ...item }));
  if (preview?.assembly?.items?.length) {
    const assemblyItems = preview.assembly.items.map((item) => ({
      ...item,
      url: item.primitive ? undefined : urls[item.file_name],
    }));
    const printableItems = assemblyItems.filter((item) => !item.is_reference);
    const deviceReferences = assemblyItems.filter(
      (item) => item.reference_kind === "device",
    );
    const hardwareReferences = assemblyItems.filter(
      (item) => item.reference_kind === "internal_hardware",
    );
    const serviceReferences = assemblyItems.filter(
      (item) => item.reference_kind === "service_hardware",
    );
    const contactReferences = assemblyItems.filter(
      (item) => item.reference_kind === "contact_hardware",
    );
    if (assemblyItems.length) {
      scenes.push({
        label: "完整安装装配",
        items: assemblyItems,
      });
    }
    if (deviceReferences.length) {
      scenes.push({
        label: "Mac mini 安装状态",
        items: [...printableItems, ...deviceReferences],
      });
    }
    if (deviceReferences.length && macInterfaceItems.length) {
      const cradle = printableItems.find(
        (item) => item.name === "mac_mini_cradle",
      );
      scenes.push({
        label: "Mac 前后接口净空",
        notes: preview?.mac_interface_access?.notes || [],
        items: [
          ...(cradle ? [{
            ...cradle,
            color_rgb: [0.45, 0.35, 0.88],
            opacity: 0.32,
          }] : []),
          ...deviceReferences.map((item) => ({
            ...item,
            opacity: 0.12,
          })),
          ...macInterfaceItems,
        ],
      });
    }
    if (deviceReferences.length && contactReferences.length) {
      const cradle = printableItems.find(
        (item) => item.name === "mac_mini_cradle",
      );
      scenes.push({
        label: "Mac 接触与底脚净空",
        items: [
          ...(cradle ? [{
            ...cradle,
            color_rgb: [0.45, 0.35, 0.88],
            opacity: 0.24,
          }] : []),
          ...deviceReferences.map((item) => ({
            ...item,
            opacity: 0.12,
          })),
          ...contactReferences.map((item) => ({
            ...item,
            color_rgb: [1.0, 0.34, 0.12],
            opacity: 1,
          })),
        ],
      });
    }
    const structuralItems = (preview?.structural_load_path?.items || []).map(
      (item) => ({ ...item }),
    );
    if (deviceReferences.length && structuralItems.length) {
      scenes.push({
        label: "整机载荷路径",
        notes: preview.structural_load_path.notes || [],
        items: [
          ...printableItems.map((item) => ({
            ...item,
            opacity: item.name === "mac_mini_cradle" ? 0.42 : 0.12,
          })),
          ...deviceReferences.map((item) => ({
            ...item,
            opacity: 0.1,
          })),
          ...contactReferences.map((item) => ({
            ...item,
            color_rgb: [1.0, 0.82, 0.1],
            opacity: 1,
          })),
          ...structuralItems,
        ],
      });
    }
    const powerButtonMechanism = assemblyItems.filter((item) =>
      [
        "fan_chassis",
        "mac_mini_cradle",
        "power_button_plunger",
      ].includes(item.name)
      || item.reference_kind === "device"
    );
    if (
      powerButtonMechanism.some(
        (item) => item.name === "power_button_plunger",
      )
    ) {
      scenes.push({
        label: "电源键机构",
        items: powerButtonMechanism.map((item) => {
          if (item.name === "power_button_plunger") {
            return {
              ...item,
              color_rgb: [0.78, 1.0, 0.24],
              opacity: 1,
            };
          }
          return {
            ...item,
            opacity: item.reference_kind === "device" ? 0.12 : 0.2,
          };
        }),
      });
    }
    const fanRetentionMechanism = assemblyItems.filter((item) =>
      item.name === "fan_chassis"
      || item.name === "120 mm PWM fan"
    );
    if (
      fanRetentionMechanism.some(
        (item) => item.name === "120 mm PWM fan",
      )
    ) {
      scenes.push({
        label: "风扇柔性卡扣",
        items: fanRetentionMechanism.map((item) => {
          if (item.name === "fan_chassis") {
            return {
              ...item,
              color_rgb: [0.42, 0.68, 0.96],
              opacity: 0.62,
            };
          }
          return {
            ...item,
            opacity: 0.16,
          };
        }),
      });
    }
    const fanIsolationMechanism = assemblyItems.filter((item) =>
      ["fan_chassis", "fan_guard", "120 mm PWM fan"].includes(item.name)
      || item.reference_kind === "service_hardware"
    );
    if (serviceReferences.length) {
      scenes.push({
        label: "风扇隔振堆叠",
        items: fanIsolationMechanism.map((item) => {
          if (item.reference_kind === "service_hardware") {
            return {
              ...item,
              color_rgb: [0.18, 1.0, 0.92],
              opacity: 1,
            };
          }
          return {
            ...item,
            opacity: item.name === "120 mm PWM fan" ? 0.12 : 0.18,
          };
        }),
      });
    }
    if (hardwareReferences.length) {
      scenes.push({
        label: "内部硬件布置",
        items: [
          ...printableItems.filter((item) => item.name === "fan_chassis"),
          ...hardwareReferences,
        ],
      });
      const carrierNames = new Set([
        "12V DC-DC module",
        "5V DC-DC module",
        "ESP32-C3 Super Mini",
        "MOSFET PWM driver",
      ]);
      const carrierHardware = hardwareReferences.filter(
        (item) => carrierNames.has(item.name),
      );
      const carrierCover = printableItems.find(
        (item) => item.name === "controller_cover",
      );
      const probeHardware = hardwareReferences.find(
        (item) => item.name.startsWith("DS18B20"),
      );
      if (carrierCover && probeHardware) {
        scenes.push({
          label: "DS18B20 探头卡座",
          service_sequence: preview?.service_access?.sequence || [],
          items: [
            {
              ...carrierCover,
              color_rgb: [0.78, 1.0, 0.24],
              opacity: 0.2,
            },
            {
              ...probeHardware,
              color_rgb: [1.0, 0.48, 0.12],
              opacity: 1,
            },
          ],
        });
      }
      if (carrierCover && carrierHardware.length === 4) {
        scenes.push({
          label: "电子仓载架装配",
          service_sequence: preview?.service_access?.sequence || [],
          items: [
            {
              ...carrierCover,
              color_rgb: [0.78, 1.0, 0.24],
              opacity: 0.46,
            },
            ...carrierHardware.map((item) => ({
              ...item,
              opacity: 0.82,
            })),
          ],
        });
        if (serviceAccessItems.length) {
          scenes.push({
            label: "电子仓维护通道",
            service_sequence: preview?.service_access?.sequence || [],
            items: [
              {
                ...carrierCover,
                color_rgb: [0.78, 1.0, 0.24],
                opacity: 0.16,
              },
              ...carrierHardware.map((item) => ({
                ...item,
                opacity: 0.16,
              })),
              ...serviceAccessItems,
            ],
          });
        }
      }
    }
    scenes.push({
      label: "完整装配（打印件）",
      items: printableItems,
    });
    if (assemblyItems.length > 1) {
      scenes.push({
        label: "完整爆炸装配",
        items: assemblyItems.map((item) => ({
          ...item,
          translation_mm: [
            Number(item.translation_mm?.[0] || 0),
            Number(item.translation_mm?.[1] || 0),
            Number(item.translation_mm?.[2] || 0)
              + (
                item.name === "controller_cover"
                  ? -25
                  : item.name === "fan_guard"
                    ? 40
                    : item.name === "mac_mini_cradle"
                      ? 60
                      : item.reference_kind === "device"
                        ? 80
                        : item.name === "120 mm PWM fan"
                          ? 50
                          : item.reference_kind === "internal_hardware"
                            ? -15
                      : 0
              ),
          ],
        })),
      });
    }
  }
  if (preview?.print_layout?.items?.length) {
    const printLayoutItems = preview.print_layout.items.map((item) => ({
      ...item,
      url: item.primitive ? undefined : urls[item.file_name],
    }));
    const xyHotspotItems = printLayoutItems.filter(
      (item) => item.reference_kind === "auto_support_xy_tile",
    );
    const xyzContactItems = printLayoutItems.filter(
      (item) => item.reference_kind === "auto_support_xyz_cell",
    );
    scenes.push({
      label: "打印方向与自动支撑包络",
      notes: preview.print_layout.notes || [],
      items: printLayoutItems.filter(
        (item) => ![
          "auto_support_xy_tile",
          "auto_support_xyz_cell",
        ].includes(item.reference_kind),
      ),
    });
    if (xyHotspotItems.length) {
      scenes.push({
        label: "支撑 XY 热点地图",
        notes: [
          "彩色方格是 20 × 20 mm 的支撑路径投影，不是生产零件。",
          "颜色越红表示路径越密；列表同时显示支撑路径和接触层数量。",
          "热图用于把切片成本映射回具体卡扣、风口、承台或墙体。",
        ],
        items: [
          ...printLayoutItems.filter((item) => !item.is_reference),
          ...xyHotspotItems,
        ],
      });
    }
    if (xyzContactItems.length) {
      scenes.push({
        label: "支撑 XYZ 接触热点",
        notes: [
          "体素尺寸为 10 × 10 × 5 mm，位置对应真实生产方向。",
          "只显示含支撑接触层的体素；红色越深表示接触路径越多。",
          "打印件以半透明显示，用于定位会粘附 PETG 支撑的具体高度和结构。",
        ],
        items: [
          ...printLayoutItems
            .filter((item) => !item.is_reference)
            .map((item) => ({ ...item, opacity: 0.18 })),
          ...xyzContactItems,
        ],
      });
    }
  }
  if (preview?.support_modifiers?.items?.length) {
    const chassisItem = (preview?.assembly?.items || []).find(
      (item) => item.name === "fan_chassis",
    );
    const modifierItems = preview.support_modifiers.items.map((item) => ({
      ...item,
      url: urls[item.file_name],
    }));
    scenes.push({
      label: "局部支撑 Modifier",
      notes: preview.support_modifiers.notes || [],
      items: [
        ...(chassisItem ? [{
          ...chassisItem,
          url: urls[chassisItem.file_name],
          opacity: 0.16,
        }] : []),
        ...modifierItems,
      ],
    });
    for (const modifier of modifierItems) {
      scenes.push({
        label: `支撑区 · ${modifier.display_name || modifier.name}`,
        notes: [
          ...(preview.support_modifiers.notes || []),
          `来源：${Number(modifier.source_cell_count || 0)} 个接触体素、${Number(modifier.source_support_interface_move_count || 0).toLocaleString()} 条支撑接触路径。`,
        ],
        items: [
          ...(chassisItem ? [{
            ...chassisItem,
            url: urls[chassisItem.file_name],
            opacity: 0.12,
          }] : []),
          modifier,
        ],
      });
    }
  }
  if (preview?.manufacturing_controls?.items?.length) {
    const actualChassis = (preview?.assembly?.items || []).find(
      (item) => item.name === "fan_chassis",
    );
    const controls = preview.manufacturing_controls.items.map((item) => ({
      ...item,
      url: urls[item.file_name],
    }));
    scenes.push({
      label: "镂空与封闭墙 A/B",
      notes: preview.manufacturing_controls.notes || [],
      items: [
        ...(actualChassis ? [{
          ...actualChassis,
          name: "fan_chassis · production portals",
          url: urls[actualChassis.file_name],
          color_rgb: [0.18, 0.95, 1.0],
          opacity: 0.9,
        }] : []),
        ...controls,
      ],
    });
  }
  for (const part of preview?.calibration?.items || []) {
    scenes.push({
      label: `校准 · ${part.display_name || part.name}`,
      items: [
        {
          ...part,
          url: urls[part.file_name],
          translation_mm: [0, 0, 0],
          rotation_deg: [0, 0, 0],
          color_rgb: [0.18, 0.95, 1.0],
          opacity: 1,
        },
      ],
    });
  }
  for (const part of preview?.parts || []) {
    scenes.push({
      label: part.name,
      items: [
        {
          ...part,
          url: urls[part.file_name],
          translation_mm: [0, 0, 0],
          rotation_deg: [0, 0, 0],
        },
      ],
    });
  }
  if (!scenes.length) {
    scenes.push(...stlFiles.map((file) => ({
      label: file.name.replace(/\.stl$/i, ""),
      items: [{
        name: file.name,
        url: file.url,
        translation_mm: [0, 0, 0],
        rotation_deg: [0, 0, 0],
      }],
    })));
  }
  const validScenes = scenes.filter((scene) =>
    scene.items.length > 0
      && scene.items.every(
        (item) => item.url
          || ["box", "rounded_box", "fan"].includes(item.primitive),
      )
  );
  elements.previewSection.hidden = validScenes.length === 0;
  elements.modelTabs.innerHTML = "";
  elements.inspectorList.innerHTML = "";
  elements.assemblyInspector.hidden = true;
  if (!validScenes.length || !modelViewer) return;

  const inspectionState = new Map(
    validScenes.map((scene) => [
      scene,
      { hidden: new Set(), highlightIndex: null },
    ]),
  );
  let activeScene = validScenes[0];

  const itemRole = (item) => {
    if (item.reference_kind === "device") return "DEVICE REFERENCE";
    if (item.reference_kind === "internal_hardware") return "HARDWARE REFERENCE";
    if (item.reference_kind === "service_hardware") return "SERVICE HARDWARE";
    if (item.reference_kind === "contact_hardware") return "CONTACT INTERFACE";
    if (item.reference_kind === "desk_contact_hardware") {
      return "DESK CONTACT";
    }
    if (item.reference_kind === "service_access") return "SERVICE ACCESS";
    if (item.reference_kind === "device_interface_access") {
      return "I/O CLEARANCE";
    }
    if (item.reference_kind === "structural_support") {
      return "STRUCTURAL SUPPORT POLYGON";
    }
    if (item.reference_kind === "structural_load") {
      return "3G LOAD PATH";
    }
    if (item.reference_kind === "manufacturing_control") {
      return "SLICE CONTROL · DO NOT PRINT";
    }
    if (item.reference_kind === "support_modifier") {
      return "SLICER MODIFIER · DO NOT PRINT";
    }
    if (item.reference_kind === "auto_support_envelope") {
      return "AUTO SUPPORT ENVELOPE";
    }
    if (item.reference_kind === "auto_support_band") {
      return "AUTO SUPPORT Z-BAND";
    }
    return "PRINTED PART";
  };

  const formattedVector = (values, fallback = "—") => {
    if (!Array.isArray(values) || values.length !== 3) return fallback;
    return values.map((value) => Number(value).toFixed(1)).join(" / ");
  };

  const displayItems = (scene) => {
    const sceneState = inspectionState.get(scene);
    return scene.items
      .map((item, index) => ({ item, index }))
      .filter(({ index }) => !sceneState.hidden.has(index))
      .map(({ item, index }) => {
        if (sceneState.highlightIndex === null) return item;
        if (index === sceneState.highlightIndex) {
          return {
            ...item,
            color_rgb: [0.78, 1.0, 0.24],
            opacity: 1,
          };
        }
        return {
          ...item,
          opacity: Math.min(Number(item.opacity ?? 1), 0.14),
        };
      });
  };

  const loadInspectedScene = async (scene) => {
    elements.modelError.hidden = true;
    try {
      await modelViewer.loadScene({
        ...scene,
        items: displayItems(scene),
      });
    } catch (error) {
      elements.modelError.textContent = error.message;
      elements.modelError.hidden = false;
    }
  };

  const renderInspector = (scene) => {
    const sceneState = inspectionState.get(scene);
    const visibleCount = scene.items.length - sceneState.hidden.size;
    const referenceCount = scene.items.filter((item) => item.is_reference).length;
    elements.assemblyInspector.hidden = false;
    elements.inspectorTitle.textContent = scene.label;
    elements.inspectorSummary.textContent =
      `${visibleCount}/${scene.items.length} 可见 · ${referenceCount} 参考物`;
    const sequence = scene.notes || scene.service_sequence || [];
    elements.serviceSequence.hidden = sequence.length === 0;
    elements.serviceSequence.innerHTML = sequence.map(
      (step) => `<li>${escapeHtml(step)}</li>`,
    ).join("");
    elements.showAllItems.disabled =
      sceneState.hidden.size === 0 && sceneState.highlightIndex === null;
    elements.inspectorList.innerHTML = "";

    scene.items.forEach((item, index) => {
      const row = document.createElement("div");
      row.className = "inspector-row";
      row.classList.toggle("is-reference", Boolean(item.is_reference));
      row.classList.toggle("is-highlighted", sceneState.highlightIndex === index);

      const visibilityLabel = document.createElement("label");
      visibilityLabel.className = "item-visibility";
      const visibility = document.createElement("input");
      visibility.type = "checkbox";
      visibility.checked = !sceneState.hidden.has(index);
      visibility.setAttribute("aria-label", `显示 ${item.name}`);
      const identity = document.createElement("span");
      const printMetrics = item.print_metrics;
      const printMetricsText = printMetrics
        ? `
          <small>
            桥接 ${Number(printMetrics.bridge_regions || 0)} ·
            悬垂 ${Number(printMetrics.overhang_regions || 0)} ·
            最长桥接 ${Number(printMetrics.max_bridge_span_mm || 0).toFixed(1)} mm
          </small>
          <small>
            自动支撑代价 +${Number(
              printMetrics.auto_support_additional_filament_weight_g || 0,
            ).toFixed(2)} g · +${Math.round(Number(
              printMetrics.auto_support_additional_time_seconds || 0,
            ) / 60)} min
          </small>
        `
        : "";
      const modifierMetricsText = item.reference_kind === "support_modifier"
        ? `
          <small>
            ${Number(item.source_cell_count || 0)} 个接触体素 ·
            ${Number(item.source_support_interface_move_count || 0).toLocaleString()} 条接触路径
          </small>
        `
        : "";
      identity.innerHTML = `
        <b>${escapeHtml(item.name)}</b>
        <small>${itemRole(item)}</small>
        ${item.available_after
          ? `<small>阶段：${escapeHtml(item.available_after)}</small>`
          : ""}
        ${printMetricsText}
        ${modifierMetricsText}
      `;
      visibilityLabel.append(visibility, identity);

      const dimensions = document.createElement("code");
      dimensions.textContent =
        `${formattedVector(item.dimensions_mm)} mm`;
      const translation = document.createElement("code");
      translation.textContent =
        `${formattedVector(item.translation_mm, "0.0 / 0.0 / 0.0")} mm`;
      const focus = document.createElement("button");
      focus.type = "button";
      focus.className = "focus-item";
      focus.textContent =
        sceneState.highlightIndex === index ? "取消聚焦" : "聚焦";
      focus.setAttribute("aria-pressed", sceneState.highlightIndex === index);

      visibility.addEventListener("change", async () => {
        if (!visibility.checked && visibleCount === 1) {
          visibility.checked = true;
          return;
        }
        if (visibility.checked) sceneState.hidden.delete(index);
        else sceneState.hidden.add(index);
        if (sceneState.hidden.has(index)
            && sceneState.highlightIndex === index) {
          sceneState.highlightIndex = null;
        }
        renderInspector(scene);
        await loadInspectedScene(scene);
      });
      focus.addEventListener("click", async () => {
        sceneState.hidden.delete(index);
        sceneState.highlightIndex =
          sceneState.highlightIndex === index ? null : index;
        renderInspector(scene);
        await loadInspectedScene(scene);
      });

      row.append(visibilityLabel, dimensions, translation, focus);
      elements.inspectorList.append(row);
    });
  };

  elements.showAllItems.onclick = async () => {
    const sceneState = inspectionState.get(activeScene);
    sceneState.hidden.clear();
    sceneState.highlightIndex = null;
    renderInspector(activeScene);
    await loadInspectedScene(activeScene);
  };

  const selectModel = async (scene, button) => {
    activeScene = scene;
    [...elements.modelTabs.children].forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    renderInspector(scene);
    await loadInspectedScene(scene);
  };

  validScenes.forEach((scene, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = scene.label;
    button.addEventListener("click", () => selectModel(scene, button));
    if (index === 0) button.classList.add("active");
    elements.modelTabs.append(button);
  });
  selectModel(validScenes[0], elements.modelTabs.children[0]);
}

function showResult(result, visionOnly = false) {
  state.busy = false;
  state.jobId = null;
  elements.emptyState.hidden = true;
  elements.progressState.hidden = true;
  elements.resultState.hidden = false;
  elements.runState.textContent = visionOnly ? "识别完成" : "生成完成";
  elements.runState.className = "run-state done";
  elements.cancelJob.hidden = true;
  renderVision(visionOnly ? result : result.vision || state.vision);
  if (!visionOnly) {
    renderProposal(result.proposal);
    renderBom(result.bom);
    renderModels(result.downloads, result.preview);
    renderValidation(
      result.validation,
      result.evidence,
      result.planner,
      result.preview?.visual,
    );
    renderAirflow(result.airflow);
    renderStructure(result.structure);
    renderManufacturing(result.manufacturing, result.evidence);
    renderCalibration(result.calibration);
    renderFiles(result.downloads, result.run_id);
    setWizardStep(4);
  }
  elements.designButton.disabled = false;
  renderPreviews();
}

async function recognize() {
  if (!state.files.length) return;
  setBusy("vision");
  try {
    const result = await api("/api/vision", {
      ...requestPayload(),
      images: await imagePayload(),
    });
    showResult(result, true);
    await analyzeConstraints();
  } catch (error) {
    showError(error);
  }
}

async function design() {
  if (elements.pcbMode.checked) {
    let pcbInput;
    let printConfiguration;
    try {
      pcbInput = JSON.parse(elements.pcbInput.value);
      printConfiguration = elements.printConfiguration.value.trim()
        ? JSON.parse(elements.printConfiguration.value)
        : undefined;
    } catch {
      showError(new Error("PCB 输入和打印配置必须是有效 JSON。"));
      return;
    }
    setBusy("design");
    try {
      const result = await runJob("/api/jobs/pcb", {
        pcb_input: pcbInput,
        print_configuration: printConfiguration,
        slice_manufacturing: elements.sliceManufacturing.checked,
        blender_preview: elements.blenderPreview.checked,
      });
      showResult(result);
    } catch (error) {
      showError(error);
    }
    return;
  }
  if (!elements.request.value.trim()) {
    showError(new Error("请先填写工程需求。"));
    return;
  }
  if (state.files.length && !state.vision) {
    showError(new Error("请先执行“识别资料”，确认组件尺寸后再生成 CAD。"));
    return;
  }
    setBusy("design");
  try {
    const payload = requestPayload();
    if (state.vision) payload.vision_report = state.vision;
    else if (state.files.length) payload.images = await imagePayload();
    const result = await runJob("/api/jobs/design", payload);
    showResult(result);
  } catch (error) {
    showError(error);
  }
}

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function runJob(endpoint, payload) {
  const job = await api(endpoint, payload);
  state.jobId = job.job_id;
  while (true) {
    const response = await fetch(`/api/jobs/${encodeURIComponent(state.jobId)}`);
    const current = await response.json();
    if (!response.ok) throw new Error(current.error || "无法读取任务状态");
    if (current.status === "succeeded") return current.result;
    if (current.status === "cancelled") {
      const error = new Error("任务已取消；不完整产物未标记为成功。");
      error.cancelled = true;
      throw error;
    }
    if (current.status === "failed") throw new Error(current.error || "任务失败");
    elements.runState.textContent = current.status === "queued" ? "排队中" : "运行中";
    await delay(500);
  }
}

async function cancelJob() {
  if (!state.jobId) return;
  try {
    const result = await api(`/api/jobs/${encodeURIComponent(state.jobId)}/cancel`, {});
    elements.runState.textContent = result.status === "cancel_requested" ? "取消待当前步骤结束" : "任务已取消";
  } catch (error) {
    showError(error);
  }
}

async function checkStatus() {
  try {
    const response = await fetch("/api/status");
    const status = await response.json();
    const codex = status.codex;
    elements.statusDot.className = `status-dot ${codex.available ? "" : "offline"}`;
    elements.statusText.textContent = codex.available
      ? `${codex.version} · 已认证`
      : "本地 Codex 不可用";
  } catch {
    elements.statusDot.className = "status-dot offline";
    elements.statusText.textContent = "GUI 后端不可用";
  }
}

elements.dropzone.addEventListener("click", () => elements.fileInput.click());
elements.fileInput.addEventListener("change", (event) => addFiles(event.target.files));
["dragenter", "dragover"].forEach((name) => {
  elements.dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    elements.dropzone.classList.add("dragging");
  });
});
["dragleave", "drop"].forEach((name) => {
  elements.dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    elements.dropzone.classList.remove("dragging");
  });
});
elements.dropzone.addEventListener("drop", (event) => addFiles(event.dataTransfer.files));
elements.planner.addEventListener("change", () => {
  if (elements.planner.value === "rules") state.vision = null;
  renderPreviews();
});
elements.pcbMode.addEventListener("change", () => {
  elements.pcbFields.hidden = !elements.pcbMode.checked;
  elements.request.disabled = elements.pcbMode.checked;
  elements.visionButton.disabled = elements.pcbMode.checked || !state.files.length;
});
elements.visionButton.addEventListener("click", recognize);
elements.designButton.addEventListener("click", design);
elements.cancelJob.addEventListener("click", () => void cancelJob());
elements.analyzeConstraints.addEventListener("click", analyzeConstraints);
elements.loadDemo.addEventListener("click", loadSmartFanDemo);
document.querySelectorAll("[data-engineering-parameter]").forEach((input) => {
  input.addEventListener("change", () => {
    input.dataset.source = "user_supplied";
    input.classList.add("confirmed");
  });
});
document.querySelectorAll("[data-manufacturing-parameter]").forEach((input) => {
  input.addEventListener("change", () => {
    markParameterSource(input, "user_supplied");
  });
});
elements.saveProfile.addEventListener("click", () => saveLocalProfile());
elements.loadProfile.addEventListener("click", loadLocalProfile);
elements.applyCalibration.addEventListener("click", applyCalibrationFeedback);
elements.resetView.addEventListener(
  "click",
  () => modelViewer?.setView("isometric"),
);
elements.topView.addEventListener(
  "click",
  () => modelViewer?.setView("top"),
);
elements.bottomView.addEventListener(
  "click",
  () => modelViewer?.setView("bottom"),
);
elements.frontView.addEventListener(
  "click",
  () => modelViewer?.setView("front"),
);
elements.rearView.addEventListener(
  "click",
  () => modelViewer?.setView("rear"),
);
elements.leftView.addEventListener(
  "click",
  () => modelViewer?.setView("left"),
);
elements.rightView.addEventListener(
  "click",
  () => modelViewer?.setView("right"),
);

elements.modelTabs.addEventListener("wheel", (event) => {
  const canScroll = elements.modelTabs.scrollWidth > elements.modelTabs.clientWidth;
  if (!canScroll || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return;
  elements.modelTabs.scrollLeft += event.deltaY;
  event.preventDefault();
}, { passive: false });
elements.modelTabs.addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const edge = event.key === "Home" ? 0 : elements.modelTabs.scrollWidth;
  const delta = event.key === "ArrowLeft" ? -180 : 180;
  elements.modelTabs.scrollTo({
    left: ["Home", "End"].includes(event.key)
      ? edge
      : elements.modelTabs.scrollLeft + delta,
    behavior: "smooth",
  });
  event.preventDefault();
});

renderPreviews();
checkStatus();
