"""
scan_image_sizes.py

掃描一個資料夾底下 (含子資料夾) 所有照片，讀出每張照片的寬 x 高，
輸出成一份 CSV 對照表 (image_sizes.csv)，供 attach_resolution.py 使用。

用法：
    python scan_image_sizes.py "C:\\Users\\SUN\\Desktop\\betelgeuse_taiwan" image_sizes.csv

行為：
    - 遞迴掃描指定資料夾底下的 .jpg/.jpeg/.png 檔案
    - 對每個檔案讀取寬高 (不需要打開整張圖片解碼，速度很快)
    - 輸出 CSV：filename, width, height
      (只存檔名，不含路徑，這樣才能跟星點 CSV 裡的 image 欄位對起來)
    - 如果同一個檔名在不同子資料夾出現、而且解析度還不一樣，會印出警告，
      請自行確認要用哪一張，避免對照錯誤
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from PIL import Image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def main() -> None:
    parser = argparse.ArgumentParser(description="掃描資料夾內所有照片的解析度")
    parser.add_argument("photo_folder", help="要掃描的照片資料夾 (會遞迴找子資料夾)")
    parser.add_argument("output_csv", help="輸出的對照表 CSV 路徑")
    args = parser.parse_args()

    folder = Path(args.photo_folder)
    if not folder.is_dir():
        raise SystemExit(f"找不到資料夾：{folder}")

    sizes: dict[str, tuple[int, int]] = {}
    conflicts: list[str] = []
    scanned = 0
    failed = 0

    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        try:
            with Image.open(path) as img:
                width, height = img.size
        except Exception as exc:  # noqa: BLE001
            print(f"[跳過，無法讀取] {path}: {exc}")
            failed += 1
            continue

        scanned += 1
        name = path.name
        if name in sizes and sizes[name] != (width, height):
            conflicts.append(
                f"{name}: 先前記錄為 {sizes[name][0]}x{sizes[name][1]}，"
                f"但 {path} 是 {width}x{height} —— 檔名重複但解析度不同，請確認"
            )
        sizes[name] = (width, height)

    with Path(args.output_csv).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "width", "height"])
        for name in sorted(sizes):
            writer.writerow([name, sizes[name][0], sizes[name][1]])

    print(f"\n掃描完成：共處理 {scanned} 張照片，{failed} 張讀取失敗，寫入 {len(sizes)} 筆到 {args.output_csv}")

    if conflicts:
        print(f"\n⚠ 發現 {len(conflicts)} 個檔名衝突 (同名但解析度不同)：")
        for line in conflicts:
            print(f"  - {line}")

    # 順便統計一下這個資料夾裡總共出現幾種不同的解析度，方便你確認猜想
    resolution_counts: dict[tuple[int, int], int] = {}
    for w, h in sizes.values():
        resolution_counts[(w, h)] = resolution_counts.get((w, h), 0) + 1
    print("\n這個資料夾裡出現的解析度統計：")
    for (w, h), count in sorted(resolution_counts.items(), key=lambda item: -item[1]):
        print(f"  {w} x {h}: {count} 張")


if __name__ == "__main__":
    main()
