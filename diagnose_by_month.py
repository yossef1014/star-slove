"""
diagnose_by_month.py

用途：把合併後的星點 CSV，依照 date_obs 的「年-月」分組，對每一組分別各自
單獨跑一次 calibrate-full，並把每個月份算出來的 cx/cy/horizon_radius_px/
rotation_deg 跟 mean_error_px 列出來比較。

目的：如果全部資料一起校正跑出離譜結果 (像 horizon_radius 崩到 91px)，
但某些月份「單獨」跑起來是正常、合理的，那就能一眼看出「是哪個月份的
資料在扯後腿」，不用整批資料一起大海撈針。

用法：
    python diagnose_by_month.py lulin_star_marks_merged.csv --calibration lulin_calibration.manual.json

需要跟 allsky_fisheye.py 放在同一個資料夾。
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import allsky_fisheye as af  # noqa: E402


def month_key(date_obs: str) -> str:
    # date_obs 格式類似 2026-07-03T22:00:31Z，取前 7 碼 "2026-07"
    return date_obs[:7] if date_obs else "(no-date)"


def main() -> None:
    parser = argparse.ArgumentParser(description="依月份分組，各自單獨跑 calibrate-full 並比較結果")
    parser.add_argument("marks_csv", help="合併後的星點 CSV")
    parser.add_argument("--calibration", required=True, help="起始猜測用的校正 JSON")
    args = parser.parse_args()

    marks = af.read_star_marks_multi(Path(args.marks_csv))
    groups: dict[str, list[dict]] = defaultdict(list)
    for mark in marks:
        groups[month_key(mark["date_obs"])].append(mark)

    print(f"讀到 {len(marks)} 筆原始標記，依月份分成 {len(groups)} 組：")
    for key in sorted(groups):
        print(f"  {key}: {len(groups[key])} 筆")
    print()

    try:
        from scipy.optimize import least_squares
    except ImportError:
        print("需要 scipy，請先 pip install scipy")
        return

    calibration_template = af.load_calibration(Path(args.calibration))

    print(f"{'月份':10s} {'可辨識筆數':>8s} {'cx':>10s} {'cy':>10s} {'radius':>10s} {'rotation':>10s} {'mean_err_px':>12s} {'max_err_px':>12s}")
    print("-" * 90)

    for key in sorted(groups):
        group_marks = groups[key]
        matches = []
        for mark in group_marks:
            catalog = af.BRIGHT_STARS.get(af.normalize_star_name(mark["name"]))
            if catalog is None or not mark["date_obs"]:
                continue
            try:
                af.Time(mark["date_obs"])
            except Exception:
                continue
            ra_deg, dec_deg = catalog
            matches.append({
                "x_obs": mark["x"], "y_obs": mark["y"],
                "ra_deg": ra_deg, "dec_deg": dec_deg, "date_obs": mark["date_obs"],
            })

        if len(matches) < 4:
            print(f"{key:10s} {len(matches):8d}   (資料不足 4 筆，跳過)")
            continue

        def residuals(params, matches=matches):
            cx, cy, radius, rotation = params
            trial = af.Calibration(**{**af.asdict(calibration_template)})
            trial.cx, trial.cy, trial.horizon_radius_px, trial.rotation_deg = cx, cy, radius, rotation
            out = []
            for m in matches:
                alt_deg, az_deg = af.radec_to_altaz(m["ra_deg"], m["dec_deg"], m["date_obs"], trial)
                x_pred, y_pred = af.altaz_to_pixel(alt_deg, az_deg, trial)
                out.append(float(x_pred) - m["x_obs"])
                out.append(float(y_pred) - m["y_obs"])
            return out

        x0 = [calibration_template.cx, calibration_template.cy,
              calibration_template.horizon_radius_px, calibration_template.rotation_deg]
        result = least_squares(residuals, x0)
        cx, cy, radius, rotation = result.x

        errs = []
        final_res = residuals(result.x)
        for i in range(0, len(final_res), 2):
            errs.append((final_res[i] ** 2 + final_res[i + 1] ** 2) ** 0.5)
        mean_err = sum(errs) / len(errs)
        max_err = max(errs)

        print(f"{key:10s} {len(matches):8d} {cx:10.1f} {cy:10.1f} {radius:10.1f} {rotation:10.1f} {mean_err:12.2f} {max_err:12.2f}")

    print()
    print("解讀方式：")
    print("- 如果大部分月份的 cx/cy/radius 數值都很接近、mean_err_px 也不大，")
    print("  但某個月份的數值差很多或 mean_err_px 特別大，該月份的資料很可能有問題")
    print("  (時間打錯、解析度不同、或標記本身點歪了)。")
    print("- 如果每個月份「各自」校正起來都正常，但全部合併在一起才跑歪，")
    print("  通常代表跨月份的假設 (同一顆相機、同一組 cx/cy/radius) 不成立，")
    print("  最可能是照片解析度中途變過。")


if __name__ == "__main__":
    main()
