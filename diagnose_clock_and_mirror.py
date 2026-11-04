"""
diagnose_clock_and_mirror.py

診斷兩個可能的系統性問題：
  1. 每張照片的相機時鐘誤差（時鐘漂移）
  2. 照片是否有左右鏡像（東西方向翻轉）

用法：
    python diagnose_clock_and_mirror.py lulin_star_marks_final2.csv --calibration lulin_calibration.manual.json

輸出：
  - 每張照片最佳時鐘修正量（小時）與對應的最小誤差
  - 對比「正常模式」vs「鏡像模式」哪個整體誤差較低
  - 把結果存進 clock_diagnosis.csv 方便進一步分析

需要跟 allsky_fisheye.py 放在同一個資料夾。
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import allsky_fisheye as af  # noqa: E402


# ──────────────────────────────────────────────
# 輔助：帶時鐘偏移的 residual 計算
# ──────────────────────────────────────────────

def compute_errors_with_offset(
    matches: list[dict],
    calibration: af.Calibration,
    clock_offset_hours: float,
    flip_x: bool = False,
) -> list[float]:
    """
    對一組 matches 套用 clock_offset_hours（把 date_obs 平移這麼多小時），
    計算每顆星的像素誤差。
    flip_x=True 代表把 x_obs 對圓心做左右鏡像再計算。
    """
    from astropy.time import Time
    import astropy.units as u_

    errors = []
    for m in matches:
        try:
            t = Time(m["date_obs"]) + clock_offset_hours * u_.hour
            shifted_date = t.isot + "Z" if not t.isot.endswith("Z") else t.isot
        except Exception:
            continue

        x_obs = m["x_obs"]
        if flip_x:
            # 對 cx 做鏡像
            x_obs = 2 * calibration.cx - x_obs

        try:
            alt_deg, az_deg = af.radec_to_altaz(m["ra_deg"], m["dec_deg"], shifted_date, calibration)
            if float(alt_deg) <= 0:
                continue
            x_pred, y_pred = af.altaz_to_pixel(alt_deg, az_deg, calibration)
            err = float(np.hypot(float(x_pred) - x_obs, float(y_pred) - m["y_obs"]))
            errors.append(err)
        except Exception:
            continue
    return errors


def find_best_clock_offset(
    matches: list[dict],
    calibration: af.Calibration,
    flip_x: bool = False,
    search_range_hours: float = 13.0,
    n_coarse: int = 53,
) -> tuple[float, float]:
    """
    在 ±search_range_hours 範圍內用粗搜尋 + 精細搜尋找最佳時鐘偏移量。
    回傳 (best_offset_hours, best_mean_error_px)。
    """
    # 粗搜尋
    coarse_offsets = np.linspace(-search_range_hours, search_range_hours, n_coarse)
    best_offset = 0.0
    best_err = float("inf")

    for offset in coarse_offsets:
        errs = compute_errors_with_offset(matches, calibration, float(offset), flip_x)
        if len(errs) < 2:
            continue
        mean_err = float(np.mean(errs))
        if mean_err < best_err:
            best_err = mean_err
            best_offset = float(offset)

    # 精細搜尋（在粗搜尋最佳點附近 ±0.5h，步長 0.02h ≈ 1.2 分鐘）
    step = (2 * search_range_hours) / (n_coarse - 1)
    fine_offsets = np.linspace(best_offset - step, best_offset + step, 51)
    for offset in fine_offsets:
        errs = compute_errors_with_offset(matches, calibration, float(offset), flip_x)
        if len(errs) < 2:
            continue
        mean_err = float(np.mean(errs))
        if mean_err < best_err:
            best_err = mean_err
            best_offset = float(offset)

    return best_offset, best_err


# ──────────────────────────────────────────────
# 主程式
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="診斷每張照片的時鐘偏移量，並測試鏡像假設"
    )
    parser.add_argument("marks_csv", help="合併後的星點 CSV（lulin_star_marks_final2.csv）")
    parser.add_argument("--calibration", required=True, help="起始校正 JSON（lulin_calibration.manual.json）")
    parser.add_argument(
        "--output",
        default="clock_diagnosis.csv",
        help="診斷結果輸出 CSV（預設 clock_diagnosis.csv）",
    )
    parser.add_argument(
        "--min-stars",
        type=int,
        default=3,
        help="每張照片至少要有幾顆可辨識星才納入分析（預設 3）",
    )
    args = parser.parse_args()

    calibration = af.load_calibration(Path(args.calibration))
    marks_raw = af.read_star_marks_multi(Path(args.marks_csv))

    # 整理成「每張照片一組」的 matches（已套用解析度換算）
    reference_w = calibration.reference_width_px
    reference_h = calibration.reference_height_px
    has_ref = reference_w > 0 and reference_h > 0

    groups: dict[str, list[dict]] = defaultdict(list)
    skipped_names: list[str] = []

    for mark in marks_raw:
        catalog = af.BRIGHT_STARS.get(af.normalize_star_name(mark["name"]))
        if catalog is None:
            skipped_names.append(mark["name"])
            continue
        if not mark["date_obs"]:
            continue
        try:
            af.Time(mark["date_obs"])
        except Exception:
            continue

        x_obs = mark["x"]
        y_obs = mark["y"]
        if has_ref and mark["image_width"] and mark["image_height"]:
            x_obs = x_obs * (reference_w / mark["image_width"])
            y_obs = y_obs * (reference_h / mark["image_height"])

        ra_deg, dec_deg = catalog
        groups[mark["image"]].append({
            "image": mark["image"],
            "date_obs": mark["date_obs"],
            "name": mark["name"],
            "x_obs": x_obs,
            "y_obs": y_obs,
            "ra_deg": ra_deg,
            "dec_deg": dec_deg,
        })

    print(f"讀到 {len(marks_raw)} 筆原始標記，辨識出 {sum(len(v) for v in groups.values())} 筆有效標記")
    print(f"共 {len(groups)} 張照片")
    if skipped_names:
        unique_skipped = sorted(set(skipped_names))
        print(f"跳過未知星名（{len(unique_skipped)} 種）：{', '.join(unique_skipped[:10])}" +
              ("..." if len(unique_skipped) > 10 else ""))
    print()

    # ── 先測試：不加時鐘偏移，正常 vs 鏡像，哪個整體誤差小 ──
    print("=" * 70)
    print("【全局測試：正常 vs 鏡像（不修正時鐘）】")
    print("=" * 70)
    all_matches = [m for v in groups.values() for m in v]
    errs_normal = compute_errors_with_offset(all_matches, calibration, 0.0, flip_x=False)
    errs_flip   = compute_errors_with_offset(all_matches, calibration, 0.0, flip_x=True)
    print(f"  正常模式：mean={np.mean(errs_normal):.1f} px，median={np.median(errs_normal):.1f} px（n={len(errs_normal)}）")
    print(f"  鏡像模式：mean={np.mean(errs_flip):.1f} px，median={np.median(errs_flip):.1f} px（n={len(errs_flip)}）")
    mirror_better = np.mean(errs_flip) < np.mean(errs_normal)
    print(f"  → {'鏡像模式誤差較小（相機照片可能是鏡像！）' if mirror_better else '正常模式誤差較小（照片應該沒有鏡像）'}")
    print()

    # ── 逐張照片：分別找最佳時鐘偏移 ──
    print("=" * 70)
    print("【逐張照片時鐘偏移分析】")
    print(f"{'照片':40s} {'星數':>4s} {'無偏移誤差':>10s} {'最佳偏移(h)':>12s} {'修正後誤差':>10s} {'改善幅度':>8s}")
    print("-" * 90)

    result_rows = []
    all_best_offsets = []

    for image in sorted(groups.keys()):
        matches = groups[image]
        if len(matches) < args.min_stars:
            print(f"  {image:38s} {len(matches):4d}  （星數不足 {args.min_stars}，跳過）")
            continue

        # 沒有時鐘偏移的基準誤差
        errs_zero = compute_errors_with_offset(matches, calibration, 0.0)
        mean_zero = float(np.mean(errs_zero)) if errs_zero else float("inf")

        # 找最佳偏移
        best_offset, best_err = find_best_clock_offset(matches, calibration)

        improvement = mean_zero - best_err
        all_best_offsets.append(best_offset)

        print(
            f"  {image:38s} {len(matches):4d}  {mean_zero:8.1f} px  "
            f"{best_offset:+10.2f} h  {best_err:8.1f} px  {improvement:+7.1f} px"
        )

        result_rows.append({
            "image": image,
            "n_stars": len(matches),
            "date_obs_recorded": matches[0]["date_obs"],
            "error_no_offset_px": round(mean_zero, 2),
            "best_clock_offset_hours": round(best_offset, 3),
            "error_with_offset_px": round(best_err, 2),
            "improvement_px": round(improvement, 2),
        })

    print()

    # ── 統計摘要 ──
    print("=" * 70)
    print("【統計摘要】")
    if all_best_offsets:
        arr = np.array(all_best_offsets)
        print(f"  最佳時鐘偏移的分布：")
        print(f"    mean  = {arr.mean():.2f} h")
        print(f"    median= {np.median(arr):.2f} h")
        print(f"    std   = {arr.std():.2f} h")
        print(f"    min   = {arr.min():.2f} h")
        print(f"    max   = {arr.max():.2f} h")

        # 偏移很一致 → 時區設定錯誤（固定偏移）
        # 偏移散佈很大 → 時鐘漂移（每張不同）
        if arr.std() < 0.5:
            print()
            print("  ✓ 偏移很一致（std < 0.5h）→ 很可能是時區設定問題，全局加固定偏移就能修")
        elif arr.std() < 2.0:
            print()
            print("  △ 偏移有些散佈（0.5h < std < 2h）→ 可能有時鐘漂移，需要逐張修正")
        else:
            print()
            print("  ✗ 偏移散佈很大（std > 2h）→ 時鐘嚴重漂移，每張都需要獨立修正")

        # 檢查有沒有「接近 ±8h」的，可能是 UTC+8 時區問題
        near_8h = np.sum(np.abs(np.abs(arr) - 8.0) < 0.5)
        near_0h = np.sum(np.abs(arr) < 0.5)
        print(f"    偏移接近 ±8h 的照片數：{near_8h}（可能是 UTC+8 vs UTC 混淆）")
        print(f"    偏移接近 0h 的照片數：{near_0h}（時鐘準確）")

    print()

    # ── 存結果 ──
    output_path = Path(args.marks_csv).parent / args.output
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        fieldnames = [
            "image", "n_stars", "date_obs_recorded",
            "error_no_offset_px", "best_clock_offset_hours",
            "error_with_offset_px", "improvement_px",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(result_rows)

    print(f"診斷結果已存至：{output_path}")
    print()
    print("解讀方式：")
    print("  - best_clock_offset_hours：把 date_obs 加上這麼多小時，誤差最小")
    print("    例如 +7.0 代表照片時鐘比實際 UTC 晚了 7 小時（可能記錄的是 UTC+7 或 UTC+8 時間）")
    print("  - error_with_offset_px：套上最佳時鐘修正後的殘差")
    print("    如果這個數字還是很大（>100px），代表時鐘不是唯一問題")
    print("  - 如果修正後誤差降到 <50px，代表時鐘修正有效果")


if __name__ == "__main__":
    main()
