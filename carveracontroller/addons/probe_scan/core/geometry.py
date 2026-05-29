"""Pure 2D construction math"""

from __future__ import annotations

import math


def _golden_minimize_1d(
    lo: float,
    hi: float,
    fn,
    *,
    iters: int = 24,
) -> tuple[float, float]:
    """Minimize fn(t) for t in [lo, hi] via golden-section search."""
    phi = (math.sqrt(5.0) - 1.0) / 2.0
    t1 = hi - phi * (hi - lo)
    t2 = lo + phi * (hi - lo)
    f1, f2 = fn(t1), fn(t2)
    for _ in range(iters):
        if f1 < f2:
            hi, t2, f2 = t2, t1, f1
            t1 = hi - phi * (hi - lo)
            f1 = fn(t1)
        else:
            lo, t1, f1 = t1, t2, f2
            t2 = lo + phi * (hi - lo)
            f2 = fn(t2)
    if f1 < f2:
        return t1, f1
    return t2, f2


def circumcircle_2d(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> tuple[float, float, float]:
    """
    Circle through three XY points (world/canvas plane).
    Returns (cx_out, cy_out, r). Raises ValueError when colinear.
    """
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-14:
        raise ValueError("colinear_points")
    ax2_py2 = ax * ax + ay * ay
    bx2_py2 = bx * bx + by * by
    cx2_py2 = cx * cx + cy * cy
    ux = (ax2_py2 * (by - cy) + bx2_py2 * (cy - ay) + cx2_py2 * (ay - by)) / d
    uy = (ax2_py2 * (cx - bx) + bx2_py2 * (ax - cx) + cx2_py2 * (bx - ax)) / d
    r = ((ux - ax) ** 2 + (uy - ay) ** 2) ** 0.5
    return ux, uy, r


def line_intersection_2d(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
    *,
    tol: float = 1e-9,
) -> tuple[float, float] | None:
    """
    Intersection point of infinite line through AB with infinite line through CD.
    Returns None when directions are parallel (including coincident/colinear degeneracy).
    """
    vx, vy = bx - ax, by - ay
    wx, wy = dx - cx, dy - cy
    den = vx * wy - vy * wx
    if abs(den) < tol:
        return None
    qx, qy = cx - ax, cy - ay
    t_num = qx * wy - qy * wx
    t = t_num / den
    return ax + t * vx, ay + t * vy


def circle_line_intersections_2d(
    cx: float,
    cy: float,
    r: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
    *,
    tol: float = 1e-9,
) -> list[tuple[float, float]]:
    """
    Intersections of a circle (cx, cy, r) with the infinite line through A and B.
    Returns 0, 1, or 2 points sorted by parameter t along the line direction.
    """
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < tol:
        return []
    dx /= length
    dy /= length
    # Translate circle centre to line origin.
    fx, fy = ax - cx, ay - cy
    a = 1.0  # dx*dx + dy*dy normalised
    b = 2.0 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - r * r
    disc = b * b - 4.0 * a * c
    if disc < 0:
        return []
    if disc < tol * tol:
        t = -b / 2.0
        return [(ax + t * dx, ay + t * dy)]
    sq = math.sqrt(disc)
    t1 = (-b - sq) / 2.0
    t2 = (-b + sq) / 2.0
    return [
        (ax + t1 * dx, ay + t1 * dy),
        (ax + t2 * dx, ay + t2 * dy),
    ]


def circle_circle_intersections_2d(
    cx1: float,
    cy1: float,
    r1: float,
    cx2: float,
    cy2: float,
    r2: float,
    *,
    tol: float = 1e-9,
) -> list[tuple[float, float]]:
    """
    Intersections of two circles. Returns 0, 1, or 2 points.
    """
    d = math.hypot(cx2 - cx1, cy2 - cy1)
    if d < tol:
        return []
    if d > r1 + r2 + tol or d < abs(r1 - r2) - tol:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d)
    h2 = r1 * r1 - a * a
    if h2 < 0:
        h2 = 0.0
    h = math.sqrt(h2)
    mx = cx1 + a * (cx2 - cx1) / d
    my = cy1 + a * (cy2 - cy1) / d
    rx = -(cy2 - cy1) * (h / d)
    ry = (cx2 - cx1) * (h / d)
    if h < tol:
        return [(mx, my)]
    return [(mx + rx, my + ry), (mx - rx, my - ry)]


def midpoint_2d(
    ax: float, ay: float, bx: float, by: float
) -> tuple[float, float]:
    """Midpoint between two 2D points."""
    return (ax + bx) / 2.0, (ay + by) / 2.0


def tangent_point_to_circle_2d(
    px_: float,
    py_: float,
    cx: float,
    cy: float,
    r: float,
    *,
    tol: float = 1e-9,
) -> list[tuple[float, float]]:
    """
    Tangent touch-points on circle (cx, cy, r) from external point (px_, py_).
    Returns 0 (point inside circle) to 2 touch-points.
    """
    d = math.hypot(px_ - cx, py_ - cy)
    if d < r - tol:
        return []
    if d < tol:
        return []
    ux, uy = (cx - px_) / d, (cy - py_) / d
    # Chord midpoint on P->C at distance (d²−r²)/d from P (r²/d from C toward P).
    cm = r * r / d
    h2 = r * r - cm * cm
    if h2 < 0:
        h2 = 0.0
    h = math.sqrt(h2)
    mx = cx - cm * ux
    my = cy - cm * uy
    perpx, perpy = -uy, ux
    if h < tol:
        return [(mx, my)]
    return [
        (mx + h * perpx, my + h * perpy),
        (mx - h * perpx, my - h * perpy),
    ]


def tangent_circle_to_circle_external_2d(
    cx1: float,
    cy1: float,
    r1: float,
    cx2: float,
    cy2: float,
    r2: float,
    *,
    tol: float = 1e-9,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """
    External tangent lines of two non-concentric circles.
    Returns up to 2 tangent lines, each as a pair of touch-points
    ((tx1, ty1), (tx2, ty2)) — one point on each circle.
    For equal radii the lines are parallel and the external centre of similitude
    is at infinity; the touch-points are still well-defined.
    """
    d = math.hypot(cx2 - cx1, cy2 - cy1)
    if d < tol:
        return []

    lines: list[tuple[tuple[float, float], tuple[float, float]]] = []

    # Equal (or nearly equal) radii: parallel external tangents.
    # When |r1-r2| is tiny the external centre of similitude is far away and
    # the general formula becomes numerically unstable.
    r_ref = max(r1, r2, tol)
    if abs(r1 - r2) < tol or abs(r1 - r2) / r_ref < 1e-3:
        ux, uy = (cx2 - cx1) / d, (cy2 - cy1) / d
        perpx, perpy = -uy, ux
        for sign in (1.0, -1.0):
            t1 = (cx1 + sign * r1 * perpx, cy1 + sign * r1 * perpy)
            t2 = (cx2 + sign * r2 * perpx, cy2 + sign * r2 * perpy)
            lines.append((t1, t2))
        return lines

    # External centre of similitude.
    # S divides C1C2 externally in ratio r1:r2.
    sx = (r1 * cx2 - r2 * cx1) / (r1 - r2)
    sy = (r1 * cy2 - r2 * cy1) / (r1 - r2)

    # Tangent lines from S to circle 1.
    pts = tangent_point_to_circle_2d(sx, sy, cx1, cy1, r1, tol=tol)
    for tp1 in pts:
        # Corresponding touch on circle 2: project onto same tangent line direction.
        dx, dy = tp1[0] - sx, tp1[1] - sy
        L = math.hypot(dx, dy)
        if L < tol:
            continue
        ux, uy = dx / L, dy / L
        # Distance from S to tangent point on circle 2.
        d2 = math.hypot(sx - cx2, sy - cy2)
        a2 = r2 * r2 / d2 if d2 > tol else 0.0
        h2_2 = r2 * r2 - a2 * a2
        if h2_2 < 0:
            h2_2 = 0.0
        h2 = math.sqrt(h2_2)
        mx2 = sx + a2 * (cx2 - sx) / d2
        my2 = sy + a2 * (cy2 - sy) / d2
        perp_x2, perp_y2 = -(cy2 - sy) / d2, (cx2 - sx) / d2
        # Choose the touch-point on circle 2 that is on the same side as tp1.
        tp2_a = (mx2 + h2 * perp_x2, my2 + h2 * perp_y2)
        tp2_b = (mx2 - h2 * perp_x2, my2 - h2 * perp_y2)
        cross_a = (tp2_a[0] - sx) * uy - (tp2_a[1] - sy) * ux
        cross_b = (tp2_b[0] - sx) * uy - (tp2_b[1] - sy) * ux
        cross_ref = (tp1[0] - sx) * uy - (tp1[1] - sy) * ux
        tp2 = tp2_a if abs(cross_a - cross_ref) < abs(cross_b - cross_ref) else tp2_b
        lines.append((tp1, tp2))
    return lines


def ellipse_line_intersections_2d(
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
    *,
    tol: float = 1e-9,
) -> list[tuple[float, float]]:
    """Intersections of axis-aligned ellipse (cx, cy, rx, ry) with infinite line through A and B."""
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < tol or rx < tol or ry < tol:
        return []
    dx /= length
    dy /= length
    ux, vy = ax - cx, ay - cy
    inv_rx2 = 1.0 / (rx * rx)
    inv_ry2 = 1.0 / (ry * ry)
    a_coef = dx * dx * inv_rx2 + dy * dy * inv_ry2
    b_coef = 2.0 * (ux * dx * inv_rx2 + vy * dy * inv_ry2)
    c_coef = ux * ux * inv_rx2 + vy * vy * inv_ry2 - 1.0
    disc = b_coef * b_coef - 4.0 * a_coef * c_coef
    if disc < 0:
        return []
    if disc < tol * tol:
        t = -b_coef / (2.0 * a_coef)
        return [(ax + t * dx, ay + t * dy)]
    sq = math.sqrt(disc)
    t1 = (-b_coef - sq) / (2.0 * a_coef)
    t2 = (-b_coef + sq) / (2.0 * a_coef)
    return [
        (ax + t1 * dx, ay + t1 * dy),
        (ax + t2 * dx, ay + t2 * dy),
    ]


def _point_on_ellipse_2d(
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    x: float,
    y: float,
    *,
    tol: float = 1e-9,
) -> bool:
    if rx < tol or ry < tol:
        return False
    val = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
    return abs(val - 1.0) <= tol * 10.0


def ellipse_ellipse_intersections_2d(
    cx1: float,
    cy1: float,
    rx1: float,
    ry1: float,
    cx2: float,
    cy2: float,
    rx2: float,
    ry2: float,
    *,
    tol: float = 1e-9,
    samples: int = 720,
) -> list[tuple[float, float]]:
    """Intersections of two axis-aligned ellipses (0–4 points)."""
    if min(rx1, ry1, rx2, ry2) < tol:
        return []

    scale = max(rx1, ry1, rx2, ry2, math.hypot(cx1 - cx2, cy1 - cy2), 1.0)
    param_tol = max(tol, 1e-6 * scale)
    if (
        abs(cx1 - cx2) <= param_tol
        and abs(cy1 - cy2) <= param_tol
        and abs(rx1 - rx2) <= param_tol
        and abs(ry1 - ry2) <= param_tol
    ):
        return []

    def rho1(t: float) -> float:
        x = cx1 + rx1 * math.cos(t)
        y = cy1 + ry1 * math.sin(t)
        return ((x - cx2) / rx2) ** 2 + ((y - cy2) / ry2) ** 2 - 1.0

    tangency_tol = max(tol * 100.0, 1e-6 * scale)
    merge = max(1e-4, 1e-3 * scale)
    roots: list[tuple[float, float]] = []

    def add_hit(t_hit: float) -> None:
        x = cx1 + rx1 * math.cos(t_hit)
        y = cy1 + ry1 * math.sin(t_hit)
        if not (
            _point_on_ellipse_2d(cx1, cy1, rx1, ry1, x, y, tol=tol)
            and _point_on_ellipse_2d(cx2, cy2, rx2, ry2, x, y, tol=tol)
        ):
            return
        if any(math.hypot(x - px, y - py) < merge for px, py in roots):
            return
        roots.append((x, y))

    def refine_root(lo_t: float, hi_t: float, lo_r: float, hi_r: float) -> None:
        for _ in range(50):
            mid_t = (lo_t + hi_t) * 0.5
            mid_r = rho1(mid_t)
            if abs(mid_r) < tol:
                add_hit(mid_t)
                return
            if lo_r * mid_r <= 0:
                hi_t, hi_r = mid_t, mid_r
            else:
                lo_t, lo_r = mid_t, mid_r
        add_hit((lo_t + hi_t) * 0.5)

    def refine_tangency(lo_t: float, hi_t: float) -> None:
        t_hit, r_hit = _golden_minimize_1d(lo_t, hi_t, lambda t: abs(rho1(t)))
        if r_hit <= tangency_tol:
            add_hit(t_hit)

    dt = 2.0 * math.pi / samples
    prev2_t = 0.0
    prev2_r = rho1(0.0)
    prev_t = 0.0
    prev_r = prev2_r

    for i in range(1, samples + 1):
        t = i * dt
        r = rho1(t)

        if abs(r) < tol:
            add_hit(t)
        elif abs(prev_r) < tol or prev_r * r < 0:
            refine_root(prev_t, t, prev_r, r)
        elif prev2_r > prev_r and prev_r > r and prev_r < tangency_tol:
            refine_tangency(prev2_t, t)
        elif prev_r > 0 and r > 0 and min(prev_r, r) < tangency_tol:
            refine_tangency(prev_t, t)

        prev2_t, prev2_r = prev_t, prev_r
        prev_t, prev_r = t, r

    # Close the 0/2π seam: the loop ends at t=2π (=0); compare the last interior
    # sample to the first sample after 0.
    seam_lo_t = (samples - 1) * dt
    seam_hi_t = dt
    seam_lo_r = rho1(seam_lo_t)
    seam_hi_r = rho1(seam_hi_t)
    seam_prev2_r = rho1((samples - 2) * dt) if samples >= 3 else seam_lo_r
    rho_end = rho1(2.0 * math.pi)

    if abs(seam_hi_r) < tol:
        add_hit(seam_hi_t)
    elif abs(seam_lo_r) < tol:
        add_hit(seam_lo_t)
    elif seam_lo_r * seam_hi_r < 0:
        if seam_lo_r * rho_end <= 0:
            refine_root(seam_lo_t, 2.0 * math.pi, seam_lo_r, rho_end)
        else:
            refine_root(0.0, seam_hi_t, rho_end, seam_hi_r)
    elif (
        samples >= 3
        and seam_prev2_r > seam_lo_r
        and seam_lo_r > seam_hi_r
        and seam_lo_r < tangency_tol
    ):
        refine_tangency((samples - 2) * dt, seam_lo_t)
    elif seam_lo_r > 0 and seam_hi_r > 0 and min(seam_lo_r, seam_hi_r) < tangency_tol:
        if seam_lo_r <= seam_hi_r:
            refine_tangency(seam_lo_t, 2.0 * math.pi)
        else:
            refine_tangency(0.0, seam_hi_t)

    return roots


def tangent_point_to_ellipse_2d(
    px_: float,
    py_: float,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    *,
    tol: float = 1e-9,
) -> list[tuple[float, float]]:
    """
    Tangent touch-points on axis-aligned ellipse from external point (px_, py_).
    Returns 0, 1, or 2 points.
    """
    if rx < tol or ry < tol:
        return []
    # Implicit: F(x,y) = ((x-cx)/rx)^2 + ((y-cy)/ry)^2 - 1; gradient at touch T is parallel to PT.
    # Parametric search on angle for robustness with axis-aligned ellipses.
    ux, vy = px_ - cx, py_ - cy
    inside = (ux / rx) ** 2 + (vy / ry) ** 2
    if inside <= 1.0 + tol:
        return []

    def dist_sq(t: float) -> float:
        tx = cx + rx * math.cos(t)
        ty = cy + ry * math.sin(t)
        return (tx - px_) ** 2 + (ty - py_) ** 2

    def ortho(t: float) -> float:
        """Dot of (T-P) with normal at T; zero at tangency."""
        tx = cx + rx * math.cos(t)
        ty = cy + ry * math.sin(t)
        nx = (tx - cx) / (rx * rx)
        ny = (ty - cy) / (ry * ry)
        return (tx - px_) * nx + (ty - py_) * ny

    candidates: list[tuple[float, float, float]] = []
    samples = 360
    prev_t = 0.0
    prev_o = ortho(0.0)
    dt = 2.0 * math.pi / samples
    merge = max(1e-4, 1e-3 * max(rx, ry, 1.0))
    for i in range(1, samples + 1):
        t = i * dt
        o = ortho(t)
        if prev_o == 0.0 or o == 0.0 or prev_o * o < 0:
            lo_t, hi_t = (i - 1) * dt, t
            lo_o, hi_o = prev_o, o
            for _ in range(50):
                mid_t = (lo_t + hi_t) * 0.5
                mid_o = ortho(mid_t)
                if abs(mid_o) < tol:
                    lo_t = hi_t = mid_t
                    break
                if lo_o * mid_o <= 0:
                    hi_t, hi_o = mid_t, mid_o
                else:
                    lo_t, lo_o = mid_t, mid_o
            t_hit, d_hit = _golden_minimize_1d(lo_t, hi_t, dist_sq)
            if d_hit > tol:
                tx = cx + rx * math.cos(t_hit)
                ty = cy + ry * math.sin(t_hit)
                dup = any(
                    math.hypot(tx - qx, ty - qy) < merge for qx, qy, _ in candidates
                )
                if not dup:
                    candidates.append((tx, ty, d_hit))
        prev_t, prev_o = t, o
    if not candidates:
        return []
    candidates.sort(key=lambda c: c[2])
    min_d = candidates[0][2]
    threshold = min_d * 1.5 + tol
    return [(tx, ty) for tx, ty, d in candidates if d <= threshold][:2]


def tangent_ellipse_to_ellipse_external_2d(
    cx1: float,
    cy1: float,
    rx1: float,
    ry1: float,
    cx2: float,
    cy2: float,
    rx2: float,
    ry2: float,
    *,
    tol: float = 1e-9,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """
    External tangent lines between two axis-aligned ellipses.
    Returns up to 4 lines as pairs of touch-points (one on each ellipse).
    """
    if min(rx1, ry1, rx2, ry2) < tol:
        return []

    lines: list[tuple[tuple[float, float], tuple[float, float]]] = []
    samples = 360
    dt = 2.0 * math.pi / samples

    def tangent_dir_at(t: float, cx: float, cy: float, rx: float, ry: float) -> tuple[float, float]:
        sx = -rx * math.sin(t)
        sy = ry * math.cos(t)
        ln = math.hypot(sx, sy)
        if ln < tol:
            return 1.0, 0.0
        return sx / ln, sy / ln

    for i in range(samples):
        t1 = i * dt
        p1 = (cx1 + rx1 * math.cos(t1), cy1 + ry1 * math.sin(t1))
        d1x, d1y = tangent_dir_at(t1, cx1, cy1, rx1, ry1)
        for sign in (1.0, -1.0):
            nx, ny = -d1y * sign, d1x * sign
            # Line through p1 with normal (nx, ny): find p2 on ellipse 2 where normal aligns.
            best: tuple[float, float] | None = None
            best_score = float("inf")
            for j in range(samples):
                t2 = j * dt
                p2 = (cx2 + rx2 * math.cos(t2), cy2 + ry2 * math.sin(t2))
                d2x, d2y = tangent_dir_at(t2, cx2, cy2, rx2, ry2)
                # External tangent: directions parallel, normals aligned along p1-p2.
                cross = abs(d1x * d2y - d1y * d2x)
                if cross > 0.05:
                    continue
                vx, vy = p2[0] - p1[0], p2[1] - p1[1]
                vn = math.hypot(vx, vy)
                if vn < tol:
                    continue
                vx /= vn
                vy /= vn
                align = abs(vx * nx + vy * ny)
                if align < best_score:
                    best_score = align
                    best = p2
            if best is not None and best_score < 0.02:
                pair = (p1, best)
                dup = False
                for a, b in lines:
                    if (
                        math.hypot(a[0] - pair[0][0], a[1] - pair[0][1]) < tol * 50
                        and math.hypot(b[0] - pair[1][0], b[1] - pair[1][1]) < tol * 50
                    ):
                        dup = True
                        break
                if not dup:
                    lines.append(pair)
    # Deduplicate and keep at most 4 distinct tangents
    if len(lines) > 4:
        lines = lines[:4]
    return lines
