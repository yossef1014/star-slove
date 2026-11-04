"""
star_marker_multi.py

可以在同一個程式裡開啟「不同張」全天魚眼照片、輪流標星，
所有照片標的星點統一存進同一份 CSV（不會互相覆蓋，用「附加」的方式寫入）。

CSV 欄位：
    image, date_obs, name, x, y

- image     : 這顆星是從哪張照片標的（存檔名，例如 2024_12_07__00_06_20.jpg）
- date_obs  : 這張照片的拍攝時間 (UTC, ISO 格式，例如 2024-12-06T16:05:11Z)
- name      : 星名（英文，例如 betelgeuse / rigel；留空會自動編號 star_01, star_02, ...）
- x, y      : 原始解析度下的 pixel 座標（不受畫面縮放顯示影響）

用法：
    python star_marker_multi.py lulin_star_marks_multi.csv

操作方式：
    1. 按「開啟照片」選擇一張魚眼照片 (jpg/png)
    2. 程式會嘗試從檔名自動判斷拍攝時間 (格式: YYYY_MM_DD__HH_MM_SS)，
       並跳出視窗讓你確認/修改這個時間 (要用 UTC)
    3. 在 "Star name" 欄位輸入星名，然後用滑鼠點圖片上的星點中心
    4. 每點一次就會立刻寫入 CSV 一列
    5. 可以隨時按「開啟照片」換下一張圖繼續標，全部存進同一份 CSV
    6. 如果點錯了，按「復原上一點」可以移除最後一筆紀錄

Guided mode（不會認星星也沒關係）：
    加上 --calibration 參數指定一份粗略的校正檔 (JSON)，程式會用它預測每顆
    亮星大概會出現在畫面上的哪裡，用紅色虛線圓圈 + 星名標出來。這時候把
    "Star name" 欄位留空，直接點提示點附近最亮的星，程式就會自動幫你填上
    正確的星名 (自動比對最近的提示點)，完全不用自己認星座。
    範例：
        python star_marker_multi.py lulin_star_marks_multi.csv --calibration lulin_calibration.manual.json
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    NS,
    RIGHT,
    TOP,
    X,
    Y,
    Button,
    Canvas,
    Entry,
    Frame,
    Label,
    Listbox,
    Scrollbar,
    StringVar,
    Tk,
    filedialog,
    messagebox,
    simpledialog,
)

from PIL import Image, ImageTk

# 讓 "guided mode" 可以重用 allsky_fisheye.py 裡的星表、投影公式。
# 這個檔案要跟 allsky_fisheye.py 放在同一個資料夾底下才能匯入。
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import allsky_fisheye as af
except ImportError:
    af = None  # 沒有這個檔案也沒關係，guided mode 會自動關閉，其餘功能照常運作

FILENAME_TIME_RE = re.compile(r"(\d{4})_(\d{2})_(\d{2})__(\d{2})_(\d{2})_(\d{2})")


def guess_date_obs_from_filename(path: Path) -> str | None:
    """嘗試從檔名猜出拍攝時間 (UTC)，支援多種常見命名格式。"""
    if af is not None and hasattr(af, "parse_filename_time"):
        parsed = af.parse_filename_time(path)
        if parsed:
            return parsed

    stem = path.stem
    for fmt in [
        "%Y_%m_%d__%H_%M_%S",
        "%Y_%m_%d_%H_%M_%S",
        "%Y-%m-%d_%H-%M-%S",
        "%Y%m%d_%H%M%S",
        "%Y-%m-%dT%H-%M-%S",
        "%Y-%m-%dT%H%M%S",
    ]:
        try:
            stamp = datetime.strptime(stem, fmt)
            return stamp.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            continue
    return None


class StarMarkerApp:
    def __init__(
        self,
        root: Tk,
        csv_path: Path,
        max_display_size: int = 1000,
        calibration_path: Path | None = None,
    ) -> None:
        self.root = root
        self.csv_path = csv_path
        self.max_display_size = max_display_size

        self.image_path: Path | None = None
        self.date_obs: str | None = None
        self.pil_image: Image.Image | None = None
        self.tk_image: ImageTk.PhotoImage | None = None
        self.base_scale: float = 1.0  # 「整張圖縮小到符合視窗」時的縮放比例
        self.zoom: float = 1.0  # 使用者額外的縮放倍率 (1.0 = 剛好符合視窗大小)
        self.min_zoom: float = 1.0
        self.max_zoom: float = 10.0
        self.scale: float = 1.0  # 實際套用的總縮放比例 = base_scale * zoom
        self.viewport_size: tuple[int, int] = (1, 1)
        self.auto_index = 0
        # 只記錄「目前這張照片」標過的點，用來畫圖 / undo / 列表顯示
        self.current_marks: list[dict] = []

        # ---- guided mode：用粗略的校正檔預測每顆星大概在哪 ----
        self.calibration = None
        if calibration_path is not None and af is not None:
            try:
                self.calibration = af.load_calibration(calibration_path)
            except Exception as exc:  # noqa: BLE001
                print(f"[警告] 無法讀取校正檔 {calibration_path}: {exc}，guided mode 停用。")
        # 目前這張照片上，尚未被使用的預測提示點： [{"name", "x", "y"}, ...]（原始解析度座標）
        self.guides: list[dict] = []

        self._ensure_csv_header()
        self._build_ui()

    # ---------- CSV 讀寫 ----------

    def _ensure_csv_header(self) -> None:
        if not self.csv_path.exists():
            # utf-8-sig：開頭加一個 BOM 標記，這樣用 Excel 直接雙擊打開 CSV 時
            # 才會自動判斷成 UTF-8，中文字不會變亂碼。
            with self.csv_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["image", "date_obs", "name", "x", "y", "image_width", "image_height"])
            return

        # 檔案已經存在 (例如你之前已經標過一部分星星，現在繼續用同一份 CSV)：
        # 如果是舊版標星工具建立的檔案，欄位只有 image,date_obs,name,x,y，
        # 沒有 image_width/image_height，這裡自動把表頭跟既有資料列都補上這
        # 兩欄 (既有資料填空白)，這樣接下來新增的列才不會跟表頭對不齊。
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        if not rows:
            with self.csv_path.open("w", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerow(["image", "date_obs", "name", "x", "y", "image_width", "image_height"])
            return

        header = rows[0]
        if "image_width" in header and "image_height" in header:
            return  # 已經是新格式，不用動

        header = header + ["image_width", "image_height"]
        migrated_rows = [header]
        for row in rows[1:]:
            migrated_rows.append(row + ["", ""])
        with self.csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(migrated_rows)

    def _append_row(self, name: str, x: float, y: float) -> None:
        width, height = self.pil_image.size if self.pil_image else ("", "")
        with self.csv_path.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    self.image_path.name if self.image_path else "",
                    self.date_obs or "",
                    name,
                    f"{x:.2f}",
                    f"{y:.2f}",
                    width,
                    height,
                ]
            )

    def _remove_last_row(self) -> None:
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            lines = f.readlines()
        if len(lines) > 1:  # 保留表頭
            with self.csv_path.open("w", encoding="utf-8-sig", newline="") as f:
                f.writelines(lines[:-1])

    # ---------- UI ----------

    def _build_ui(self) -> None:
        self.root.title("多張魚眼照片標星工具")

        top = Frame(self.root)
        top.pack(side=TOP, fill=X)

        Button(top, text="開啟照片", command=self.open_image).pack(side=LEFT, padx=4, pady=4)

        Label(top, text="Star name:").pack(side=LEFT, padx=(12, 2))
        self.name_var = StringVar()
        Entry(top, textvariable=self.name_var, width=20).pack(side=LEFT, padx=2)

        Button(top, text="復原上一點", command=self.undo_last).pack(side=LEFT, padx=12)

        Button(top, text="－", width=3, command=self.zoom_out_button).pack(side=LEFT, padx=(12, 0))
        self.zoom_var = StringVar(value="縮放: 100%")
        Label(top, textvariable=self.zoom_var, width=10).pack(side=LEFT)
        Button(top, text="＋", width=3, command=self.zoom_in_button).pack(side=LEFT)
        Button(top, text="重置縮放", command=self.zoom_reset).pack(side=LEFT, padx=(4, 0))

        self.status_var = StringVar(value="尚未開啟照片")
        Label(top, textvariable=self.status_var, fg="blue").pack(side=LEFT, padx=12)

        body = Frame(self.root)
        body.pack(side=TOP, fill=BOTH, expand=True)

        canvas_frame = Frame(body)
        canvas_frame.pack(side=LEFT, fill=BOTH, expand=True)
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.canvas = Canvas(canvas_frame, bg="black", cursor="cross")
        v_scroll = Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        h_scroll = Scrollbar(canvas_frame, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky=NS)
        h_scroll.grid(row=1, column=0, sticky="ew")

        self.canvas.bind("<Button-1>", self.on_click)
        # Windows / macOS 滑鼠滾輪
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        # Linux 滑鼠滾輪 (往上/往下各是不同事件)
        self.canvas.bind("<Button-4>", lambda e: self._zoom_at(e.x, e.y, 1.15))
        self.canvas.bind("<Button-5>", lambda e: self._zoom_at(e.x, e.y, 1 / 1.15))

        side = Frame(body, width=240)
        side.pack(side=RIGHT, fill=Y)
        Label(side, text="這張照片已標的星：").pack(anchor="w")
        self.listbox = Listbox(side, width=32)
        self.listbox.pack(fill=BOTH, expand=True)
        Label(
            side,
            text="提示：滑鼠滾輪可縮放\n(以游標位置為中心)，\n放大後可拖曳捲軸移動畫面。",
            fg="gray40",
            justify=LEFT,
        ).pack(anchor="w", pady=(8, 0))

    # ---------- 動作 ----------

    def open_image(self) -> None:
        path_str = filedialog.askopenfilename(
            title="選擇魚眼照片",
            filetypes=[("Image files", "*.jpg *.jpeg *.png"), ("All files", "*.*")],
        )
        if not path_str:
            return
        self.image_path = Path(path_str)

        guessed = guess_date_obs_from_filename(self.image_path)
        date_obs = simpledialog.askstring(
            "拍攝時間 (date-obs)",
            "請確認/輸入這張照片的拍攝時間\n(UTC, ISO 格式，例如 2024-12-06T16:05:11Z)：",
            initialvalue=guessed or "",
            parent=self.root,
        )
        if date_obs is None:
            date_obs = guessed
        self.date_obs = date_obs

        self.pil_image = Image.open(self.image_path).convert("RGB")
        width, height = self.pil_image.size
        self.base_scale = min(1.0, self.max_display_size / max(width, height))
        self.zoom = 1.0
        self.scale = self.base_scale * self.zoom

        self.viewport_size = (
            max(1, int(width * self.base_scale)),
            max(1, int(height * self.base_scale)),
        )
        self.canvas.config(width=self.viewport_size[0], height=self.viewport_size[1])

        self.current_marks = []
        self.listbox.delete(0, END)
        self.auto_index = 0
        self._compute_guides()
        self._render_canvas_image()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.zoom_var.set(f"縮放: {int(self.zoom * 100)}%")

        self.status_var.set(
            f"{self.image_path.name} | date_obs = {self.date_obs or '未設定！請小心'}"
        )
        if not self.date_obs:
            messagebox.showwarning(
                "沒有拍攝時間",
                "這張照片沒有設定 date_obs，標出來的星點之後沒辦法拿去做校正。\n"
                "建議重新按「開啟照片」，在跳出的視窗填入正確時間。",
            )

    def _render_canvas_image(self) -> None:
        """依照目前的 self.scale (base_scale * zoom) 重新產生要顯示的圖片，
        並更新 scrollregion，接著重畫提示點與已標記的星。"""
        if self.pil_image is None:
            return
        width, height = self.pil_image.size
        disp_w = max(1, int(width * self.scale))
        disp_h = max(1, int(height * self.scale))
        display_image = self.pil_image.resize((disp_w, disp_h))
        self.tk_image = ImageTk.PhotoImage(display_image)
        self.canvas.config(scrollregion=(0, 0, disp_w, disp_h))
        self._redraw_all_marks()

    def _compute_guides(self) -> None:
        self.guides = []
        if self.calibration is None or af is None or not self.date_obs:
            return
        for name, (ra_deg, dec_deg) in af.BRIGHT_STARS.items():
            try:
                alt_deg, az_deg = af.radec_to_altaz(ra_deg, dec_deg, self.date_obs, self.calibration)
                if float(alt_deg) <= 0:
                    continue  # 在地平線以下，這張照片看不到
                x, y = af.altaz_to_pixel(alt_deg, az_deg, self.calibration)
            except Exception:  # noqa: BLE001
                continue
            self.guides.append({"name": name, "x": float(x), "y": float(y)})

    def _draw_guides(self) -> None:
        if not self.pil_image:
            return
        width, height = self.pil_image.size
        for guide in self.guides:
            gx, gy = guide["x"], guide["y"]
            if not (0 <= gx < width and 0 <= gy < height):
                continue
            cx = int(round(gx * self.scale))
            cy = int(round(gy * self.scale))
            r = 16
            self.canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                outline="#ff5050", width=1, dash=(3, 2),
            )
            self.canvas.create_text(
                cx, cy + r + 10, text=guide["name"], fill="#ff8080", anchor="n"
            )

    def _nearest_unused_guide(self, x_full: float, y_full: float, max_dist_px: float) -> dict | None:
        best = None
        best_dist = max_dist_px
        for guide in self.guides:
            dist = ((guide["x"] - x_full) ** 2 + (guide["y"] - y_full) ** 2) ** 0.5
            if dist <= best_dist:
                best = guide
                best_dist = dist
        return best

    def _zoom_at(self, screen_x: int, screen_y: int, factor: float) -> None:
        if self.pil_image is None:
            return

        # 記錄游標目前對應到原始圖片上的哪個點，縮放後要讓這個點還在同一個螢幕位置
        canvas_x = self.canvas.canvasx(screen_x)
        canvas_y = self.canvas.canvasy(screen_y)
        img_x = canvas_x / self.scale
        img_y = canvas_y / self.scale

        new_zoom = min(max(self.zoom * factor, self.min_zoom), self.max_zoom)
        if abs(new_zoom - self.zoom) < 1e-6:
            return
        self.zoom = new_zoom
        self.scale = self.base_scale * self.zoom
        self._render_canvas_image()
        self.zoom_var.set(f"縮放: {int(self.zoom * 100)}%")

        width, height = self.pil_image.size
        disp_w = max(1, int(width * self.scale))
        disp_h = max(1, int(height * self.scale))
        view_w, view_h = self.viewport_size

        new_canvas_x = img_x * self.scale
        new_canvas_y = img_y * self.scale
        max_x_fraction = max(disp_w - view_w, 0) / disp_w
        max_y_fraction = max(disp_h - view_h, 0) / disp_h
        x_fraction = min(max((new_canvas_x - screen_x) / disp_w, 0.0), max_x_fraction)
        y_fraction = min(max((new_canvas_y - screen_y) / disp_h, 0.0), max_y_fraction)
        self.canvas.xview_moveto(x_fraction)
        self.canvas.yview_moveto(y_fraction)

    def on_mousewheel(self, event) -> None:
        # Windows: event.delta 是 120 的倍數；正值=往上滾(放大)，負值=往下滾(縮小)
        factor = 1.15 if event.delta > 0 else 1 / 1.15
        self._zoom_at(event.x, event.y, factor)

    def zoom_in_button(self) -> None:
        cx = self.canvas.winfo_width() // 2
        cy = self.canvas.winfo_height() // 2
        self._zoom_at(cx, cy, 1.25)

    def zoom_out_button(self) -> None:
        cx = self.canvas.winfo_width() // 2
        cy = self.canvas.winfo_height() // 2
        self._zoom_at(cx, cy, 1 / 1.25)

    def zoom_reset(self) -> None:
        if self.pil_image is None:
            return
        self.zoom = 1.0
        self.scale = self.base_scale
        self._render_canvas_image()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.zoom_var.set(f"縮放: {int(self.zoom * 100)}%")

    def on_click(self, event) -> None:
        if self.pil_image is None:
            messagebox.showinfo("提示", "請先按「開啟照片」載入一張圖片")
            return

        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        x_full = canvas_x / self.scale
        y_full = canvas_y / self.scale

        typed_name = self.name_var.get().strip()
        guide_match = None
        if not typed_name:
            # 沒手動輸入名字時，才嘗試自動比對最近的提示點（顯示畫面上 40 像素內）
            guide_match = self._nearest_unused_guide(x_full, y_full, max_dist_px=40 / self.scale)

        if typed_name:
            name = typed_name
        elif guide_match is not None:
            name = guide_match["name"]
            self.guides.remove(guide_match)  # 用掉這個提示，避免重複建議
        else:
            self.auto_index += 1
            name = f"star_{self.auto_index:02d}"

        self._append_row(name, x_full, y_full)
        self.current_marks.append({"name": name, "x": x_full, "y": y_full})

        self._draw_mark(canvas_x, canvas_y, name)
        self.listbox.insert(END, f"{name}  ({x_full:.1f}, {y_full:.1f})")

    def _draw_mark(self, cx: int, cy: int, name: str) -> None:
        r = 6
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline="yellow", width=2)
        self.canvas.create_line(cx - r - 3, cy, cx - r, cy, fill="yellow", width=2)
        self.canvas.create_line(cx + r, cy, cx + r + 3, cy, fill="yellow", width=2)
        self.canvas.create_text(cx + r + 6, cy - 8, text=name, fill="yellow", anchor="w")

    def _redraw_all_marks(self) -> None:
        # 圖片本身保留在畫布最底層，接著畫紅色虛線提示點，最後畫使用者實際標記(蓋在最上面)
        self.canvas.delete("all")
        if self.tk_image is not None:
            self.canvas.create_image(0, 0, anchor="nw", image=self.tk_image)
        self._draw_guides()
        for mark in self.current_marks:
            cx = int(round(mark["x"] * self.scale))
            cy = int(round(mark["y"] * self.scale))
            self._draw_mark(cx, cy, mark["name"])

    def undo_last(self) -> None:
        if not self.current_marks:
            messagebox.showinfo("提示", "這張照片目前還沒有標記可以復原")
            return
        self._remove_last_row()
        self.current_marks.pop()
        self.listbox.delete(END)
        self._redraw_all_marks()


def main() -> None:
    parser = argparse.ArgumentParser(description="多張魚眼照片共用同一份 CSV 的手動標星工具")
    parser.add_argument("output_csv", help="要寫入/續寫的星點 CSV 檔案路徑")
    parser.add_argument(
        "--max-display-size",
        type=int,
        default=1000,
        help="圖片顯示視窗的最大邊長 (pixel)，預設 1000，不影響實際記錄的座標",
    )
    parser.add_argument(
        "--calibration",
        help=(
            "選填：一份粗略的校正 JSON (例如 lulin_calibration.manual.json)。"
            "提供的話，開啟照片後程式會用它預測每顆亮星大概在畫面上的哪裡，"
            "用紅色虛線圓圈標出來並附上星名——你只要對著提示點附近點擊，"
            "程式就會自動幫你填上正確的星名，不用自己認星座。"
        ),
    )
    args = parser.parse_args()

    calibration_path = Path(args.calibration) if args.calibration else None

    root = Tk()
    StarMarkerApp(
        root,
        Path(args.output_csv),
        max_display_size=args.max_display_size,
        calibration_path=calibration_path,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
