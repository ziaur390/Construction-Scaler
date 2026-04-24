/**
 * Construction Scaler — Web Measurement Engine
 *
 * Canvas-based PDF viewer with distance and area measurement.
 * Communicates with a FastAPI backend for PDF rendering and scale detection.
 */
(function () {
  "use strict";

  // ── Configuration ──────────────────────────────────────────────
  const API_BASE =
    window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
      ? "http://127.0.0.1:8000"
      : "https://construction-scaler.onrender.com";

  // ── Auth Check ──────────────────────────────────────────────────
  const token = localStorage.getItem("cs_token");
  const username = localStorage.getItem("cs_username");
  
  if (!token) {
    window.location.href = "./login.html";
    return;
  }

  // ── DOM Elements ───────────────────────────────────────────────
  const canvas = document.getElementById("measureCanvas");
  if (!canvas) return; // Not on the workspace page

  const ctx = canvas.getContext("2d");
  const pdfInput = document.getElementById("pdfInput");
  const btnImport = document.getElementById("btnImport");
  const btnImport2 = document.getElementById("btnImport2");
  const btnDistance = document.getElementById("btnDistance");
  const btnPolyline = document.getElementById("btnPolyline");
  const btnArea = document.getElementById("btnArea");
  const btnCount = document.getElementById("btnCount");
  const btnCalibrate = document.getElementById("btnCalibrate");
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

  // New UI Elements
  const btnSummary = document.getElementById("btnSummary");
  const summaryPanel = document.getElementById("summaryPanel");
  const btnCloseSummary = document.getElementById("btnCloseSummary");
  const summaryContent = document.getElementById("summaryContent");
  const btnExportCSV = document.getElementById("btnExportCSV");

  const labelPopup = document.getElementById("labelPopup");
  const labelBtns = document.querySelectorAll(".label-btn");
  const btnSkipLabel = document.getElementById("btnSkipLabel");
  
  const userGreeting = document.getElementById("userGreeting");
  const btnLogout = document.getElementById("btnLogout");

  if (userGreeting) userGreeting.textContent = `Welcome, ${username}`;
  
  if (btnLogout) {
    btnLogout.addEventListener("click", () => {
      localStorage.removeItem("cs_token");
      localStorage.removeItem("cs_username");
      window.location.href = "./login.html";
    });
  }

  // ── State ──────────────────────────────────────────────────────
  let sessionId = null;
  let currentFilename = "";
  let pageCount = 0;
  let currentPage = 0;
  let pageDPI = 150;
  let pageImage = null;
  let scales = [];

  let mode = "distance"; // "distance" | "polyline" | "area" | "count" | "calibrate"

  // View transform
  let zoom = 1;
  let panX = 0;
  let panY = 0;
  let fitScale = 1;

  // Measurement state
  let distPoint1 = null;
  let polyPoints = [];
  let mouseImg = null;

  let pendingMeasurement = null;

  // Completed measurements for overlay
  let measurements = [];
  let hiddenCategories = {};

  const categoryColors = {
    "Plumbing": "#3b82f6",     // Blue
    "Electrical": "#ef4444",   // Red
    "HVAC": "#f97316",         // Orange
    "Framing": "#8b5cf6",      // Purple
    "Concrete": "#64748b",     // Slate
    "Area": "#10b981",         // Green
    "Count": "#eab308",        // Yellow
    "Uncategorized": "#0f172a" // Ink
  };

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
    fitScale = Math.min(sx, sy) * 0.95;
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

    ctx.fillStyle = "#e8ecef";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    if (!pageImage) return;

    ctx.save();
    ctx.translate(panX, panY);
    ctx.scale(fitScale * zoom, fitScale * zoom);

    ctx.drawImage(pageImage, 0, 0);

    for (const m of measurements) {
      const cat = m.category || "Uncategorized";
      if (hiddenCategories[cat]) continue;
      
      const color = categoryColors[cat] || categoryColors["Uncategorized"];

      if (m.type === "distance") {
        drawDistanceLine(m.points[0], m.points[1], m.text, color);
      } else if (m.type === "area") {
        drawPolygon(m.points, m.text, color);
      } else if (m.type === "polyline") {
        drawPolyline(m.points, m.text, color);
      } else if (m.type === "count") {
        drawCountPoint(m.points[0], color);
      }
    }

    if (mode === "distance" && distPoint1) {
      drawPoint(distPoint1, "#3b82f6");
      if (mouseImg) {
        drawRubberLine(distPoint1, mouseImg, "#3b82f6");
      }
    }

    if (mode === "calibrate" && distPoint1) {
      drawPoint(distPoint1, "#f59e0b");
      if (mouseImg) {
        drawRubberLine(distPoint1, mouseImg, "#f59e0b");
      }
    }

    if ((mode === "area" || mode === "polyline") && polyPoints.length > 0) {
      const isArea = mode === "area";
      const color = isArea ? "#8b5cf6" : "#f97316";
      ctx.strokeStyle = color;
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
      if (isArea && mouseImg) {
        ctx.lineTo(polyPoints[0].x, polyPoints[0].y); // Close path visually
      }
      ctx.stroke();
      ctx.setLineDash([]);
      for (const p of polyPoints) drawPoint(p, color);
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

  function drawRubberLine(a, b, color = "rgba(59,130,246,0.6)") {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2 / (fitScale * zoom);
    ctx.setLineDash([6 / (fitScale * zoom), 4 / (fitScale * zoom)]);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawDistanceLine(a, b, label, color = "#3b82f6") {
    const lw = 2.5 / (fitScale * zoom);
    ctx.strokeStyle = color;
    ctx.lineWidth = lw;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
    drawPoint(a, color);
    drawPoint(b, color);

    if (label) {
      const mx = (a.x + b.x) / 2;
      const my = (a.y + b.y) / 2;
      drawLabelBox(label, mx, my, color);
    }
  }

  function drawPolyline(pts, label, color = "#f97316") {
    if (pts.length < 2) return;
    const lw = 2.5 / (fitScale * zoom);
    ctx.strokeStyle = color;
    ctx.lineWidth = lw;
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
    ctx.stroke();
    for (const p of pts) drawPoint(p, color);

    if (label) {
      const last = pts[pts.length - 1];
      drawLabelBox(label, last.x, last.y - 20 / (fitScale * zoom), color);
    }
  }

  function drawPolygon(pts, label, color = "#8b5cf6") {
    if (pts.length < 3) return;
    // Extract RGB from hex for fill
    let r=139, g=92, b=246; // default purple
    if (color.startsWith("#") && color.length === 7) {
      r = parseInt(color.slice(1,3), 16);
      g = parseInt(color.slice(3,5), 16);
      b = parseInt(color.slice(5,7), 16);
    }
    ctx.fillStyle = `rgba(${r},${g},${b},0.15)`;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.5 / (fitScale * zoom);
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    for (const p of pts) drawPoint(p, color);

    if (label) {
      const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
      const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
      drawLabelBox(label, cx, cy, color);
    }
  }

  function drawCountPoint(p, color = "#eab308") {
    const r = 8 / (fitScale * zoom);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 2 / (fitScale * zoom);
    ctx.stroke();
  }

  function drawLabelBox(text, x, y, borderColor) {
    const fs = Math.max(12, 14 / (fitScale * zoom));
    ctx.font = `bold ${fs}px "Space Grotesk", sans-serif`;
    const tw = ctx.measureText(text).width;
    const pad = 6 / (fitScale * zoom);
    ctx.fillStyle = "rgba(255,255,255,0.92)";
    ctx.fillRect(x - tw / 2 - pad, y - fs / 2 - pad, tw + pad * 2, fs + pad * 2);
    ctx.strokeStyle = borderColor;
    ctx.lineWidth = 1 / (fitScale * zoom);
    ctx.strokeRect(x - tw / 2 - pad, y - fs / 2 - pad, tw + pad * 2, fs + pad * 2);
    ctx.fillStyle = "#0f172a";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, x, y);
  }

  // ── API ────────────────────────────────────────────────────────

  async function uploadPDF(file) {
    emptyState.style.display = "none";
    loadingOverlay.style.display = "flex";
    setStatus("Uploading…", false);

    try {
      const form = new FormData();
      form.append("file", file);

      // Retry upload up to 3 times (handles Render cold start)
      let res;
      for (let attempt = 1; attempt <= 3; attempt++) {
        try {
          setStatus(attempt > 1 ? `Waking up server… attempt ${attempt}/3` : "Uploading…", false);
          res = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: form });
          break;
        } catch (fetchErr) {
          if (attempt === 3) throw fetchErr;
          await new Promise(r => setTimeout(r, 3000 * attempt));
        }
      }

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
      // Retry up to 3 times to handle Render free-tier cold start
      let res;
      for (let attempt = 1; attempt <= 3; attempt++) {
        try {
          setStatus(attempt > 1 ? `Waking up server… attempt ${attempt}/3` : `Rendering page ${num}…`, true);
          res = await fetch(`${API_BASE}/api/page/${sessionId}/${num}`);
          break;
        } catch (fetchErr) {
          if (attempt === 3) throw fetchErr;
          await new Promise(r => setTimeout(r, 3000 * attempt)); // wait 3s, then 6s
        }
      }

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
      
      // Always add the custom scale option at the end
      const customOpt = document.createElement("option");
      customOpt.value = "custom";
      customOpt.textContent = "+ Add Custom Scale...";
      scaleSelect.appendChild(customOpt);

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
        headers: { 
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          session_id: sessionId,
          filename: currentFilename,
          page_num: currentPage,
          type: m.type,
          points: m.points,
          result_text: m.text,
          scale_label: m.scale,
          category_label: m.category || null
        })
      });
    } catch (err) {
      console.error("Failed to save measurement:", err);
    }
  }

  async function loadMeasurementsFromDB(pageNum) {
    if (!currentFilename) return;
    try {
      const res = await fetch(`${API_BASE}/api/measurements/${currentFilename}`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        measurements = data
          .filter(m => m.page_num === pageNum)
          .map(m => ({
            type: m.type,
            points: m.points,
            text: m.result_text,
            scale: m.scale_label,
            category: m.category_label || null
          }));
        draw();
      }
    } catch (err) {
      console.error("Failed to load measurements:", err);
    }
  }

  // ── Measurement Labeling & Summary ─────────────────────────────

  function showLabelPopup(m, x, y) {
    pendingMeasurement = m;
    labelPopup.style.display = "block";

    const rect = canvas.getBoundingClientRect();
    let px = rect.left + x + 20;
    let py = rect.top + y - 20;

    if (px + 240 > window.innerWidth) px = window.innerWidth - 250;
    if (py + 200 > window.innerHeight) py = window.innerHeight - 210;

    labelPopup.style.left = `${px}px`;
    labelPopup.style.top = `${py}px`;
  }

  function finalizeMeasurement(category) {
    if (!pendingMeasurement) return;
    pendingMeasurement.category = category;
    measurements.push(pendingMeasurement);
    saveMeasurementToDB(pendingMeasurement);
    showResult(`${pendingMeasurement.text}  (${pendingMeasurement.scale})` + (category ? ` - ${category}` : ''));
    setStatus(`${pendingMeasurement.type === 'area' ? 'Area' : 'Distance'}: ${pendingMeasurement.text}`, true);
    pendingMeasurement = null;
    labelPopup.style.display = "none";
    draw();
    renderSummary();
  }

  labelBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      finalizeMeasurement(btn.textContent);
    });
  });

  if (btnSkipLabel) {
    btnSkipLabel.addEventListener("click", () => {
      finalizeMeasurement(null);
    });
  }

  function renderSummary() {
    if (!summaryContent) return;
    summaryContent.innerHTML = "";
    if (measurements.length === 0) {
      summaryContent.innerHTML = "<p style='opacity:0.6;font-size:0.85rem;text-align:center;margin-top:20px;'>No measurements yet.</p>";
      return;
    }

    const groups = {};
    measurements.forEach(m => {
      const cat = m.category || "Uncategorized";
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(m);
    });

    for (const [cat, items] of Object.entries(groups)) {
      const groupEl = document.createElement("div");
      groupEl.className = "summary-group";

      const title = document.createElement("div");
      title.className = "summary-group-title";
      title.style.display = "flex";
      title.style.justifyContent = "space-between";
      title.style.alignItems = "center";
      
      const labelDiv = document.createElement("div");
      labelDiv.style.display = "flex";
      labelDiv.style.alignItems = "center";
      labelDiv.style.gap = "8px";

      const chk = document.createElement("input");
      chk.type = "checkbox";
      chk.checked = !hiddenCategories[cat];
      chk.addEventListener("change", (e) => {
        hiddenCategories[cat] = !e.target.checked;
        draw();
      });

      const colorDot = document.createElement("span");
      colorDot.style.display = "inline-block";
      colorDot.style.width = "10px";
      colorDot.style.height = "10px";
      colorDot.style.borderRadius = "50%";
      colorDot.style.backgroundColor = categoryColors[cat] || categoryColors["Uncategorized"];

      labelDiv.appendChild(chk);
      labelDiv.appendChild(colorDot);
      labelDiv.appendChild(document.createTextNode(cat));

      title.appendChild(labelDiv);
      title.appendChild(document.createTextNode(`${items.length} item(s)`));
      
      groupEl.appendChild(title);

      items.forEach(item => {
        const itemEl = document.createElement("div");
        itemEl.className = "summary-item";
        const t = item.type.charAt(0).toUpperCase() + item.type.slice(1);
        itemEl.innerHTML = `<span>${t}</span><span>${item.text}</span>`;
        groupEl.appendChild(itemEl);
      });

      summaryContent.appendChild(groupEl);
    }
  }

  if (btnSummary) {
    btnSummary.addEventListener("click", () => {
      summaryPanel.style.display = summaryPanel.style.display === "none" ? "flex" : "none";
      if (summaryPanel.style.display === "flex") renderSummary();
    });
  }

  if (btnCloseSummary) {
    btnCloseSummary.addEventListener("click", () => {
      summaryPanel.style.display = "none";
    });
  }

  if (btnExportCSV) {
    btnExportCSV.addEventListener("click", async () => {
      if (!currentFilename) return;
      try {
        btnExportCSV.textContent = "Exporting...";
        const res = await fetch(`${API_BASE}/api/measurements/${currentFilename}`, {
          headers: { "Authorization": `Bearer ${token}` }
        });
        
        if (res.ok) {
          const data = await res.json();
          let csvContent = "data:text/csv;charset=utf-8,";
          csvContent += "ID,Page,Type,Result,Scale,Category,Date\n";
          
          data.forEach(m => {
            const date = new Date(m.timestamp).toLocaleString();
            const cat = m.category_label || "Uncategorized";
            const result = m.result_text.replace(/"/g, '""'); // Escape quotes
            const scale = m.scale_label.replace(/"/g, '""');
            const row = `${m.id},${m.page_num},${m.type},"${result}","${scale}","${cat}","${date}"`;
            csvContent += row + "\n";
          });
          
          const encodedUri = encodeURI(csvContent);
          const link = document.createElement("a");
          link.setAttribute("href", encodedUri);
          link.setAttribute("download", `${currentFilename}_measurements.csv`);
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
        }
      } catch (err) {
        console.error("Failed to export CSV:", err);
      } finally {
        btnExportCSV.textContent = "Export to CSV";
      }
    });
  }

  // ── BUG FIX: was using pan.x / pan.y (undefined), now uses panX / panY ──

  function completeMeasureDistance(p1, p2) {
    const distPx = pixelDistance(p1, p2);
    const paperIn = distPx / pageDPI;
    const scale = getSelectedScale();
    const label = formatDistance(paperIn, scale);
    const scaleLabel = scale ? scale.raw : "no scale";

    const m = { type: "distance", points: [p1, p2], text: label, scale: scaleLabel, category: null };

    // FIX: use panX/panY instead of pan.x/pan.y
    const canvasPos = imageToCanvas(mouseImg.x, mouseImg.y);
    showLabelPopup(m, canvasPos.x, canvasPos.y);
  }

  function completeMeasureArea(pts) {
    const areaPx = polygonAreaPx(pts);
    const paperIn2 = areaPx / (pageDPI * pageDPI);
    const scale = getSelectedScale();
    const label = formatArea(paperIn2, scale);
    const scaleLabel = scale ? scale.raw : "no scale";

    const m = { type: "area", points: [...pts], text: label, scale: scaleLabel, category: null };

    const canvasPos = imageToCanvas(mouseImg.x, mouseImg.y);
    showLabelPopup(m, canvasPos.x, canvasPos.y);
  }

  function completeMeasurePolyline(pts) {
    let totalPx = 0;
    for (let i = 1; i < pts.length; i++) {
      totalPx += pixelDistance(pts[i - 1], pts[i]);
    }
    const paperIn = totalPx / pageDPI;
    const scale = getSelectedScale();
    const label = formatDistance(paperIn, scale);
    const scaleLabel = scale ? scale.raw : "no scale";

    const m = { type: "polyline", points: [...pts], text: label, scale: scaleLabel, category: null };

    const canvasPos = imageToCanvas(mouseImg.x, mouseImg.y);
    showLabelPopup(m, canvasPos.x, canvasPos.y);
  }

  function completeMeasureCount(pt) {
    const m = { type: "count", points: [pt], text: "1", scale: "N/A", category: null };
    const canvasPos = imageToCanvas(pt.x, pt.y);
    showLabelPopup(m, canvasPos.x, canvasPos.y);
  }

  function completeCalibrate(p1, p2) {
    const distPx = pixelDistance(p1, p2);
    const paperIn = distPx / pageDPI;

    const input = prompt("Enter the real-world distance of this line in feet (e.g., 3 for a 3ft door):");
    if (!input) return;

    const realFt = parseFloat(input);
    if (isNaN(realFt) || realFt <= 0) {
      alert("Invalid distance entered.");
      return;
    }

    const realIn = realFt * 12;
    // ratio is paper / real
    const ratio = paperIn / realIn;

    // Convert ratio back to multiplier to show custom scale name (e.g., 1/8" = 1'0" is 1/96 ratio)
    const multiplier = Math.round(1 / ratio);
    const raw = `Calibrated 1:${multiplier}`;
    const newScale = {
      kind: "OK",
      ratio: ratio,
      raw: raw,
      label: raw
    };
    scales.push(newScale);

    // Remove custom option temporarily
    const lastOpt = scaleSelect.lastElementChild;
    if (lastOpt && lastOpt.value === "custom") scaleSelect.removeChild(lastOpt);

    // Add new scale
    const opt = document.createElement("option");
    opt.value = scales.length - 1;
    opt.textContent = newScale.label;
    scaleSelect.appendChild(opt);

    // Put custom option back
    if (lastOpt && lastOpt.value === "custom") scaleSelect.appendChild(lastOpt);

    scaleSelect.value = scales.length - 1;
    setStatus(`Calibrated scale: ${raw}`, true);
  }

  function clearMeasurements() {
    measurements = [];
    distPoint1 = null;
    polyPoints = [];
    pendingMeasurement = null;
    if (labelPopup) labelPopup.style.display = "none";
    showResult("");
    draw();
    renderSummary();
  }

  // ── Event Handlers ─────────────────────────────────────────────

  function getMousePos(e) {
    const rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  canvas.addEventListener("mousedown", (e) => {
    if (!pageImage) return;

    if (e.button === 1 || (e.button === 0 && e.ctrlKey)) {
      e.preventDefault();
      isPanning = true;
      panStart = getMousePos(e);
      canvas.style.cursor = "grabbing";
      return;
    }

    const pos = getMousePos(e);
    const imgPos = canvasToImage(pos.x, pos.y);

    if (imgPos.x < 0 || imgPos.y < 0 || imgPos.x > pageImage.width || imgPos.y > pageImage.height) return;

    if (e.button === 2) {
      e.preventDefault();
      if (mode === "distance" || mode === "calibrate") {
        distPoint1 = null;
        draw();
      } else if (mode === "area" && polyPoints.length >= 3) {
        completeMeasureArea(polyPoints);
        polyPoints = [];
        draw();
      } else if (mode === "polyline" && polyPoints.length >= 2) {
        completeMeasurePolyline(polyPoints);
        polyPoints = [];
        draw();
      } else {
        polyPoints = [];
        draw();
      }
      return;
    }

    if (e.button === 0 && !e.ctrlKey) {
      if (mode === "distance") {
        if (!distPoint1) {
          distPoint1 = imgPos;
        } else {
          completeMeasureDistance(distPoint1, imgPos);
          distPoint1 = null;
        }
        draw();
      } else if (mode === "calibrate") {
        if (!distPoint1) {
          distPoint1 = imgPos;
        } else {
          completeCalibrate(distPoint1, imgPos);
          distPoint1 = null;
        }
        draw();
      } else if (mode === "count") {
        completeMeasureCount(imgPos);
        draw();
      } else {
        // polyline or area
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

    if (cursorInfo && imgPos.x >= 0 && imgPos.y >= 0 && imgPos.x <= (pageImage?.width || 0) && imgPos.y <= (pageImage?.height || 0)) {
      cursorInfo.textContent = `${Math.round(imgPos.x)}, ${Math.round(imgPos.y)} px`;
    }

    if ((mode === "distance" || mode === "calibrate") && distPoint1) {
      draw();
    } else if ((mode === "area" || mode === "polyline") && polyPoints.length > 0) {
      draw();
    }
  });

  canvas.addEventListener("mouseup", () => {
    if (isPanning) {
      isPanning = false;
      canvas.style.cursor = "crosshair";
    }
  });

  canvas.addEventListener("wheel", (e) => {
    if (!pageImage) return;
    e.preventDefault();
    const pos = getMousePos(e);
    const imgBefore = canvasToImage(pos.x, pos.y);

    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    zoom = Math.max(0.1, Math.min(30, zoom * factor));

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
    document.querySelectorAll(".control-pill").forEach(b => b.classList.remove("active"));
    btnDistance.classList.add("active");
    distPoint1 = null; polyPoints = [];
    canvas.style.cursor = "crosshair";
    setStatus("Mode: Distance — click two points to measure", true);
    draw();
  });

  if (btnPolyline) btnPolyline.addEventListener("click", () => {
    mode = "polyline";
    document.querySelectorAll(".control-pill").forEach(b => b.classList.remove("active"));
    btnPolyline.classList.add("active");
    distPoint1 = null; polyPoints = [];
    canvas.style.cursor = "crosshair";
    setStatus("Mode: Polyline — left-click points, right-click to finish", true);
    draw();
  });

  if (btnArea) btnArea.addEventListener("click", () => {
    mode = "area";
    document.querySelectorAll(".control-pill").forEach(b => b.classList.remove("active"));
    btnArea.classList.add("active");
    distPoint1 = null; polyPoints = [];
    canvas.style.cursor = "crosshair";
    setStatus("Mode: Area — click points, right-click to close polygon", true);
    draw();
  });

  if (btnCount) btnCount.addEventListener("click", () => {
    mode = "count";
    document.querySelectorAll(".control-pill").forEach(b => b.classList.remove("active"));
    btnCount.classList.add("active");
    distPoint1 = null; polyPoints = [];
    canvas.style.cursor = "crosshair";
    setStatus("Mode: Count — click to place markers", true);
    draw();
  });

  if (btnCalibrate) btnCalibrate.addEventListener("click", () => {
    mode = "calibrate";
    document.querySelectorAll(".control-pill").forEach(b => b.classList.remove("active"));
    btnCalibrate.classList.add("active");
    distPoint1 = null; polyPoints = [];
    canvas.style.cursor = "crosshair";
    setStatus("Mode: Calibrate — click two points of a known distance", true);
    draw();
  });

  if (btnPrev) btnPrev.addEventListener("click", () => {
    if (currentPage > 1) loadPage(currentPage - 1);
  });

  if (btnNext) btnNext.addEventListener("click", () => {
    if (currentPage < pageCount) loadPage(currentPage + 1);
  });

  if (btnClear) btnClear.addEventListener("click", clearMeasurements);

  if (scaleSelect) {
    scaleSelect.addEventListener("change", () => {
      if (scaleSelect.value === "custom") {
        const input = prompt("Enter a custom scale multiplier.\n\nExamples:\nFor 1/8\" = 1'0\", enter 96 (since 1 foot / 0.125 inch = 96)\nFor 1/4\" = 1'0\", enter 48\nFor 1:100, enter 100");
        const multiplier = parseFloat(input);
        if (!isNaN(multiplier) && multiplier > 0) {
          const raw = `Custom 1:${multiplier}`;
          const newScale = {
            kind: "OK",
            ratio: 1 / multiplier,
            raw: raw,
            label: raw
          };
          scales.push(newScale);
          
          // Remove custom option temporarily
          const lastOpt = scaleSelect.lastElementChild;
          if (lastOpt && lastOpt.value === "custom") {
            scaleSelect.removeChild(lastOpt);
          }
          
          // Add new scale
          const opt = document.createElement("option");
          opt.value = scales.length - 1;
          opt.textContent = newScale.label;
          scaleSelect.appendChild(opt);
          
          // Put custom option back
          if (lastOpt && lastOpt.value === "custom") {
            scaleSelect.appendChild(lastOpt);
          }
          
          scaleSelect.value = scales.length - 1;
        } else {
          if (input !== null) alert("Invalid multiplier. Please enter a valid number (e.g. 96).");
          // Revert selection
          scaleSelect.value = scales.length > 0 ? 0 : "";
        }
      }
    });
  }

  // Keyboard shortcuts
  document.addEventListener("keydown", (e) => {
    if (!pageImage) return;
    if (e.key === "Escape") { distPoint1 = null; polyPoints = []; draw(); }
    if (e.key === "ArrowRight") { if (currentPage < pageCount) loadPage(currentPage + 1); }
    if (e.key === "ArrowLeft") { if (currentPage > 1) loadPage(currentPage - 1); }
    if (e.key === "r") { fitView(); draw(); }
    if (e.key === "c") { clearMeasurements(); }
    if (e.key === "z" && e.ctrlKey) {
      // Undo logic
      if (mode === "distance" && distPoint1) {
        distPoint1 = null;
        draw();
      } else if ((mode === "area" || mode === "polyline") && polyPoints.length > 0) {
        polyPoints.pop();
        draw();
      } else if (measurements.length > 0) {
        // Remove last measurement
        const lastM = measurements.pop();
        // Since we don't have a backend delete endpoint yet, we just remove it locally.
        // A full implementation would delete it from the server.
        draw();
        renderSummary();
        setStatus("Undo: removed last measurement.", true);
      }
    }
  });

  // ── Init ───────────────────────────────────────────────────────

  window.addEventListener("resize", resizeCanvas);
  canvas.style.cursor = "crosshair";
  resizeCanvas();

  // Check backend health (with cold-start awareness)
  setStatus("Connecting to server…", false);
  fetch(`${API_BASE}/api/health`)
    .then((r) => r.ok
      ? setStatus("Backend connected ✓", true)
      : setStatus("Backend offline — start server", false))
    .catch(() => setStatus("Server is waking up — please wait…", false));

  // ── Landing page scroll effect ─────────────────────────────────
  const header = document.getElementById("mainHeader");
  if (header) {
    window.addEventListener("scroll", () => {
      header.classList.toggle("scrolled", window.scrollY > 50);
    });
  }
})();