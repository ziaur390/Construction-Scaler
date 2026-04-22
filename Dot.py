"""
Plan / Drawing PDF Viewer + Measurement Tool (OFFLINE, no AI required)

WHAT THIS APP DOES
------------------
1) Lets you pick a PDF file (no hardcoded filename).
2) Renders ONE page at a time (fast; does not load whole PDF as images).
3) Detects "scale text" (e.g., 1/8" = 1'-0", 1" = 20', 1:100) from the PDF TEXT LAYER.
   - If the page is a scanned image (no selectable text), scale detection will likely be empty.
4) DISTANCE mode:
   - Left click once = start point
   - Left click second time = end point
   - Computes paper distance using (pixels + BASE_DPI)
   - Picks the NEAREST numeric scale to your measured area and converts to real distance
   - Draws the measured line on the page and prints results
5) AREA mode:
   - Left click adds polygon points
   - Right click closes polygon and computes area
   - Uses the same scale selection logic as distance
   - Draws filled polygon + prints results
6) Zoom in/out with mouse wheel (REAL zoom: changes view window, not DPI)
7) Display-only rotation (CW/CCW) without breaking calibration
8) If multiple scales are found:
   - It auto-picks the nearest numeric scale, BUT you can override using the scale list
9) If NO scale is detected:
   - You can drag a rectangle ("Mark Scale Area") around where you SEE the scale text
   - It will attempt to parse scales from only that region and add them to the list

NOTE ABOUT "TRAINING"
---------------------
This app is OFFLINE and does NOT train an ML model.
However, it logs user actions to a local file:
    training_data.jsonl
So later you (or a future offline AI module) can learn patterns.
This is "data collection", not automatic learning.

INSTALL
-------
pip install pymupdf matplotlib numpy

RUN
---
python plan_viewer.py
"""

from __future__ import annotations

import re
import math
import json
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.widgets import Button, TextBox, RadioButtons, RectangleSelector


# ================== GLOBAL SETTINGS ==================
BASE_DPI = 200            # IMPORTANT: fixed render DPI (pixels <-> inches calibration depends on it)
REAL_UNITS = "ft"         # "ft" or "m" (output units for real-world)
SHOW_SCALE_BOXES = False  # debug option: draw boxes around detected scale text lines
# =====================================================


# =====================================================
# 1) OFFLINE "TRAINING" / LOGGING HELPERS
# =====================================================
def _log_path() -> Path:
    """
    Returns a path in the same directory as this script:
        training_data.jsonl
    If __file__ is not available (rare), fallback to current working directory.
    """
    try:
        return Path(__file__).with_name("training_data.jsonl")
    except Exception:
        return Path("training_data.jsonl")


def log_event(payload: dict):
    """
    Append one JSON line to training_data.jsonl.
    This can later be used for offline learning / analytics.

    Example events:
      - measurement (auto scale chosen, manual correction)
      - mark_area_no_scale (user said scale exists but detection failed)
      - mark_area_found_scales (user helped locate scale text)
    """
    payload = dict(payload)
    payload["ts"] = datetime.now().isoformat(timespec="seconds")
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # logging is optional; never break the app if disk write fails
        pass


# =====================================================
# 2) FILE PICKER (NO HARDCODED PDF PATH)
# =====================================================
def pick_pdf_file() -> str | None:
    """
    Opens a standard file selection dialog to choose a PDF.

    Returns:
      - Full file path (string) if selected
      - None if user cancels

    Uses tkinter (comes with normal Python on Windows).
    """
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)  # bring dialog to the front
        path = filedialog.askopenfilename(
            title="Select a PDF",
            filetypes=[("PDF files", "*.pdf")],
        )
        root.destroy()
        return path if path else None
    except Exception:
        return None


# =====================================================
# 3) SCALE PARSING (TEXT -> SCALE RATIO)
# =====================================================
def _parse_fraction_or_float(s: str) -> float:
    """
    Converts:
      "1/8" -> 0.125
      "0.25" -> 0.25
      "2" -> 2.0
    """
    s = s.strip().replace(" ", "")
    if "/" in s and re.fullmatch(r"\d+/\d+", s):
        a, b = s.split("/")
        return float(a) / float(b)
    return float(s)


def parse_scale_to_ratio_paper_in_per_real_in(text: str):
    """
    Attempt to parse common drawing scale formats.

    Returns tuple: (kind, ratio, raw)
      kind:
        - "OK"       => numeric scale detected and usable
        - "NTS"      => Not To Scale (no real-world conversion possible)
        - "AS_NOTED" => scale varies by detail (no single conversion possible)
        - "NONE"     => no scale found in that text

      ratio:
        - Only if kind == "OK"
        - ratio = paper_inches / real_inches
          Example: 1/8" = 1'-0"
            paper = 0.125 inches
            real  = 12 inches
            ratio = 0.125/12 = 0.010416666...

      raw:
        - short raw match string for display
    """
    # Normalize weird quotes/dashes from PDFs
    t = " ".join(
        text.replace("’", "'")
            .replace("″", '"')
            .replace("“", '"')
            .replace("”", '"')
            .replace("–", "-")
            .replace("—", "-")
            .split()
    ).strip()

    # Handle explicit NTS / AS NOTED
    if re.search(r"\bNTS\b", t, re.IGNORECASE):
        return ("NTS", None, "NTS")
    if re.search(r"\bAS\s+NOTED\b", t, re.IGNORECASE):
        return ("AS_NOTED", None, "AS NOTED")

    # ARCHITECTURAL format example:
    #   1/8" = 1'-0"
    #   1/4" = 1'-0"
    #   3/16"=1'-0"
    m = re.search(
        r'(?P<paper>\d+(?:\s*/\s*\d+)?(?:\.\d+)?)\s*"?\s*=\s*(?P<ft>\d+)\s*\'\s*(?:-?\s*(?P<inch>\d+)\s*"?\s*)?',
        t,
        re.IGNORECASE
    )
    if m:
        paper_in = _parse_fraction_or_float(m.group("paper"))
        ft = int(m.group("ft"))
        inch = int(m.group("inch") or 0)
        real_in = ft * 12 + inch
        if real_in > 0 and paper_in > 0:
            return ("OK", paper_in / real_in, m.group(0))

    # ENGINEERING format example:
    #   1" = 20'
    m = re.search(
        r'(?P<paper>\d+(?:\s*/\s*\d+)?(?:\.\d+)?)\s*"?\s*=\s*(?P<ft>\d+(?:\.\d+)?)\s*\'',
        t,
        re.IGNORECASE
    )
    if m:
        paper_in = _parse_fraction_or_float(m.group("paper"))
        real_ft = float(m.group("ft"))
        real_in = real_ft * 12.0
        if real_in > 0 and paper_in > 0:
            return ("OK", paper_in / real_in, m.group(0))

    # RATIO format example:
    #   1:100
    m = re.search(r"\b(?P<a>\d+)\s*:\s*(?P<b>\d+)\b", t)
    if m:
        a = int(m.group("a"))
        b = int(m.group("b"))
        if a > 0 and b > 0:
            # for ratio scales, paper/real is a/b (same units)
            return ("OK", float(a) / float(b), m.group(0))

    return ("NONE", None, None)


# =====================================================
# 4) EXTRACT TEXT LINES FROM THE PDF TEXT LAYER
# =====================================================
def extract_all_text_lines(page: fitz.Page):
    """
    Extract all text lines from a page using get_text("dict"):

    Returns list of dict:
      {
        "text": "some line",
        "bbox_pts": (x0,y0,x1,y1)  # in PDF points
      }

    IMPORTANT:
    - This works best for vector PDFs / CAD exports.
    - Scanned images usually have no text layer => list may be empty.
    """
    d = page.get_text("dict")
    out = []
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            # type 0 = text; other types are images etc.
            continue
        for line in block.get("lines", []):
            parts = [sp.get("text", "") for sp in line.get("spans", [])]
            line_text = "".join(parts).strip()
            if not line_text:
                continue
            bbox = line.get("bbox", None)
            if not bbox:
                continue
            out.append({"text": line_text, "bbox_pts": tuple(map(float, bbox))})
    return out


def extract_scale_candidates_from_lines(lines):
    """
    Given the extracted text lines, check each line for scale patterns.

    Returns list of candidates:
      {
        "raw": "1/8\"=1'-0\"",
        "ratio": 0.0104166...,   # only if OK
        "bbox_pts": ...,
        "kind": "OK"/"NTS"/"AS_NOTED",
        "full_line": "... full original line ..."
      }
    """
    cands = []
    for ln in lines:
        kind, ratio, raw = parse_scale_to_ratio_paper_in_per_real_in(ln["text"])
        if kind in ("OK", "NTS", "AS_NOTED"):
            cands.append({
                "raw": raw if raw else ln["text"],
                "ratio": ratio,
                "bbox_pts": ln["bbox_pts"],
                "kind": kind,
                "full_line": ln["text"],
            })
    return cands


# =====================================================
# 5) COORDINATE CONVERSIONS: PDF POINTS -> PIXELS
# =====================================================
def pts_bbox_to_pixels(page: fitz.Page, bbox_pts, dpi: float):
    """
    Convert a bbox in PDF points -> pixels of the rendered image.

    Why this matters:
    - Text bboxes come in PDF coordinate system
    - Our page image is in pixel coordinates after rendering
    - We must map them correctly so "nearest scale" works

    Uses:
      m = page.rotation_matrix * Matrix(zoom, zoom)

    Note:
    - page.rotation_matrix uses PDF metadata rotation (not our display rotation).
    - This conversion matches the pixmap rendered with the same matrix.
    """
    zoom = dpi / 72.0
    m = page.rotation_matrix * fitz.Matrix(zoom, zoom)
    r = fitz.Rect(bbox_pts) * m
    return (float(r.x0), float(r.y0), float(r.x1), float(r.y1))


def center_of_bbox(b):
    """Return center (cx, cy) of bbox = (x0,y0,x1,y1)."""
    x0, y0, x1, y1 = b
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def bbox_intersects(a, b):
    """
    Returns True if bboxes a and b overlap.
    Used when user drags rectangle to "Mark Scale Area".
    """
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 < bx0 or ax0 > bx1 or ay1 < by0 or ay0 > by1)


def pick_nearest_numeric_scale(scale_boxes_px, click_mid_px):
    """
    Given a list of scale candidate boxes and a click midpoint (mx,my),
    return the nearest numeric scale (kind == "OK").

    Returns:
      (best_scale_dict, best_index_in_list)

    If there is no numeric scale, returns (None, None).
    """
    mx, my = click_mid_px
    best = None
    best_idx = None
    for i, s in enumerate(scale_boxes_px):
        if s["kind"] != "OK":
            continue
        cx, cy = center_of_bbox(s["bbox_px"])
        dist = math.hypot(cx - mx, cy - my)
        if best is None or dist < best["dist"]:
            best = {**s, "dist": dist}
            best_idx = i
    return best, best_idx


# =====================================================
# 6) CALIBRATION / MEASUREMENT MATH
#    PIXELS + DPI is the calibration baseline
# =====================================================
def paper_distance_from_pixels(p1, p2, dpi: float):
    """
    Compute distance in pixels and convert to inches/mm on paper.

    Key idea:
      pixels / dpi = inches
    """
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    dist_px = math.hypot(dx, dy)
    dist_in = dist_px / float(dpi)
    dist_mm = dist_in * 25.4
    return dist_px, dist_in, dist_mm


def polygon_area_px2(points_xy):
    """
    Compute polygon area in pixel^2 using shoelace formula.
    No strict limit on points — you can click many points.
    (More points = slower redraw, but usually fine.)
    """
    if len(points_xy) < 3:
        return 0.0
    x = [p[0] for p in points_xy]
    y = [p[1] for p in points_xy]
    s = 0.0
    n = len(points_xy)
    for i in range(n):
        j = (i + 1) % n
        s += x[i] * y[j] - x[j] * y[i]
    return abs(s) / 2.0


def paper_area_from_pixels(points_xy, dpi: float):
    """
    Convert pixel area -> paper area:
      (pixels^2) / (dpi^2) = inches^2
    """
    area_px2 = polygon_area_px2(points_xy)
    area_in2 = area_px2 / (float(dpi) ** 2)
    area_mm2 = area_in2 * (25.4 ** 2)
    return area_px2, area_in2, area_mm2


def real_distance_from_paper(paper_in: float, ratio_paper_in_per_real_in: float):
    """
    If ratio = paper_in / real_in, then:
      real_in = paper_in / ratio
    """
    real_in = paper_in / ratio_paper_in_per_real_in
    real_ft = real_in / 12.0
    real_m = real_in * 0.0254
    return real_in, real_ft, real_m


def real_area_from_paper(paper_in2: float, ratio_paper_in_per_real_in: float):
    """
    Area scales with ratio^2:
      paper_area = ratio^2 * real_area
      real_area  = paper_area / ratio^2
    """
    real_in2 = paper_in2 / (ratio_paper_in_per_real_in ** 2)
    real_ft2 = real_in2 / 144.0
    real_m2 = real_in2 * (0.0254 ** 2)
    return real_in2, real_ft2, real_m2


# =====================================================
# 7) DISPLAY-ONLY ROTATION HELPERS
#    IMPORTANT: This does NOT change BASE_DPI calibration.
#    We rotate the IMAGE for user convenience, but convert clicks back to BASE coords.
# =====================================================
def base_to_disp(x, y, k, w0, h0):
    """
    Convert a point from BASE image coords -> DISPLAY coords after k*90 rotation.

    k values:
      0 = no rotation
      1 = 90° CCW
      2 = 180°
      3 = 270° CCW
    """
    k %= 4
    if k == 0:
        return x, y
    if k == 1:
        return y, (w0 - 1) - x
    if k == 2:
        return (w0 - 1) - x, (h0 - 1) - y
    return (h0 - 1) - y, x


def disp_to_base(xd, yd, k, w0, h0):
    """
    Inverse mapping: DISPLAY coords -> BASE coords.
    Used so measured distances remain correct regardless of display rotation.
    """
    k %= 4
    if k == 0:
        return xd, yd
    if k == 1:
        return (w0 - 1) - yd, xd
    if k == 2:
        return (w0 - 1) - xd, (h0 - 1) - yd
    return yd, (h0 - 1) - xd


def rotate_bbox(bbox, k, w0, h0):
    """
    Rotate an axis-aligned bbox by k*90 degrees and return the new axis-aligned bbox.
    Used to rotate detected scale boxes with the displayed image.
    """
    x0, y0, x1, y1 = bbox
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    rc = [base_to_disp(x, y, k, w0, h0) for x, y in corners]
    xs = [p[0] for p in rc]
    ys = [p[1] for p in rc]
    return (min(xs), min(ys), max(xs), max(ys))


# =====================================================
# 8) MAIN APPLICATION CLASS
# =====================================================
class PlanViewer:
    """
    A single-window Matplotlib UI application.

    Main internal ideas:
      - Render one page at BASE_DPI into self.arr0 (base image)
      - Apply display rotation to get self.arr (display image)
      - Zoom/pan is done by changing axes xlim/ylim (no re-render needed)
      - All measurements are computed in DISPLAY pixels + BASE_DPI
      - We always keep a base coordinate copy so display rotation doesn't break calibration
    """

    def __init__(self):
        # ----- PDF state -----
        self.pdf_path = None
        self.doc = None
        self.page_index = 0

        # display rotation (k * 90°)
        self.rot_k = 0

        # ----- Rendered images -----
        self.arr0 = None   # base (unrotated) image
        self.h0 = 0
        self.w0 = 0

        self.arr = None    # displayed (rotated) image
        self.h = 0
        self.w = 0

        # ----- Extracted text lines and scale candidates -----
        self.all_lines_base = []   # base coords
        self.all_lines_disp = []   # rotated to display coords

        self.scale_boxes_base = []  # scale candidates in base coords
        self.scale_boxes_disp = []  # scale candidates rotated to display coords

        # UI flags
        self.show_boxes = SHOW_SCALE_BOXES

        # Mode:
        self.mode = "distance"  # "distance" or "area"

        # temp picks stored in BASE coords
        self.p1_base = None
        self.p2_base = None
        self.poly_points_base = []  # area mode points

        # last measurement persistent overlay
        self.last_type = None       # "distance" or "area"
        self.last_line_base = None  # ((x1,y1),(x2,y2)) in base coords
        self.last_poly_base = None  # polygon points in base coords
        self.last_text = ""
        self.last_auto_idx = None

        # cached paper values so scale override recomputes without re-clicking
        self.last_paper_in = None
        self.last_paper_mm = None
        self.last_paper_in2 = None
        self.last_paper_mm2 = None
        self.last_mid_disp = None   # midpoint/centroid in display coords (for logs)

        # view (zoom/pan)
        self.view_zoom = 1.0
        self.cx = 0.0
        self.cy = 0.0

        # rectangle selector tool for "Mark Scale Area"
        self.rs = None

        # ----- Matplotlib Figure / Axes -----
        self.fig, self.ax = plt.subplots(figsize=(13.5, 8))

        # Leave room for right-side scale panel & bottom buttons
        plt.subplots_adjust(right=0.78, bottom=0.24)

        # build the UI widgets (buttons, textboxes, scale list)
        self._build_ui()

        # crosshair lines (created in redraw)
        self.vline = None
        self.hline = None

        # connect matplotlib events
        self.fig.canvas.mpl_connect("scroll_event", self.on_scroll)
        self.fig.canvas.mpl_connect("button_press_event", self.on_click)
        self.fig.canvas.mpl_connect("key_press_event", self.on_key)
        self.fig.canvas.mpl_connect("motion_notify_event", self.on_move)

        # draw an empty screen so app doesn't crash before PDF is loaded
        self.redraw_empty("Click 'Open PDF' to start.")

        # auto-open file picker at start
        self.open_pdf_dialog(initial=True)

    # -------------------------------------------------
    # UI BUILDING
    # -------------------------------------------------
    def _build_ui(self):
        """
        Creates:
          - Buttons (Open, Prev/Next page, Rotate, Distance/Area mode, Reset, Boxes, Mark Area, Clear)
          - Page textbox + Go button
          - Right-side scale list panel (RadioButtons)
        """

        def btn(x, y, label, cb, w=0.10, h=0.06):
            axb = self.fig.add_axes([x, y, w, h])
            b = Button(axb, label)
            b.on_clicked(cb)
            return b

        # bottom row 1
        y1 = 0.03
        self.btn_open = btn(0.02, y1, "Open PDF", lambda _e: self.open_pdf_dialog(), w=0.09)
        self.btn_prev = btn(0.12, y1, "Prev", lambda _e: self.prev_page(), w=0.06)
        self.btn_next = btn(0.19, y1, "Next", lambda _e: self.next_page(), w=0.06)
        self.btn_rot_l = btn(0.26, y1, "Rotate ⟲", lambda _e: self.rotate_ccw(), w=0.08)
        self.btn_rot_r = btn(0.35, y1, "Rotate ⟳", lambda _e: self.rotate_cw(), w=0.08)

        self.btn_mode_dist = btn(0.44, y1, "Distance", lambda _e: self.set_mode("distance"), w=0.08)
        self.btn_mode_area = btn(0.53, y1, "Area", lambda _e: self.set_mode("area"), w=0.06)

        self.btn_reset = btn(0.61, y1, "Reset", lambda _e: self.reset_view(), w=0.06)
        self.btn_boxes = btn(0.68, y1, "Scale Boxes", lambda _e: self.toggle_boxes(), w=0.09)
        self.btn_mark = btn(0.78, y1, "Mark Scale Area", lambda _e: self.start_mark_area(), w=0.14)
        self.btn_clear = btn(0.93, y1, "Clear", lambda _e: self.clear_all(), w=0.05)

        # bottom row 2 (page navigation)
        y2 = 0.12
        ax_tb = self.fig.add_axes([0.02, y2, 0.10, 0.06])
        self.page_box = TextBox(ax_tb, "Page", initial="1")
        self.page_box.on_submit(lambda _txt: self.go_to_page_from_box())

        ax_go = self.fig.add_axes([0.13, y2, 0.05, 0.06])
        self.btn_go = Button(ax_go, "Go")
        self.btn_go.on_clicked(lambda _e: self.go_to_page_from_box())

        # Right-side scale list
        self.ax_scale = self.fig.add_axes([0.80, 0.22, 0.18, 0.74])
        self.ax_scale.set_title("Scales (click to change)")
        self.ax_scale.axis("off")
        self.radio = None
        self._build_scale_panel([])

    def redraw_empty(self, msg: str):
        """Show a simple text message instead of trying to imshow(None)."""
        self.ax.clear()
        self.ax.axis("off")
        self.ax.set_title(msg)
        self.fig.canvas.draw_idle()

    def _build_scale_panel(self, labels):
        """
        Rebuilds the right-side scale list.
        If labels empty => show message
        Else => create RadioButtons with the labels
        """
        self.ax_scale.clear()
        self.ax_scale.set_title("Scales (click to change)", fontsize=10)

        if not labels:
            self.ax_scale.text(
                0.02, 0.98,
                "No scales detected.\nUse 'Mark Scale Area'.",
                va="top", fontsize=9
            )
            self.ax_scale.axis("off")
            self.radio = None
            self.fig.canvas.draw_idle()
            return

        self.ax_scale.axis("on")
        self.ax_scale.set_xticks([])
        self.ax_scale.set_yticks([])

        self.radio = RadioButtons(self.ax_scale, labels, active=0)
        self.radio.on_clicked(self.on_scale_radio_change)
        self.fig.canvas.draw_idle()

    def _labels_for_scales(self):
        """
        Build readable labels for the scale list.
        Example:
          "1) OK: 1/8\"=1'-0\""
          "2) NTS: NTS"
        """
        labels = []
        for i, s in enumerate(self.scale_boxes_disp):
            raw = (s.get("raw") or "").strip().replace("\n", " ")
            if len(raw) > 34:
                raw = raw[:34] + "…"
            labels.append(f"{i+1}) {s['kind']}: {raw}")
        return labels

    def _set_radio_active(self, idx: int | None):
        """
        Programmatically select the radio button (scale) at idx.
        Used after auto-picking nearest scale so UI matches the auto choice.
        """
        if self.radio is None or idx is None:
            return
        idx = max(0, min(idx, len(self.scale_boxes_disp) - 1))
        try:
            self.radio.set_active(idx)
        except Exception:
            pass

    def set_mode(self, mode: str):
        """Switch between distance and area mode. Clears temporary picks."""
        if mode not in ("distance", "area"):
            return
        self.mode = mode
        self.p1_base = None
        self.p2_base = None
        self.poly_points_base = []
        self.redraw()

    # -------------------------------------------------
    # PDF OPEN / LOAD / RENDER
    # -------------------------------------------------
    def open_pdf_dialog(self, initial=False):
        """Ask user to pick a PDF and open it."""
        path = pick_pdf_file()
        if not path:
            if initial:
                print("No PDF selected. Close window or click Open PDF.")
            return
        self.open_pdf(path)

    def open_pdf(self, path: str):
        """
        Open a PDF, reset state, load page 1.
        """
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass

        self.pdf_path = path
        self.doc = fitz.open(path)
        self.page_index = 0
        self.rot_k = 0

        # clear measurement state but avoid redraw before page is loaded
        self.clear_all(keep_pdf=True, redraw_now=False)

        self.load_page(0)

    def load_page(self, idx0: int):
        """
        Load + render a page at BASE_DPI, extract text lines, detect scales.
        """
        if self.doc is None:
            return

        idx0 = max(0, min(idx0, self.doc.page_count - 1))
        self.page_index = idx0

        page = self.doc[self.page_index]

        # Render page image at fixed DPI
        zoom = BASE_DPI / 72.0
        m = page.rotation_matrix * fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=m, alpha=False)

        # Convert raw pixmap bytes -> numpy uint8 array shape (H,W,3)
        self.arr0 = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, 3))
        self.h0, self.w0 = self.arr0.shape[:2]

        # Extract ALL text lines
        self.all_lines_base = extract_all_text_lines(page)
        for ln in self.all_lines_base:
            # convert PDF point bbox to pixel bbox
            ln["bbox_px"] = pts_bbox_to_pixels(page, ln["bbox_pts"], BASE_DPI)

        # Detect scale candidates from text lines
        self.scale_boxes_base = extract_scale_candidates_from_lines(self.all_lines_base)
        for s in self.scale_boxes_base:
            s["bbox_px"] = pts_bbox_to_pixels(page, s["bbox_pts"], BASE_DPI)

        # Apply our display rotation
        self.apply_rotation()

        # Reset view
        self.view_zoom = 1.0
        self.cx = self.w / 2.0
        self.cy = self.h / 2.0

        # Update page box
        self.page_box.set_val(str(self.page_index + 1))

        # Refresh scale list UI
        self._build_scale_panel(self._labels_for_scales())

        # Console prints
        print(f"\n[Page {self.page_index+1}/{self.doc.page_count}] Scales detected: {len(self.scale_boxes_disp)}")
        if len(self.scale_boxes_disp) == 0:
            print("  -> No scale text found on this page (text layer).")
        else:
            for s in self.scale_boxes_disp[:8]:
                print(f"  - {s['kind']}: {s['raw']}")

        self.redraw()

    def apply_rotation(self):
        """
        Apply display rotation to:
          - the rendered image
          - scale boxes and text boxes
        """
        self.arr = np.rot90(self.arr0, self.rot_k)
        self.h, self.w = self.arr.shape[:2]

        self.all_lines_disp = []
        for ln in self.all_lines_base:
            rb = rotate_bbox(ln["bbox_px"], self.rot_k, self.w0, self.h0)
            self.all_lines_disp.append({**ln, "bbox_px_disp": rb})

        self.scale_boxes_disp = []
        for s in self.scale_boxes_base:
            rb = rotate_bbox(s["bbox_px"], self.rot_k, self.w0, self.h0)
            self.scale_boxes_disp.append({**s, "bbox_px_disp": rb})

        # For simplicity, we store display bbox in the same key expected by other functions
        for s in self.scale_boxes_disp:
            s["bbox_px"] = s["bbox_px_disp"]

    # -------------------------------------------------
    # VIEW CONTROL (ZOOM/PAN)
    # -------------------------------------------------
    def update_title(self):
        """Update window title with helpful instructions."""
        rot_deg = (self.rot_k % 4) * 90
        ok_count = sum(1 for s in self.scale_boxes_disp if s["kind"] == "OK")
        mode_txt = "DISTANCE" if self.mode == "distance" else "AREA"
        self.ax.set_title(
            f"{self.pdf_path}\n"
            f"Page {self.page_index+1}/{self.doc.page_count} | Rotation {rot_deg}° | Zoom {self.view_zoom:.2f}x | Mode: {mode_txt} | Numeric scales: {ok_count}\n"
            "Wheel=zoom | Left click=add | Right click=finish polygon (AREA) or clear picks (DIST) | n/p next/prev | [ ] rotate | r reset | b boxes | c clear last | q quit"
        )

    def apply_view(self):
        """
        Zoom is implemented by changing axis limits (xlim/ylim).
        The image itself is not re-rendered; we just view a smaller region.
        """
        vw = self.w / self.view_zoom
        vh = self.h / self.view_zoom

        x0 = max(0, self.cx - vw / 2.0)
        x1 = min(self.w, self.cx + vw / 2.0)
        y0 = max(0, self.cy - vh / 2.0)
        y1 = min(self.h, self.cy + vh / 2.0)

        self.ax.set_xlim(x0, x1)
        self.ax.set_ylim(y1, y0)  # origin="upper" so invert y axis
        self.update_title()

    def reset_view(self):
        """Reset zoom/pan to show whole page."""
        if self.arr is None:
            return
        self.view_zoom = 1.0
        self.cx = self.w / 2.0
        self.cy = self.h / 2.0
        self.redraw()

    def toggle_boxes(self):
        """Toggle drawing of scale bounding boxes (debug)."""
        self.show_boxes = not self.show_boxes
        self.redraw()

    # -------------------------------------------------
    # PAGE NAVIGATION + ROTATION
    # -------------------------------------------------
    def next_page(self):
        """Load next page."""
        if self.doc and self.page_index < self.doc.page_count - 1:
            self.p1_base = None
            self.p2_base = None
            self.poly_points_base = []
            self.load_page(self.page_index + 1)

    def prev_page(self):
        """Load previous page."""
        if self.doc and self.page_index > 0:
            self.p1_base = None
            self.p2_base = None
            self.poly_points_base = []
            self.load_page(self.page_index - 1)

    def go_to_page_from_box(self):
        """Go to page number typed in the Page textbox."""
        if not self.doc:
            return
        raw = self.page_box.text.strip()
        if not raw:
            return
        try:
            p = int(raw)
        except ValueError:
            print("Invalid page number.")
            return
        p = max(1, min(self.doc.page_count, p))
        self.p1_base = None
        self.p2_base = None
        self.poly_points_base = []
        self.load_page(p - 1)

    def rotate_ccw(self):
        """
        Rotate view 90° CCW (display-only).
        Calibration remains correct because clicks are mapped back to base coords.
        """
        if self.arr0 is None:
            return
        self.rot_k = (self.rot_k + 1) % 4
        self.apply_rotation()
        self._build_scale_panel(self._labels_for_scales())
        self.redraw()

    def rotate_cw(self):
        """Rotate view 90° CW (display-only)."""
        if self.arr0 is None:
            return
        self.rot_k = (self.rot_k - 1) % 4
        self.apply_rotation()
        self._build_scale_panel(self._labels_for_scales())
        self.redraw()

    # -------------------------------------------------
    # CLEAR / RESET MEASUREMENTS
    # -------------------------------------------------
    def clear_last_measure(self, redraw_now: bool = True):
        """Remove last drawn line/polygon and results."""
        self.last_type = None
        self.last_line_base = None
        self.last_poly_base = None
        self.last_text = ""
        self.last_auto_idx = None
        self.last_paper_in = None
        self.last_paper_mm = None
        self.last_paper_in2 = None
        self.last_paper_mm2 = None
        self.last_mid_disp = None

        if redraw_now and self.arr is not None:
            self.redraw()

    def clear_all(self, _evt=None, keep_pdf=False, redraw_now: bool = True):
        """
        Clear current picks + last measurement.
        Optionally close PDF if keep_pdf=False.
        """
        self.p1_base = None
        self.p2_base = None
        self.poly_points_base = []
        self.clear_last_measure(redraw_now=False)

        if not keep_pdf:
            if self.doc is not None:
                try:
                    self.doc.close()
                except Exception:
                    pass
                self.doc = None
                self.pdf_path = None
            self.arr0 = None
            self.arr = None

        if redraw_now:
            if self.arr is None:
                self.redraw_empty("No PDF loaded. Click 'Open PDF'.")
            else:
                self.redraw()

    # -------------------------------------------------
    # DRAW / RENDER OVERLAYS
    # -------------------------------------------------
    def redraw(self):
        """
        Redraw the page image and overlays:
          - crosshair
          - scale boxes (optional)
          - last measurement line/polygon (persist)
          - temporary picks (while user is clicking)
        """
        if self.arr is None:
            self.redraw_empty("No PDF loaded. Click 'Open PDF'.")
            return

        self.ax.clear()
        self.ax.imshow(self.arr, origin="upper")
        self.ax.axis("off")

        # crosshair lines
        self.vline = self.ax.axvline(0, linewidth=1, alpha=0.5, visible=False)
        self.hline = self.ax.axhline(0, linewidth=1, alpha=0.5, visible=False)

        # debug: draw scale text boxes
        if self.show_boxes:
            for s in self.scale_boxes_disp:
                x0, y0, x1, y1 = s["bbox_px"]
                rect = patches.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, linewidth=1)
                self.ax.add_patch(rect)

        # last measurement overlays
        if self.last_type == "distance" and self.last_line_base is not None:
            (bx1, by1), (bx2, by2) = self.last_line_base
            x1, y1 = base_to_disp(bx1, by1, self.rot_k, self.w0, self.h0)
            x2, y2 = base_to_disp(bx2, by2, self.rot_k, self.w0, self.h0)

            self.ax.plot([x1, x2], [y1, y2], linewidth=2)
            self.ax.plot([x1], [y1], marker="o", markersize=6)
            self.ax.plot([x2], [y2], marker="o", markersize=6)
            if self.last_text:
                mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                self.ax.text(mx, my, self.last_text, fontsize=10,
                             bbox=dict(facecolor="white", alpha=0.85))

        if self.last_type == "area" and self.last_poly_base is not None:
            pts_disp = [base_to_disp(p[0], p[1], self.rot_k, self.w0, self.h0) for p in self.last_poly_base]
            poly = patches.Polygon(pts_disp, closed=True, fill=True, alpha=0.20)
            self.ax.add_patch(poly)
            xs = [p[0] for p in pts_disp]
            ys = [p[1] for p in pts_disp]
            self.ax.plot(xs + [xs[0]], ys + [ys[0]], linewidth=2)
            for p in pts_disp:
                self.ax.plot([p[0]], [p[1]], marker="o", markersize=4)
            if self.last_text:
                mx = sum(xs) / len(xs)
                my = sum(ys) / len(ys)
                self.ax.text(mx, my, self.last_text, fontsize=10,
                             bbox=dict(facecolor="white", alpha=0.85))

        # temporary picks overlays
        if self.mode == "distance":
            if self.p1_base is not None:
                x1, y1 = base_to_disp(self.p1_base[0], self.p1_base[1], self.rot_k, self.w0, self.h0)
                self.ax.plot([x1], [y1], marker="x", markersize=9)
        else:
            if self.poly_points_base:
                pts_disp = [base_to_disp(p[0], p[1], self.rot_k, self.w0, self.h0) for p in self.poly_points_base]
                xs = [p[0] for p in pts_disp]
                ys = [p[1] for p in pts_disp]
                self.ax.plot(xs, ys, linewidth=1)
                for p in pts_disp:
                    self.ax.plot([p[0]], [p[1]], marker="x", markersize=7)

        self.apply_view()
        self.fig.canvas.draw_idle()

    # -------------------------------------------------
    # CROSSHAIR CURSOR
    # -------------------------------------------------
    def on_move(self, event):
        """
        Mouse move event:
          - Show crosshair lines following mouse cursor
        """
        if self.arr is None or self.vline is None or self.hline is None:
            return
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            self.vline.set_visible(False)
            self.hline.set_visible(False)
            self.fig.canvas.draw_idle()
            return
        self.vline.set_xdata([event.xdata, event.xdata])
        self.hline.set_ydata([event.ydata, event.ydata])
        self.vline.set_visible(True)
        self.hline.set_visible(True)
        self.fig.canvas.draw_idle()

    # -------------------------------------------------
    # ZOOM (MOUSE WHEEL)
    # -------------------------------------------------
    def on_scroll(self, event):
        """
        Mouse wheel zoom:
          - wheel up => zoom in
          - wheel down => zoom out
        """
        if self.arr is None:
            return
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        if event.button == "up":
            self.zoom_at(1.25, event.xdata, event.ydata)
        elif event.button == "down":
            self.zoom_at(1 / 1.25, event.xdata, event.ydata)

    def zoom_at(self, factor, x, y):
        """
        Zoom around a specific point (x,y) in display coords.
        """
        if self.arr is None:
            return
        self.cx = max(0, min(self.w, x))
        self.cy = max(0, min(self.h, y))
        self.view_zoom = max(1.0, min(25.0, self.view_zoom * factor))
        self.redraw()

    # -------------------------------------------------
    # KEYBOARD SHORTCUTS
    # -------------------------------------------------
    def on_key(self, event):
        """
        Keyboard shortcuts:
          n/right arrow => next page
          p/left arrow  => prev page
          [             => rotate CCW
          ]             => rotate CW
          r             => reset view
          b             => toggle scale boxes
          c             => clear last measurement overlay
          q             => quit
        """
        if event.key in ("n", "right"):
            self.next_page()
        elif event.key in ("p", "left"):
            self.prev_page()
        elif event.key == "[":
            self.rotate_ccw()
        elif event.key == "]":
            self.rotate_cw()
        elif event.key == "r":
            self.reset_view()
        elif event.key == "b":
            self.toggle_boxes()
        elif event.key == "c":
            self.clear_last_measure()
        elif event.key == "q":
            plt.close(self.fig)

    # -------------------------------------------------
    # CLICK HANDLING (DISTANCE + AREA)
    # -------------------------------------------------
    def on_click(self, event):
        """
        Main click handler:
          - Left click adds points (distance or area)
          - Right click:
              distance mode => clears current picks
              area mode     => closes polygon and computes area
        """
        if self.arr is None:
            return
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return

        xd, yd = float(event.xdata), float(event.ydata)

        # convert the clicked display coords back to base coords
        xb, yb = disp_to_base(xd, yd, self.rot_k, self.w0, self.h0)

        # right click
        if event.button == 3:
            if self.mode == "distance":
                self.p1_base = None
                self.p2_base = None
                self.redraw()
                return
            else:
                self.finish_area_polygon()
                return

        # only handle left click for adding points
        if event.button != 1:
            return

        if self.mode == "distance":
            self.handle_distance_click(xb, yb)
        else:
            self.handle_area_click(xb, yb)

    def handle_distance_click(self, xb, yb):
        """
        Distance mode logic:
          - first click sets start point
          - second click computes distance and resets for next measurement
        """
        if self.p1_base is None:
            self.p1_base = (xb, yb)
            self.redraw()
            return

        # second click
        p2_base = (xb, yb)

        # convert both base points to DISPLAY points (pixels)
        # because pixel distance is measured in the displayed image coordinates
        x1d, y1d = base_to_disp(self.p1_base[0], self.p1_base[1], self.rot_k, self.w0, self.h0)
        x2d, y2d = base_to_disp(p2_base[0], p2_base[1], self.rot_k, self.w0, self.h0)

        # midpoint used to pick nearest scale
        mid = ((x1d + x2d) / 2.0, (y1d + y2d) / 2.0)
        self.last_mid_disp = mid

        # PAPER distance from pixels + DPI
        _, paper_in, paper_mm = paper_distance_from_pixels((x1d, y1d), (x2d, y2d), BASE_DPI)
        self.last_paper_in = paper_in
        self.last_paper_mm = paper_mm
        self.last_paper_in2 = None
        self.last_paper_mm2 = None

        # auto-pick nearest numeric scale
        chosen, auto_idx = (None, None)
        if self.scale_boxes_disp:
            chosen, auto_idx = pick_nearest_numeric_scale(self.scale_boxes_disp, mid)
        self.last_auto_idx = auto_idx

        # store last measurement overlay
        self.last_type = "distance"
        self.last_line_base = (self.p1_base, p2_base)
        self.last_poly_base = None

        # reset temporary picks for next measurement
        self.p1_base = None
        self.p2_base = None

        if chosen is None or chosen.get("ratio") is None:
            self.last_text = f"{paper_in:.3f} in (paper)\nNO SCALE"
            print("\nNo numeric scale auto-found near clicked area.")
            print(f"Paper distance: {paper_in:.4f} in ({paper_mm:.2f} mm)")
        else:
            ratio = chosen["ratio"]
            real_in, real_ft, real_m = real_distance_from_paper(paper_in, ratio)

            print("\n[AUTO] Chosen scale:", chosen["raw"])
            print(f"Paper distance: {paper_in:.4f} in ({paper_mm:.2f} mm)")
            if REAL_UNITS.lower() == "ft":
                print(f"Real distance:  {real_ft:.4f} ft ({real_in:.2f} in)")
                self.last_text = f"{real_ft:.3f} ft (AUTO)\n{chosen['raw']}"
            else:
                print(f"Real distance:  {real_m:.4f} m ({real_in:.2f} in)")
                self.last_text = f"{real_m:.3f} m (AUTO)\n{chosen['raw']}"

            # auto-select scale in UI list
            if auto_idx is not None:
                self._set_radio_active(auto_idx)

        # log what happened
        self.log_measurement(auto_idx=auto_idx, user_idx=auto_idx)

        self.redraw()

    def handle_area_click(self, xb, yb):
        """Area mode: left click adds points to polygon (base coords)."""
        self.poly_points_base.append((xb, yb))
        self.redraw()

    def finish_area_polygon(self):
        """
        Area mode: right click finishes polygon, computes area, chooses scale near centroid.
        """
        if len(self.poly_points_base) < 3:
            print("Area mode: need at least 3 points. Keep left-clicking to add points.")
            return

        # convert base polygon points -> display points for pixel area calculation
        pts_disp = [base_to_disp(p[0], p[1], self.rot_k, self.w0, self.h0) for p in self.poly_points_base]

        # centroid used to pick nearest scale
        xs = [p[0] for p in pts_disp]
        ys = [p[1] for p in pts_disp]
        centroid = (sum(xs) / len(xs), sum(ys) / len(ys))
        self.last_mid_disp = centroid

        # compute paper area from pixels
        _, paper_in2, paper_mm2 = paper_area_from_pixels(pts_disp, BASE_DPI)
        self.last_paper_in2 = paper_in2
        self.last_paper_mm2 = paper_mm2
        self.last_paper_in = None
        self.last_paper_mm = None

        # auto-pick nearest numeric scale
        chosen, auto_idx = (None, None)
        if self.scale_boxes_disp:
            chosen, auto_idx = pick_nearest_numeric_scale(self.scale_boxes_disp, centroid)
        self.last_auto_idx = auto_idx

        # store last measurement overlay
        self.last_type = "area"
        self.last_poly_base = list(self.poly_points_base)
        self.last_line_base = None

        # clear temp polygon points
        self.poly_points_base = []

        if chosen is None or chosen.get("ratio") is None:
            self.last_text = f"{paper_in2:.3f} in² (paper)\nNO SCALE"
            print("\nNo numeric scale auto-found near polygon area.")
            print(f"Paper area: {paper_in2:.4f} in² ({paper_mm2:.2f} mm²)")
        else:
            ratio = chosen["ratio"]
            real_in2, real_ft2, real_m2 = real_area_from_paper(paper_in2, ratio)

            print("\n[AUTO] Chosen scale:", chosen["raw"])
            print(f"Paper area: {paper_in2:.4f} in² ({paper_mm2:.2f} mm²)")
            if REAL_UNITS.lower() == "ft":
                print(f"Real area:  {real_ft2:.4f} ft² ({real_in2:.2f} in²)")
                self.last_text = f"{real_ft2:.3f} ft² (AUTO)\n{chosen['raw']}"
            else:
                print(f"Real area:  {real_m2:.4f} m² ({real_in2:.2f} in²)")
                self.last_text = f"{real_m2:.3f} m² (AUTO)\n{chosen['raw']}"

            # auto-select scale in UI list
            if auto_idx is not None:
                self._set_radio_active(auto_idx)

        self.log_measurement(auto_idx=auto_idx, user_idx=auto_idx)
        self.redraw()

    # -------------------------------------------------
    # MANUAL SCALE OVERRIDE (RadioButtons)
    # -------------------------------------------------
    def on_scale_radio_change(self, label: str):
        """
        User clicked a different scale from the list.
        We recompute real-world result using the cached paper distance/area.
        """
        if not self.scale_boxes_disp:
            return
        try:
            idx = int(label.split(")")[0]) - 1
        except Exception:
            return
        idx = max(0, min(idx, len(self.scale_boxes_disp) - 1))
        chosen = self.scale_boxes_disp[idx]

        # If no previous measurement, just print selected scale
        if self.last_type is None:
            print(f"[SCALE SELECTED] {chosen['kind']}: {chosen.get('raw','')}")
            return

        # If user picked NTS/AS NOTED => no real conversion
        if chosen["kind"] != "OK" or chosen.get("ratio") is None:
            if self.last_type == "distance" and self.last_paper_in is not None:
                paper_in = float(self.last_paper_in)
                paper_mm = float(self.last_paper_mm or (paper_in * 25.4))
                self.last_text = f"{paper_in:.3f} in (paper)\n{chosen['kind']}"
                print(f"\n[MANUAL] Selected: {chosen['kind']}")
                print(f"Paper distance: {paper_in:.4f} in ({paper_mm:.2f} mm)")
                print("Real distance:  not available for NTS/AS NOTED.")
            elif self.last_type == "area" and self.last_paper_in2 is not None:
                paper_in2 = float(self.last_paper_in2)
                paper_mm2 = float(self.last_paper_mm2 or (paper_in2 * (25.4**2)))
                self.last_text = f"{paper_in2:.3f} in² (paper)\n{chosen['kind']}"
                print(f"\n[MANUAL] Selected: {chosen['kind']}")
                print(f"Paper area: {paper_in2:.4f} in² ({paper_mm2:.2f} mm²)")
                print("Real area:  not available for NTS/AS NOTED.")

            self.redraw()

            # log correction if it differs from auto
            if self.last_auto_idx is not None and idx != self.last_auto_idx:
                self.log_correction(auto_idx=self.last_auto_idx, user_idx=idx)
            return

        # numeric scale selected => convert
        ratio = chosen["ratio"]

        if self.last_type == "distance" and self.last_paper_in is not None:
            paper_in = float(self.last_paper_in)
            paper_mm = float(self.last_paper_mm or (paper_in * 25.4))
            real_in, real_ft, real_m = real_distance_from_paper(paper_in, ratio)

            print(f"\n[MANUAL] Selected scale: {chosen['raw']}")
            print(f"Paper distance: {paper_in:.4f} in ({paper_mm:.2f} mm)")
            if REAL_UNITS.lower() == "ft":
                print(f"Real distance:  {real_ft:.4f} ft ({real_in:.2f} in)")
                self.last_text = f"{real_ft:.3f} ft (MANUAL)\n{chosen['raw']}"
            else:
                print(f"Real distance:  {real_m:.4f} m ({real_in:.2f} in)")
                self.last_text = f"{real_m:.3f} m (MANUAL)\n{chosen['raw']}"

        elif self.last_type == "area" and self.last_paper_in2 is not None:
            paper_in2 = float(self.last_paper_in2)
            paper_mm2 = float(self.last_paper_mm2 or (paper_in2 * (25.4**2)))
            real_in2, real_ft2, real_m2 = real_area_from_paper(paper_in2, ratio)

            print(f"\n[MANUAL] Selected scale: {chosen['raw']}")
            print(f"Paper area: {paper_in2:.4f} in² ({paper_mm2:.2f} mm²)")
            if REAL_UNITS.lower() == "ft":
                print(f"Real area:  {real_ft2:.4f} ft² ({real_in2:.2f} in²)")
                self.last_text = f"{real_ft2:.3f} ft² (MANUAL)\n{chosen['raw']}"
            else:
                print(f"Real area:  {real_m2:.4f} m² ({real_in2:.2f} in²)")
                self.last_text = f"{real_m2:.3f} m² (MANUAL)\n{chosen['raw']}"

        self.redraw()

        if self.last_auto_idx is not None and idx != self.last_auto_idx:
            self.log_correction(auto_idx=self.last_auto_idx, user_idx=idx)

    # -------------------------------------------------
    # MARK SCALE AREA (USER HELPS SCALE DETECTION)
    # -------------------------------------------------
    def start_mark_area(self):
        """
        Activates a RectangleSelector tool.
        User drags a rectangle around where they see the scale text.
        We then try to parse scales from lines intersecting that rectangle.
        """
        if not self.doc or self.arr is None:
            return

        # disable old selector if exists
        if self.rs is not None:
            try:
                self.rs.set_active(False)
            except Exception:
                pass
            self.rs = None

        print("\n[Mark Scale Area] Drag rectangle around the scale text and release.")
        self.rs = RectangleSelector(
            self.ax,
            self.on_area_selected,
            useblit=True,
            button=[1],
            interactive=True
        )

    def on_area_selected(self, eclick, erelease):
        """
        Callback when rectangle is drawn and released.
        We find text lines intersecting the rectangle and try to parse scales.
        """
        # turn off selector
        if self.rs is not None:
            try:
                self.rs.set_active(False)
            except Exception:
                pass
            self.rs = None

        if (eclick.xdata is None or eclick.ydata is None or
                erelease.xdata is None or erelease.ydata is None):
            return

        # rectangle in DISPLAY coords
        x0 = min(eclick.xdata, erelease.xdata)
        x1 = max(eclick.xdata, erelease.xdata)
        y0 = min(eclick.ydata, erelease.ydata)
        y1 = max(eclick.ydata, erelease.ydata)
        rect_disp = (float(x0), float(y0), float(x1), float(y1))

        # collect all text lines that intersect this rectangle
        lines_in_area = []
        for ln in self.all_lines_disp:
            bb = ln["bbox_px_disp"]
            if bbox_intersects(bb, rect_disp):
                lines_in_area.append(ln)

        # parse each line directly
        new_candidates = []
        for ln in lines_in_area:
            kind, ratio, raw = parse_scale_to_ratio_paper_in_per_real_in(ln["text"])
            if kind in ("OK", "NTS", "AS_NOTED"):
                new_candidates.append({
                    "raw": raw if raw else ln["text"],
                    "ratio": ratio,
                    "kind": kind,
                    "full_line": ln["text"],
                    "bbox_px": ln["bbox_px"],  # base px bbox
                })

        # also attempt simple multiline joins by grouping nearby lines
        def y_center(bb): return (bb[1] + bb[3]) / 2.0
        area_lines_sorted = sorted(
            lines_in_area,
            key=lambda L: (y_center(L["bbox_px_disp"]), L["bbox_px_disp"][0])
        )

        groups = []
        cur = []
        last_y = None
        y_thresh = 18.0  # pixels: vertical grouping threshold
        for ln in area_lines_sorted:
            yc = y_center(ln["bbox_px_disp"])
            if last_y is None or abs(yc - last_y) <= y_thresh:
                cur.append(ln)
            else:
                if cur:
                    groups.append(cur)
                cur = [ln]
            last_y = yc
        if cur:
            groups.append(cur)

        for g in groups:
            g_sorted = sorted(g, key=lambda L: L["bbox_px_disp"][0])
            combo_text = " ".join([L["text"] for L in g_sorted])
            kind, ratio, raw = parse_scale_to_ratio_paper_in_per_real_in(combo_text)
            if kind in ("OK", "NTS", "AS_NOTED"):
                # union bbox in BASE coords
                xs0, ys0, xs1, ys1 = [], [], [], []
                for L in g_sorted:
                    b = L["bbox_px"]
                    xs0.append(b[0]); ys0.append(b[1]); xs1.append(b[2]); ys1.append(b[3])
                union_bb = (min(xs0), min(ys0), max(xs1), max(ys1))
                new_candidates.append({
                    "raw": raw if raw else combo_text,
                    "ratio": ratio,
                    "kind": kind,
                    "full_line": combo_text,
                    "bbox_px": union_bb,
                })

        # dedupe candidates by (kind, raw)
        seen = set()
        uniq = []
        for c in new_candidates:
            key = (c["kind"], c["raw"])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(c)

        if not uniq:
            print("[Mark Scale Area] Still no scales detected in that area.")
            log_event({
                "type": "mark_area_no_scale",
                "pdf": str(self.pdf_path),
                "page": self.page_index + 1,
                "rot_deg": (self.rot_k % 4) * 90,
                "rect_disp": rect_disp,
            })
            return

        # Add new scales to base list (avoid duplicates)
        existing_keys = {(s["kind"], s["raw"]) for s in self.scale_boxes_base}
        added = 0
        for c in uniq:
            key = (c["kind"], c["raw"])
            if key in existing_keys:
                continue
            self.scale_boxes_base.append({
                "raw": c["raw"],
                "ratio": c["ratio"],
                "kind": c["kind"],
                "full_line": c["full_line"],
                "bbox_pts": None,   # we don't have PDF pts for this new scale
                "bbox_px": c["bbox_px"],
            })
            existing_keys.add(key)
            added += 1

        print(f"[Mark Scale Area] Added {added} new scale(s). Total now: {len(self.scale_boxes_base)}")

        # re-apply rotation and refresh scale list
        self.apply_rotation()
        self._build_scale_panel(self._labels_for_scales())
        self.redraw()

        log_event({
            "type": "mark_area_found_scales",
            "pdf": str(self.pdf_path),
            "page": self.page_index + 1,
            "rot_deg": (self.rot_k % 4) * 90,
            "rect_disp": rect_disp,
            "added": added,
            "total_scales": len(self.scale_boxes_base),
        })

    # -------------------------------------------------
    # LOGGING HELPERS
    # -------------------------------------------------
    def _candidates_for_log(self):
        """
        Save scale candidate list in normalized coordinates so it is resolution-independent.
        """
        out = []
        for s in self.scale_boxes_disp:
            x0, y0, x1, y1 = s["bbox_px"]
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            out.append({
                "kind": s["kind"],
                "raw": s.get("raw"),
                "ratio": s.get("ratio"),
                "bbox_norm": [
                    x0 / max(1, self.w), y0 / max(1, self.h),
                    x1 / max(1, self.w), y1 / max(1, self.h)
                ],
                "center_norm": [cx / max(1, self.w), cy / max(1, self.h)],
            })
        return out

    def log_measurement(self, auto_idx, user_idx):
        """Log a measurement action."""
        if not self.doc:
            return

        mid_norm = None
        if self.last_mid_disp is not None:
            mid_norm = [
                self.last_mid_disp[0] / max(1, self.w),
                self.last_mid_disp[1] / max(1, self.h)
            ]

        payload = {
            "type": "measurement",
            "measure_kind": self.last_type,
            "pdf": str(self.pdf_path),
            "page": self.page_index + 1,
            "rot_deg": (self.rot_k % 4) * 90,
            "dpi": BASE_DPI,
            "units": REAL_UNITS,
            "auto_idx": auto_idx,
            "user_idx": user_idx,
            "click_mid_norm": mid_norm,
            "candidates": self._candidates_for_log(),
        }
        if self.last_type == "distance":
            payload["paper_in"] = self.last_paper_in
            payload["paper_mm"] = self.last_paper_mm
        if self.last_type == "area":
            payload["paper_in2"] = self.last_paper_in2
            payload["paper_mm2"] = self.last_paper_mm2

        log_event(payload)

    def log_correction(self, auto_idx, user_idx):
        """Log when user overrides auto-selected scale."""
        log_event({
            "type": "scale_correction",
            "measure_kind": self.last_type,
            "pdf": str(self.pdf_path),
            "page": self.page_index + 1,
            "rot_deg": (self.rot_k % 4) * 90,
            "dpi": BASE_DPI,
            "auto_idx": auto_idx,
            "user_idx": user_idx,
            "paper_in": self.last_paper_in,
            "paper_in2": self.last_paper_in2,
            "click_mid_norm": (
                [
                    self.last_mid_disp[0] / max(1, self.w),
                    self.last_mid_disp[1] / max(1, self.h)
                ]
                if self.last_mid_disp else None
            ),
            "candidates": self._candidates_for_log(),
        })


# =====================================================
# 9) MAIN ENTRY
# =====================================================
def main():
    app = PlanViewer()
    plt.show()


if __name__ == "__main__":
    main()
