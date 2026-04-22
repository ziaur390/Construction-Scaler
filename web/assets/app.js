/**
 * Construction Scaler — Web Measurement Engine
 *
 * Canvas-based PDF viewer with distance and area measurement.
 * Communicates with a FastAPI backend for PDF rendering and scale detection.
 */
(function () {
  "use strict";

  // ── Configuration ──────────────────────────────────────────────
  // UPDATE THIS after deploying the backend to Render:
  const API_BASE =
    window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
      ? "http://127.0.0.1:8000"
      : "https://construction-scaler-api.onrender.com"; // ← Replace with your actual Render URL

  // ── DOM Elements ───────────────────────────────────────────────
  const canvas = document.getElementById("measureCanvas");
  if (!canvas) return; // Not on the workspace page

  const ctx = canvas.getContext("2d");
  const pdfInput = document.getElementById("pdfInput");
  const btnImport = document.getElementById("btnImport");
  const btnImport2 = document.getElementById("btnImport2");
  const btnDistance = document.getElementById("btnDistance");
  const btnArea = document.getElementById("btnArea");
  const btnPrev = document.getElementById("btnPrev");
  const btnNext = document.getElementById("btnNext");
  const btnClear = document.getElementById("btnClear");
  const scaleSelect = document.getElementById("scaleSelect");
  const pageInfo = document.getElementById("pageInfo");
  const resultBadge = document.getElementById("resultBadge");
  const emptyState = document.getElementById("emptyState");
  const loadingOverlay = document.getElementById("loadingOverlay");
  const statusText = document.getElementById("statusText");
  const statusDot = document.getElementById("statusDot");
  const cursorInfo = document.getElementById("cursorInfo");
  const zoomInfo = document.getElementById("zoomInfo");

  // ── State ──────────────────────────────────────────────────────
  let sessionId = null;
  let currentFilename = "";
  let pageCount = 0;
  let currentPage = 0;
  let pageDPI = 150;
  let pageImage = null; // Image object
  let scales = [];

  let mode = "distance"; // "distance" | "area"

  // View transform
  let zoom = 1;
  let panX = 0;
  let panY = 0;
  let fitScale = 1; // scale to fit image in canvas

  // Measurement state
  let distPoint1 = null; // {x, y} in image coords
  let polyPoints = []; // [{x,y}, ...] in image coords
  let mouseImg = null; // current mouse in image coords

  // Completed measurements for overlay
  let measurements = []; // [{type, points, text, scale}]

  // Pan drag state
  let isPanning = false;
  let panStart = { x: 0, y: 0 };

  // ── Helpers ────────────────────────────────────────────────────

  function canvasToImage(cx, cy) {
    return {
      x: (cx - panX) / (fitScale * zoom),
      y: (cy - panY) / (fitScale * zoom),
    };
  }

  function imageToCanvas(ix, iy) {
    return {
      x: ix * fitScale * zoom + panX,
      y: iy * fitScale * zoom + panY,
    };
  }

  function pixelDistance(p1, p2) {
    return Math.hypot(p2.x - p1.x, p2.y - p1.y);
  }

  function polygonAreaPx(pts) {
    if (pts.length < 3) return 0;
    let s = 0;
    for (let i = 0; i < pts.length; i++) {
      const j = (i + 1) % pts.length;
      s += pts[i].x * pts[j].y - pts[j].x * pts[i].y;
    }
    return Math.abs(s) / 2;
  }

  function getSelectedScale() {
    const idx = parseInt(scaleSelect.value, 10);
    if (isNaN(idx) || idx < 0 || idx >= scales.length) return null;
    return scales[idx];
  }

  function formatDistance(paperIn, scale) {
    if (!scale || !scale.ratio) {
      return `${(paperIn * 25.4).toFixed(1)} mm (paper) — no scale`;
    }
    const realIn = paperIn / scale.ratio;
    const realFt = realIn / 12;
    if (realFt >= 1) {
      return `${realFt.toFixed(2)} ft`;
    }
    return `${realIn.toFixed(2)} in`;
  }

  function formatArea(paperIn2, scale) {
    if (!scale || !scale.ratio) {
      return `${(paperIn2 * 25.4 * 25.4).toFixed(1)} mm² (paper) — no scale`;
    }
    const realIn2 = paperIn2 / (scale.ratio * scale.ratio);
    const realFt2 = realIn2 / 144;
    if (realFt2 >= 1) {
      return `${realFt2.toFixed(2)} ft²`;
    }
    return `${realIn2.toFixed(2)} in²`;
  }

  function setStatus(text, active) {
    if (statusText) statusText.textContent = text;
    if (statusDot) statusDot.classList.toggle("active", !!active);
  }

  function showResult(text) {
    if (resultBadge) {
      resultBadge.textContent = text;
      resultBadge.style.display = text ? "inline-flex" : "none";
    }
  }

  // ── Canvas Sizing ──────────────────────────────────────────────

  function resizeCanvas() {
    const parent = canvas.parentElement;
    canvas.width = parent.clientWidth;
    canvas.height = parent.clientHeight;
    if (pageImage) computeFitScale();
    draw();
  }

  function computeFitScale() {
    if (!pageImage) return;
    const sx = canvas.width / pageImage.width;
    const sy = canvas.height / pageImage.height;
    fitScale = Math.min(sx, sy) * 0.95; // 95% to leave a small margin
  }

  function fitView() {
    if (!pageImage) return;
    computeFitScale();
    zoom = 1;
    panX = (canvas.width - pageImage.width * fitScale) / 2;
    panY = (canvas.height - pageImage.height * fitScale) / 2;
  }

  // ── Drawing ────────────────────────────────────────────────────

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Background
    ctx.fillStyle = "#e8ecef";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    if (!pageImage) return;

    ctx.save();
    ctx.translate(panX, panY);
    ctx.scale(fitScale * zoom, fitScale * zoom);

    // Draw page image
    ctx.drawImage(pageImage, 0, 0);

    // Draw completed measurements
    for (const m of measurements) {
      if (m.type === "distance") {
        drawDistanceLine(m.points[0], m.points[1], m.text);
      } else if (m.type === "area") {
        drawPolygon(m.points, m.text);
      }
    }

    // Draw in-progress measurement
    if (mode === "distance" && distPoint1) {
      drawPoint(distPoint1, "#3b82f6");
      if (mouseImg) {
        drawRubberLine(distPoint1, mouseImg);
      }
    }

    if (mode === "area" && polyPoints.length > 0) {
      // Draw partial polygon
      ctx.strokeStyle = "#8b5cf6";
      ctx.lineWidth = 2 / (fitScale * zoom);
      ctx.setLineDash([6 / (fitScale * zoom), 4 / (fitScale * zoom)]);
      ctx.beginPath();
      ctx.moveTo(polyPoints[0].x, polyPoints[0].y);
      for (let i = 1; i < polyPoints.length; i++) {
        ctx.lineTo(polyPoints[i].x, polyPoints[i].y);
      }
      if (mouseImg) {
        ctx.lineTo(mouseImg.x, mouseImg.y);
      }
      ctx.stroke();
      ctx.setLineDash([]);
      for (const p of polyPoints) drawPoint(p, "#8b5cf6");
    }

    ctx.restore();
  }

  function drawPoint(p, color) {
    const r = 5 / (fitScale * zoom);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 1.5 / (fitScale * zoom);
    ctx.stroke();
  }

  function drawRubberLine(a, b) {
    ctx.strokeStyle = "rgba(59,130,246,0.6)";
    ctx.lineWidth = 2 / (fitScale * zoom);
    ctx.setLineDash([6 / (fitScale * zoom), 4 / (fitScale * zoom)]);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawDistanceLine(a, b, label) {
    const lw = 2.5 / (fitScale * zoom);
    ctx.strokeStyle = "#3b82f6";
    ctx.lineWidth = lw;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
    drawPoint(a, "#3b82f6");
    drawPoint(b, "#3b82f6");

    // Label
    if (label) {
      const mx = (a.x + b.x) / 2;
      const my = (a.y + b.y) / 2;
      const fs = Math.max(12, 14 / (fitScale * zoom));
      ctx.font = `bold ${fs}px "Space Grotesk", sans-serif`;
      const tw = ctx.measureText(label).width;
      const pad = 6 / (fitScale * zoom);
      ctx.fillStyle = "rgba(255,255,255,0.92)";
      ctx.fillRect(mx - tw / 2 - pad, my - fs / 2 - pad, tw + pad * 2, fs + pad * 2);
      ctx.strokeStyle = "#3b82f6";
      ctx.lineWidth = 1 / (fitScale * zoom);
      ctx.strokeRect(mx - tw / 2 - pad, my - fs / 2 - pad, tw + pad * 2, fs + pad * 2);
      ctx.fillStyle = "#0f172a";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, mx, my);
    }
  }

  function drawPolygon(pts, label) {
    if (pts.length < 3) return;
    ctx.fillStyle = "rgba(139,92,246,0.15)";
    ctx.strokeStyle = "#8b5cf6";
    ctx.lineWidth = 2.5 / (fitScale * zoom);
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    for (const p of pts) drawPoint(p, "#8b5cf6");

    if (label) {
      const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
      const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
      const fs = Math.max(12, 14 / (fitScale * zoom));
      ctx.font = `bold ${fs}px "Space Grotesk", sans-serif`;
      const tw = ctx.measureText(label).width;
      const pad = 6 / (fitScale * zoom);
      ctx.fillStyle = "rgba(255,255,255,0.92)";
      ctx.fillRect(cx - tw / 2 - pad, cy - fs / 2 - pad, tw + pad * 2, fs + pad * 2);
      ctx.strokeStyle = "#8b5cf6";
      ctx.lineWidth = 1 / (fitScale * zoom);
      ctx.strokeRect(cx - tw / 2 - pad, cy - fs / 2 - pad, tw + pad * 2, fs + pad * 2);
      ctx.fillStyle = "#0f172a";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, cx, cy);
    }
  }

  // ── API ────────────────────────────────────────────────────────

  async function uploadPDF(file) {
    emptyState.style.display = "none";
    loadingOverlay.style.display = "flex";
    setStatus("Uploading…", false);

    try {
      const form = new FormData();
      form.append("file", file);

      const res = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: form });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Upload failed (${res.status})`);
      }

      const data = await res.json();
      sessionId = data.session_id;
      currentFilename = data.filename;
      pageCount = data.page_count;

      setStatus(`Loaded: ${data.filename} (${pageCount} pages)`, true);
      await loadPage(1);
    } catch (err) {
      loadingOverlay.style.display = "none";
      emptyState.style.display = "flex";
      setStatus(`Error: ${err.message}`, false);
      alert(`Upload failed: ${err.message}`);
    }
  }

  async function loadPage(num) {
    if (!sessionId) return;
    loadingOverlay.style.display = "flex";
    setStatus(`Rendering page ${num}…`, true);

    try {
      const res = await fetch(`${API_BASE}/api/page/${sessionId}/${num}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Load failed (${res.status})`);
      }

      const data = await res.json();
      currentPage = data.page_num;
      pageCount = data.page_count;
      pageDPI = data.dpi;
      scales = data.scales || [];

      // Update scale dropdown
      scaleSelect.innerHTML = "";
      if (scales.length === 0) {
        scaleSelect.innerHTML = '<option value="">No scales detected</option>';
      } else {
        let firstOK = -1;
        scales.forEach((s, i) => {
          const opt = document.createElement("option");
          opt.value = i;
          opt.textContent = s.label;
          if (s.kind === "OK" && firstOK < 0) firstOK = i;
          scaleSelect.appendChild(opt);
        });
        if (firstOK >= 0) scaleSelect.value = firstOK;
      }

      // Load image
      const img = new Image();
      img.onload = async () => {
        pageImage = img;
        fitView();
        clearMeasurements();
        await loadMeasurementsFromDB(num);
        loadingOverlay.style.display = "none";
        emptyState.style.display = "none";
        pageInfo.textContent = `${currentPage} / ${pageCount}`;
        setStatus(`Page ${currentPage} — ${scales.filter(s => s.kind === "OK").length} scale(s) detected`, true);
        draw();
      };
      img.onerror = () => {
        loadingOverlay.style.display = "none";
        setStatus("Failed to decode page image.", false);
      };
      img.src = "data:image/jpeg;base64," + data.image;
    } catch (err) {
      loadingOverlay.style.display = "none";
      setStatus(`Error: ${err.message}`, false);
    }
  }

  // ── Measurement Logic ──────────────────────────────────────────

  async function saveMeasurementToDB(m) {
    if (!sessionId) return;
    try {
      await fetch(`${API_BASE}/api/measurements`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          filename: currentFilename,
          page_num: currentPage,
          type: m.type,
          points: m.points,
          result_text: m.text,
          scale_label: m.scale
        })
      });
    } catch (err) {
      console.error("Failed to save measurement:", err);
    }
  }

  async function loadMeasurementsFromDB(pageNum) {
    if (!currentFilename) return;
    try {
      const res = await fetch(`${API_BASE}/api/measurements/${currentFilename}`);
      if (res.ok) {
        const data = await res.json();
        // Filter by current page and map to internal format
        measurements = data
          .filter(m => m.page_num === pageNum)
          .map(m => ({
            type: m.type,
            points: m.points,
            text: m.result_text,
            scale: m.scale_label
          }));
        draw();
      }
    } catch (err) {
      console.error("Failed to load measurements:", err);
    }
  }

  function completeMeasureDistance(p1, p2) {
    const distPx = pixelDistance(p1, p2);
    const paperIn = distPx / pageDPI;
    const scale = getSelectedScale();
    const label = formatDistance(paperIn, scale);
    const scaleLabel = scale ? scale.raw : "no scale";

    const m = { type: "distance", points: [p1, p2], text: label, scale: scaleLabel };
    measurements.push(m);
    saveMeasurementToDB(m);
    showResult(`${label}  (${scaleLabel})`);
    setStatus(`Distance: ${label}`, true);
  }

  function completeMeasureArea(pts) {
    const areaPx = polygonAreaPx(pts);
    const paperIn2 = areaPx / (pageDPI * pageDPI);
    const scale = getSelectedScale();
    const label = formatArea(paperIn2, scale);
    const scaleLabel = scale ? scale.raw : "no scale";

    const m = { type: "area", points: [...pts], text: label, scale: scaleLabel };
    measurements.push(m);
    saveMeasurementToDB(m);
    showResult(`${label}  (${scaleLabel})`);
    setStatus(`Area: ${label}`, true);
  }

  function clearMeasurements() {
    measurements = [];
    distPoint1 = null;
    polyPoints = [];
    showResult("");
    draw();
  }

  // ── Event Handlers ─────────────────────────────────────────────

  function getMousePos(e) {
    const rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  canvas.addEventListener("mousedown", (e) => {
    if (!pageImage) return;

    // Middle button or ctrl+left = pan
    if (e.button === 1 || (e.button === 0 && e.ctrlKey)) {
      e.preventDefault();
      isPanning = true;
      panStart = getMousePos(e);
      canvas.style.cursor = "grabbing";
      return;
    }

    const pos = getMousePos(e);
    const imgPos = canvasToImage(pos.x, pos.y);

    // Bounds check
    if (imgPos.x < 0 || imgPos.y < 0 || imgPos.x > pageImage.width || imgPos.y > pageImage.height) return;

    // Right click
    if (e.button === 2) {
      e.preventDefault();
      if (mode === "distance") {
        distPoint1 = null;
        draw();
      } else if (mode === "area" && polyPoints.length >= 3) {
        completeMeasureArea(polyPoints);
        polyPoints = [];
        draw();
      }
      return;
    }

    // Left click
    if (e.button === 0 && !e.ctrlKey) {
      if (mode === "distance") {
        if (!distPoint1) {
          distPoint1 = imgPos;
        } else {
          completeMeasureDistance(distPoint1, imgPos);
          distPoint1 = null;
        }
        draw();
      } else {
        polyPoints.push(imgPos);
        draw();
      }
    }
  });

  canvas.addEventListener("mousemove", (e) => {
    if (!pageImage) return;
    const pos = getMousePos(e);

    if (isPanning) {
      panX += pos.x - panStart.x;
      panY += pos.y - panStart.y;
      panStart = pos;
      draw();
      return;
    }

    const imgPos = canvasToImage(pos.x, pos.y);
    mouseImg = imgPos;

    // Update cursor info
    if (cursorInfo && imgPos.x >= 0 && imgPos.y >= 0 && imgPos.x <= (pageImage?.width || 0) && imgPos.y <= (pageImage?.height || 0)) {
      cursorInfo.textContent = `${Math.round(imgPos.x)}, ${Math.round(imgPos.y)} px`;
    }

    // Redraw for rubber band
    if ((mode === "distance" && distPoint1) || (mode === "area" && polyPoints.length > 0)) {
      draw();
    }
  });

  canvas.addEventListener("mouseup", () => {
    if (isPanning) {
      isPanning = false;
      canvas.style.cursor = mode === "distance" ? "crosshair" : "crosshair";
    }
  });

  canvas.addEventListener("wheel", (e) => {
    if (!pageImage) return;
    e.preventDefault();
    const pos = getMousePos(e);
    const imgBefore = canvasToImage(pos.x, pos.y);

    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    zoom = Math.max(0.1, Math.min(30, zoom * factor));

    // Adjust pan so zoom centers on mouse
    panX = pos.x - imgBefore.x * fitScale * zoom;
    panY = pos.y - imgBefore.y * fitScale * zoom;

    if (zoomInfo) zoomInfo.textContent = `${Math.round(zoom * 100)}%`;
    draw();
  }, { passive: false });

  canvas.addEventListener("contextmenu", (e) => e.preventDefault());

  // ── Button Handlers ────────────────────────────────────────────

  if (btnImport) btnImport.addEventListener("click", () => pdfInput.click());
  if (btnImport2) btnImport2.addEventListener("click", () => pdfInput.click());
  if (pdfInput) pdfInput.addEventListener("change", (e) => {
    if (e.target.files[0]) uploadPDF(e.target.files[0]);
  });

  if (btnDistance) btnDistance.addEventListener("click", () => {
    mode = "distance";
    btnDistance.classList.add("active");
    btnArea.classList.remove("active");
    distPoint1 = null;
    polyPoints = [];
    canvas.style.cursor = "crosshair";
    setStatus("Mode: Distance — click two points to measure", true);
    draw();
  });

  if (btnArea) btnArea.addEventListener("click", () => {
    mode = "area";
    btnArea.classList.add("active");
    btnDistance.classList.remove("active");
    distPoint1 = null;
    polyPoints = [];
    canvas.style.cursor = "crosshair";
    setStatus("Mode: Area — click points, right-click to close polygon", true);
    draw();
  });

  if (btnPrev) btnPrev.addEventListener("click", () => {
    if (currentPage > 1) loadPage(currentPage - 1);
  });

  if (btnNext) btnNext.addEventListener("click", () => {
    if (currentPage < pageCount) loadPage(currentPage + 1);
  });

  if (btnClear) btnClear.addEventListener("click", clearMeasurements);

  // Keyboard shortcuts
  document.addEventListener("keydown", (e) => {
    if (!pageImage) return;
    if (e.key === "Escape") { distPoint1 = null; polyPoints = []; draw(); }
    if (e.key === "ArrowRight" || e.key === "n") { if (currentPage < pageCount) loadPage(currentPage + 1); }
    if (e.key === "ArrowLeft" || e.key === "p") { if (currentPage > 1) loadPage(currentPage - 1); }
    if (e.key === "r") { fitView(); draw(); }
    if (e.key === "d") { btnDistance?.click(); }
    if (e.key === "a") { btnArea?.click(); }
    if (e.key === "c") { clearMeasurements(); }
  });

  // ── Init ───────────────────────────────────────────────────────

  window.addEventListener("resize", resizeCanvas);
  canvas.style.cursor = "crosshair";
  resizeCanvas();

  // Check backend health
  fetch(`${API_BASE}/api/health`)
    .then((r) => r.ok ? setStatus("Backend connected", true) : setStatus("Backend offline — start server", false))
    .catch(() => setStatus("Backend offline — start the FastAPI server", false));

  // ── Landing page scroll effect (runs on index.html too) ───────
  const header = document.getElementById("mainHeader");
  if (header) {
    window.addEventListener("scroll", () => {
      header.classList.toggle("scrolled", window.scrollY > 50);
    });
  }
})();
