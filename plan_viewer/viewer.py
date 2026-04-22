from __future__ import annotations

import fitz
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.widgets import Button, RadioButtons, RectangleSelector, TextBox

from .config import BASE_DPI, REAL_UNITS, SHOW_SCALE_BOXES
from .file_picker import pick_pdf_file
from .geometry import (
    base_to_disp,
    bbox_intersects,
    disp_to_base,
    paper_area_from_pixels,
    paper_distance_from_pixels,
    pick_nearest_numeric_scale,
    pts_bbox_to_pixels,
    real_area_from_paper,
    real_distance_from_paper,
    rotate_bbox,
)
from .logging_utils import log_event
from .scales import (
    extract_all_text_lines,
    extract_scale_candidates_from_lines,
    parse_scale_to_ratio_paper_in_per_real_in,
)


class PlanViewer:
    def __init__(self):
        self.brand_name = "Construction Scaler"
        self.current_screen = "home"
        self.home_focus = "overview"
        self.pdf_path = None
        self.doc = None
        self.page_index = 0
        self.rot_k = 0

        self.arr0 = None
        self.h0 = 0
        self.w0 = 0
        self.arr = None
        self.h = 0
        self.w = 0

        self.all_lines_base = []
        self.all_lines_disp = []
        self.scale_boxes_base = []
        self.scale_boxes_disp = []

        self.show_boxes = SHOW_SCALE_BOXES
        self.mode = "distance"

        self.p1_base = None
        self.p2_base = None
        self.poly_points_base = []

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

        self.view_zoom = 1.0
        self.cx = 0.0
        self.cy = 0.0
        self.rs = None

        self.fig, self.ax = plt.subplots(figsize=(13.5, 8))
        self.fig.patch.set_facecolor("#f4f1ea")
        plt.subplots_adjust(right=0.78, bottom=0.24, top=0.82)

        self._build_ui()
        self.vline = None
        self.hline = None

        self.fig.canvas.mpl_connect("scroll_event", self.on_scroll)
        self.fig.canvas.mpl_connect("button_press_event", self.on_click)
        self.fig.canvas.mpl_connect("key_press_event", self.on_key)
        self.fig.canvas.mpl_connect("motion_notify_event", self.on_move)

        self.show_home()

    def _build_ui(self):
        self.workspace_axes = []
        self.header_axes = []
        self.home_axes = []

        def btn(x, y, label, cb, w=0.10, h=0.06, color="#d7c3a3", hover="#c8ad85", text_color="#2f2419"):
            axis = self.fig.add_axes([x, y, w, h])
            axis.set_facecolor(color)
            button = Button(axis, label)
            button.color = color
            button.hovercolor = hover
            button.label.set_color(text_color)
            button.on_clicked(cb)
            return axis, button

        self.ax_nav = self.fig.add_axes([0.02, 0.86, 0.96, 0.10])
        self.ax_nav.set_facecolor("#1f3a3d")
        self.ax_nav.set_xticks([])
        self.ax_nav.set_yticks([])
        for spine in self.ax_nav.spines.values():
            spine.set_visible(False)

        self.nav_home_ax, self.btn_nav_home = btn(0.58, 0.885, "Home", lambda _e: self.show_home("overview"), w=0.08, h=0.045, color="#e5d6bf", hover="#d9c2a1")
        self.nav_about_ax, self.btn_nav_about = btn(0.67, 0.885, "About Us", lambda _e: self.show_home("about"), w=0.09, h=0.045, color="#e5d6bf", hover="#d9c2a1")
        self.nav_services_ax, self.btn_nav_services = btn(0.77, 0.885, "What We Provide", lambda _e: self.show_home("services"), w=0.12, h=0.045, color="#e5d6bf", hover="#d9c2a1")
        self.nav_test_ax, self.btn_nav_test = btn(0.90, 0.885, "Test Tool", lambda _e: self.launch_test_tool(), w=0.08, h=0.045, color="#d48a42", hover="#bf7430", text_color="white")
        self.header_axes.extend([self.nav_home_ax, self.nav_about_ax, self.nav_services_ax, self.nav_test_ax])

        self.ax_footer = self.fig.add_axes([0.02, 0.01, 0.96, 0.05])
        self.ax_footer.set_facecolor("#1f3a3d")
        self.ax_footer.set_xticks([])
        self.ax_footer.set_yticks([])
        for spine in self.ax_footer.spines.values():
            spine.set_visible(False)

        self.home_tool_ax, self.btn_home_tool = btn(0.08, 0.18, "Launch Test Tool", lambda _e: self.launch_test_tool(), w=0.18, h=0.07, color="#d48a42", hover="#bf7430", text_color="white")
        self.home_open_ax, self.btn_home_open = btn(0.28, 0.18, "Open Project PDF", lambda _e: self.open_pdf_dialog(), w=0.18, h=0.07, color="#6d8b74", hover="#57705d", text_color="white")
        self.home_axes.extend([self.home_tool_ax, self.home_open_ax])

        def workspace_btn(x, y, label, cb, w=0.10, h=0.06):
            axis, button = btn(x, y, label, cb, w=w, h=h)
            self.workspace_axes.append(axis)
            return button

        y1 = 0.03
        self.btn_home = workspace_btn(0.02, y1, "Home", lambda _e: self.show_home(), w=0.06)
        self.btn_open = workspace_btn(0.09, y1, "Open PDF", lambda _e: self.open_pdf_dialog(), w=0.09)
        self.btn_prev = workspace_btn(0.19, y1, "Prev", lambda _e: self.prev_page(), w=0.06)
        self.btn_next = workspace_btn(0.26, y1, "Next", lambda _e: self.next_page(), w=0.06)
        self.btn_rot_l = workspace_btn(0.33, y1, "Rotate CCW", lambda _e: self.rotate_ccw(), w=0.09)
        self.btn_rot_r = workspace_btn(0.43, y1, "Rotate CW", lambda _e: self.rotate_cw(), w=0.08)
        self.btn_mode_dist = workspace_btn(0.52, y1, "Distance", lambda _e: self.set_mode("distance"), w=0.08)
        self.btn_mode_area = workspace_btn(0.61, y1, "Area", lambda _e: self.set_mode("area"), w=0.06)
        self.btn_reset = workspace_btn(0.68, y1, "Reset", lambda _e: self.reset_view(), w=0.06)
        self.btn_boxes = workspace_btn(0.75, y1, "Scale Boxes", lambda _e: self.toggle_boxes(), w=0.09)
        self.btn_mark = workspace_btn(0.85, y1, "Mark Scale Area", lambda _e: self.start_mark_area(), w=0.12)
        self.btn_clear = workspace_btn(0.98 - 0.05, y1, "Clear", lambda _e: self.clear_all(), w=0.05)

        y2 = 0.12
        ax_tb = self.fig.add_axes([0.02, y2, 0.10, 0.06])
        self.workspace_axes.append(ax_tb)
        self.page_box = TextBox(ax_tb, "Page", initial="1")
        self.page_box.on_submit(lambda _txt: self.go_to_page_from_box())

        ax_go = self.fig.add_axes([0.13, y2, 0.05, 0.06])
        self.workspace_axes.append(ax_go)
        self.btn_go = Button(ax_go, "Go")
        self.btn_go.on_clicked(lambda _e: self.go_to_page_from_box())

        self.ax_scale = self.fig.add_axes([0.80, 0.22, 0.18, 0.74])
        self.workspace_axes.append(self.ax_scale)
        self.ax_scale.set_title("Scales (click to change)")
        self.ax_scale.axis("off")
        self.radio = None
        self._build_scale_panel([])
        self._set_workspace_visibility(False)

    def _set_workspace_visibility(self, visible: bool):
        for axis in self.workspace_axes:
            axis.set_visible(visible)

    def _set_home_visibility(self, visible: bool):
        for axis in self.home_axes:
            axis.set_visible(visible)

    def show_home(self, focus: str = "overview"):
        self.current_screen = "home"
        self.home_focus = focus
        self._set_workspace_visibility(False)
        self._set_home_visibility(True)
        self._draw_brand_shell()
        self._draw_home_screen()

    def launch_test_tool(self):
        self.current_screen = "workspace"
        self._set_home_visibility(False)
        self._set_workspace_visibility(True)
        if self.arr is None:
            self.redraw_empty("Open a construction drawing PDF to begin measuring.")
        else:
            self.redraw()

    def _draw_brand_shell(self):
        self.ax_nav.clear()
        self.ax_nav.set_facecolor("#1f3a3d")
        self.ax_nav.set_xticks([])
        self.ax_nav.set_yticks([])
        for spine in self.ax_nav.spines.values():
            spine.set_visible(False)
        self.ax_nav.text(0.02, 0.62, self.brand_name, color="white", fontsize=21, fontweight="bold", transform=self.ax_nav.transAxes)
        self.ax_nav.text(0.02, 0.20, "Offline plan measurement for builders, estimators, and project teams.", color="#d9e6df", fontsize=10, transform=self.ax_nav.transAxes)

        self.ax_footer.clear()
        self.ax_footer.set_facecolor("#1f3a3d")
        self.ax_footer.set_xticks([])
        self.ax_footer.set_yticks([])
        for spine in self.ax_footer.spines.values():
            spine.set_visible(False)
        self.ax_footer.text(0.02, 0.52, "Construction Scaler", color="white", fontsize=10, fontweight="bold", transform=self.ax_footer.transAxes, va="center")
        self.ax_footer.text(0.28, 0.52, "About Us", color="#d9e6df", fontsize=9, transform=self.ax_footer.transAxes, va="center")
        self.ax_footer.text(0.40, 0.52, "What We Provide", color="#d9e6df", fontsize=9, transform=self.ax_footer.transAxes, va="center")
        self.ax_footer.text(0.60, 0.52, "Test Tool", color="#d9e6df", fontsize=9, transform=self.ax_footer.transAxes, va="center")
        self.ax_footer.text(0.98, 0.52, "Professional offline PDF measurement workflow", color="#d9e6df", fontsize=9, transform=self.ax_footer.transAxes, va="center", ha="right")

    def _draw_home_screen(self):
        self.ax.clear()
        self.ax.set_facecolor("#f4f1ea")
        self.ax.axis("off")

        accent = {
            "overview": "#d48a42",
            "about": "#6d8b74",
            "services": "#5e7b8c",
        }.get(self.home_focus, "#d48a42")

        self.ax.add_patch(
            patches.FancyBboxPatch(
                (0.04, 0.58),
                0.72,
                0.30,
                boxstyle="round,pad=0.02,rounding_size=0.03",
                facecolor="#f8f6f2",
                edgecolor="#d8cfbf",
                linewidth=1.5,
                transform=self.ax.transAxes,
            )
        )
        self.ax.add_patch(
            patches.FancyBboxPatch(
                (0.79, 0.58),
                0.17,
                0.30,
                boxstyle="round,pad=0.02,rounding_size=0.03",
                facecolor=accent,
                edgecolor=accent,
                linewidth=1.2,
                transform=self.ax.transAxes,
                alpha=0.96,
            )
        )
        self.ax.add_patch(
            patches.FancyBboxPatch(
                (0.04, 0.12),
                0.28,
                0.36,
                boxstyle="round,pad=0.02,rounding_size=0.03",
                facecolor="#fbfaf7",
                edgecolor="#d8cfbf",
                linewidth=1.2,
                transform=self.ax.transAxes,
            )
        )
        self.ax.add_patch(
            patches.FancyBboxPatch(
                (0.36, 0.12),
                0.28,
                0.36,
                boxstyle="round,pad=0.02,rounding_size=0.03",
                facecolor="#fbfaf7",
                edgecolor="#d8cfbf",
                linewidth=1.2,
                transform=self.ax.transAxes,
            )
        )
        self.ax.add_patch(
            patches.FancyBboxPatch(
                (0.68, 0.12),
                0.28,
                0.36,
                boxstyle="round,pad=0.02,rounding_size=0.03",
                facecolor="#fbfaf7",
                edgecolor="#d8cfbf",
                linewidth=1.2,
                transform=self.ax.transAxes,
            )
        )

        self.ax.text(0.07, 0.82, "Construction PDF measurement that feels production-ready.", fontsize=22, fontweight="bold", color="#1f2b2d", transform=self.ax.transAxes)
        self.ax.text(0.07, 0.70, "Open drawing sets, detect scales from the PDF text layer, measure distance and area, and keep everything offline for field-friendly workflows.", fontsize=11, color="#48585a", transform=self.ax.transAxes)
        self.ax.text(0.82, 0.80, "MVP", fontsize=24, fontweight="bold", color="white", transform=self.ax.transAxes, ha="center")
        self.ax.text(0.82, 0.68, "Professional UI\nOffline workflow\nUser-ready test tool", fontsize=11, color="white", transform=self.ax.transAxes, ha="center", va="center")

        self.ax.text(0.07, 0.44, "About Us", fontsize=16, fontweight="bold", color="#1f2b2d", transform=self.ax.transAxes)
        self.ax.text(0.07, 0.34, "We built Construction Scaler for estimators, site engineers, and project managers who need fast quantity checks without cloud lock-in. The goal is simple: make plan review clearer, faster, and more dependable.", fontsize=10.5, color="#4f5b5c", transform=self.ax.transAxes, wrap=True)

        self.ax.text(0.39, 0.44, "What We Provide", fontsize=16, fontweight="bold", color="#1f2b2d", transform=self.ax.transAxes)
        self.ax.text(0.39, 0.35, "1. One-page PDF rendering for responsive navigation\n2. Automatic scale detection from text layers\n3. Distance and area takeoff support\n4. Manual scale review and mark-area recovery\n5. Offline usage with local activity logging", fontsize=10.3, color="#4f5b5c", transform=self.ax.transAxes, linespacing=1.5)

        self.ax.text(0.71, 0.44, "Test Tool", fontsize=16, fontweight="bold", color="#1f2b2d", transform=self.ax.transAxes)
        self.ax.text(0.71, 0.35, "Use the test tool to open a project PDF and measure sheets directly. This is the working MVP workspace your users will interact with during validation and pilot testing.", fontsize=10.5, color="#4f5b5c", transform=self.ax.transAxes, wrap=True)
        self.ax.text(0.71, 0.18, "Use the orange button above to launch the tool.", fontsize=10.5, color="#d48a42", fontweight="bold", transform=self.ax.transAxes)

        self.fig.canvas.draw_idle()

    def redraw_empty(self, msg: str):
        self._draw_brand_shell()
        self.ax.clear()
        self.ax.set_facecolor("#f4f1ea")
        self.ax.axis("off")
        self.ax.text(0.05, 0.86, "Measurement Workspace", fontsize=20, fontweight="bold", color="#1f2b2d", transform=self.ax.transAxes)
        self.ax.text(0.05, 0.76, msg, fontsize=11, color="#536163", transform=self.ax.transAxes)
        self.ax.add_patch(
            patches.FancyBboxPatch(
                (0.05, 0.24),
                0.90,
                0.38,
                boxstyle="round,pad=0.02,rounding_size=0.03",
                facecolor="#fbfaf7",
                edgecolor="#d8cfbf",
                linewidth=1.2,
                transform=self.ax.transAxes,
            )
        )
        self.ax.text(0.08, 0.53, "What this workspace supports", fontsize=14, fontweight="bold", color="#1f2b2d", transform=self.ax.transAxes)
        self.ax.text(0.08, 0.41, "Open one drawing page at a time, inspect detected scales, measure linework, calculate polygon areas, rotate pages for readability, and recover scales manually when a scanned sheet has weak text detection.", fontsize=10.2, color="#4f5b5c", transform=self.ax.transAxes, wrap=True)
        self.fig.canvas.draw_idle()

    def _build_scale_panel(self, labels):
        self.ax_scale.clear()
        self.ax_scale.set_title("Scales (click to change)", fontsize=10)
        if not labels:
            self.ax_scale.text(0.02, 0.98, "No scales detected.\nUse 'Mark Scale Area'.", va="top", fontsize=9)
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
        labels = []
        for idx, scale in enumerate(self.scale_boxes_disp):
            raw = (scale.get("raw") or "").strip().replace("\n", " ")
            if len(raw) > 34:
                raw = raw[:34] + "..."
            labels.append(f"{idx + 1}) {scale['kind']}: {raw}")
        return labels

    def _set_radio_active(self, idx: int | None):
        if self.radio is None or idx is None:
            return
        idx = max(0, min(idx, len(self.scale_boxes_disp) - 1))
        try:
            self.radio.set_active(idx)
        except Exception:
            pass

    def set_mode(self, mode: str):
        if mode not in ("distance", "area"):
            return
        self.mode = mode
        self.p1_base = None
        self.p2_base = None
        self.poly_points_base = []
        self.redraw()

    def open_pdf_dialog(self, initial=False):
        self.current_screen = "workspace"
        self._set_home_visibility(False)
        self._set_workspace_visibility(True)
        path = pick_pdf_file()
        if not path:
            if initial:
                print("No PDF selected. Close window or click Open PDF.")
                self.show_home()
            elif self.arr is None:
                self.redraw_empty("Open a construction drawing PDF to begin measuring.")
            return
        self.open_pdf(path)

    def open_pdf(self, path: str):
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass

        self.pdf_path = path
        self.doc = fitz.open(path)
        self.page_index = 0
        self.rot_k = 0
        self.current_screen = "workspace"
        self._set_home_visibility(False)
        self._set_workspace_visibility(True)
        self.clear_all(keep_pdf=True, redraw_now=False)
        self.load_page(0)

    def load_page(self, idx0: int):
        if self.doc is None:
            return

        idx0 = max(0, min(idx0, self.doc.page_count - 1))
        self.page_index = idx0
        page = self.doc[self.page_index]

        zoom = BASE_DPI / 72.0
        matrix = page.rotation_matrix * fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        self.arr0 = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, 3))
        self.h0, self.w0 = self.arr0.shape[:2]

        self.all_lines_base = extract_all_text_lines(page)
        for line in self.all_lines_base:
            line["bbox_px"] = pts_bbox_to_pixels(page, line["bbox_pts"], BASE_DPI)

        self.scale_boxes_base = extract_scale_candidates_from_lines(self.all_lines_base)
        for scale in self.scale_boxes_base:
            scale["bbox_px"] = pts_bbox_to_pixels(page, scale["bbox_pts"], BASE_DPI)

        self.apply_rotation()
        self.view_zoom = 1.0
        self.cx = self.w / 2.0
        self.cy = self.h / 2.0
        self.page_box.set_val(str(self.page_index + 1))
        self._build_scale_panel(self._labels_for_scales())

        print(f"\n[Page {self.page_index + 1}/{self.doc.page_count}] Scales detected: {len(self.scale_boxes_disp)}")
        if not self.scale_boxes_disp:
            print("  -> No scale text found on this page (text layer).")
        else:
            for scale in self.scale_boxes_disp[:8]:
                print(f"  - {scale['kind']}: {scale['raw']}")

        self.redraw()

    def apply_rotation(self):
        self.arr = np.rot90(self.arr0, self.rot_k)
        self.h, self.w = self.arr.shape[:2]

        self.all_lines_disp = []
        for line in self.all_lines_base:
            rotated_bbox = rotate_bbox(line["bbox_px"], self.rot_k, self.w0, self.h0)
            self.all_lines_disp.append({**line, "bbox_px_disp": rotated_bbox})

        self.scale_boxes_disp = []
        for scale in self.scale_boxes_base:
            rotated_bbox = rotate_bbox(scale["bbox_px"], self.rot_k, self.w0, self.h0)
            self.scale_boxes_disp.append({**scale, "bbox_px_disp": rotated_bbox})

        for scale in self.scale_boxes_disp:
            scale["bbox_px"] = scale["bbox_px_disp"]

    def update_title(self):
        rot_deg = (self.rot_k % 4) * 90
        ok_count = sum(1 for scale in self.scale_boxes_disp if scale["kind"] == "OK")
        mode_text = "DISTANCE" if self.mode == "distance" else "AREA"
        self.ax.set_title(
            f"{self.brand_name} | {self.pdf_path}\n"
            f"Page {self.page_index + 1}/{self.doc.page_count} | Rotation {rot_deg} deg | "
            f"Zoom {self.view_zoom:.2f}x | Mode: {mode_text} | Numeric scales: {ok_count}\n"
            "Wheel=zoom | Left click=add | Right click=finish polygon (AREA) or clear picks (DIST) | "
            "n/p next/prev | [ ] rotate | r reset | b boxes | c clear last | q quit"
        )

    def apply_view(self):
        vw = self.w / self.view_zoom
        vh = self.h / self.view_zoom
        x0 = max(0, self.cx - vw / 2.0)
        x1 = min(self.w, self.cx + vw / 2.0)
        y0 = max(0, self.cy - vh / 2.0)
        y1 = min(self.h, self.cy + vh / 2.0)
        self.ax.set_xlim(x0, x1)
        self.ax.set_ylim(y1, y0)
        self.update_title()

    def reset_view(self):
        if self.arr is None:
            return
        self.view_zoom = 1.0
        self.cx = self.w / 2.0
        self.cy = self.h / 2.0
        self.redraw()

    def toggle_boxes(self):
        self.show_boxes = not self.show_boxes
        self.redraw()

    def next_page(self):
        if self.doc and self.page_index < self.doc.page_count - 1:
            self.p1_base = None
            self.p2_base = None
            self.poly_points_base = []
            self.load_page(self.page_index + 1)

    def prev_page(self):
        if self.doc and self.page_index > 0:
            self.p1_base = None
            self.p2_base = None
            self.poly_points_base = []
            self.load_page(self.page_index - 1)

    def go_to_page_from_box(self):
        if not self.doc:
            return
        raw = self.page_box.text.strip()
        if not raw:
            return
        try:
            page_number = int(raw)
        except ValueError:
            print("Invalid page number.")
            return
        page_number = max(1, min(self.doc.page_count, page_number))
        self.p1_base = None
        self.p2_base = None
        self.poly_points_base = []
        self.load_page(page_number - 1)

    def rotate_ccw(self):
        if self.arr0 is None:
            return
        self.rot_k = (self.rot_k + 1) % 4
        self.apply_rotation()
        self._build_scale_panel(self._labels_for_scales())
        self.redraw()

    def rotate_cw(self):
        if self.arr0 is None:
            return
        self.rot_k = (self.rot_k - 1) % 4
        self.apply_rotation()
        self._build_scale_panel(self._labels_for_scales())
        self.redraw()

    def clear_last_measure(self, redraw_now: bool = True):
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

    def redraw(self):
        if self.arr is None:
            self.redraw_empty("No PDF loaded. Click 'Open PDF'.")
            return

        self._draw_brand_shell()
        self.ax.clear()
        self.ax.set_facecolor("#f4f1ea")
        self.ax.imshow(self.arr, origin="upper")
        self.ax.axis("off")
        self.vline = self.ax.axvline(0, linewidth=1, alpha=0.5, visible=False)
        self.hline = self.ax.axhline(0, linewidth=1, alpha=0.5, visible=False)

        if self.show_boxes:
            for scale in self.scale_boxes_disp:
                x0, y0, x1, y1 = scale["bbox_px"]
                rect = patches.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, linewidth=1)
                self.ax.add_patch(rect)

        if self.last_type == "distance" and self.last_line_base is not None:
            (bx1, by1), (bx2, by2) = self.last_line_base
            x1, y1 = base_to_disp(bx1, by1, self.rot_k, self.w0, self.h0)
            x2, y2 = base_to_disp(bx2, by2, self.rot_k, self.w0, self.h0)
            self.ax.plot([x1, x2], [y1, y2], linewidth=2)
            self.ax.plot([x1], [y1], marker="o", markersize=6)
            self.ax.plot([x2], [y2], marker="o", markersize=6)
            if self.last_text:
                mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                self.ax.text(mx, my, self.last_text, fontsize=10, bbox=dict(facecolor="white", alpha=0.85))

        if self.last_type == "area" and self.last_poly_base is not None:
            points = [base_to_disp(p[0], p[1], self.rot_k, self.w0, self.h0) for p in self.last_poly_base]
            poly = patches.Polygon(points, closed=True, fill=True, alpha=0.20)
            self.ax.add_patch(poly)
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            self.ax.plot(xs + [xs[0]], ys + [ys[0]], linewidth=2)
            for point in points:
                self.ax.plot([point[0]], [point[1]], marker="o", markersize=4)
            if self.last_text:
                self.ax.text(sum(xs) / len(xs), sum(ys) / len(ys), self.last_text, fontsize=10, bbox=dict(facecolor="white", alpha=0.85))

        if self.mode == "distance":
            if self.p1_base is not None:
                x1, y1 = base_to_disp(self.p1_base[0], self.p1_base[1], self.rot_k, self.w0, self.h0)
                self.ax.plot([x1], [y1], marker="x", markersize=9)
        elif self.poly_points_base:
            points = [base_to_disp(p[0], p[1], self.rot_k, self.w0, self.h0) for p in self.poly_points_base]
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            self.ax.plot(xs, ys, linewidth=1)
            for point in points:
                self.ax.plot([point[0]], [point[1]], marker="x", markersize=7)

        self.apply_view()
        self.fig.canvas.draw_idle()

    def on_move(self, event):
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

    def on_scroll(self, event):
        if self.arr is None:
            return
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        if event.button == "up":
            self.zoom_at(1.25, event.xdata, event.ydata)
        elif event.button == "down":
            self.zoom_at(1 / 1.25, event.xdata, event.ydata)

    def zoom_at(self, factor, x, y):
        if self.arr is None:
            return
        self.cx = max(0, min(self.w, x))
        self.cy = max(0, min(self.h, y))
        self.view_zoom = max(1.0, min(25.0, self.view_zoom * factor))
        self.redraw()

    def on_key(self, event):
        if self.current_screen != "workspace":
            if event.key in ("h", "home"):
                self.show_home()
            elif event.key in ("t", "enter"):
                self.launch_test_tool()
            return
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

    def on_click(self, event):
        if self.arr is None:
            return
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return

        xd, yd = float(event.xdata), float(event.ydata)
        xb, yb = disp_to_base(xd, yd, self.rot_k, self.w0, self.h0)

        if event.button == 3:
            if self.mode == "distance":
                self.p1_base = None
                self.p2_base = None
                self.redraw()
            else:
                self.finish_area_polygon()
            return

        if event.button != 1:
            return

        if self.mode == "distance":
            self.handle_distance_click(xb, yb)
        else:
            self.handle_area_click(xb, yb)

    def handle_distance_click(self, xb, yb):
        if self.p1_base is None:
            self.p1_base = (xb, yb)
            self.redraw()
            return

        p2_base = (xb, yb)
        x1d, y1d = base_to_disp(self.p1_base[0], self.p1_base[1], self.rot_k, self.w0, self.h0)
        x2d, y2d = base_to_disp(p2_base[0], p2_base[1], self.rot_k, self.w0, self.h0)
        mid = ((x1d + x2d) / 2.0, (y1d + y2d) / 2.0)
        self.last_mid_disp = mid

        _, paper_in, paper_mm = paper_distance_from_pixels((x1d, y1d), (x2d, y2d), BASE_DPI)
        self.last_paper_in = paper_in
        self.last_paper_mm = paper_mm
        self.last_paper_in2 = None
        self.last_paper_mm2 = None

        chosen, auto_idx = (None, None)
        if self.scale_boxes_disp:
            chosen, auto_idx = pick_nearest_numeric_scale(self.scale_boxes_disp, mid)
        self.last_auto_idx = auto_idx

        self.last_type = "distance"
        self.last_line_base = (self.p1_base, p2_base)
        self.last_poly_base = None
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
            if auto_idx is not None:
                self._set_radio_active(auto_idx)

        self.log_measurement(auto_idx=auto_idx, user_idx=auto_idx)
        self.redraw()

    def handle_area_click(self, xb, yb):
        self.poly_points_base.append((xb, yb))
        self.redraw()

    def finish_area_polygon(self):
        if len(self.poly_points_base) < 3:
            print("Area mode: need at least 3 points. Keep left-clicking to add points.")
            return

        points_disp = [base_to_disp(p[0], p[1], self.rot_k, self.w0, self.h0) for p in self.poly_points_base]
        xs = [point[0] for point in points_disp]
        ys = [point[1] for point in points_disp]
        centroid = (sum(xs) / len(xs), sum(ys) / len(ys))
        self.last_mid_disp = centroid

        _, paper_in2, paper_mm2 = paper_area_from_pixels(points_disp, BASE_DPI)
        self.last_paper_in2 = paper_in2
        self.last_paper_mm2 = paper_mm2
        self.last_paper_in = None
        self.last_paper_mm = None

        chosen, auto_idx = (None, None)
        if self.scale_boxes_disp:
            chosen, auto_idx = pick_nearest_numeric_scale(self.scale_boxes_disp, centroid)
        self.last_auto_idx = auto_idx

        self.last_type = "area"
        self.last_poly_base = list(self.poly_points_base)
        self.last_line_base = None
        self.poly_points_base = []

        if chosen is None or chosen.get("ratio") is None:
            self.last_text = f"{paper_in2:.3f} in^2 (paper)\nNO SCALE"
            print("\nNo numeric scale auto-found near polygon area.")
            print(f"Paper area: {paper_in2:.4f} in^2 ({paper_mm2:.2f} mm^2)")
        else:
            ratio = chosen["ratio"]
            real_in2, real_ft2, real_m2 = real_area_from_paper(paper_in2, ratio)
            print("\n[AUTO] Chosen scale:", chosen["raw"])
            print(f"Paper area: {paper_in2:.4f} in^2 ({paper_mm2:.2f} mm^2)")
            if REAL_UNITS.lower() == "ft":
                print(f"Real area:  {real_ft2:.4f} ft^2 ({real_in2:.2f} in^2)")
                self.last_text = f"{real_ft2:.3f} ft^2 (AUTO)\n{chosen['raw']}"
            else:
                print(f"Real area:  {real_m2:.4f} m^2 ({real_in2:.2f} in^2)")
                self.last_text = f"{real_m2:.3f} m^2 (AUTO)\n{chosen['raw']}"
            if auto_idx is not None:
                self._set_radio_active(auto_idx)

        self.log_measurement(auto_idx=auto_idx, user_idx=auto_idx)
        self.redraw()

    def on_scale_radio_change(self, label: str):
        if not self.scale_boxes_disp:
            return
        try:
            idx = int(label.split(")")[0]) - 1
        except Exception:
            return
        idx = max(0, min(idx, len(self.scale_boxes_disp) - 1))
        chosen = self.scale_boxes_disp[idx]

        if self.last_type is None:
            print(f"[SCALE SELECTED] {chosen['kind']}: {chosen.get('raw', '')}")
            return

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
                paper_mm2 = float(self.last_paper_mm2 or (paper_in2 * (25.4 ** 2)))
                self.last_text = f"{paper_in2:.3f} in^2 (paper)\n{chosen['kind']}"
                print(f"\n[MANUAL] Selected: {chosen['kind']}")
                print(f"Paper area: {paper_in2:.4f} in^2 ({paper_mm2:.2f} mm^2)")
                print("Real area:  not available for NTS/AS NOTED.")

            self.redraw()
            if self.last_auto_idx is not None and idx != self.last_auto_idx:
                self.log_correction(auto_idx=self.last_auto_idx, user_idx=idx)
            return

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
            paper_mm2 = float(self.last_paper_mm2 or (paper_in2 * (25.4 ** 2)))
            real_in2, real_ft2, real_m2 = real_area_from_paper(paper_in2, ratio)
            print(f"\n[MANUAL] Selected scale: {chosen['raw']}")
            print(f"Paper area: {paper_in2:.4f} in^2 ({paper_mm2:.2f} mm^2)")
            if REAL_UNITS.lower() == "ft":
                print(f"Real area:  {real_ft2:.4f} ft^2 ({real_in2:.2f} in^2)")
                self.last_text = f"{real_ft2:.3f} ft^2 (MANUAL)\n{chosen['raw']}"
            else:
                print(f"Real area:  {real_m2:.4f} m^2 ({real_in2:.2f} in^2)")
                self.last_text = f"{real_m2:.3f} m^2 (MANUAL)\n{chosen['raw']}"

        self.redraw()
        if self.last_auto_idx is not None and idx != self.last_auto_idx:
            self.log_correction(auto_idx=self.last_auto_idx, user_idx=idx)

    def start_mark_area(self):
        if not self.doc or self.arr is None:
            return
        if self.rs is not None:
            try:
                self.rs.set_active(False)
            except Exception:
                pass
            self.rs = None

        print("\n[Mark Scale Area] Drag rectangle around the scale text and release.")
        self.rs = RectangleSelector(self.ax, self.on_area_selected, useblit=True, button=[1], interactive=True)

    def on_area_selected(self, eclick, erelease):
        if self.rs is not None:
            try:
                self.rs.set_active(False)
            except Exception:
                pass
            self.rs = None

        if (
            eclick.xdata is None
            or eclick.ydata is None
            or erelease.xdata is None
            or erelease.ydata is None
        ):
            return

        x0 = min(eclick.xdata, erelease.xdata)
        x1 = max(eclick.xdata, erelease.xdata)
        y0 = min(eclick.ydata, erelease.ydata)
        y1 = max(eclick.ydata, erelease.ydata)
        rect_disp = (float(x0), float(y0), float(x1), float(y1))

        lines_in_area = []
        for line in self.all_lines_disp:
            if bbox_intersects(line["bbox_px_disp"], rect_disp):
                lines_in_area.append(line)

        new_candidates = []
        for line in lines_in_area:
            kind, ratio, raw = parse_scale_to_ratio_paper_in_per_real_in(line["text"])
            if kind in ("OK", "NTS", "AS_NOTED"):
                new_candidates.append(
                    {
                        "raw": raw if raw else line["text"],
                        "ratio": ratio,
                        "kind": kind,
                        "full_line": line["text"],
                        "bbox_px": line["bbox_px"],
                    }
                )

        def y_center(bbox):
            return (bbox[1] + bbox[3]) / 2.0

        area_lines_sorted = sorted(lines_in_area, key=lambda line: (y_center(line["bbox_px_disp"]), line["bbox_px_disp"][0]))
        groups = []
        current = []
        last_y = None
        y_thresh = 18.0
        for line in area_lines_sorted:
            yc = y_center(line["bbox_px_disp"])
            if last_y is None or abs(yc - last_y) <= y_thresh:
                current.append(line)
            else:
                if current:
                    groups.append(current)
                current = [line]
            last_y = yc
        if current:
            groups.append(current)

        for group in groups:
            sorted_group = sorted(group, key=lambda line: line["bbox_px_disp"][0])
            combo_text = " ".join(line["text"] for line in sorted_group)
            kind, ratio, raw = parse_scale_to_ratio_paper_in_per_real_in(combo_text)
            if kind in ("OK", "NTS", "AS_NOTED"):
                xs0, ys0, xs1, ys1 = [], [], [], []
                for line in sorted_group:
                    bbox = line["bbox_px"]
                    xs0.append(bbox[0])
                    ys0.append(bbox[1])
                    xs1.append(bbox[2])
                    ys1.append(bbox[3])
                union_bbox = (min(xs0), min(ys0), max(xs1), max(ys1))
                new_candidates.append(
                    {
                        "raw": raw if raw else combo_text,
                        "ratio": ratio,
                        "kind": kind,
                        "full_line": combo_text,
                        "bbox_px": union_bbox,
                    }
                )

        seen = set()
        unique = []
        for candidate in new_candidates:
            key = (candidate["kind"], candidate["raw"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)

        if not unique:
            print("[Mark Scale Area] Still no scales detected in that area.")
            log_event(
                {
                    "type": "mark_area_no_scale",
                    "pdf": str(self.pdf_path),
                    "page": self.page_index + 1,
                    "rot_deg": (self.rot_k % 4) * 90,
                    "rect_disp": rect_disp,
                }
            )
            return

        existing_keys = {(scale["kind"], scale["raw"]) for scale in self.scale_boxes_base}
        added = 0
        for candidate in unique:
            key = (candidate["kind"], candidate["raw"])
            if key in existing_keys:
                continue
            self.scale_boxes_base.append(
                {
                    "raw": candidate["raw"],
                    "ratio": candidate["ratio"],
                    "kind": candidate["kind"],
                    "full_line": candidate["full_line"],
                    "bbox_pts": None,
                    "bbox_px": candidate["bbox_px"],
                }
            )
            existing_keys.add(key)
            added += 1

        print(f"[Mark Scale Area] Added {added} new scale(s). Total now: {len(self.scale_boxes_base)}")
        self.apply_rotation()
        self._build_scale_panel(self._labels_for_scales())
        self.redraw()

        log_event(
            {
                "type": "mark_area_found_scales",
                "pdf": str(self.pdf_path),
                "page": self.page_index + 1,
                "rot_deg": (self.rot_k % 4) * 90,
                "rect_disp": rect_disp,
                "added": added,
                "total_scales": len(self.scale_boxes_base),
            }
        )

    def _candidates_for_log(self):
        candidates = []
        for scale in self.scale_boxes_disp:
            x0, y0, x1, y1 = scale["bbox_px"]
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            candidates.append(
                {
                    "kind": scale["kind"],
                    "raw": scale.get("raw"),
                    "ratio": scale.get("ratio"),
                    "bbox_norm": [x0 / max(1, self.w), y0 / max(1, self.h), x1 / max(1, self.w), y1 / max(1, self.h)],
                    "center_norm": [cx / max(1, self.w), cy / max(1, self.h)],
                }
            )
        return candidates

    def log_measurement(self, auto_idx, user_idx):
        if not self.doc:
            return

        mid_norm = None
        if self.last_mid_disp is not None:
            mid_norm = [self.last_mid_disp[0] / max(1, self.w), self.last_mid_disp[1] / max(1, self.h)]

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
        log_event(
            {
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
                    [self.last_mid_disp[0] / max(1, self.w), self.last_mid_disp[1] / max(1, self.h)]
                    if self.last_mid_disp
                    else None
                ),
                "candidates": self._candidates_for_log(),
            }
        )
