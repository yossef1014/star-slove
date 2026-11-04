"""
merge_sizes.py

把組員各自在自己電腦上用 scan_image_sizes.py 掃出來的解析度對照表
(filename,width,height)，合併成一份給 attach_resolution.py 使用。

用法：
    python merge_sizes.py merged_sizes.csv sizes_小明.csv sizes_小華.csv sizes_小美.csv

行為：
    - 依序讀入每份輸入 CSV
    - 如果同一個檔名在不同人的對照表裡出現、而且解析度不一樣，會印出警告，
      請自行確認 (通常代表兩人手上有同檔名但不同來源的照片，要弄清楚哪張才對)
    - 沒有衝突的話，同檔名重複出現只會保留一筆，不會出錯
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="合併多份照片解析度對照表")
    parser.add_argument("output_csv", help="合併後輸出的 CSV 路徑")
    parser.add_argument("input_csvs", nargs="+", help="要合併的來源 CSV 檔案（組員各自掃描出來的那份）")
    args = parser.parse_args()

    sizes: dict[str, tuple[str, str]] = {}
    sources: dict[str, str] = {}
    conflicts: list[str] = []

    for input_path_str in args.input_csvs:
        input_path = Path(input_path_str)
        with input_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                name = row["filename"]
                size = (row["width"], row["height"])
                count += 1
                if name in sizes and sizes[name] != size:
                    conflicts.append(
                        f"{name}: {sources[name]} 說是 {sizes[name][0]}x{sizes[name][1]}，"
                        f"但 {input_path.name} 說是 {size[0]}x{size[1]} —— 請確認哪個才對"
                    )
                    continue  # 保留先出現的那筆，衝突的部分列出來讓你自己判斷
                sizes[name] = size
                sources[name] = input_path.name
        print(f"{input_path.name}: 讀入 {count} 筆")

    output_path = Path(args.output_csv)
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "width", "height"])
        for name in sorted(sizes):
            writer.writerow([name, sizes[name][0], sizes[name][1]])

    print(f"\n合併完成：共 {len(sizes)} 張照片的解析度資料 -> {output_path}")

    if conflicts:
        print(f"\n⚠ 發現 {len(conflicts)} 個檔名衝突：")
        for line in conflicts:
            print(f"  - {line}")


if __name__ == "__main__":
    main()
