"""
attach_resolution.py

把 scan_image_sizes.py 掃出來的「檔名 -> 解析度」對照表，接回你已經標好
星點的 CSV，補上 image_width / image_height 這兩欄。這樣不用重新標記任何
一張照片，就能讓 calibrate-full 知道每一筆資料是從多大的照片點出來的，
正確處理「相機中途切換過解析度/像素合併模式」的狀況。

用法：
    python attach_resolution.py lulin_star_marks_merged.csv image_sizes.csv lulin_star_marks_with_resolution.csv

行為：
    - 用星點 CSV 裡的 image 欄位 (檔名)，去 image_sizes.csv 裡查對應的寬高
    - 找得到的就補上 image_width/image_height
    - 找不到的會列出來，讓你知道還有哪些照片的解析度沒有資料
      (通常代表 scan_image_sizes.py 掃描的資料夾不完整，需要再掃別的資料夾)
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


def load_sizes(path: Path) -> dict[str, tuple[str, str]]:
    sizes: dict[str, tuple[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sizes[row["filename"]] = (row["width"], row["height"])
    return sizes


def main() -> None:
    parser = argparse.ArgumentParser(description="把解析度對照表接回星點標記 CSV")
    parser.add_argument("marks_csv", help="現有的星點標記 CSV (image,date_obs,name,x,y,...)")
    parser.add_argument("sizes_csv", help="scan_image_sizes.py 產生的解析度對照表")
    parser.add_argument("output_csv", help="輸出補齊解析度後的星點 CSV")
    args = parser.parse_args()

    sizes = load_sizes(Path(args.sizes_csv))

    with Path(args.marks_csv).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        base_fields = [name for name in (reader.fieldnames or []) if name not in ("image_width", "image_height")]

    output_fields = base_fields + ["image_width", "image_height"]

    matched = 0
    unmatched_images: Counter[str] = Counter()

    output_rows = []
    for row in rows:
        image = (row.get("image") or "").strip()
        size = sizes.get(image)
        entry = {field: row.get(field, "") for field in base_fields}
        if size:
            entry["image_width"], entry["image_height"] = size
            matched += 1
        else:
            entry["image_width"], entry["image_height"] = "", ""
            if image:
                unmatched_images[image] += 1
        output_rows.append(entry)

    with Path(args.output_csv).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"總共 {len(rows)} 筆標記，成功補上解析度 {matched} 筆 -> {args.output_csv}")

    if unmatched_images:
        total_unmatched_marks = sum(unmatched_images.values())
        print(
            f"\n⚠ 有 {total_unmatched_marks} 筆標記 (來自 {len(unmatched_images)} 張照片) "
            f"在解析度對照表裡找不到，這些照片可能沒被 scan_image_sizes.py 掃到："
        )
        for image, count in sorted(unmatched_images.items(), key=lambda item: -item[1])[:20]:
            print(f"  - {image}: {count} 筆標記")
        if len(unmatched_images) > 20:
            print(f"  ...還有 {len(unmatched_images) - 20} 張照片，省略顯示")


if __name__ == "__main__":
    main()
