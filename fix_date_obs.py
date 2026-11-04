"""
fix_date_obs.py

分析並修正 star marks CSV 中的 date_obs 時區問題。

鹿林天文台 (UTC+8) 觀測通常在本地時間 20:00~06:00（隔天）
= UTC 12:00~22:00，或隔天 UTC 00:00~22:00（若觀測跨午夜）。

如果 date_obs 記錄的是台灣本地時間但被標成 UTC (Z 結尾)，
那麼本地 08:00 被存成 "T08:00:00Z"，真正的 UTC 應是 "T00:00:00Z"。
換句話說，要「減去 8 小時」才是真正的 UTC。

用法：
    python fix_date_obs.py lulin_star_marks_final2.csv lulin_star_marks_fixed.csv

本腳本會：
1. 解析每張照片的 date_obs UTC 小時
2. 判斷該小時在鹿林天文台是否是「合理的夜間觀測時段」
3. 如果不是（例如 UTC 08:00 = 台灣 16:00，大白天），
   嘗試看看扣掉 8 小時後是否在夜間觀測時段
4. 如果是，就把那筆 date_obs 自動扣掉 8 小時
5. 輸出修正後的 CSV 及診斷報告

注意：本腳本只做「確定的」修正，不確定的會標出來讓你人工確認。
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path


# 鹿林天文台在 UTC+8，合理的天文觀測夜間時段（本地時間）：
# 一般約本地 20:00 ~ 次日 06:00
# 轉成 UTC 就是 12:00 ~ 22:00（當天），或 00:00 ~ 00:00（跨日，但用 UTC 表達時會跨到隔天）
# 簡化判斷：UTC 小時在 10~22 之間 → 本地約 18:00~06:00 → 夜間 ✓
#           UTC 小時在  0~10 之間 → 本地約 08:00~18:00 → 白天 ✗（除非是凌晨本地0~2點對到 UTC 16~18）
#
# 實際上鹿林台的觀測窗口（UTC）：大約 11:00 ~ 21:00（本地 19:00 ~ 05:00+1）
NIGHT_UTC_HOURS_MIN = 11   # UTC 11:00 以後算夜間（本地 19:00+）
NIGHT_UTC_HOURS_MAX = 5    # UTC 05:00 以前算夜間（本地 13:00，但跨日0點算法）

def is_night_utc(hour: int) -> bool:
    """判斷這個 UTC 小時在鹿林是否屬於夜間觀測時段。"""
    # 夜間 UTC 11:00~23:00 或 UTC 00:00~05:00（跨午夜）
    return hour >= NIGHT_UTC_HOURS_MIN or hour <= NIGHT_UTC_HOURS_MAX


def fix_date_obs(date_obs: str, offset_hours: int = -8) -> str:
    """把 date_obs 加上 offset_hours 小時，保持 ISO 格式（Z 結尾）。"""
    if not date_obs:
        return date_obs
    try:
        dt = datetime.fromisoformat(date_obs.replace("Z", "+00:00"))
        dt_fixed = dt + timedelta(hours=offset_hours)
        return dt_fixed.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return date_obs


def main() -> None:
    parser = argparse.ArgumentParser(description="修正 star marks CSV 中的 date_obs 時區問題")
    parser.add_argument("input_csv", help="輸入的星點標記 CSV")
    parser.add_argument("output_csv", help="輸出修正後的 CSV")
    parser.add_argument(
        "--offset",
        type=int,
        default=-8,
        help="要套用的時鐘修正小時數（預設 -8，即從 UTC+8 本地時間還原成 UTC）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只顯示診斷，不實際寫入輸出檔",
    )
    args = parser.parse_args()

    with Path(args.input_csv).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    # 按「照片」分組，統計每張照片的 date_obs
    image_groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        image_groups[row.get("image", "")].append(row)

    # 分析每張照片
    fixed_images: set[str] = set()
    already_night: set[str] = set()
    ambiguous: set[str] = set()
    bad_date: set[str] = set()

    print(f"分析 {len(image_groups)} 張照片的 date_obs...")
    print()

    stats = {"night_ok": 0, "fixed": 0, "ambiguous": 0, "bad": 0, "skipped": 0}

    for image, image_rows in sorted(image_groups.items()):
        date_obs = image_rows[0].get("date_obs", "")
        if not date_obs or len(date_obs) < 13:
            bad_date.add(image)
            stats["bad"] += 1
            continue

        try:
            utc_hour = int(date_obs[11:13])
        except ValueError:
            bad_date.add(image)
            stats["bad"] += 1
            continue

        is_currently_night = is_night_utc(utc_hour)
        fixed_date = fix_date_obs(date_obs, args.offset)
        fixed_hour = int(fixed_date[11:13]) if len(fixed_date) >= 13 else -1
        is_fixed_night = is_night_utc(fixed_hour)

        if is_currently_night:
            # 目前的 UTC 時間已經是夜間 → 不需要修正
            already_night.add(image)
            stats["night_ok"] += 1
        elif is_fixed_night:
            # 目前是白天，但修正後是夜間 → 確定需要修正
            fixed_images.add(image)
            stats["fixed"] += 1
        else:
            # 修正前後都不像夜間（或都像夜間）→ 標記為不確定
            ambiguous.add(image)
            stats["ambiguous"] += 1

    print(f"診斷結果：")
    print(f"  ✓ date_obs 已經是正確的 UTC 夜間時段：{stats['night_ok']} 張照片")
    print(f"  → 需要修正 (date_obs 看起來是本地時間)：{stats['fixed']} 張照片")
    print(f"  ? 不確定（需要人工確認）：{stats['ambiguous']} 張照片")
    print(f"  ✗ date_obs 格式有問題：{stats['bad']} 張照片")
    print()

    if fixed_images:
        print(f"會被修正的照片（套用 {args.offset:+d}h）：")
        for img in sorted(fixed_images)[:20]:
            date_obs = image_groups[img][0]["date_obs"]
            fixed = fix_date_obs(date_obs, args.offset)
            print(f"  {img[:45]:45s}  {date_obs}  ->  {fixed}")
        if len(fixed_images) > 20:
            print(f"  ...還有 {len(fixed_images) - 20} 張（已省略）")
        print()

    if ambiguous:
        print(f"不確定的照片（請人工確認）：")
        for img in sorted(ambiguous)[:10]:
            date_obs = image_groups[img][0]["date_obs"]
            print(f"  {img[:45]:45s}  {date_obs}")
        if len(ambiguous) > 10:
            print(f"  ...還有 {len(ambiguous) - 10} 張")
        print()

    if args.dry_run:
        print("[dry-run 模式，不寫入輸出檔]")
        return

    # 寫入修正後的 CSV
    output_rows = []
    corrections = 0
    for row in rows:
        new_row = dict(row)
        image = row.get("image", "")
        if image in fixed_images:
            old_date = row.get("date_obs", "")
            new_date = fix_date_obs(old_date, args.offset)
            new_row["date_obs"] = new_date
            corrections += 1
        output_rows.append(new_row)

    with Path(args.output_csv).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"完成：修正了 {corrections} 筆記錄 ({len(fixed_images)} 張照片)")
    print(f"輸出至：{args.output_csv}")
    print()
    print("下一步建議：")
    print(f"  1. 用修正後的 CSV 重新跑 calibrate-full：")
    print(f"     python allsky_fisheye.py calibrate-full {args.output_csv} \\")
    print(f"         lulin_calibration.fixed.json \\")
    print(f"         --calibration lulin_calibration.manual.json \\")
    print(f"         --fit-clock --clock-group-by date \\")
    print(f"         --report report_fixed.csv")


if __name__ == "__main__":
    main()
