from __future__ import annotations

import math

import fitz


def pts_bbox_to_pixels(page: fitz.Page, bbox_pts, dpi: float):
    zoom = dpi / 72.0
    matrix = page.rotation_matrix * fitz.Matrix(zoom, zoom)
    rect = fitz.Rect(bbox_pts) * matrix
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def center_of_bbox(bbox):
    x0, y0, x1, y1 = bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def bbox_intersects(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 < bx0 or ax0 > bx1 or ay1 < by0 or ay0 > by1)


def pick_nearest_numeric_scale(scale_boxes_px, click_mid_px):
    mx, my = click_mid_px
    best = None
    best_idx = None
    for idx, scale in enumerate(scale_boxes_px):
        if scale["kind"] != "OK":
            continue
        cx, cy = center_of_bbox(scale["bbox_px"])
        dist = math.hypot(cx - mx, cy - my)
        if best is None or dist < best["dist"]:
            best = {**scale, "dist": dist}
            best_idx = idx
    return best, best_idx


def paper_distance_from_pixels(p1, p2, dpi: float):
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    dist_px = math.hypot(dx, dy)
    dist_in = dist_px / float(dpi)
    dist_mm = dist_in * 25.4
    return dist_px, dist_in, dist_mm


def polygon_area_px2(points_xy):
    if len(points_xy) < 3:
        return 0.0
    total = 0.0
    count = len(points_xy)
    for idx in range(count):
        jdx = (idx + 1) % count
        total += points_xy[idx][0] * points_xy[jdx][1] - points_xy[jdx][0] * points_xy[idx][1]
    return abs(total) / 2.0


def paper_area_from_pixels(points_xy, dpi: float):
    area_px2 = polygon_area_px2(points_xy)
    area_in2 = area_px2 / (float(dpi) ** 2)
    area_mm2 = area_in2 * (25.4 ** 2)
    return area_px2, area_in2, area_mm2


def real_distance_from_paper(paper_in: float, ratio_paper_in_per_real_in: float):
    real_in = paper_in / ratio_paper_in_per_real_in
    real_ft = real_in / 12.0
    real_m = real_in * 0.0254
    return real_in, real_ft, real_m


def real_area_from_paper(paper_in2: float, ratio_paper_in_per_real_in: float):
    real_in2 = paper_in2 / (ratio_paper_in_per_real_in ** 2)
    real_ft2 = real_in2 / 144.0
    real_m2 = real_in2 * (0.0254 ** 2)
    return real_in2, real_ft2, real_m2


def base_to_disp(x, y, k, w0, h0):
    k %= 4
    if k == 0:
        return x, y
    if k == 1:
        return y, (w0 - 1) - x
    if k == 2:
        return (w0 - 1) - x, (h0 - 1) - y
    return (h0 - 1) - y, x


def disp_to_base(xd, yd, k, w0, h0):
    k %= 4
    if k == 0:
        return xd, yd
    if k == 1:
        return (w0 - 1) - yd, xd
    if k == 2:
        return (w0 - 1) - xd, (h0 - 1) - yd
    return yd, (h0 - 1) - xd


def rotate_bbox(bbox, k, w0, h0):
    x0, y0, x1, y1 = bbox
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    rotated = [base_to_disp(x, y, k, w0, h0) for x, y in corners]
    xs = [point[0] for point in rotated]
    ys = [point[1] for point in rotated]
    return (min(xs), min(ys), max(xs), max(ys))
