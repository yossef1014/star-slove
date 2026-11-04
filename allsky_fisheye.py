from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.io import fits
from astropy.time import Time
import astropy.units as u
from astropy.utils import iers
from PIL import Image, ImageDraw, ImageFont

# 這個程式不需要「角秒等級」的極端精度，用內建/快取的地球自轉修正資料就綽綽有餘。
# 停用自動連網下載 IERS 資料表，避免在校園網路/防火牆環境下卡住甚至直接報錯。
iers.conf.auto_download = False
iers.conf.auto_max_age = None


BRIGHT_STARS = {
    "betelgeuse": (88.7929, 7.4071),
    "rigel": (78.6345, -8.2016),
    "bellatrix": (81.2828, 6.3497),
    "saiph": (86.9391, -9.6696),
    "alnitak": (85.1897, -1.9426),
    "alnilam": (84.0534, -1.2019),
    "mintaka": (83.0017, -0.2991),
    "sirius": (101.2872, -16.7161),
    "procyon": (114.8255, 5.2250),
    "aldebaran": (68.9800, 16.5093),
    "capella": (79.1723, 45.9980),
    # 一月新增：涵蓋一月晚間全天空更分散的方位/高度，有助於聯合校正
    "polaris": (37.9546, 89.2642),      # 北極星，幾乎不動，對校正圓心/旋轉角很有幫助
    "canopus": (95.9879, -52.6956),     # 全天第二亮，南方低空，對校正 horizon_radius 很關鍵
    "pollux": (116.3289, 28.0261),
    "castor": (113.6499, 31.8883),
    "elnath": (81.5726, 28.6075),
    "menkalinan": (89.8817, 44.9475),
    "alhena": (99.4279, 16.3993),
    "adhara": (104.6565, -28.9719),
    "regulus": (152.0929, 11.9672),
    # 五～七月新增：春夏季星空 (獅子座之後、室女座、天蠍座、夏季大三角)
    "spica": (201.2983, -11.1614),        # 角宿一，室女座 α
    "denebola": (177.2650, 14.5719),      # 五帝座一，獅子座 β
    "alphard": (141.8968, -8.6586),       # 星宿一，長蛇座 α
    "antares": (247.3521, -26.4319),      # 心宿二，天蠍座 α
    "vega": (279.2346, 38.7836),          # 織女一，天琴座 α
    "altair": (297.6958, 8.8683),         # 河鼓二，牽牛星，天鷹座 α
    "deneb": (310.3579, 45.2803),         # 天津四，天鵝座 α (別名 Arided)
    "fomalhaut": (344.4125, -29.6222),    # 北落師門，南魚座 α
    "hamal": (31.7933, 23.4625),          # 婁宿三，白羊座 α
    # 北斗七星 (大熊座)
    "dubhe": (165.9319, 61.7511),         # 天樞，北斗一
    "merak": (165.4604, 56.3825),         # 天璇，北斗二
    "phecda": (178.4576, 53.6947),        # 天璣，北斗三
    "megrez": (183.8567, 57.0325),        # 天權，北斗四
    "alioth": (193.5071, 55.9597),        # 玉衡，北斗五
    "mizar": (200.9813, 54.9253),         # 開陽，北斗六
    "alkaid": (206.8850, 49.3133),        # 搖光，北斗七
    # 仙后座 / 仙女座 / 天鵝座尾部 / 天蠍座尾 / 飛馬座 / 人馬座 (跟隨夏季觀測會用到)
    "schedar": (10.1267, 56.5372),        # 王良四，仙后座 α
    "gammacas": (14.1771, 60.7167),       # 策，仙后座 γ
    "alrakis": (257.1963, 65.7147),       # 上弼，天龍座 ζ
    "alpheratz": (2.0971, 29.0906),       # 壁宿二，仙女座 α
    "mirach": (17.4329, 35.6206),         # 奎宿九，仙女座 β
    "shaula": (263.4021, -37.1039),       # 尾宿八，天蠍座 λ
    "markab": (346.1904, 15.2053),        # 室宿一，飛馬座 α
    "nunki": (283.8163, -26.2967),        # 斗宿四，人馬座 σ
    "hydraetau1": (142.286, -2.769),      # 星宿二，長蛇座 τ¹ (座標精度較低，建議日後覆核)
    "arcturus": (213.9154, 19.1826),      # 大角，牧夫座 α，全天第四亮星
    "rasalhague": (263.7338, 12.5603),    # 候，蛇夫座 α
    "diphda": (10.8975, -17.9867),        # 土司空，鯨魚座 β (別名 Deneb Kaitos)
    "ankaa": (6.5708, -42.3061),          # 火鳥六，鳳凰座 α
    "algenib": (3.3092, 15.1836),         # 壁宿一，飛馬座 γ
}

STAR_ALIASES = {
    "參宿四": "betelgeuse",
    "參宿七": "rigel",
    "參宿五": "bellatrix",
    "參宿六": "saiph",
    "參宿一": "alnitak",
    "參宿二": "alnilam",
    "參宿三": "mintaka",
    "天狼星": "sirius",
    "南河三": "procyon",
    "畢宿五": "aldebaran",
    "五車二": "capella",
    "北極星": "polaris",
    "老人星": "canopus",
    "北河三": "pollux",
    "北河二": "castor",
    "五車五": "elnath",
    "五車三": "menkalinan",
    "井宿三": "alhena",
    "弧矢七": "adhara",
    "軒轅十四": "regulus",
    # 五～七月新增
    "角宿一": "spica",
    "五帝座一": "denebola",
    "星宿一": "alphard",
    "心宿二": "antares",
    "織女一": "vega",
    "河鼓二": "altair",
    "天津四": "deneb",
    "arided": "deneb",             # Deneb 的歷史別名
    "北落師門": "fomalhaut",
    "婁宿三": "hamal",
    "天樞": "dubhe",
    "北斗一": "dubhe",
    "天璇": "merak",
    "北斗二": "merak",
    "天璣": "phecda",
    "北斗三": "phecda",
    "天權": "megrez",
    "北斗四": "megrez",
    "玉衡": "alioth",
    "北斗五": "alioth",
    "開陽": "mizar",
    "北斗六": "mizar",
    "搖光": "alkaid",
    "北斗七": "alkaid",
    "王良四": "schedar",
    "策": "gammacas",
    "上弼": "alrakis",
    "壁宿二": "alpheratz",
    "奎宿九": "mirach",
    "尾宿八": "shaula",
    "室宿一": "markab",
    "斗宿四": "nunki",
    "星宿二": "hydraetau1",
    "大角": "arcturus",
    "候": "rasalhague",
    "侯": "rasalhague",             # 常見同音手誤
    "土司空": "diphda",
    "denebkaitos": "diphda",       # Diphda 的別名
    "火鳥六": "ankaa",
    "壁宿一": "algenib",
    "alhajoth": "capella",         # Capella 的歷史別名 (阿拉伯文音譯)
    # 常見手滑錯字，直接視為對應的正確星名
    "betelgeux": "betelgeuse",
    "sirlus": "sirius",
    "begulus": "regulus",
    "rpocyon": "procyon",
    "caonpus": "canopus",
    "formalhaut": "fomalhaut",
}


@dataclass
class Calibration:
    instrument: str = "All-sky fisheye camera"
    observer: str = "Unknown"
    site: str = "Unknown"
    latitude_deg: float = 23.5
    longitude_deg: float = 120.9
    height_m: float = 100.0
    projection: str = "equidistant"
    cx: float = 1024.0
    cy: float = 1024.0
    horizon_radius_px: float = 980.0
    rotation_deg: float = 0.0
    notes: str = "Initial all-sky fisheye calibration."
    # cx/cy/horizon_radius_px 都是「在這個基準解析度下」量出來的像素座標。
    # 如果相機曾經用不同的像素合併(binning)/解析度拍照，量測到的星點座標要先
    # 換算成這個基準解析度下的等效座標，才能跟其他解析度的照片一起校正。
    reference_width_px: float = 0.0
    reference_height_px: float = 0.0
    east_left: bool = True  # 天球星圖標準方位：面向北方仰望天空時，左為東、右為西


def load_calibration(path: Path) -> Calibration:
    values = json.loads(path.read_text(encoding="utf-8"))
    from dataclasses import fields
    valid_keys = {f.name for f in fields(Calibration)}
    filtered = {k: v for k, v in values.items() if k in valid_keys}
    return Calibration(**filtered)


def write_calibration(path: Path, calibration: Calibration) -> None:
    path.write_text(json.dumps(asdict(calibration), indent=2), encoding="utf-8")


def normalize_star_name(name: str) -> str:
    normalized = name.strip().lower().replace(" ", "").replace("_", "")
    return STAR_ALIASES.get(normalized, normalized)


def normalize_date_obs(date_obs: str | None) -> str:
    if date_obs:
        return date_obs
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_png_as_array(path: Path, keep_rgb: bool) -> np.ndarray:
    image = Image.open(path)
    if keep_rgb:
        image = image.convert("RGB")
        data = np.array(image)
        return np.moveaxis(data, -1, 0)

    image = image.convert("L")
    return np.array(image)


def parse_filename_time(path: Path) -> str | None:
    """嘗試從檔名解析拍攝時間 (UTC)。
    支援多種格式：
    1. 鹿林慣用：YYYY_MM_DD__HH_MM_SS
    2. 常見底線格式：YYYY_MM_DD_HHMMSS 或 YYYYMMDD_HHMMSS
    3. ISO 常見格式：YYYY-MM-DDTHH-MM-SS 或 YYYY-MM-DDTHHMMSS
    """
    stem = path.stem
    # 1. YYYY_MM_DD__HH_MM_SS
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


# 保留舊函式名稱以維持相容性
parse_lulin_filename_time = parse_filename_time


def lulin_default_calibration() -> Calibration:
    return Calibration(
        instrument="Alcor System ALPHEA 6CW All Sky Camera; ZWO ASI178MC + 1.55mm fisheye lens",
        observer="Lulin Observatory",
        site="Lulin Observatory",
        latitude_deg=23.4667,
        longitude_deg=120.8667,
        height_m=2862.0,
        projection="equidistant",
        cx=735.0,
        cy=515.0,
        horizon_radius_px=510.0,
        rotation_deg=0.0,
        reference_width_px=1548.0,
        reference_height_px=1040.0,
        notes=(
            "Initial Lulin all-sky estimate. Confirm cx/cy/radius with estimate-circle, "
            "then refine rotation_deg with identified stars. Reference resolution assumed "
            "1548x1040 (2x2-binned mode) based on the original manual cx/cy/radius guess; "
            "photos at other resolutions get rescaled to this reference before fitting."
        ),
    )


def fit_circle_kasa(points: np.ndarray) -> tuple[float, float, float]:
    x = points[:, 0]
    y = points[:, 1]
    design = np.column_stack([x, y, np.ones_like(x)])
    rhs = -(x * x + y * y)
    a, b, c = np.linalg.lstsq(design, rhs, rcond=None)[0]
    cx = -a / 2.0
    cy = -b / 2.0
    radius = float(np.sqrt((cx * cx) + (cy * cy) - c))
    return float(cx), float(cy), radius


def estimate_sky_circle(
    image_path: Path,
    threshold: int = 24,
    max_x: int | None = None,
    max_y: int | None = None,
    base_calibration: Calibration | None = None,
    mask_timestamp_corner: bool = False,
) -> tuple[Calibration, np.ndarray]:
    image = Image.open(image_path).convert("L")
    gray = np.array(image)
    height, width = gray.shape

    allowed = np.ones_like(gray, dtype=bool)
    if max_x is not None:
        allowed[:, max_x:] = False
    if max_y is not None:
        allowed[max_y:, :] = False
    if mask_timestamp_corner:
        allowed[:30, :160] = False

    mask = (gray > threshold) & allowed
    points: list[tuple[int, int]] = []

    for y in range(40, min(height - 40, max_y or height), 4):
        xs = np.flatnonzero(mask[y])
        if xs.size >= 30:
            points.append((int(xs[0]), y))
            points.append((int(xs[-1]), y))

    y_limit = min(height, max_y or height)
    x_limit = min(width, max_x or width)
    for x in range(40, x_limit - 40, 4):
        ys = np.flatnonzero(mask[:y_limit, x])
        if ys.size >= 30:
            points.append((x, int(ys[0])))
            points.append((x, int(ys[-1])))

    if len(points) < 20:
        raise ValueError("Not enough sky-edge points found. Try lowering --threshold.")

    edge_points = np.array(points, dtype=float)
    cx, cy, radius = fit_circle_kasa(edge_points)
    calibration = base_calibration or Calibration()
    calibration.cx = cx
    calibration.cy = cy
    calibration.horizon_radius_px = radius
    calibration.reference_width_px = float(width)
    calibration.reference_height_px = float(height)
    calibration.notes = (
        f"Estimated from {image_path.name} with threshold={threshold}, "
        f"max_x={max_x}, max_y={max_y}. Refine rotation_deg with stars."
    )
    return calibration, edge_points


def save_circle_diagnostic(
    image_path: Path,
    output_path: Path,
    calibration: Calibration,
    points: np.ndarray,
) -> None:
    image = Image.open(image_path).convert("RGB")
    overlay = np.array(image)
    height, width, _ = overlay.shape

    for x, y in points.astype(int):
        if 0 <= x < width and 0 <= y < height:
            overlay[y, x] = [255, 64, 64]

    angles = np.linspace(0, 2 * np.pi, 1440)
    xs = np.rint(calibration.cx + calibration.horizon_radius_px * np.cos(angles)).astype(int)
    ys = np.rint(calibration.cy + calibration.horizon_radius_px * np.sin(angles)).astype(int)
    valid = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
    overlay[ys[valid], xs[valid]] = [0, 255, 80]

    cx = int(round(calibration.cx))
    cy = int(round(calibration.cy))
    for dy in range(-8, 9):
        yy = cy + dy
        if 0 <= yy < height and 0 <= cx < width:
            overlay[yy, cx] = [255, 255, 0]
    for dx in range(-8, 9):
        xx = cx + dx
        if 0 <= cy < height and 0 <= xx < width:
            overlay[cy, xx] = [255, 255, 0]

    Image.fromarray(overlay).save(output_path)


def read_star_marks(path: Path) -> list[dict[str, Any]]:
    marks: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            try:
                name = row["name"].strip()
                x = float(row["x"])
                y = float(row["y"])
            except (KeyError, TypeError, ValueError):
                continue
            marks.append({"name": name, "x": x, "y": y})
    return marks


def read_star_marks_multi(path: Path) -> list[dict[str, Any]]:
    """Read a star-marks CSV that may additionally include image/date_obs/
    image_width/image_height columns (as produced by star_marker_multi.py or
    attach_resolution.py). Rows missing those columns simply get empty
    strings/None back, so old-format CSVs still parse fine."""
    marks: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            try:
                name = row["name"].strip()
                x = float(row["x"])
                y = float(row["y"])
            except (KeyError, TypeError, ValueError):
                continue
            image = (row.get("image") or "").strip()
            date_obs = (row.get("date_obs") or "").strip()

            image_width = None
            image_height = None
            try:
                width_str = (row.get("image_width") or "").strip()
                height_str = (row.get("image_height") or "").strip()
                if width_str and height_str:
                    image_width = float(width_str)
                    image_height = float(height_str)
            except (TypeError, ValueError):
                image_width = None
                image_height = None

            marks.append(
                {
                    "name": name,
                    "x": x,
                    "y": y,
                    "image": image,
                    "date_obs": date_obs,
                    "image_width": image_width,
                    "image_height": image_height,
                }
            )
    return marks


def circular_mean_deg(values: list[float]) -> float:
    radians = np.radians(values)
    mean_angle = np.degrees(np.arctan2(np.mean(np.sin(radians)), np.mean(np.cos(radians))))
    return float(mean_angle % 360.0)


def angular_difference_deg(a: float, b: float) -> float:
    return float((a - b + 180.0) % 360.0 - 180.0)


def pixel_to_altaz(
    x: float | np.ndarray,
    y: float | np.ndarray,
    calibration: Calibration,
) -> tuple[Any, Any]:
    if calibration.projection != "equidistant":
        raise ValueError(f"Unsupported projection: {calibration.projection}")

    dx = np.asarray(x) - calibration.cx
    dy = np.asarray(y) - calibration.cy
    r = np.sqrt((dx * dx) + (dy * dy))

    theta_deg = (r / calibration.horizon_radius_px) * 90.0
    alt_deg = 90.0 - theta_deg

    dx_eff = -dx if getattr(calibration, "east_left", True) else dx
    phi_deg = np.degrees(np.arctan2(dx_eff, -dy))
    az_deg = (phi_deg + calibration.rotation_deg) % 360.0

    return alt_deg, az_deg


def altaz_to_pixel(
    alt_deg: float | np.ndarray,
    az_deg: float | np.ndarray,
    calibration: Calibration,
) -> tuple[Any, Any]:
    if calibration.projection != "equidistant":
        raise ValueError(f"Unsupported projection: {calibration.projection}")

    theta_deg = 90.0 - np.asarray(alt_deg)
    radius = (theta_deg / 90.0) * calibration.horizon_radius_px
    phi_deg = (np.asarray(az_deg) - calibration.rotation_deg) % 360.0
    phi_rad = np.radians(phi_deg)
    x_sign = -1.0 if getattr(calibration, "east_left", True) else 1.0
    x = calibration.cx + x_sign * radius * np.sin(phi_rad)
    y = calibration.cy - radius * np.cos(phi_rad)
    return x, y


def altaz_to_radec(
    alt_deg: float | np.ndarray,
    az_deg: float | np.ndarray,
    date_obs: str,
    calibration: Calibration,
) -> tuple[Any, Any]:
    location = EarthLocation(
        lat=calibration.latitude_deg * u.deg,
        lon=calibration.longitude_deg * u.deg,
        height=calibration.height_m * u.m,
    )
    frame = AltAz(
        alt=np.asarray(alt_deg) * u.deg,
        az=np.asarray(az_deg) * u.deg,
        obstime=Time(date_obs),
        location=location,
    )
    sky = SkyCoord(frame).icrs
    return sky.ra.deg, sky.dec.deg


def radec_to_altaz(
    ra_deg: float | np.ndarray,
    dec_deg: float | np.ndarray,
    date_obs: str,
    calibration: Calibration,
) -> tuple[Any, Any]:
    location = EarthLocation(
        lat=calibration.latitude_deg * u.deg,
        lon=calibration.longitude_deg * u.deg,
        height=calibration.height_m * u.m,
    )
    sky = SkyCoord(ra=np.asarray(ra_deg) * u.deg, dec=np.asarray(dec_deg) * u.deg)
    altaz = sky.transform_to(
        AltAz(
            obstime=Time(date_obs),
            location=location,
        )
    )
    return altaz.alt.deg, altaz.az.deg


def add_header_metadata(
    header: fits.Header,
    calibration: Calibration,
    date_obs: str,
    exptime: float | None,
    source_png: Path,
) -> None:
    header["ORIGIN"] = "Custom all-sky fisheye converter"
    header["DATE-OBS"] = date_obs
    header["INSTRUME"] = calibration.instrument
    header["OBSERVER"] = calibration.observer
    header["SITENAME"] = calibration.site
    header["OBJECT"] = "ALLSKY"
    header["SRCFILE"] = source_png.name

    if exptime is not None:
        header["EXPTIME"] = float(exptime)

    header["LATITUDE"] = (float(calibration.latitude_deg), "Observer latitude, degrees")
    header["LONGITUD"] = (float(calibration.longitude_deg), "Observer longitude, degrees")
    header["ELEVATIO"] = (float(calibration.height_m), "Observer elevation, meters")
    header["FISHPROJ"] = (calibration.projection, "Fisheye projection model")
    header["FISHCX"] = (float(calibration.cx), "Fisheye zenith center X, pixels")
    header["FISHCY"] = (float(calibration.cy), "Fisheye zenith center Y, pixels")
    header["FISHRAD"] = (float(calibration.horizon_radius_px), "Horizon radius, pixels")
    header["FISHROT"] = (float(calibration.rotation_deg), "Image-to-azimuth rotation, degrees")
    header["COMMENT"] = "Fisheye model: equidistant theta = r / FISHRAD * 90 deg"


def convert_png_to_fits(
    png_path: Path,
    fits_path: Path,
    calibration: Calibration,
    date_obs: str | None,
    exptime: float | None,
    keep_rgb: bool,
) -> None:
    normalized_date_obs = normalize_date_obs(date_obs)
    data = read_png_as_array(png_path, keep_rgb=keep_rgb)

    hdu = fits.PrimaryHDU(data=data)
    add_header_metadata(hdu.header, calibration, normalized_date_obs, exptime, png_path)
    hdu.writeto(fits_path, overwrite=True)


def command_sample_calibration(args: argparse.Namespace) -> None:
    output = Path(args.output)
    write_calibration(output, Calibration())
    print(f"Wrote sample calibration: {output}")


def command_lulin_calibration(args: argparse.Namespace) -> None:
    output = Path(args.output)
    write_calibration(output, lulin_default_calibration())
    print(f"Wrote Lulin calibration: {output}")


def command_init_calibration(args: argparse.Namespace) -> None:
    output = Path(args.output)
    cal = Calibration(
        instrument=args.instrument or "All-sky fisheye camera",
        observer=args.observer or "Unknown",
        site=args.site or "Unknown",
        latitude_deg=float(args.lat),
        longitude_deg=float(args.lon),
        height_m=float(args.height),
        notes=f"Initialized for {args.site} ({args.instrument}).",
    )
    write_calibration(output, cal)
    print(f"Wrote initial calibration for {args.site}: {output}")


def command_estimate_circle(args: argparse.Namespace) -> None:
    image_path = Path(args.input)
    base_cal = load_calibration(Path(args.base_calibration)) if getattr(args, "base_calibration", None) else None
    calibration, points = estimate_sky_circle(
        image_path,
        threshold=args.threshold,
        max_x=args.max_x,
        max_y=args.max_y,
        base_calibration=base_cal,
        mask_timestamp_corner=getattr(args, "mask_timestamp", False),
    )
    write_calibration(Path(args.output), calibration)
    if args.diagnostic:
        save_circle_diagnostic(image_path, Path(args.diagnostic), calibration, points)
    result = {
        "cx": calibration.cx,
        "cy": calibration.cy,
        "horizon_radius_px": calibration.horizon_radius_px,
        "edge_points": int(len(points)),
        "calibration": args.output,
        "diagnostic": args.diagnostic,
    }
    print(json.dumps(result, indent=2))


def command_manual_circle(args: argparse.Namespace) -> None:
    calibration = load_calibration(Path(args.base_calibration)) if args.base_calibration else Calibration()
    calibration.cx = args.cx
    calibration.cy = args.cy
    calibration.horizon_radius_px = args.radius
    calibration.notes = "Manual sky-circle calibration. Refine rotation_deg with identified stars."
    write_calibration(Path(args.output), calibration)
    if args.diagnostic:
        empty_points = np.empty((0, 2), dtype=float)
        save_circle_diagnostic(Path(args.input), Path(args.diagnostic), calibration, empty_points)
    print(
        json.dumps(
            {
                "cx": calibration.cx,
                "cy": calibration.cy,
                "horizon_radius_px": calibration.horizon_radius_px,
                "calibration": args.output,
                "diagnostic": args.diagnostic,
            },
            indent=2,
        )
    )


def command_convert(args: argparse.Namespace) -> None:
    calibration = load_calibration(Path(args.calibration))
    date_obs = args.date_obs
    if date_obs is None and args.date_from_filename:
        date_obs = parse_filename_time(Path(args.input))
    convert_png_to_fits(
        png_path=Path(args.input),
        fits_path=Path(args.output),
        calibration=calibration,
        date_obs=date_obs,
        exptime=args.exptime,
        keep_rgb=args.keep_rgb,
    )
    print(f"Wrote FITS: {args.output}")


def command_pixel_to_sky(args: argparse.Namespace) -> None:
    calibration = load_calibration(Path(args.calibration))
    date_obs = normalize_date_obs(args.date_obs)
    alt_deg, az_deg = pixel_to_altaz(args.x, args.y, calibration)
    ra_deg, dec_deg = altaz_to_radec(alt_deg, az_deg, date_obs, calibration)
    result = {
        "x": args.x,
        "y": args.y,
        "date_obs": date_obs,
        "alt_deg": float(alt_deg),
        "az_deg": float(az_deg),
        "ra_deg": float(ra_deg),
        "dec_deg": float(dec_deg),
    }
    print(json.dumps(result, indent=2))


def command_sky_to_pixel(args: argparse.Namespace) -> None:
    calibration = load_calibration(Path(args.calibration))
    date_obs = normalize_date_obs(args.date_obs)
    alt_deg, az_deg = radec_to_altaz(args.ra, args.dec, date_obs, calibration)
    x, y = altaz_to_pixel(alt_deg, az_deg, calibration)
    result = {
        "ra_deg": args.ra,
        "dec_deg": args.dec,
        "date_obs": date_obs,
        "alt_deg": float(alt_deg),
        "az_deg": float(az_deg),
        "x": float(x),
        "y": float(y),
    }
    print(json.dumps(result, indent=2))


def command_calibrate_rotation(args: argparse.Namespace) -> None:
    calibration = load_calibration(Path(args.calibration))
    marks = read_star_marks(Path(args.marks))
    date_obs = normalize_date_obs(args.date_obs)
    utc_offset_hours = float(getattr(args, "utc_offset", 0.0) or 0.0)
    if utc_offset_hours != 0.0:
        date_obs = (Time(date_obs) + utc_offset_hours * u.hour).isot + "Z"

    matches: list[dict[str, Any]] = []
    skipped: list[str] = []

    for mark in marks:
        catalog = BRIGHT_STARS.get(normalize_star_name(mark["name"]))
        if catalog is None:
            skipped.append(mark["name"])
            continue

        ra_deg, dec_deg = catalog
        alt_deg, az_deg = radec_to_altaz(ra_deg, dec_deg, date_obs, calibration)
        dx = mark["x"] - calibration.cx
        dx_eff = -dx if getattr(calibration, "east_left", True) else dx
        observed_phi = float(np.degrees(np.arctan2(dx_eff, -(mark["y"] - calibration.cy))) % 360.0)
        rotation_deg = (float(az_deg) - observed_phi) % 360.0
        matches.append(
            {
                "name": mark["name"],
                "x_obs": mark["x"],
                "y_obs": mark["y"],
                "ra_deg": ra_deg,
                "dec_deg": dec_deg,
                "alt_deg": float(alt_deg),
                "az_deg": float(az_deg),
                "observed_phi_deg": observed_phi,
                "rotation_deg": rotation_deg,
            }
        )

    if len(matches) < 2:
        raise ValueError(
            "Need at least two recognized stars. Use English names such as Betelgeuse, Rigel, Bellatrix, Saiph."
        )

    fitted_rotation = circular_mean_deg([match["rotation_deg"] for match in matches])
    calibration.rotation_deg = fitted_rotation
    calibration.notes = (
        f"rotation_deg calibrated from {len(matches)} recognized marks in {Path(args.marks).name}; "
        "cx/cy/radius remain manual initial values."
    )
    write_calibration(Path(args.output), calibration)

    residuals = []
    for match in matches:
        x_pred, y_pred = altaz_to_pixel(match["alt_deg"], match["az_deg"], calibration)
        error_px = float(np.hypot(float(x_pred) - match["x_obs"], float(y_pred) - match["y_obs"]))
        match["x_pred"] = float(x_pred)
        match["y_pred"] = float(y_pred)
        match["error_px"] = error_px
        match["rotation_residual_deg"] = angular_difference_deg(match["rotation_deg"], fitted_rotation)
        residuals.append(error_px)

    if args.report:
        with Path(args.report).open("w", encoding="utf-8-sig", newline="") as file:
            fieldnames = [
                "name",
                "x_obs",
                "y_obs",
                "x_pred",
                "y_pred",
                "error_px",
                "ra_deg",
                "dec_deg",
                "alt_deg",
                "az_deg",
                "rotation_deg",
                "rotation_residual_deg",
            ]
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            for match in matches:
                writer.writerow({key: match[key] for key in fieldnames})

    if args.diagnostic:
        save_rotation_diagnostic(Path(args.image), Path(args.diagnostic), matches)

    result = {
        "rotation_deg": fitted_rotation,
        "recognized_stars": [match["name"] for match in matches],
        "skipped_names": skipped,
        "mean_error_px": float(np.mean(residuals)),
        "max_error_px": float(np.max(residuals)),
        "calibration": args.output,
        "report": args.report,
        "diagnostic": args.diagnostic,
    }
    print(json.dumps(result, indent=2))


def command_calibrate_full(args: argparse.Namespace) -> None:
    """Jointly fit cx, cy, horizon_radius_px and rotation_deg from star marks that can
    span *multiple* photos (different date_obs), since the lens/camera geometry
    (cx/cy/radius) is assumed fixed while only the sky position (alt/az) changes
    between images. This needs the star_marker_multi.py CSV format:
        image, date_obs, name, x, y
    """
    try:
        from scipy.optimize import least_squares
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit(
            "This command needs scipy. Install it with: pip install scipy"
        ) from exc

    calibration = load_calibration(Path(args.calibration))
    marks = read_star_marks_multi(Path(args.marks))
    fallback_date_obs = normalize_date_obs(args.date_obs) if args.date_obs else None

    matches: list[dict[str, Any]] = []
    skipped: list[str] = []
    marks_missing_resolution = 0

    reference_w = calibration.reference_width_px
    reference_h = calibration.reference_height_px
    has_reference_resolution = reference_w > 0 and reference_h > 0

    utc_offset_hours = float(getattr(args, "utc_offset", 0.0) or 0.0)

    for mark in marks:
        catalog = BRIGHT_STARS.get(normalize_star_name(mark["name"]))
        if catalog is None:
            skipped.append(mark["name"])
            continue

        date_obs = mark["date_obs"] or fallback_date_obs
        if not date_obs:
            skipped.append(f"{mark['name']} (missing date_obs, no --date-obs fallback given)")
            continue

        if utc_offset_hours != 0.0:
            try:
                date_obs = (Time(date_obs) + utc_offset_hours * u.hour).isot + "Z"
            except Exception:
                pass

        try:
            Time(date_obs)  # 先驗證這個時間字串格式合不合法，不合法就跳過這一筆，不要讓整批計算中斷
        except Exception:  # noqa: BLE001
            skipped.append(
                f"{mark['name']} (invalid date_obs: {date_obs!r}, image={mark['image']!r} — 請檢查這張照片的拍攝時間有沒有打錯字)"
            )
            continue

        x_obs = mark["x"]
        y_obs = mark["y"]

        # 如果這筆標記知道自己是從多大解析度的照片點的，就換算成校正檔裡
        # 「基準解析度」下的等效座標，這樣不同解析度 (例如相機切換過像素合併
        # 模式) 拍的照片才能安全地混在一起做聯合校正。
        if has_reference_resolution and mark["image_width"] and mark["image_height"]:
            scale_x = reference_w / mark["image_width"]
            scale_y = reference_h / mark["image_height"]
            x_obs = x_obs * scale_x
            y_obs = y_obs * scale_y
        elif has_reference_resolution:
            marks_missing_resolution += 1

        ra_deg, dec_deg = catalog
        matches.append(
            {
                "image": mark["image"] or "(unspecified)",
                "name": mark["name"],
                "x_obs": x_obs,
                "y_obs": y_obs,
                "ra_deg": ra_deg,
                "dec_deg": dec_deg,
                "date_obs": date_obs,
            }
        )

    if len(matches) < 4:
        raise ValueError(
            "Need at least 4 recognized, dated star marks (ideally spread across "
            "multiple images and sky positions) for full calibration."
        )

    fit_clock_offset = bool(getattr(args, "fit_clock_offset", False))
    max_offset_hours = float(getattr(args, "max_clock_offset_hours", 12.0))

    image_offsets: dict[str, float] = {}

    ref_w = calibration.reference_width_px if calibration.reference_width_px > 0 else 1548.0
    ref_h = calibration.reference_height_px if calibration.reference_height_px > 0 else 1040.0
    
    # 物理邊界限制，防止演算法把半徑壓扁或把圓心移出感光元件
    min_cx = float(getattr(args, "min_cx", None) or (ref_w * 0.40))
    max_cx = float(getattr(args, "max_cx", None) or (ref_w * 0.60))
    min_cy = float(getattr(args, "min_cy", None) or (ref_h * 0.40))
    max_cy = float(getattr(args, "max_cy", None) or (ref_h * 0.60))
    min_radius = float(getattr(args, "min_radius", None) or (ref_h * 0.44))
    max_radius = float(getattr(args, "max_radius", None) or (ref_h * 0.54))

    lower_geom = [min_cx, min_cy, min_radius, -360.0]
    upper_geom = [max_cx, max_cy, max_radius, 720.0]

    x0_geom = [
        float(np.clip(calibration.cx, min_cx + 1, max_cx - 1)),
        float(np.clip(calibration.cy, min_cy + 1, max_cy - 1)),
        float(np.clip(calibration.horizon_radius_px, min_radius + 1, max_radius - 1)),
        float(calibration.rotation_deg),
    ]

    if not fit_clock_offset:
        def residuals(params: np.ndarray) -> list[float]:
            cx, cy, radius, rotation = params
            trial = Calibration(**{**asdict(calibration)})
            trial.cx = float(cx)
            trial.cy = float(cy)
            trial.horizon_radius_px = float(radius)
            trial.rotation_deg = float(rotation)

            residual_values: list[float] = []
            for match in matches:
                alt_deg, az_deg = radec_to_altaz(match["ra_deg"], match["dec_deg"], match["date_obs"], trial)
                x_pred, y_pred = altaz_to_pixel(alt_deg, az_deg, trial)
                residual_values.append(float(x_pred) - match["x_obs"])
                residual_values.append(float(y_pred) - match["y_obs"])
            return residual_values

        fit_result = least_squares(residuals, np.array(x0_geom, dtype=float), bounds=(lower_geom, upper_geom))
        cx, cy, radius, rotation = fit_result.x
    else:
        # 相機時鐘不可靠時的做法：把「時鐘誤差(小時)」也當成未知數一起解。
        location = EarthLocation(
            lat=calibration.latitude_deg * u.deg,
            lon=calibration.longitude_deg * u.deg,
            height=calibration.height_m * u.m,
        )

        def day_key(date_obs: str) -> str:
            return date_obs[:10] if date_obs else "(unknown)"

        day_list = sorted({day_key(m["date_obs"]) for m in matches})
        day_to_index = {day: i for i, day in enumerate(day_list)}
        n_days = len(day_list)

        ra_arr = np.array([m["ra_deg"] for m in matches])
        dec_arr = np.array([m["dec_deg"] for m in matches])
        x_obs_arr = np.array([m["x_obs"] for m in matches])
        y_obs_arr = np.array([m["y_obs"] for m in matches])
        base_time_arr = Time([m["date_obs"] for m in matches])
        day_idx_arr = np.array([day_to_index[day_key(m["date_obs"])] for m in matches])
        sky_all = SkyCoord(ra=ra_arr * u.deg, dec=dec_arr * u.deg)

        def residuals_with_offset(params: np.ndarray) -> np.ndarray:
            cx, cy, radius, rotation = params[:4]
            offsets = params[4:]
            trial = Calibration(**{**asdict(calibration)})
            trial.cx, trial.cy, trial.horizon_radius_px, trial.rotation_deg = cx, cy, radius, rotation

            t_all = base_time_arr + offsets[day_idx_arr] * u.hour
            altaz = sky_all.transform_to(AltAz(obstime=t_all, location=location))
            x_pred, y_pred = altaz_to_pixel(altaz.alt.deg, altaz.az.deg, trial)
            res = np.empty(2 * len(matches))
            res[0::2] = np.asarray(x_pred) - x_obs_arr
            res[1::2] = np.asarray(y_pred) - y_obs_arr
            return res

        x0 = np.concatenate([x0_geom, np.zeros(n_days)])
        lower = np.concatenate([lower_geom, [-max_offset_hours] * n_days])
        upper = np.concatenate([upper_geom, [max_offset_hours] * n_days])
        fit_result = least_squares(residuals_with_offset, x0, bounds=(lower, upper))
        cx, cy, radius, rotation = fit_result.x[:4]
        day_offsets = dict(zip(day_list, fit_result.x[4:].tolist()))
        image_offsets = {
            match["image"]: day_offsets[day_key(match["date_obs"])] for match in matches
        }

    rotation = float(rotation % 360.0)

    calibration.cx = float(cx)
    calibration.cy = float(cy)
    calibration.horizon_radius_px = float(radius)
    calibration.rotation_deg = rotation
    calibration.notes = (
        f"cx/cy/horizon_radius_px/rotation_deg jointly fit from {len(matches)} marks "
        f"across {len({match['image'] for match in matches})} image(s) in {Path(args.marks).name}."
        + (" Per-image clock offsets were also fit (camera clock treated as unreliable)." if fit_clock_offset else "")
    )
    write_calibration(Path(args.output), calibration)

    report_rows: list[dict[str, Any]] = []
    errors: list[float] = []
    for match in matches:
        date_obs_for_residual = match["date_obs"]
        offset_hours = image_offsets.get(match["image"], 0.0)
        if fit_clock_offset and offset_hours:
            date_obs_for_residual = (Time(match["date_obs"]) + offset_hours * u.hour).isot + "Z"

        alt_deg, az_deg = radec_to_altaz(match["ra_deg"], match["dec_deg"], date_obs_for_residual, calibration)
        x_pred, y_pred = altaz_to_pixel(alt_deg, az_deg, calibration)
        error_px = float(np.hypot(float(x_pred) - match["x_obs"], float(y_pred) - match["y_obs"]))
        errors.append(error_px)
        report_rows.append(
            {
                "image": match["image"],
                "name": match["name"],
                "date_obs": match["date_obs"],
                "clock_offset_hours": round(offset_hours, 3) if fit_clock_offset else "",
                "x_obs": match["x_obs"],
                "y_obs": match["y_obs"],
                "x_pred": float(x_pred),
                "y_pred": float(y_pred),
                "error_px": error_px,
                "ra_deg": match["ra_deg"],
                "dec_deg": match["dec_deg"],
            }
        )

    if args.report:
        fieldnames = [
            "image",
            "name",
            "date_obs",
            "clock_offset_hours",
            "x_obs",
            "y_obs",
            "x_pred",
            "y_pred",
            "error_px",
            "ra_deg",
            "dec_deg",
        ]
        with Path(args.report).open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            for row in report_rows:
                writer.writerow(row)

    result = {
        "cx": calibration.cx,
        "cy": calibration.cy,
        "horizon_radius_px": calibration.horizon_radius_px,
        "rotation_deg": calibration.rotation_deg,
        "reference_width_px": calibration.reference_width_px,
        "reference_height_px": calibration.reference_height_px,
        "recognized_marks": len(matches),
        "marks_missing_resolution_info": marks_missing_resolution,
        "fit_clock_offset": fit_clock_offset,
        "images_used": sorted({match["image"] for match in matches}),
        "skipped_names": skipped,
        "mean_error_px": float(np.mean(errors)),
        "max_error_px": float(np.max(errors)),
        "calibration": args.output,
        "report": args.report,
    }
    if fit_clock_offset:
        # image_offsets 目前每張照片都有值，但同一天的照片會是同一個數字；
        # 這裡整理成「每個觀測日」對應一個校正量，比列出上百張照片更好讀。
        day_offset_map: dict[str, float] = {}
        for match in matches:
            day = match["date_obs"][:10] if match["date_obs"] else "(unknown)"
            day_offset_map[day] = image_offsets[match["image"]]

        offset_values = list(day_offset_map.values())
        result["clock_offset_hours_stats"] = {
            "min": min(offset_values),
            "max": max(offset_values),
            "mean": float(np.mean(offset_values)),
        }
        result["clock_offset_hours_by_day"] = {
            day: round(off, 2) for day, off in sorted(day_offset_map.items())
        }
    print(json.dumps(result, indent=2, ensure_ascii=False))


def save_rotation_diagnostic(image_path: Path, output_path: Path, matches: list[dict[str, Any]]) -> None:
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()

    for match in matches:
        x_obs = match["x_obs"]
        y_obs = match["y_obs"]
        x_pred = match["x_pred"]
        y_pred = match["y_pred"]
        name = match["name"]

        draw.line((x_obs - 8, y_obs, x_obs + 8, y_obs), fill=(255, 255, 0), width=2)
        draw.line((x_obs, y_obs - 8, x_obs, y_obs + 8), fill=(255, 255, 0), width=2)
        draw.ellipse((x_pred - 7, y_pred - 7, x_pred + 7, y_pred + 7), outline=(0, 255, 255), width=2)
        draw.line((x_obs, y_obs, x_pred, y_pred), fill=(255, 80, 80), width=1)
        draw.text((x_obs + 10, y_obs - 18), name, fill=(255, 255, 0), font=font)

    draw.text((12, 32), "yellow cross = your click; cyan circle = model prediction", fill=(255, 255, 255), font=font)
    image.save(output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert all-sky fisheye PNG images to FITS and test fisheye sky mapping."
    )
    subparsers = parser.add_subparsers(required=True)

    sample = subparsers.add_parser("sample-calibration")
    sample.add_argument("output")
    sample.set_defaults(func=command_sample_calibration)

    init_cal = subparsers.add_parser("init-calibration", help="建立新站點/新相機的初始設定檔")
    init_cal.add_argument("output", help="輸出的 JSON 設定檔路徑")
    init_cal.add_argument("--site", required=True, help="觀測站名稱 (例如 'Alishan')")
    init_cal.add_argument("--lat", type=float, required=True, help="觀測站緯度 (度)")
    init_cal.add_argument("--lon", type=float, required=True, help="觀測站經度 (度)")
    init_cal.add_argument("--height", type=float, default=100.0, help="海拔高度 (公尺，預設 100)")
    init_cal.add_argument("--instrument", default="All-sky fisheye camera", help="相機與鏡頭型號描述")
    init_cal.add_argument("--observer", default="Unknown", help="觀測者或組織名稱")
    init_cal.set_defaults(func=command_init_calibration)

    lulin = subparsers.add_parser("lulin-calibration")
    lulin.add_argument("output")
    lulin.set_defaults(func=command_lulin_calibration)

    estimate = subparsers.add_parser("estimate-circle")
    estimate.add_argument("input")
    estimate.add_argument("output")
    estimate.add_argument("--base-calibration", help="新站點的設定檔 JSON；若有提供，將更新其圓心半徑並保留經緯度站名")
    estimate.add_argument("--diagnostic")
    estimate.add_argument("--threshold", type=int, default=24)
    estimate.add_argument("--max-x", type=int, default=None, help="遮蔽 X 軸右側像素 (如浮水印)")
    estimate.add_argument("--max-y", type=int, default=None, help="遮蔽 Y 軸下方像素 (如浮水印)")
    estimate.add_argument("--mask-timestamp", action="store_true", help="遮蔽左上角時間戳 (鹿林相機適用)")
    estimate.set_defaults(func=command_estimate_circle)

    manual = subparsers.add_parser("manual-circle")
    manual.add_argument("input")
    manual.add_argument("output")
    manual.add_argument("--cx", type=float, required=True)
    manual.add_argument("--cy", type=float, required=True)
    manual.add_argument("--radius", type=float, required=True)
    manual.add_argument("--base-calibration")
    manual.add_argument("--diagnostic")
    manual.set_defaults(func=command_manual_circle)

    convert = subparsers.add_parser("convert")
    convert.add_argument("input")
    convert.add_argument("output")
    convert.add_argument("--calibration", required=True)
    convert.add_argument("--date-obs")
    convert.add_argument("--date-from-filename", action="store_true")
    convert.add_argument("--exptime", type=float)
    convert.add_argument("--keep-rgb", action="store_true")
    convert.set_defaults(func=command_convert)

    pixel = subparsers.add_parser("pixel-to-sky")
    pixel.add_argument("x", type=float)
    pixel.add_argument("y", type=float)
    pixel.add_argument("--calibration", required=True)
    pixel.add_argument("--date-obs")
    pixel.set_defaults(func=command_pixel_to_sky)

    sky = subparsers.add_parser("sky-to-pixel")
    sky.add_argument("ra", type=float)
    sky.add_argument("dec", type=float)
    sky.add_argument("--calibration", required=True)
    sky.add_argument("--date-obs", required=True)
    sky.set_defaults(func=command_sky_to_pixel)

    rotate = subparsers.add_parser("calibrate-rotation")
    rotate.add_argument("marks")
    rotate.add_argument("output")
    rotate.add_argument("--calibration", required=True)
    rotate.add_argument("--date-obs", required=True)
    rotate.add_argument("--image", required=True)
    rotate.add_argument("--diagnostic")
    rotate.add_argument("--report")
    rotate.add_argument("--utc-offset", type=float, default=0.0, help="拍攝時間時區偏移 (小時)")
    rotate.set_defaults(func=command_calibrate_rotation)

    full = subparsers.add_parser(
        "calibrate-full",
        help="Jointly fit cx/cy/horizon_radius_px/rotation_deg from marks spanning multiple images.",
    )
    full.add_argument("marks", help="CSV with columns: image, date_obs, name, x, y (from star_marker_multi.py)")
    full.add_argument("output")
    full.add_argument("--calibration", required=True, help="Initial calibration JSON to start the fit from")
    full.add_argument(
        "--date-obs",
        help="Fallback date-obs (ISO) used only for marks whose row has no date_obs value",
    )
    full.add_argument("--report")
    full.add_argument(
        "--utc-offset",
        type=float,
        default=0.0,
        help="拍攝時間時區偏移 (小時)。若原標記為台灣時間 (UTC+8)，請給 -8.0 轉為真實 UTC",
    )
    full.add_argument("--min-radius", type=float, default=None, help="地平線半徑的物理下限 (像素，防止數值崩潰)")
    full.add_argument("--max-radius", type=float, default=None, help="地平線半徑的物理上限 (像素)")
    full.add_argument("--min-cx", type=float, default=None, help="圓心 X 物理下限 (像素)")
    full.add_argument("--max-cx", type=float, default=None, help="圓心 X 物理上限 (像素)")
    full.add_argument("--min-cy", type=float, default=None, help="圓心 Y 物理下限 (像素)")
    full.add_argument("--max-cy", type=float, default=None, help="圓心 Y 物理上限 (像素)")
    full.add_argument(
        "--fit-clock-offset",
        action="store_true",
        help=(
            "相機時鐘不可信任時使用：額外幫『每一張照片』各自解一個時間校正量(小時)，"
            "跟 cx/cy/horizon_radius_px/rotation_deg 一起聯合擬合。"
        ),
    )
    full.add_argument(
        "--max-clock-offset-hours",
        type=float,
        default=20.0,
        help="--fit-clock-offset 時，每張照片時間校正量的上下限 (小時)，預設 ±20",
    )
    full.set_defaults(func=command_calibrate_full)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
