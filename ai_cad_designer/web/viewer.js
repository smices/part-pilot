class STLViewer {
  constructor(canvas, { onStatus, onDimensions } = {}) {
    this.canvas = canvas;
    this.onStatus = onStatus || (() => {});
    this.onDimensions = onDimensions || (() => {});
    this.gl = canvas.getContext("webgl", { antialias: true, alpha: true });
    this.yaw = -0.65;
    this.pitch = -0.65;
    this.zoom = 0.72;
    this.vertexCount = 0;
    this.drag = null;
    this.loadToken = 0;
    if (!this.gl) throw new Error("当前浏览器不支持 WebGL");
    this.program = this.createProgram();
    this.buffer = this.gl.createBuffer();
    this.locations = {
      position: this.gl.getAttribLocation(this.program, "aPosition"),
      normal: this.gl.getAttribLocation(this.program, "aNormal"),
      color: this.gl.getAttribLocation(this.program, "aColor"),
      yaw: this.gl.getUniformLocation(this.program, "uYaw"),
      pitch: this.gl.getUniformLocation(this.program, "uPitch"),
      zoom: this.gl.getUniformLocation(this.program, "uZoom"),
      aspect: this.gl.getUniformLocation(this.program, "uAspect"),
    };
    this.bindInteraction();
    new ResizeObserver(() => this.draw()).observe(canvas);
  }

  shader(type, source) {
    const shader = this.gl.createShader(type);
    this.gl.shaderSource(shader, source);
    this.gl.compileShader(shader);
    if (!this.gl.getShaderParameter(shader, this.gl.COMPILE_STATUS)) {
      throw new Error(this.gl.getShaderInfoLog(shader) || "WebGL shader error");
    }
    return shader;
  }

  createProgram() {
    const vertex = this.shader(this.gl.VERTEX_SHADER, `
      attribute vec3 aPosition;
      attribute vec3 aNormal;
      attribute vec4 aColor;
      uniform float uYaw;
      uniform float uPitch;
      uniform float uZoom;
      uniform float uAspect;
      varying float vLight;
      varying vec4 vColor;
      void main() {
        float cy = cos(uYaw);
        float sy = sin(uYaw);
        float cp = cos(uPitch);
        float sp = sin(uPitch);
        // CAD data is Z-up: orbit around Z, then tilt around X for a
        // conventional engineering isometric view.
        mat3 rz = mat3(cy, sy, 0.0, -sy, cy, 0.0, 0.0, 0.0, 1.0);
        mat3 rx = mat3(1.0, 0.0, 0.0, 0.0, cp, sp, 0.0, -sp, cp);
        vec3 position = rx * rz * aPosition;
        vec3 normal = normalize(rx * rz * aNormal);
        vec3 light = normalize(vec3(0.35, 0.7, 1.0));
        vLight = 0.22 + 0.78 * max(dot(normal, light), 0.0);
        vColor = aColor;
        gl_Position = vec4(
          position.x * uZoom / uAspect,
          position.y * uZoom,
          -position.z * 0.18,
          1.0
        );
      }
    `);
    const fragment = this.shader(this.gl.FRAGMENT_SHADER, `
      precision mediump float;
      varying float vLight;
      varying vec4 vColor;
      void main() {
        gl_FragColor = vec4(vColor.rgb * vLight, vColor.a);
      }
    `);
    const program = this.gl.createProgram();
    this.gl.attachShader(program, vertex);
    this.gl.attachShader(program, fragment);
    this.gl.linkProgram(program);
    if (!this.gl.getProgramParameter(program, this.gl.LINK_STATUS)) {
      throw new Error(this.gl.getProgramInfoLog(program) || "WebGL link error");
    }
    return program;
  }

  bindInteraction() {
    this.canvas.addEventListener("pointerdown", (event) => {
      this.drag = { x: event.clientX, y: event.clientY };
      this.canvas.setPointerCapture(event.pointerId);
    });
    this.canvas.addEventListener("pointermove", (event) => {
      if (!this.drag) return;
      this.yaw += (event.clientX - this.drag.x) * 0.012;
      this.pitch = Math.max(
        -1.45,
        Math.min(1.45, this.pitch + (event.clientY - this.drag.y) * 0.012),
      );
      this.drag = { x: event.clientX, y: event.clientY };
      this.draw();
    });
    this.canvas.addEventListener("pointerup", () => { this.drag = null; });
    this.canvas.addEventListener("pointercancel", () => { this.drag = null; });
    this.canvas.addEventListener("wheel", (event) => {
      event.preventDefault();
      this.zoom = Math.max(
        0.25,
        Math.min(1.8, this.zoom * Math.exp(-event.deltaY * 0.001)),
      );
      this.draw();
    }, { passive: false });
  }

  reset() {
    this.yaw = -0.65;
    this.pitch = -0.65;
    this.zoom = 0.72;
    this.draw();
  }

  setView(view) {
    const presets = {
      isometric: [-0.65, -0.65, 0.72],
      top: [0, 0, 0.72],
      bottom: [0, Math.PI, 0.72],
      // A negative quarter turn maps CAD +Z to screen +Y. Using a
      // positive quarter turn visually inverts the assembly and makes
      // installed devices appear below their supports.
      front: [0, -Math.PI / 2, 0.72],
      rear: [Math.PI, -Math.PI / 2, 0.72],
      left: [-Math.PI / 2, -Math.PI / 2, 0.72],
      right: [Math.PI / 2, -Math.PI / 2, 0.72],
    };
    const preset = presets[view];
    if (!preset) throw new Error(`未知工程视角: ${view}`);
    [this.yaw, this.pitch, this.zoom] = preset;
    this.draw();
  }

  parse(buffer) {
    const view = new DataView(buffer);
    const count = buffer.byteLength >= 84 ? view.getUint32(80, true) : 0;
    const binary = 84 + count * 50 === buffer.byteLength;
    const positions = [];
    const normals = [];
    if (binary) {
      let offset = 84;
      for (let triangle = 0; triangle < count; triangle += 1) {
        const normal = [
          view.getFloat32(offset, true),
          view.getFloat32(offset + 4, true),
          view.getFloat32(offset + 8, true),
        ];
        offset += 12;
        for (let vertex = 0; vertex < 3; vertex += 1) {
          positions.push(
            view.getFloat32(offset, true),
            view.getFloat32(offset + 4, true),
            view.getFloat32(offset + 8, true),
          );
          normals.push(...normal);
          offset += 12;
        }
        offset += 2;
      }
    } else {
      const text = new TextDecoder().decode(buffer);
      const pattern = /vertex\s+([-+\deE.]+)\s+([-+\deE.]+)\s+([-+\deE.]+)/g;
      let match;
      while ((match = pattern.exec(text)) !== null) {
        positions.push(Number(match[1]), Number(match[2]), Number(match[3]));
      }
      if (!positions.length || positions.length % 9 !== 0) {
        throw new Error("无法解析 STL 网格");
      }
      this.computeNormals(positions, normals);
    }
    return { positions, normals, triangleCount: positions.length / 9 };
  }

  computeNormals(positions, normals) {
    for (let index = 0; index < positions.length; index += 9) {
      const ax = positions[index + 3] - positions[index];
      const ay = positions[index + 4] - positions[index + 1];
      const az = positions[index + 5] - positions[index + 2];
      const bx = positions[index + 6] - positions[index];
      const by = positions[index + 7] - positions[index + 1];
      const bz = positions[index + 8] - positions[index + 2];
      const nx = ay * bz - az * by;
      const ny = az * bx - ax * bz;
      const nz = ax * by - ay * bx;
      const length = Math.hypot(nx, ny, nz) || 1;
      for (let vertex = 0; vertex < 3; vertex += 1) {
        normals.push(nx / length, ny / length, nz / length);
      }
    }
  }

  boxMesh(dimensions) {
    const [length, width, height] = dimensions.map(Number);
    const x = length / 2;
    const y = width / 2;
    const vertices = [
      [-x, -y, 0], [x, -y, 0], [x, y, 0], [-x, y, 0],
      [-x, -y, height], [x, -y, height], [x, y, height], [-x, y, height],
    ];
    const faces = [
      [0, 2, 1], [0, 3, 2],
      [4, 5, 6], [4, 6, 7],
      [0, 1, 5], [0, 5, 4],
      [1, 2, 6], [1, 6, 5],
      [2, 3, 7], [2, 7, 6],
      [3, 0, 4], [3, 4, 7],
    ];
    const positions = faces.flatMap((face) =>
      face.flatMap((vertexIndex) => vertices[vertexIndex])
    );
    const normals = [];
    this.computeNormals(positions, normals);
    return { positions, normals, triangleCount: faces.length };
  }

  roundedBoxMesh(dimensions, radius = 9, cornerSegments = 6) {
    const [length, width, height] = dimensions.map(Number);
    const x = length / 2;
    const y = width / 2;
    const usableRadius = Math.min(Number(radius), x - 0.1, y - 0.1);
    const outline = [];
    const corners = [
      [x - usableRadius, -y + usableRadius, -Math.PI / 2],
      [x - usableRadius, y - usableRadius, 0],
      [-x + usableRadius, y - usableRadius, Math.PI / 2],
      [-x + usableRadius, -y + usableRadius, Math.PI],
    ];
    corners.forEach(([centerX, centerY, startAngle]) => {
      for (let segment = 0; segment <= cornerSegments; segment += 1) {
        const angle = startAngle + segment * (Math.PI / 2 / cornerSegments);
        outline.push([
          centerX + usableRadius * Math.cos(angle),
          centerY + usableRadius * Math.sin(angle),
        ]);
      }
    });

    const positions = [];
    const pushTriangle = (a, b, c) => positions.push(...a, ...b, ...c);
    outline.forEach((point, index) => {
      const next = outline[(index + 1) % outline.length];
      const low = [point[0], point[1], 0];
      const lowNext = [next[0], next[1], 0];
      const high = [point[0], point[1], height];
      const highNext = [next[0], next[1], height];
      pushTriangle([0, 0, 0], lowNext, low);
      pushTriangle([0, 0, height], high, highNext);
      pushTriangle(low, lowNext, highNext);
      pushTriangle(low, highNext, high);
    });
    const normals = [];
    this.computeNormals(positions, normals);
    return {
      positions,
      normals,
      triangleCount: outline.length * 4,
    };
  }

  fanMesh(dimensions) {
    const [length, width, height] = dimensions.map(Number);
    const positions = [];
    let triangleCount = 0;
    const appendBox = (
      size,
      translation = [0, 0, 0],
      angle = 0,
      radialOffset = 0,
    ) => {
      const mesh = this.boxMesh(size);
      const cosine = Math.cos(angle);
      const sine = Math.sin(angle);
      for (let index = 0; index < mesh.positions.length; index += 3) {
        const localX = mesh.positions[index] + radialOffset;
        const localY = mesh.positions[index + 1];
        positions.push(
          localX * cosine - localY * sine + translation[0],
          localX * sine + localY * cosine + translation[1],
          mesh.positions[index + 2] + translation[2],
        );
      }
      triangleCount += mesh.triangleCount;
    };

    const frame = Math.max(7, Math.min(length, width) * 0.067);
    appendBox([length, frame, height], [0, (width - frame) / 2, 0]);
    appendBox([length, frame, height], [0, -(width - frame) / 2, 0]);
    appendBox([frame, width - 2 * frame, height], [(length - frame) / 2, 0, 0]);
    appendBox([frame, width - 2 * frame, height], [-(length - frame) / 2, 0, 0]);

    const hub = Math.min(length, width) * 0.2;
    const rotorHeight = Math.max(4, height * 0.24);
    const rotorZ = (height - rotorHeight) / 2;
    appendBox([hub, hub, rotorHeight], [0, 0, rotorZ], Math.PI / 4);
    const bladeLength = Math.min(length, width) * 0.29;
    const bladeWidth = Math.max(6, Math.min(length, width) * 0.07);
    for (let blade = 0; blade < 7; blade += 1) {
      appendBox(
        [bladeLength, bladeWidth, rotorHeight],
        [0, 0, rotorZ],
        blade * (Math.PI * 2 / 7),
        hub / 2 + bladeLength / 2 - 2,
      );
    }
    const normals = [];
    this.computeNormals(positions, normals);
    return { positions, normals, triangleCount };
  }

  rotate(vector, rotationDeg) {
    const [rx, ry, rz] = rotationDeg.map((value) => value * Math.PI / 180);
    let [x, y, z] = vector;
    [y, z] = [y * Math.cos(rx) - z * Math.sin(rx), y * Math.sin(rx) + z * Math.cos(rx)];
    [x, z] = [x * Math.cos(ry) + z * Math.sin(ry), -x * Math.sin(ry) + z * Math.cos(ry)];
    [x, y] = [x * Math.cos(rz) - y * Math.sin(rz), x * Math.sin(rz) + y * Math.cos(rz)];
    return [x, y, z];
  }

  transformMesh(mesh, item) {
    const translation = item.translation_mm || [0, 0, 0];
    const rotation = item.rotation_deg || [0, 0, 0];
    const positions = [];
    const normals = [];
    for (let index = 0; index < mesh.positions.length; index += 3) {
      const position = this.rotate(mesh.positions.slice(index, index + 3), rotation);
      const normal = this.rotate(mesh.normals.slice(index, index + 3), rotation);
      positions.push(
        position[0] + translation[0],
        position[1] + translation[1],
        position[2] + translation[2],
      );
      normals.push(...normal);
    }
    return {
      positions,
      normals,
      triangleCount: mesh.triangleCount,
      color: item.color,
      opacity: Number(item.opacity ?? (item.is_reference ? 0.42 : 1.0)),
    };
  }

  buildBuffer(meshes) {
    const minimum = [Infinity, Infinity, Infinity];
    const maximum = [-Infinity, -Infinity, -Infinity];
    let vertexCount = 0;
    for (const mesh of meshes) {
      vertexCount += mesh.positions.length / 3;
      for (let index = 0; index < mesh.positions.length; index += 3) {
        for (let axis = 0; axis < 3; axis += 1) {
          minimum[axis] = Math.min(minimum[axis], mesh.positions[index + axis]);
          maximum[axis] = Math.max(maximum[axis], mesh.positions[index + axis]);
        }
      }
    }
    const center = minimum.map((value, axis) => (value + maximum[axis]) / 2);
    const extents = maximum.map((value, axis) => value - minimum[axis]);
    const span = Math.max(...extents) || 1;
    const interleaved = new Float32Array(vertexCount * 10);
    let vertexOffset = 0;
    for (const mesh of meshes) {
      for (let index = 0; index < mesh.positions.length / 3; index += 1) {
        const output = (vertexOffset + index) * 10;
        interleaved[output] =
          (mesh.positions[index * 3] - center[0]) * 2 / span;
        interleaved[output + 1] =
          (mesh.positions[index * 3 + 1] - center[1]) * 2 / span;
        interleaved[output + 2] =
          (mesh.positions[index * 3 + 2] - center[2]) * 2 / span;
        interleaved[output + 3] = mesh.normals[index * 3];
        interleaved[output + 4] = mesh.normals[index * 3 + 1];
        interleaved[output + 5] = mesh.normals[index * 3 + 2];
        interleaved[output + 6] = mesh.color[0];
        interleaved[output + 7] = mesh.color[1];
        interleaved[output + 8] = mesh.color[2];
        interleaved[output + 9] = mesh.opacity;
      }
      vertexOffset += mesh.positions.length / 3;
    }
    return { interleaved, extents, vertexCount };
  }

  async loadScene(scene) {
    const token = ++this.loadToken;
    this.onStatus(`LOADING · ${scene.label}`);
    const palette = [
      [0.78, 1.0, 0.24],
      [0.33, 0.91, 0.83],
      [0.91, 0.74, 0.33],
      [0.72, 0.56, 1.0],
      [0.94, 0.94, 0.9],
    ];
    const meshes = await Promise.all(scene.items.map(async (item, index) => {
      let mesh;
      if (item.primitive === "box") {
        mesh = this.boxMesh(item.dimensions_mm);
      } else if (item.primitive === "rounded_box") {
        mesh = this.roundedBoxMesh(
          item.dimensions_mm,
          item.radius_mm || 9,
        );
      } else if (item.primitive === "fan") {
        mesh = this.fanMesh(item.dimensions_mm);
      } else {
        const response = await fetch(item.url);
        if (!response.ok) throw new Error(`无法加载 ${item.name}`);
        mesh = this.parse(await response.arrayBuffer());
      }
      return this.transformMesh(
        mesh,
        {
          ...item,
          color: Array.isArray(item.color_rgb)
            ? item.color_rgb
            : item.is_reference
              ? [0.52, 0.56, 0.58]
              : palette[index % palette.length],
        },
      );
    }));
    if (token !== this.loadToken) return;
    const geometry = this.buildBuffer(meshes);
    this.vertexCount = geometry.vertexCount;
    this.gl.bindBuffer(this.gl.ARRAY_BUFFER, this.buffer);
    this.gl.bufferData(
      this.gl.ARRAY_BUFFER,
      geometry.interleaved,
      this.gl.STATIC_DRAW,
    );
    this.reset();
    const triangles = meshes.reduce((sum, mesh) => sum + mesh.triangleCount, 0);
    const extents = geometry.extents.map((value) => value.toFixed(1));
    this.onStatus(
      `${scene.label} · ${scene.items.length} PARTS · ${triangles} TRIANGLES`,
    );
    this.onDimensions(extents);
  }

  async load(url, name) {
    return this.loadScene({
      label: name,
      items: [
        {
          name,
          url,
          translation_mm: [0, 0, 0],
          rotation_deg: [0, 0, 0],
        },
      ],
    });
  }

  draw() {
    if (!this.vertexCount || this.canvas.offsetParent === null) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.floor(this.canvas.clientWidth * ratio));
    const height = Math.max(1, Math.floor(this.canvas.clientHeight * ratio));
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
    const gl = this.gl;
    gl.viewport(0, 0, width, height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.useProgram(this.program);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    gl.enableVertexAttribArray(this.locations.position);
    gl.vertexAttribPointer(this.locations.position, 3, gl.FLOAT, false, 40, 0);
    gl.enableVertexAttribArray(this.locations.normal);
    gl.vertexAttribPointer(this.locations.normal, 3, gl.FLOAT, false, 40, 12);
    gl.enableVertexAttribArray(this.locations.color);
    gl.vertexAttribPointer(this.locations.color, 4, gl.FLOAT, false, 40, 24);
    gl.uniform1f(this.locations.yaw, this.yaw);
    gl.uniform1f(this.locations.pitch, this.pitch);
    gl.uniform1f(this.locations.zoom, this.zoom);
    gl.uniform1f(this.locations.aspect, width / height);
    gl.drawArrays(gl.TRIANGLES, 0, this.vertexCount);
  }
}

window.STLViewer = STLViewer;
