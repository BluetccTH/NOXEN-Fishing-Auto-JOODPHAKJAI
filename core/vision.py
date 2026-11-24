from __future__ import annotations

import numpy as np


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    mask = np.asarray(mask, dtype=bool).reshape(-1)
    if mask.size == 0:
        return []
    padded = np.concatenate(([False], mask, [False])).astype(np.int8)
    changes = np.diff(padded)
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    return [(int(a), int(b)) for a, b in zip(starts, ends)]


def _bridge_gaps(mask: np.ndarray, max_gap: int) -> np.ndarray:
    """Fill only short false gaps between true runs."""
    out = np.asarray(mask, dtype=bool).copy()
    if out.size == 0 or max_gap <= 0:
        return out
    true_indices = np.flatnonzero(out)
    if true_indices.size < 2:
        return out
    for left, right in zip(true_indices[:-1], true_indices[1:]):
        gap = int(right - left - 1)
        if 0 < gap <= max_gap:
            out[left + 1:right] = True
    return out


def _rgb(frame: np.ndarray) -> np.ndarray:
    if frame.ndim != 3 or frame.shape[2] < 3:
        raise ValueError("ภาพที่ส่งให้ระบบตรวจจับต้องเป็น RGB")
    return frame[:, :, :3].astype(np.uint8, copy=False)


def detect_charge(frame: np.ndarray) -> float | None:
    """Read the vertical charge meter: green/yellow cap + white fill below.

    The meter is narrow and may sit in a larger user-selected region. White
    fill rows are bridged across small bloom/compression gaps before pairing
    them with the green cap. Returns fill-height / total-meter-height.
    """
    rgb = _rgb(frame).astype(np.int16)
    h, w, _ = rgb.shape
    if h < 35 or w < 5:
        return None

    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    spread = np.maximum.reduce([r, g, b]) - np.minimum.reduce([r, g, b])
    white = (r > 180) & (g > 180) & (b > 180) & (spread < 105)

    col_score = white.sum(axis=0).astype(np.float32)
    peak = float(col_score.max()) if col_score.size else 0.0
    if peak < max(5.0, h * 0.07):
        return None

    active_cols = col_score >= max(3.0, peak * 0.42)
    max_width = max(8, int(w * (0.72 if w <= 40 else 0.40)))
    candidates = []
    for left, right in _runs(active_cols):
        width = right - left
        if 2 <= width <= max_width:
            candidates.append((float(col_score[left:right].sum()), left, right))
    if not candidates:
        return None
    _score, left, right = max(candidates, key=lambda item: item[0])

    white_rows = white[:, left:right].mean(axis=1) >= 0.54
    white_rows = _bridge_gaps(white_rows, max(3, int(h * 0.012)))
    white_runs = [(a, z) for a, z in _runs(white_rows) if z - a >= max(8, int(h * 0.07))]
    if not white_runs:
        return None

    # Green/yellow-green cap. The color tolerance allows the olive tint seen
    # in the game capture and modest lighting/post-processing changes.
    green = (g > 55) & (g > b * 1.16) & (r > 35) & (g > r * 0.74)
    green_rows = green[:, left:right].mean(axis=1) >= 0.24
    green_runs = [(a, z) for a, z in _runs(green_rows) if z - a >= max(6, int(h * 0.03))]

    max_gap = max(12, int(h * 0.035))
    pairs = []
    for cap_top, cap_bottom in green_runs:
        for white_top, white_bottom in white_runs:
            gap = white_top - cap_bottom
            if -2 <= gap <= max_gap and white_bottom > white_top:
                # Prefer adjacent color sections with a long white fill.
                pairs.append((gap, -(white_bottom - white_top), cap_top, white_top, white_bottom))
    if pairs:
        _gap, _neg_fill, meter_top, fill_top, fill_bottom = min(pairs)
        meter_height = fill_bottom - meter_top
        fill_height = fill_bottom - fill_top
        if meter_height > 0 and fill_height > 0:
            return float(np.clip(fill_height / meter_height, 0.0, 1.0))

    # If the white fill has almost covered the whole meter, the green cap may
    # be invisible; accept a near-top white run as a full charge.
    longest_white = max(white_runs, key=lambda run: run[1] - run[0])
    if longest_white[0] <= max(3, int(h * 0.12)):
        return 1.0
    return None


def detect_control_bar(frame: np.ndarray) -> tuple[float, float] | None:
    """Detect the wide movable pale control bar in the Fisch-style reel UI.

    Holding left mouse moves this bar to the right; releasing lets it drift
    left. Returns (center_x, width_px), in crop coordinates.
    """
    rgb = _rgb(frame)
    h, w, _ = rgb.shape
    if h < 18 or w < 100:
        return None
    a = rgb.astype(np.float32)
    gray = 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]
    y0, y1 = max(0, int(h * 0.24)), min(h, int(h * 0.78))
    band = gray[y0:y1, :]
    profile = np.mean(band, axis=0)
    profile = np.convolve(profile, np.ones(7, dtype=np.float32) / 7.0, mode="same")
    q18, q92 = np.percentile(profile, [18, 92])
    threshold = max(78.0, float(q18 + 0.40 * max(0.0, q92 - q18)))
    mask = profile > threshold
    if mask.size >= 7:
        smooth = np.convolve(mask.astype(np.float32), np.ones(5, dtype=np.float32) / 5.0, mode="same")
        mask = smooth >= 0.58
    min_width = max(18, int(w * 0.12))
    # The in-game control block is substantially narrower than the full rail.
    # Wide bright scenery/overlays can otherwise be selected as a false bar.
    # Allow a few edge pixels added by profile smoothing, while still
    # rejecting scene highlights that span a large portion of the crop.
    max_width = max(min_width, int(w * 0.30) + 8)
    candidates = []
    for left, right in _runs(mask):
        width = right - left
        if min_width <= width <= max_width:
            brightness = float(profile[left:right].mean())
            candidates.append((brightness, width, left, right))
    if not candidates:
        return None
    # The wide white/gray slider is the control bar; the thin vertical marker
    # is detected separately and must never be mistaken for this rectangle.
    _brightness, width, left, right = max(candidates, key=lambda item: (item[1], item[0]))
    return ((left + right) / 2.0, float(width))


def detect_fish_marker(
    frame: np.ndarray,
    *,
    expected_x: float | None = None,
    max_expected_distance: float | None = None,
) -> tuple[float, float] | None:
    """Detect the narrow blue-gray/purple vertical fish indicator.

    The marker may look dark slate in one frame and have only dark caps around
    a pale center when it overlaps the bright control bar. We search for its
    cool-toned vertical core and require a tall, narrow component. When a prior
    position is supplied, an optional distance gate rejects remote lookalikes
    instead of switching tracks. Returns (center_x, center_y), in crop coordinates.
    """
    rgb = _rgb(frame).astype(np.int16)
    h, w, _ = rgb.shape
    if h < 25 or w < 100:
        return None
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]

    # The real marker is a narrow cool blue-gray/slate pill. A broad lavender
    # threshold also matches water reflections and the pale moving block; on
    # some frames those pixels merge into a very wide component and hide the
    # actual marker. Keep the mask focused on blue-gray pixels only.
    marker_mask = (
        (b > r * 1.08) & (b > g * 1.035) &
        (r > 30) & (g > 30) & (b < 230) & (g < 190)
    )

    # Avoid text above and the progress strip below. The marker sits around
    # the horizontal rail and can extend slightly beyond its top/bottom edge.
    y0, y1 = max(0, int(h * 0.14)), min(h, int(h * 0.86))
    band = marker_mask[y0:y1, :]
    scores = band.sum(axis=0).astype(np.float32)
    # Ignore one- or two-pixel color noise from water reflections. The real
    # capsule contributes a compact column of blue-gray pixels, including its
    # visible caps when its center is covered by the pale control block.
    threshold = max(3.0, h * 0.035)
    active_cols = scores >= threshold
    max_width = max(14, int(w * 0.045))
    candidates = []
    for left, right in _runs(active_cols):
        width = right - left
        if not (2 <= width <= max_width):
            continue
        ys_local, _xs = np.where(band[:, left:right])
        if ys_local.size < max(8, int(h * 0.055)):
            continue
        y_top = int(ys_local.min()) + y0
        y_bottom = int(ys_local.max()) + y0
        span = y_bottom - y_top + 1
        if span < max(20, int(h * 0.20)):
            continue
        # The indicator straddles the rail's vertical midpoint. This rejects
        # isolated grass/water reflections and the bottom progress fill.
        if y_top > h * 0.50 or y_bottom < h * 0.52:
            continue
        occupancy = float(scores[left:right].sum())
        continuity = span / max(1.0, float(h))
        candidates.append((occupancy * continuity, left, right, y_top, y_bottom))
    if not candidates:
        return None
    if expected_x is None or not np.isfinite(float(expected_x)):
        chosen = max(candidates, key=lambda item: item[0])
    else:
        # When a prior track exists, reject candidates outside its plausible
        # motion envelope. Merely down-ranking distant candidates is unsafe:
        # if the true marker is briefly occluded, a water reflection can still
        # win and make the controller believe the fish teleported.
        if max_expected_distance is not None:
            distance_limit = max(0.0, float(max_expected_distance))
            nearby = [
                item for item in candidates
                if abs(((item[1] + item[2]) / 2.0) - float(expected_x)) <= distance_limit
            ]
            if not nearby:
                return None
            candidates = nearby

        # Prefer the strongest candidate near the predicted position.
        scale = max(16.0, w * 0.08)
        chosen = max(
            candidates,
            key=lambda item: item[0] / (1.0 + abs(((item[1] + item[2]) / 2.0) - float(expected_x)) / scale),
        )
    _score, left, right, y_top, y_bottom = chosen
    return ((left + right) / 2.0, (y_top + y_bottom) / 2.0)


def predict_fish_x(
    previous_x: float | None,
    velocity: float,
    age_seconds: float,
    frame_width: int,
    *,
    max_age_seconds: float = 0.25,
) -> float | None:
    """Predict a marker position only while its last observation is fresh."""
    if previous_x is None or frame_width <= 0:
        return None
    age = float(age_seconds)
    if not np.isfinite(age) or age < 0.0 or age > max(0.0, float(max_age_seconds)):
        return None
    predicted = float(previous_x) + float(velocity) * age
    if not np.isfinite(predicted):
        return None
    return float(np.clip(predicted, 0.0, float(frame_width - 1)))


def reel_completion_confirmed(
    control_bar: tuple[float, float] | None,
    fish_marker: tuple[float, float] | None,
    progress_value: float | None,
    *,
    progress_high_water: float,
    disappear_progress: float,
    absent_for: float,
    confirm_seconds: float,
) -> bool:
    """Accept disappearance as success only when every reel UI element is absent."""
    return (
        control_bar is None
        and fish_marker is None
        and progress_value is None
        and float(progress_high_water) >= float(disappear_progress)
        and float(absent_for) >= max(0.0, float(confirm_seconds))
    )


def fisch_edge_should_hold(
    fish_x: float,
    bar_center_x: float,
    bar_width: float,
    currently_held: bool,
    *,
    fish_velocity: float = 0.0,
    bar_velocity: float = 0.0,
    prediction_seconds: float = 0.10,
    edge_guard_ratio: float = 0.78,
) -> bool:
    """Keep the fish inside the moving bar instead of chasing its exact center.

    Holding moves the pale bar right; releasing lets it drift left. The input
    changes only when the predicted fish position approaches a guarded edge.
    Both fish and bar velocity are included to anticipate overshoot.
    """
    width = max(1.0, float(bar_width))
    horizon = float(np.clip(prediction_seconds, 0.0, 0.25))
    relative_position = float(fish_x) - float(bar_center_x)
    relative_velocity = float(np.clip(fish_velocity, -1600.0, 1600.0)) - float(
        np.clip(bar_velocity, -1800.0, 1800.0)
    )
    predicted_error = relative_position + relative_velocity * horizon
    guard = float(np.clip(edge_guard_ratio, 0.55, 0.92))
    safe_radius = max(6.0, (width * 0.5) * guard)

    if predicted_error >= safe_radius:
        return True
    if predicted_error <= -safe_radius:
        return False
    return bool(currently_held)


def fisch_should_hold(
    fish_x: float,
    bar_center_x: float,
    bar_width: float,
    currently_held: bool,
    *,
    prediction_px: float = 0.0,
    deadband_ratio: float = 0.10,
) -> bool:
    """Choose the Fisch-style mouse state for tracking the fish marker.

    Mouse-down pushes the white control bar right. Mouse-up lets it drift left.
    The controller steers the bar center toward the predicted fish position,
    with a deadband to avoid rapidly toggling when the two are aligned.
    """
    width = max(1.0, float(bar_width))
    predicted_fish_x = float(fish_x) + float(prediction_px)
    error = predicted_fish_x - float(bar_center_x)
    deadband = max(6.0, width * float(np.clip(deadband_ratio, 0.03, 0.25)))
    if error > deadband:
        return True
    if error < -deadband:
        return False
    return bool(currently_held)


def detect_progress(frame: np.ndarray) -> float | None:
    """Read left-to-right progress filled in coral/pink or white."""
    rgb = _rgb(frame).astype(np.int16)
    h, w, _ = rgb.shape
    if h < 8 or w < 40:
        return None
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    pink = (r > 135) & (b > 80) & (r > g * 1.08)
    coral = (r > 190) & (g > 95) & (b > 65) & (r > g * 1.18) & (g > b * 1.08)
    white = (
        (r > 175) & (g > 165) & (b > 165) &
        (np.maximum.reduce([r, g, b]) - np.minimum.reduce([r, g, b]) < 100)
    )
    active = pink | coral | white
    y0, y1 = max(0, int(h * 0.16)), min(h, max(1, int(h * 0.84)))
    profile = active[y0:y1, :].mean(axis=0)
    filled = profile >= 0.26
    filled = _bridge_gaps(filled, max(2, int(w * 0.012)))
    start_candidates = np.flatnonzero(filled[:max(2, int(w * 0.08))])
    if start_candidates.size == 0:
        if float(filled.mean()) >= 0.94:
            return 1.0
        return None
    start = int(start_candidates[0])
    if start > max(2, int(w * 0.04)):
        return None
    end = start
    while end < w and filled[end]:
        end += 1
    if end < max(5, int(w * 0.03)):
        return None
    return float(np.clip(end / w, 0.0, 1.0))


# Compatibility aliases for old debug/config code or snapshots.
def detect_target_center(frame: np.ndarray) -> tuple[float, float] | None:
    return detect_control_bar(frame)


def detect_handle_center(frame: np.ndarray) -> tuple[float, float] | None:
    return detect_fish_marker(frame)
