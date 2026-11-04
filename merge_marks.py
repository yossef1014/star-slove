"""
merge_marks.py

把組員各自標的星點 CSV（每人一份）合併成一份給 `allsky_fisheye.py
calibrate-full` 使用的檔案。

必要欄位：image, date_obs, name, x, y
選填欄位：image_width, image_height (新版 star_marker_multi.py 會自動記錄，
          用來讓不同解析度拍的照片可以安全地一起校正；沒有這兩欄的舊檔案
          一樣能合併，缺的部分留空即可)

用法：
    python merge_marks.py merged.csv marks_小明.csv marks_小華.csv marks_小美.csv

行為：
    - 依序讀入每份輸入 CSV
    - 完全重複的列（同一張照片、同一顆星、同樣座標）只會保留一份，
      避免有人不小心重複上傳同一份檔案
    - 合併結果依 image、name 排序後輸出，方便你之後人工檢查
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

REQUIRED_FIELDS = ["image", "date_obs", "name", "x", "y"]
OPTIONAL_FIELDS = ["image_width", "image_height"]
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS


def load_marks(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        available = reader.fieldnames or []
        missing = [field for field in REQUIRED_FIELDS if field not in available]
        if missing:
            raise ValueError(
                f"{path.name} 缺少欄位 {missing}，"
                f"它有的欄位是 {available}。"
                f"請確認這份檔案是用 star_marker_multi.py 產生的。"
            )
        has_resolution = "image_width" in available and "image_height" in available
        rows = []
        for row in reader:
            entry = {field: (row.get(field) or "").strip() for field in REQUIRED_FIELDS}
            if has_resolution:
                entry["image_width"] = (row.get("image_width") or "").strip()
                entry["image_height"] = (row.get("image_height") or "").strip()
            else:
                entry["image_width"] = ""
                entry["image_height"] = ""
            rows.append(entry)
        return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="合併多份星點標記 CSV")
    parser.add_argument("output_csv", help="合併後輸出的 CSV 路徑")
    parser.add_argument("input_csvs", nargs="+", help="要合併的來源 CSV 檔案（可以多個組員各一份）")
    args = parser.parse_args()

    all_rows: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()
    duplicate_count = 0
    missing_resolution_count = 0

    for input_path_str in args.input_csvs:
        input_path = Path(input_path_str)
        rows = load_marks(input_path)
        for row in rows:
            key = tuple(row[field] for field in ALL_FIELDS)
            if key in seen:
                duplicate_count += 1
                continue
            seen.add(key)
            if not row["image_width"] or not row["image_height"]:
                missing_resolution_count += 1
            all_rows.append(row)
        print(f"{input_path.name}: 讀入 {len(rows)} 筆")

    all_rows.sort(key=lambda r: (r["image"], r["name"]))

    output_path = Path(args.output_csv)
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ALL_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\n合併完成：共 {len(all_rows)} 筆星點紀錄 -> {output_path}")
    if duplicate_count:
        print(f"（其中略過了 {duplicate_count} 筆完全重複的紀錄）")
    if missing_resolution_count:
        print(
            f"（有 {missing_resolution_count} 筆缺少 image_width/image_height，"
            f"如果照片解析度不一致，建議先用 scan_image_sizes.py + attach_resolution.py 補齊）"
        )

    images = sorted({row["image"] for row in all_rows if row["image"]})
    print(f"涵蓋 {len(images)} 張照片：{', '.join(images)}")


if __name__ == "__main__":
    main()
