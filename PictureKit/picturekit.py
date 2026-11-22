#!/usr/bin/env python3
"""PictureKit local 16-bit RAW developer. Binds to localhost only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
import errno
import gc
import hashlib
import io
import json
import os
import time
import re
import shutil
import signal
import struct
import subprocess
import tempfile
import threading
import uuid
import warnings
import webbrowser

import numpy as np
import rawpy
import tifffile
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageCms

try:
    import lensfunpy  # オープンなレンズ補正DB（Adobe LCPからの脱却先）
except ImportError:
    lensfunpy = None

ROOT = Path(__file__).resolve().parent
SESSION = tempfile.TemporaryDirectory(prefix="picturekit-")
WORK = Path(SESSION.name)
CAMERAS = json.loads((ROOT / "cameras.json").read_text(encoding="utf-8"))
LENS_PROFILE_DIRS = [
    Path("/Library/Application Support/Adobe/CameraRaw/LensProfiles"),
    Path.home() / "Library/Application Support/Adobe/CameraRaw/LensProfiles",
]
LENS_MAKERS = ("PENTAX", "RICOH", "SIGMA")
_LENS_PROFILES = None
_LCP_CACHE = {}
_LENSFUN_DB = None
_LENSFUN_CACHE = {}
LENSFUN_PREFIX = "lf:"
CAMERA_PROFILE_DIR = Path(
    "/Library/Application Support/Adobe/CameraRaw/CameraProfiles")
_DCP_CACHE = {}
# ACR3標準トーンカーブ（DNG SDK dng_render.cpp由来・1025点）。
# LR/ACRはカーブを持たないプロファイル（Adobe Standard等）にこれを適用する
try:
    _ACR_TABLE = np.asarray(json.loads(
        (ROOT / "acr-tone-curve.json").read_text(encoding="utf-8"))["curve"],
        dtype=np.float32)
    ACR_DEFAULT_CURVE = (np.linspace(0, 1, len(_ACR_TABLE), dtype=np.float32),
                         _ACR_TABLE)
except (OSError, ValueError, KeyError):
    ACR_DEFAULT_CURVE = None
# 同梱の標準プロファイル＝ACR標準カーブだけ（色テーブル無し）。Adobe Camera Rawの
# DCPが無いMacでも、RAWの既定が「暗くフラット」にならないための受け皿。
# 空のプロファイル（""）は従来どおりカーブ無しのlinear表示として残す
KIT_STANDARD = "PictureKit Standard"
KIT_STANDARD_PROFILE = ({"curve": ACR_DEFAULT_CURVE}
                        if ACR_DEFAULT_CURVE is not None else None)
DCP_LUT_SIZE = 65  # DCP（HSVテーブル＋カーブ）を焼き込む3D LUTの一辺

# linear sRGB(D65) ↔ linear ProPhoto(D50)。DCPのHSVテーブルはProPhoto前提
_SRGB_TO_XYZ = np.array([[.4124564, .3575761, .1804375],
                         [.2126729, .7151522, .0721750],
                         [.0193339, .1191920, .9503041]], dtype=np.float64)
_PROPHOTO_TO_XYZ = np.array([[.7976749, .1351917, .0313534],
                             [.2880402, .7118741, .0000857],
                             [.0, .0, .8252100]], dtype=np.float64)
_BRADFORD_D65_D50 = np.array([[1.0478112, .0228866, -.0501270],
                              [.0295424, .9904844, -.0170491],
                              [-.0092345, .0150436, .7521316]], dtype=np.float64)
SRGB_TO_PROPHOTO = (np.linalg.inv(_PROPHOTO_TO_XYZ)
                    @ _BRADFORD_D65_D50 @ _SRGB_TO_XYZ).astype(np.float32)
PROPHOTO_TO_SRGB = np.linalg.inv(SRGB_TO_PROPHOTO.astype(np.float64)).astype(np.float32)
FILES = {}
RECIPES_PATH = ROOT / "recipes.json"  # 旧一括保存（imagesフォルダへ自動移行して廃止）
_RECIPES_LOCK = threading.Lock()
MAX_BYTES = 200 * 1024 * 1024
ALLOWED = {".pef", ".dng", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}
RAW_EXTENSIONS = {".pef", ".dng"}
TONE_KNEE = 0.75  # linearでここまで恒等。超過分だけ白点(2-TONE_KNEE)へ畳むshoulder
# ホワイトバランスの係数（wbModel 2）。旧係数は temp .25 / tint R,B .08 G .12
WB_MODEL = 2
WB_TEMP_COEF = 1.0
WB_TINT_RB_COEF = .2
WB_TINT_G_COEF = .3
WB_TEMP_SCALE_FROM_V1 = .25 / WB_TEMP_COEF   # 旧値→新値の換算
WB_TINT_SCALE_FROM_V1 = .08 / WB_TINT_RB_COEF
SRGB_PROFILE = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
NEUTRAL = {"curve": [0, 64, 128, 192, 255], "cropAspect": "original"}


def file_fingerprint(data):
    """旧recipe探索用の軽量指紋（先頭4MB＋サイズ）。"""
    head = hashlib.sha256(data[:4 * 1024 * 1024] + str(len(data)).encode())
    return head.hexdigest()[:32]


def file_fingerprint_v2(data):
    """改名に影響されない正本指紋。open時にbody全体があるため追加I/Oなし。"""
    return hashlib.sha256(data).hexdigest()


def migrate_legacy_recipes():
    """旧recipes.json（一括保存）をimagesフォルダの写真ごとJSONへ移行して削除。"""
    try:
        data = json.loads(RECIPES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(data, dict):
        IMAGES_DIR.mkdir(exist_ok=True)
        for fingerprint, entry in data.items():
            if not (isinstance(entry, dict)
                    and isinstance(entry.get("recipe"), dict)):
                continue
            stem = re.sub(r"[^\w.-]+", "_",
                          Path(str(entry.get("name", "picture"))).stem) or "picture"
            target = IMAGES_DIR / f"{stem}-{fingerprint}.json"
            if not target.exists():
                target.write_text(
                    json.dumps(entry["recipe"], ensure_ascii=False),
                    encoding="utf-8")
    RECIPES_PATH.unlink(missing_ok=True)


def run_sips(args, timeout=120):
    result = subprocess.run(
        ["sips", *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "sipsで画像を処理できませんでした")
    return result.stdout

def camera_model(path):
    try:
        output = run_sips(["-g", "model", str(path)], timeout=30)
        match = re.search(r"^\s*model:\s*(.+?)\s*$", output, re.MULTILINE)
        if match:
            return match.group(1).strip()
    except (RuntimeError, subprocess.TimeoutExpired):
        pass
    result = subprocess.run(
        ["mdls", "-raw", "-name", "kMDItemAcquisitionModel", str(path)],
        capture_output=True, text=True, timeout=15, check=False
    )
    value = result.stdout.strip().strip('"')
    return "" if value in {"", "(null)"} else value.strip()


def match_camera(model):
    key = model.casefold()
    return next((c for c in CAMERAS if key in {m.casefold() for m in c["models"]}), None)


def _dng_baseline_exposure(path):
    """DNGのBaselineExposure(50730)。ACR/LRは常時適用する基準感度の補正値で、
    GR IIIは-0.51EV等が入っている。未適用だとLRより明るく・彩度過多に出る。"""
    try:
        data = Path(path).read_bytes()
        endian = "<" if data[:2] == b"II" else ">"
        offset = struct.unpack_from(endian + "I", data, 4)[0]
        count = struct.unpack_from(endian + "H", data, offset)[0]
        for i in range(count):
            tag, typ, num, value = struct.unpack_from(
                endian + "HHII", data, offset + 2 + i * 12)
            if tag == 50730 and typ == 10:  # SRATIONAL
                numerator, denominator = struct.unpack_from(endian + "ii",
                                                            data, value)
                if denominator:
                    return max(-3.0, min(3.0, numerator / denominator))
    except (OSError, ValueError, struct.error):
        pass
    return 0.0


def _source_focal(path):
    try:
        with Image.open(path) as opened:
            return float(opened.getexif().get_ifd(34665).get(37386, 0) or 0)
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0


def _source_info(path):
    """撮影情報（EXIF）を表示用に整形して返す。無い項目は省く。"""
    info = {}
    try:
        with Image.open(path) as opened:
            exif = opened.getexif()
            ifd = exif.get_ifd(34665)

            def as_float(tag):
                try:
                    return float(ifd.get(tag, 0))
                except (TypeError, ValueError):
                    return 0.0

            shutter = as_float(33434)
            if shutter >= 1:
                info["shutter"] = f"{shutter:g}秒"
            elif shutter > 0:
                info["shutter"] = f"1/{round(1 / shutter)}秒"
            aperture = as_float(33437)
            if aperture:
                info["aperture"] = f"F{aperture:g}"
            iso = ifd.get(34855)
            if iso:
                info["iso"] = f"ISO {int(iso)}"
            focal = as_float(37386)
            focal35 = ifd.get(41989)
            if focal:
                text = f"{focal:g}mm"
                if focal35 and abs(int(focal35) - focal) > 1:
                    text += f"（35mm判 {int(focal35)}mm）"
                info["focal"] = text
            date = ifd.get(36867) or exif.get(306)
            if date:
                info["date"] = re.sub(r"^(\d{4}):(\d{2}):(\d{2})", r"\1/\2/\3",
                                      str(date))
            lens = ifd.get(42036)
            if lens and str(lens).strip():
                info["lens"] = str(lens).strip()
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return info


def lens_profiles():
    """Adobe Camera Raw同梱のLCP（レンズプロファイル）一覧。LRの
    「レンズ補正を使用」と同じデータ源。無いMacでは空dictを返す。"""
    global _LENS_PROFILES
    if _LENS_PROFILES is None:
        found = {}
        for root in LENS_PROFILE_DIRS:
            if not root.is_dir():
                continue
            for path in root.rglob("*.lcp"):
                if any(maker in path.stem.upper() for maker in LENS_MAKERS):
                    name = re.sub(r"\s*-\s*RAW$", "", path.stem)
                    found.setdefault(name, path)
        _LENS_PROFILES = dict(sorted(found.items()))
    return _LENS_PROFILES


def lensfun_db():
    global _LENSFUN_DB
    if _LENSFUN_DB is None and lensfunpy is not None:
        _LENSFUN_DB = lensfunpy.Database()
    return _LENSFUN_DB


def lensfun_camera(model):
    db = lensfun_db()
    if db is None or not model:
        return None
    cameras = db.find_cameras(None, model, loose_search=True)
    return cameras[0] if cameras else None


def lensfun_lenses(model):
    """機種に合うlensfunレンズ一覧（オープンDB・UI用）。"""
    camera = lensfun_camera(model)
    if camera is None:
        return []
    try:
        lenses = lensfun_db().find_lenses(camera, loose_search=True)
    except lensfunpy.LensfunError:
        lenses = []
    return sorted({lens.model for lens in lenses})


def load_lensfun_model(model, lens_name, focal, width, height):
    """lensfunの歪曲を「半径→半径」テーブル（半対角=1の相対座標）として返す。
    Modifierの座標マップから抽出するため正規化仕様の解釈違いが起きない。
    相対テーブルなのでpreview/フル解像度の両方で同じものが使える。"""
    key = (model, lens_name, round(float(focal or 0), 1))
    if key in _LENSFUN_CACHE:
        return _LENSFUN_CACHE[key]
    result = None
    camera = lensfun_camera(model)
    if camera is not None:
        lenses = lensfun_db().find_lenses(camera, None, lens_name,
                                          loose_search=True)
        if lenses:
            lens = lenses[0]
            sample_w = 1024
            sample_h = max(8, round(sample_w * height / max(width, 1)))
            modifier = lensfunpy.Modifier(lens, camera.crop_factor,
                                          sample_w, sample_h)
            # scale=1.0で自動ズームを無効化（既定は塗り残し防止の拡大が混入し、
            # 中心倍率が1でなくなる。枠合わせは自前のfill iterationが担う）
            modifier.initialize(float(focal) or float(lens.min_focal),
                                8.0, 1000.0, scale=1.0)
            coords = modifier.apply_geometry_distortion()
            if coords is not None:
                cx, cy = (sample_w - 1) / 2, (sample_h - 1) / 2
                half_diagonal = float(np.hypot(cx, cy))
                ts = np.linspace(0, 1, 64, dtype=np.float32)
                xs = np.round(cx + ts * cx).astype(int)
                ys = np.round(cy + ts * cy).astype(int)
                ru = np.hypot(xs - cx, ys - cy) / half_diagonal
                rd = np.hypot(coords[ys, xs, 0] - cx,
                              coords[ys, xs, 1] - cy) / half_diagonal
                order = np.argsort(ru)
                ru = ru[order].astype(np.float32)
                rd = rd[order].astype(np.float32)
                # PTLENS系は中心倍率(1-a-b-c)≠1の正規化。Adobeと同じ
                # 「中心倍率1・純粋な歪曲のみ」へ正規化する（K-1 28mmで2.9%）
                slope0 = float(rd[1] / max(ru[1], 1e-9)) if len(ru) > 1 else 1.0
                if slope0 > 0:
                    rd = rd / np.float32(slope0)
                result = {"radial": (ru, rd)}
    _LENSFUN_CACHE[key] = result
    return result


def load_lens_model(name, focal):
    """LCPから撮影焦点距離に最も近い歪曲モデル(k1..k3・正規化焦点・中心)を返す。"""
    path = lens_profiles().get(name)
    if not path:
        return None
    key = (name, round(float(focal or 0), 1))
    if key not in _LCP_CACHE:
        blocks = []
        for block in path.read_text(encoding="utf-8",
                                    errors="replace").split("<rdf:li")[1:]:
            if "RadialDistortParam1" not in block:
                continue
            values = dict(re.findall(r'stCamera:(\w+)="([-\d.eE]+)"', block))
            try:
                blocks.append({
                    "focal": float(values["FocalLength"]),
                    "distance": float(values.get("FocusDistance", 10000)),
                    "k1": float(values["RadialDistortParam1"]),
                    "k2": float(values.get("RadialDistortParam2", 0)),
                    "k3": float(values.get("RadialDistortParam3", 0)),
                    "cx": float(values.get("ImageXCenter", .5)),
                    "cy": float(values.get("ImageYCenter", .5)),
                    "fx": (float(values["FocalLengthX"])
                           if "FocalLengthX" in values else None),
                })
            except (KeyError, ValueError):
                continue
        model = None
        if blocks:
            target = focal or blocks[0]["focal"]
            nearest = min(blocks, key=lambda b: abs(b["focal"] - target))["focal"]
            candidates = [b for b in blocks if b["focal"] == nearest]
            # EXIFに撮影距離が無いため遠距離（風景・建物）側を既定にする。
            # 近接ブロック（例: 28mm 0.5mはk1=-0.162、∞は-0.136）を選ぶと
            # 遠景で約2割の過補正になり壁が逆反りする
            chosen = max(candidates, key=lambda b: b["distance"])
            # FocalLengthXはanchorブロックにしか無いので同焦点→全体→36mm換算の順で補完
            fx = (chosen["fx"]
                  or next((b["fx"] for b in candidates if b["fx"]), None)
                  or next((b["fx"] for b in blocks if b["fx"]), nearest / 36.0))
            model = {**{k: chosen[k] for k in ("k1", "k2", "k3", "cx", "cy")},
                     "fx": fx}
        _LCP_CACHE[key] = model
    return _LCP_CACHE[key]


class LensMapper:
    """出力座標→元座標の写像（歪曲補正＋角度補正）と、そのbilinear再サンプル。
    apply_lens_geometry（全面）とLazyLens（100%表示の領域だけ）が同じ式を使う＝
    どちらで計算しても画素値は同じになる（tileと書き出しの一致を保つ）。
    Adobeの歪曲モデルは「理想座標→実座標」なので逆算不要でそのまま使える。
    amountは適用率（LRのゆがみ量と同じ・1.0=100%）。straightenは度（＋で右上がり）。
    回転時は四隅が欠けないよう同アスペクト最大の内接範囲へ自動スケール。"""

    def __init__(self, height, width, model, amount=1.0, straighten=0.0):
        self.height, self.width = height, width
        theta = float(np.deg2rad(max(-10.0, min(10.0, straighten))))
        self.cos_t, self.sin_t = np.float32(np.cos(theta)), np.float32(np.sin(theta))
        c, s = abs(float(self.cos_t)), abs(float(self.sin_t))
        self.fit = np.float32(min(width / (width * c + height * s),
                                  height / (width * s + height * c))) if theta else np.float32(1)
        self.center_x = np.float32((width - 1) / 2)
        self.center_y = np.float32((height - 1) / 2)
        self.strength = np.float32(max(0.0, min(1.5, amount)))
        self.model = model
        if model is None:
            self.mode = None
            self.focal = self.cx = self.cy = None
        elif "radial" in model:
            # lensfun由来: 半径→半径テーブル（半対角=1・光軸=画像中心）
            self.mode = "radial"
            self.table_ru, self.table_rd = model["radial"]
            self.unit = np.float32(np.hypot((width - 1) / 2, (height - 1) / 2))
            self.focal = self.cx = self.cy = None
        else:
            self.mode = "adobe"
            self.focal = model["fx"] * max(width, height)
            self.cx = model["cx"] * width - .5
            self.cy = model["cy"] * height - .5
        self.k1, self.k2, self.k3 = ((model["k1"], model["k2"], model["k3"])
                                     if model and "radial" not in model else (0.0, 0.0, 0.0))
        # 塗り残し防止スケール: 出力境界が必ず元frame内からサンプルされる範囲まで縮める
        # （樽型補正はそのまま収まる。糸巻き型はLR同様わずかに拡大相当になる）
        self.scale = 1.0
        if model is not None:
            edge_x = np.linspace(0, width - 1, 64, dtype=np.float32)
            edge_y = np.linspace(0, height - 1, 64, dtype=np.float32)
            border_x = np.concatenate([edge_x, edge_x, np.zeros(64, np.float32),
                                       np.full(64, width - 1, np.float32)])
            border_y = np.concatenate([np.zeros(64, np.float32),
                                       np.full(64, height - 1, np.float32),
                                       edge_y, edge_y])
            for _ in range(24):
                sx, sy = self.distort(border_x, border_y, self.scale)
                if (sx.min() >= 0 and sx.max() <= width - 1
                        and sy.min() >= 0 and sy.max() <= height - 1):
                    break
                self.scale *= .99

    def factor_of(self, r2):
        return 1 + self.strength * (self.k1 + (self.k2 + self.k3 * r2) * r2) * r2

    def rotate(self, out_x, out_y):
        """出力座標→回転・内接スケール後の元座標"""
        dx = out_x - self.center_x
        dy = out_y - self.center_y
        return ((dx * self.cos_t - dy * self.sin_t) * self.fit + self.center_x,
                (dx * self.sin_t + dy * self.cos_t) * self.fit + self.center_y)

    def distort(self, px, py, scale):
        """回転後座標→歪曲モデル適用後の元座標"""
        if self.mode == "radial":
            dx = (px - self.center_x) / self.unit * scale
            dy = (py - self.center_y) / self.unit * scale
            undistorted = np.sqrt(dx * dx + dy * dy)
            distorted = np.interp(undistorted, self.table_ru,
                                  self.table_rd).astype(np.float32)
            ratio = np.where(undistorted > 1e-6,
                             distorted / np.maximum(undistorted, 1e-6), 1.0)
            ratio = 1 + (ratio - 1) * self.strength  # ゆがみ量sliderの適用率
            return (dx * ratio * self.unit + self.center_x,
                    dy * ratio * self.unit + self.center_y)
        xn = (px - self.cx) / self.focal * scale
        yn = (py - self.cy) / self.focal * scale
        factor = self.factor_of(xn * xn + yn * yn)
        return xn * factor * self.focal + self.cx, yn * factor * self.focal + self.cy

    def resample(self, linear, xs, ys):
        """出力座標xs(1,W)・ys(H,1)の画素をlinearからbilinearで取る（uint16）。"""
        width, height = self.width, self.height
        sx, sy = self.rotate(xs, ys)
        if self.model is not None:
            sx, sy = self.distort(sx, sy, self.scale)
        x0 = np.clip(np.floor(sx).astype(np.int32), 0, width - 2)
        y0 = np.clip(np.floor(sy).astype(np.int32), 0, height - 2)
        wx = np.clip(sx - x0, 0, 1).astype(np.float32)[:, :, None]
        wy = np.clip(sy - y0, 0, 1).astype(np.float32)[:, :, None]
        mixed = (linear[y0, x0] * (1 - wx) * (1 - wy)
                 + linear[y0, x0 + 1] * wx * (1 - wy)
                 + linear[y0 + 1, x0] * (1 - wx) * wy
                 + linear[y0 + 1, x0 + 1] * wx * wy)
        return np.clip(mixed + .5, 0, 65535).astype(np.uint16)


def apply_lens_geometry(linear, model, amount=1.0, straighten=0.0):
    """歪曲補正＋角度補正の再サンプリング（出力画素→元座標のbilinear・1回の補間で合成）。"""
    height, width = linear.shape[:2]
    mapper = LensMapper(height, width, model, amount, straighten)
    output = np.empty((height, width, 3), dtype=np.uint16)
    xs = np.arange(width, dtype=np.float32)[None, :]
    for top in range(0, height, 256):
        stop = min(top + 256, height)
        ys = np.arange(top, stop, dtype=np.float32)[:, None]
        output[top:stop] = mapper.resample(linear, xs, ys)
    return output


class LazyLens:
    """レンズ補正後のフルサイズ画像を「要求された領域だけ」その場で計算するndarray風の
    入れ物（100%表示用）。shapeと2次元スライスだけに応える。
    以前は100%の初回に24MP全面を補正してcache（約3秒・137MB）してから1タイルを切り出して
    いた。tileに要るのは1.5MP程度なので、写像を領域に限って計算する（2026-11-02）。
    値はapply_lens_geometryと同じLensMapperの式なので、全面cacheから切り出した場合と一致する。"""

    def __init__(self, base, mapper, top=0, left=0, height=None, width=None):
        self._base, self._mapper = base, mapper
        self._top, self._left = top, left
        height = mapper.height - top if height is None else height
        width = mapper.width - left if width is None else width
        self.shape = (height, width, 3)
        self.dtype = np.uint16

    def _range(self, key, size):
        if isinstance(key, slice):
            return key.indices(size)
        return int(key), int(key) + 1, 1

    def __getitem__(self, key):
        if not isinstance(key, tuple):
            key = (key,)
        rows = self._range(key[0], self.shape[0]) if len(key) > 0 else (0, self.shape[0], 1)
        cols = self._range(key[1], self.shape[1]) if len(key) > 1 else (0, self.shape[1], 1)
        if rows[2] == 1 and cols[2] == 1:  # 連続領域は遅延のまま（crop_linearの切り抜きなど）
            return LazyLens(self._base, self._mapper, self._top + rows[0], self._left + cols[0],
                            max(0, rows[1] - rows[0]), max(0, cols[1] - cols[0]))
        ys = np.arange(self._top + rows[0], self._top + rows[1], rows[2], dtype=np.float32)
        xs = np.arange(self._left + cols[0], self._left + cols[1], cols[2], dtype=np.float32)
        return self._mapper.resample(self._base, xs[None, :], ys[:, None])

    def __array__(self, dtype=None, copy=None):
        height, width = self.shape[:2]
        output = np.empty((height, width, 3), dtype=np.uint16)
        xs = np.arange(self._left, self._left + width, dtype=np.float32)[None, :]
        for top in range(0, height, 256):
            stop = min(top + 256, height)
            ys = np.arange(self._top + top, self._top + stop, dtype=np.float32)[:, None]
            output[top:stop] = self._mapper.resample(self._base, xs, ys)
        return output if dtype is None else output.astype(dtype)

    def astype(self, dtype, **_):
        return np.asarray(self).astype(dtype)


def source_linear(item, settings, preview=False, lazy=False):
    """レンズ補正の有無を吸収した現像元linearを返す（補正結果はitem内にcache）。
    lazy=True（100%表示）は、全面cacheが無ければLazyLens＝要る領域だけ計算して返す。"""
    base = item["preview_linear"] if preview else item["linear"]
    name = str(settings.get("lensProfile", "") or "")
    amount = positive_number(settings, "lensAmount", 100, 150) / 100
    straighten = number(settings, "straighten", 10)
    model = None
    if name and amount > 0:
        if name.startswith(LENSFUN_PREFIX):  # オープンDB（lensfun）
            model = load_lensfun_model(item.get("model", ""),
                                       name[len(LENSFUN_PREFIX):],
                                       item.get("focal", 0),
                                       item["width"], item["height"])
        else:  # Adobe LCP
            model = load_lens_model(name, item.get("focal", 0))
    if model is None and not straighten:
        return np.load(base, mmap_mode="r", allow_pickle=False)
    tag = "preview" if preview else "full"
    cache_key = f"{name}:{amount:.2f}:{straighten:.1f}"
    cache = Path(item["dir"]) / f"lens-{tag}.npy"
    if item.get(f"lens_key_{tag}") != cache_key or not cache.exists():
        source = np.load(base, mmap_mode="r", allow_pickle=False)
        if lazy:
            height, width = source.shape[:2]
            return LazyLens(source, LensMapper(height, width, model, amount, straighten))
        np.save(cache, apply_lens_geometry(source, model, amount, straighten),
                allow_pickle=False)
        item[f"lens_key_{tag}"] = cache_key
    return np.load(cache, mmap_mode="r", allow_pickle=False)


def camera_profiles(model):
    """機種名に合うAdobe DCP（カメラプロファイル）一覧 name→path。"""
    key = ("profiles", model.casefold())
    if key not in _DCP_CACHE:

        def search(target):
            found = {}
            for path in CAMERA_PROFILE_DIR.rglob("*.dcp"):
                stem = path.stem
                if target.casefold() in stem.casefold():
                    name = re.sub(re.escape(target), "", stem,
                                  flags=re.IGNORECASE).strip()
                    # DCP名は「<機種名> Adobe Standard／Camera 〜」の形。残りが
                    # それ以外で始まるのは別機種への部分一致（K-1→K-1 Mark II、
                    # GR III→GR III HDF/GR IIIx）なので除外する
                    if not re.match(r"(?i)(adobe|camera)\b", name):
                        continue
                    found[name or stem] = path
            return found

        found = {}
        if model and CAMERA_PROFILE_DIR.is_dir():
            # 限定モデル名（例: GR IIIx Urban Edition）はDCP名に無いことがある
            # ため、見つかるまで後ろの語を削って探す
            words = model.split()
            while words and not found:
                found = search(" ".join(words))
                words.pop()
        if "Adobe Standard" in found:
            # Kit Vivid = satScale中立化前のAdobe Standard発色（彩度がLR比
            # +80%乗る）。2026-08-11の修正で消えた画を利用者指名で残す
            found["Kit Vivid"] = found["Adobe Standard"]
        _DCP_CACHE[key] = dict(sorted(found.items()))
    return _DCP_CACHE[key]


def parse_dcp(path):
    """DCP(TIFF)からトーンカーブ・HueSatDeltas・LookTableを取り出す。"""
    data = path.read_bytes()
    endian = "<" if data[:2] == b"II" else ">"
    offset = struct.unpack_from(endian + "I", data, 4)[0]
    count = struct.unpack_from(endian + "H", data, offset)[0]
    tags = {}
    for i in range(count):
        tag, typ, num, value = struct.unpack_from(
            endian + "HHII", data, offset + 2 + i * 12)
        tags[tag] = (num, value)

    def floats(tag):
        num, value = tags[tag]
        return np.frombuffer(data, dtype=endian + "f4", count=num,
                             offset=value).astype(np.float32)

    def dims_of(tag):
        num, value = tags[tag]
        return struct.unpack_from(endian + "III", data, value)

    profile = {}
    if 0xC6FC in tags:  # ProfileToneCurve（linear→linear・per channel）
        curve = floats(0xC6FC).reshape(-1, 2)
        profile["curve"] = (np.ascontiguousarray(curve[:, 0]),
                            np.ascontiguousarray(curve[:, 1]))
    hsv_tag = 0xC6FB if 0xC6FB in tags else (0xC6FA if 0xC6FA in tags else None)
    if hsv_tag and 0xC6F9 in tags:  # HueSatDeltas（昼光側の2を優先）
        hd, sd, vd = dims_of(0xC6F9)
        profile["hsv"] = (floats(hsv_tag).reshape(vd, hd, sd, 3), (hd, sd, vd))
    if 0xC726 in tags and 0xC725 in tags:  # LookTable
        hd, sd, vd = dims_of(0xC725)
        profile["look"] = (floats(0xC726).reshape(vd, hd, sd, 3), (hd, sd, vd))
    return profile


def load_camera_profile(model, name):
    if not name:
        return None
    if name == KIT_STANDARD:
        return KIT_STANDARD_PROFILE
    if not model:
        return None
    path = camera_profiles(model).get(name)
    if not path:
        return None
    vivid = name == "Kit Vivid"  # 中立化をスキップ＝彩度の乗った旧発色
    key = ("dcp", str(path), vivid)
    if key not in _DCP_CACHE:
        try:
            profile = parse_dcp(path)
            if "hsv" in profile and not vivid:
                # HueSatDeltas（校正層）のsatScaleは「カメラ生の淡い色→適正」への
                # 補正で、LibRawの行列変換後に掛けると二重適用になり彩度が
                # LR比+80%になる（2026-08-11実測）。hue/valは残しsatだけ中立化。
                # Lookテーブル（作画層＝Camera Positive Film等）は触らない
                table, dims = profile["hsv"]
                table = table.copy()
                table[..., 1] = 1.0
                profile["hsv"] = (table, dims)
            if "curve" not in profile and ACR_DEFAULT_CURVE is not None:
                # LR/ACR同様、カーブ無しプロファイル（Adobe Standard等）には
                # ACR3標準カーブを適用（これが無いと暗くフラットに出る）
                profile["curve"] = ACR_DEFAULT_CURVE
            if vivid:
                profile["_direct"] = True  # LUT化せず全画素計算（apply_dcp_encoded）
            _DCP_CACHE[key] = profile
        except (OSError, KeyError, ValueError, struct.error):
            _DCP_CACHE[key] = None
    return _DCP_CACHE[key]


def _hsv_from_rgb(flat):
    maximum = flat.max(axis=1)
    minimum = flat.min(axis=1)
    chroma = maximum - minimum
    hue = np.zeros_like(maximum)
    safe = chroma > 1e-8
    r, g, b = flat[:, 0], flat[:, 1], flat[:, 2]
    rmax = safe & (r >= g) & (r >= b)
    gmax = safe & ~rmax & (g >= b)
    bmax = safe & ~rmax & ~gmax
    hue[rmax] = ((g - b)[rmax] / chroma[rmax]) % 6
    hue[gmax] = (b - r)[gmax] / chroma[gmax] + 2
    hue[bmax] = (r - g)[bmax] / chroma[bmax] + 4
    hue *= 60
    saturation = np.where(maximum > 1e-8, chroma / np.maximum(maximum, 1e-8), 0)
    return hue, saturation.astype(np.float32), maximum


def _rgb_from_hsv(hue, saturation, value):
    hue = (hue % 360) / 60
    index = np.floor(hue).astype(np.int32) % 6
    fraction = (hue - np.floor(hue)).astype(np.float32)
    p = value * (1 - saturation)
    q = value * (1 - saturation * fraction)
    t = value * (1 - saturation * (1 - fraction))
    r = np.choose(index, [value, q, p, p, t, value])
    g = np.choose(index, [t, value, value, q, p, p])
    b = np.choose(index, [p, p, t, value, value, q])
    return np.stack([r, g, b], axis=1)


def _apply_hsv_table(hue, saturation, value, table, dims):
    hd, sd, vd = dims

    def bilinear(vi):
        hf = hue / 360 * hd
        h0 = np.floor(hf).astype(np.int32) % hd
        h1 = (h0 + 1) % hd
        wh = (hf - np.floor(hf)).astype(np.float32)[:, None]
        sf = np.clip(saturation, 0, 1) * (sd - 1)
        s0 = np.floor(sf).astype(np.int32)
        s1 = np.minimum(s0 + 1, sd - 1)
        ws = (sf - s0).astype(np.float32)[:, None]
        return (table[vi, h0, s0] * (1 - wh) * (1 - ws)
                + table[vi, h1, s0] * wh * (1 - ws)
                + table[vi, h0, s1] * (1 - wh) * ws
                + table[vi, h1, s1] * wh * ws)

    if vd == 1:
        delta = bilinear(0)
    else:
        vf = np.clip(value, 0, 1) * (vd - 1)
        v0 = np.floor(vf).astype(np.int32)
        v1 = np.minimum(v0 + 1, vd - 1)
        wv = (vf - v0).astype(np.float32)[:, None]
        delta = bilinear(v0) * (1 - wv) + bilinear(v1) * wv
    hue = hue + delta[:, 0]
    saturation = np.clip(saturation * delta[:, 1], 0, 1)
    value = np.clip(value * delta[:, 2], 0, 1)
    return hue, saturation, value


def apply_dcp(rgb, dcp):
    """カメラプロファイル適用。DNG spec順: ProPhoto HSVでHueSatDeltas→LookTable、
    トーンカーブはRGB各channelへ（per-channel curveの彩度の乗り方がAdobeの階調）。"""
    shape = rgb.shape
    flat = np.clip(rgb.reshape(-1, 3) @ SRGB_TO_PROPHOTO.T, 0, 1)
    if "hsv" in dcp or "look" in dcp:
        hue, saturation, value = _hsv_from_rgb(flat)
        for key in ("hsv", "look"):
            if key in dcp:
                hue, saturation, value = _apply_hsv_table(
                    hue, saturation, value, *dcp[key])
        flat = _rgb_from_hsv(hue, saturation, value)
    if "curve" in dcp:
        # dng_sdkのDoBaselineRGBTone方式: 最大/最小チャンネルへカーブを掛け、
        # 中間チャンネルは両者の比率で補間する。素朴なper-channel適用だと
        # 彩度が過剰に乗る（LR比+90%を実測）
        xs, ys = dcp["curve"]
        top = flat.max(axis=1)
        bottom = flat.min(axis=1)
        top_mapped = np.interp(top, xs, ys).astype(np.float32)
        bottom_mapped = np.interp(bottom, xs, ys).astype(np.float32)
        scale = ((top_mapped - bottom_mapped)
                 / np.maximum(top - bottom, 1e-9)).astype(np.float32)
        flat = bottom_mapped[:, None] + (flat - bottom[:, None]) * scale[:, None]
    flat = flat @ PROPHOTO_TO_SRGB.T
    return np.clip(flat, 0, 1).reshape(shape).astype(np.float32)


def dcp_lut(dcp):
    """DCP適用＋sRGBエンコードを3D LUT（encoded sRGB→encoded sRGB）へ焼き込む。
    HSVテーブルの全画素計算は1400px previewで1秒超かかり、スライダーの体感を
    決めていた（2026-11-02実測: 0.7秒→1.7秒）。LUTはプロファイルごとに1回だけ作り
    dcp dict自身にcacheする。入力をencoded側で刻むので暗部の刻みも細かい。"""
    table = dcp.get("_lut")
    if table is None:
        n = DCP_LUT_SIZE
        axis = np.linspace(0, 1, n, dtype=np.float32)
        blue, green, red = np.meshgrid(axis, axis, axis, indexing="ij")
        encoded = np.stack([red, green, blue], axis=-1).reshape(-1, 1, 3)
        linear = np.where(encoded <= .04045, encoded / 12.92,
                          ((encoded + .055) / 1.055) ** 2.4).astype(np.float32)
        table = srgb_encode(apply_dcp(linear, dcp)).reshape(n, n, n, 3)
        table = np.clip(table, 0, 1).astype(np.float32)
        dcp["_lut"] = table
    return table


def apply_dcp_encoded(rgb, dcp):
    """linear sRGB(0..1)にDCPを掛け、encoded sRGBで返す。通常はLUT経由。
    Kit Vivid（彩度テーブルを中立化しない旧発色）は値の飛びが大きくLUTで
    最大15/255ずれるため、従来どおり全画素計算する。"""
    if dcp.get("_direct"):
        return srgb_encode(apply_dcp(rgb, dcp))
    return apply_lut3d(srgb_encode(rgb), dcp_lut(dcp))


def srgb_to_linear(image):
    values = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    values = np.where(values <= .04045, values / 12.92,
                      ((values + .055) / 1.055) ** 2.4)
    return np.clip(values * 65535 + .5, 0, 65535).astype(np.uint16)


def libraw_message(error):
    """LibRawのエラー（bytesで来る）を日本語の文に。"""
    detail = error.args[0] if error.args else str(error)
    if isinstance(detail, bytes):
        detail = detail.decode("utf-8", errors="replace")
    detail = str(detail)
    known = {
        "Unsupported file format or not RAW file":
            "RAWとして読めません。対応していない形式か、ファイルが壊れています",
        "Input/output error": "ファイルを読み込めませんでした（読み込み中にエラー）",
        "Unsufficient memory": "メモリが足りず展開できません",
        "Cancelled by callback": "展開を中断しました",
        "Bad crop box": "RAWの画像範囲が不正です",
        "Too big": "RAWの画像サイズが大きすぎます",
    }
    for key, text in known.items():
        if key.casefold() in detail.casefold():
            return text
    return f"RAWを展開できません（LibRaw: {detail}）"


def decode_linear(source):
    """(linear uint16, 明るさ補償gain) を返す。

    highlight_mode=Blend/Reconstruct系はWB係数 max/min 倍だけ全体を暗くして
    ハイライトのheadroomを確保する仕様のため、同じ係数をgainとして返し
    現像時に掛け戻す（旧BASE_EXPOSURE=1.3の決め打ちを廃止。実測: K-1で2.203）。
    """
    if source.suffix.lower() not in RAW_EXTENSIONS:
        with Image.open(source) as opened:
            return srgb_to_linear(ImageOps.exif_transpose(opened)), 1.0
    try:
        with rawpy.imread(str(source)) as raw:
            sizes = raw.sizes
            balance = [g for g in raw.camera_whitebalance if g > 0]
            gain = min(8.0, max(1.0, max(balance) / min(balance))) if balance else 1.0
            gain *= 2 ** _dng_baseline_exposure(source)  # LR/ACRと同じ基準感度補正
            # 輝度NR（FBDD/wavelet/median）は掛けない。ISO5000実測でエッジ量が
            # 3.88→0.95に潰れる一方、空ノイズstdは1.12→0.97しか減らない。
            # Lightroom同様、輝度NR 0＋カラーNRのみをdefaultとする
            linear = raw.postprocess(
                use_camera_wb=True, no_auto_bright=True, output_bps=16,
                gamma=(1, 1), output_color=rawpy.ColorSpace.sRGB,
                highlight_mode=rawpy.HighlightMode.Blend,
                # DHTはAHD比で細部+12%（エッジ量4.56→5.13）・ノイズ同等（2026-08-10実測）
                demosaic_algorithm=rawpy.DemosaicAlgorithm.DHT,
            )
            left = max(0, sizes.crop_left_margin - sizes.left_margin)
            top = max(0, sizes.crop_top_margin - sizes.top_margin)
            width = sizes.crop_width or sizes.width
            height = sizes.crop_height or sizes.height
            if left + width <= linear.shape[1] and top + height <= linear.shape[0]:
                linear = linear[top:top + height, left:left + width]
            return linear, gain
    except rawpy.LibRawError as error:
        raise RuntimeError(libraw_message(error)) from error

def resize_linear(linear, max_side=1400):
    height, width = linear.shape[:2]
    scale = min(1.0, max_side / max(width, height))
    if scale == 1:
        return np.array(linear, copy=True)
    size = (round(width * scale), round(height * scale))
    channels = [
        np.asarray(Image.fromarray(linear[:, :, channel]).resize(
            size, Image.Resampling.LANCZOS), dtype=np.uint16)
        for channel in range(3)
    ]
    return np.stack(channels, axis=2)


def number(settings, name, limit=100):
    try:
        value = float(settings.get(name, 0))
    except (TypeError, ValueError):
        value = 0
    return max(-limit, min(limit, value))


def positive_number(settings, name, default=0, limit=100):
    try:
        value = float(settings.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(0, min(limit, value))


LUT_DIR = ROOT / "luts"
_LUT_CACHE = {}


def lut_names():
    if not LUT_DIR.is_dir():
        return []
    return sorted(path.name for path in LUT_DIR.glob("*.cube"))


def parse_cube(text):
    """.cube（3D LUT）を(N,N,N,3) float32へ。行の並びはr最速＝[b][g][r]で格納。"""
    size = 0
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        upper = line.upper()
        if upper.startswith(("TITLE", "DOMAIN_MIN", "DOMAIN_MAX")):
            continue  # DOMAINは0-1前提（写真用.cubeの標準）
        if upper.startswith("LUT_1D_SIZE"):
            raise ValueError("1D LUTは未対応です（3D .cubeを使ってください）")
        if upper.startswith("LUT_3D_SIZE"):
            size = int(line.split()[-1])
            if not 2 <= size <= 129:
                raise ValueError("LUT_3D_SIZEが不正です")
            continue
        parts = line.split()
        if len(parts) >= 3:
            try:
                rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
            except ValueError:
                continue
    if not size or len(rows) != size ** 3:
        raise ValueError(".cubeの形式が読めません（3D LUTのみ対応）")
    table = np.asarray(rows, dtype=np.float32).reshape(size, size, size, 3)
    return np.clip(table, 0, 1)


def load_lut(settings):
    """recipeのlut名からLUTを読む（luts/内・cache付き）。無ければ黙ってskip
    ＝LUTファイルの無い環境でもrecipeの他の設定は生きる。"""
    name = Path(str(settings.get("lut", "") or "")).name
    if not name.lower().endswith(".cube"):
        return None
    path = LUT_DIR / name
    if not path.exists():
        return None
    key = (str(path), path.stat().st_mtime)
    if key not in _LUT_CACHE:
        try:
            _LUT_CACHE[key] = parse_cube(
                path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            _LUT_CACHE[key] = None
    return _LUT_CACHE[key]


def apply_lut3d(rgb, table):
    """3D LUTのtrilinear適用（rgbは0..1のHxWx3 float32）。
    格子は1次元に潰して平坦indexで8点を拾う（3軸fancy indexの約2倍速い）。"""
    n = table.shape[0]
    flat = table.reshape(-1, 3)
    scaled = np.clip(rgb, 0, 1) * (n - 1)
    low = np.minimum(scaled.astype(np.int32), n - 2)  # 非負なのでastype=floor
    frac = (scaled - low).astype(np.float32)
    base = (low[..., 2] * n + low[..., 1]) * n + low[..., 0]
    fr = frac[..., 0][..., None]
    fg = frac[..., 1][..., None]
    fb = frac[..., 2][..., None]
    step_g, step_b = n, n * n
    c00 = flat[base] * (1 - fr) + flat[base + 1] * fr
    c01 = flat[base + step_g] * (1 - fr) + flat[base + step_g + 1] * fr
    c10 = flat[base + step_b] * (1 - fr) + flat[base + step_b + 1] * fr
    c11 = (flat[base + step_b + step_g] * (1 - fr)
           + flat[base + step_b + step_g + 1] * fr)
    c0 = c00 + (c01 - c00) * fg
    c1 = c10 + (c11 - c10) * fg
    return c0 + (c1 - c0) * fb


def curve_points_of(entry):
    """カーブ制御点[[x,y]...]を検証。2〜16点・x昇順dedupe・0-255。
    全点が対角線上（恒等）ならNone＝適用しない。"""
    if not isinstance(entry, list):
        return None
    points = []
    for pair in entry[:16]:
        try:
            x, y = float(pair[0]), float(pair[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        points.append((min(255.0, max(0.0, x)), min(255.0, max(0.0, y))))
    points.sort(key=lambda p: p[0])
    deduped = []
    for point in points:
        if deduped and point[0] - deduped[-1][0] < 1:
            deduped[-1] = point
        else:
            deduped.append(point)
    if len(deduped) < 2:
        return None
    if all(abs(y - x) < .25 for x, y in deduped):
        return None
    return deduped


def monotone_curve_lut(points):
    """制御点→256要素LUT(0..1)。単調3次Hermite（Fritsch-Carlson）＝
    Photoshopのカーブに近い滑らかさで、オーバーシュートしない。"""
    xs = np.asarray([p[0] for p in points], dtype=np.float64)
    ys = np.asarray([p[1] for p in points], dtype=np.float64) / 255
    grid = np.arange(256, dtype=np.float64)
    if len(xs) == 2:
        return np.clip(np.interp(grid, xs, ys), 0, 1).astype(np.float32)
    h = np.diff(xs)
    delta = np.diff(ys) / h
    m = np.empty(len(xs))
    m[0], m[-1] = delta[0], delta[-1]
    m[1:-1] = (delta[:-1] + delta[1:]) / 2
    for i in range(len(delta)):  # 単調性の制限（区間の傾き0は平ら、比が3超は縮める）
        if delta[i] == 0:
            m[i] = m[i + 1] = 0
        else:
            a, b = m[i] / delta[i], m[i + 1] / delta[i]
            s = a * a + b * b
            if s > 9:
                t = 3 / np.sqrt(s)
                m[i], m[i + 1] = t * a * delta[i], t * b * delta[i]
    idx = np.clip(np.searchsorted(xs, grid, side="right") - 1, 0, len(xs) - 2)
    t = np.clip((grid - xs[idx]) / h[idx], 0, 1)
    t2, t3 = t * t, t * t * t
    out = ((2 * t3 - 3 * t2 + 1) * ys[idx] + (t3 - 2 * t2 + t) * h[idx] * m[idx]
           + (-2 * t3 + 3 * t2) * ys[idx + 1] + (t3 - t2) * h[idx] * m[idx + 1])
    out = np.where(grid <= xs[0], ys[0], np.where(grid >= xs[-1], ys[-1], out))
    return np.clip(out, 0, 1).astype(np.float32)


CURVE_LUT_X = np.linspace(0, 1, 256, dtype=np.float32)


def channel_curve_luts(settings):
    """curves:{lum,r,g,b:[[x,y]...]} → (lum,r,g,b)のLUT tuple（無指定/恒等はNone）。"""
    data = settings.get("curves")
    if not isinstance(data, dict):
        return None
    luts = []
    for key in ("lum", "r", "g", "b"):
        points = curve_points_of(data.get(key))
        luts.append(None if points is None else monotone_curve_lut(points))
    return tuple(luts) if any(l is not None for l in luts) else None


def crop_linear(linear, settings):
    """(クロップ後配列, geometry) を返す。geometryは(クロップ左, 上, 元幅, 元高)。
    周辺光量補正はレンズ光軸＝センサー中心基準なので、クロップ後も元座標が要る。
    cropZoom(0-200)は選択比率のまま内側へ切り込む拡大（100=2倍ズーム相当）。
    角度補正（straighten）はこの前段のwarpで済んでいるので、回転後の画から
    選んだ比率で切り抜ける。"""
    height, width = linear.shape[:2]
    aspect = str(settings.get("cropAspect", "original"))
    ratios = {"1:1": 1.0, "3:2": 1.5, "4:3": 4 / 3, "16:9": 16 / 9}
    zoom = 1 + positive_number(settings, "cropZoom", 0, 200) / 100
    if aspect not in ratios and zoom <= 1:
        return linear, (0, 0, width, height)
    ratio = ratios.get(aspect, width / max(1, height))
    crop_width, crop_height = width, round(width / ratio)
    if crop_height > height:
        crop_height, crop_width = height, round(height * ratio)
    crop_width = max(16, round(crop_width / zoom))
    crop_height = max(16, round(crop_height / zoom))
    pos_x = (number(settings, "cropX") + 100) / 200
    pos_y = (number(settings, "cropY") + 100) / 200
    left = round((width - crop_width) * pos_x)
    top = round((height - crop_height) * pos_y)
    return (linear[top:top + crop_height, left:left + crop_width],
            (left, top, width, height))


def vignette_plane(xs_px, ys_px, geometry, amount):
    """周辺光量補正のゲイン面。xs_px/ys_pxはクロップ後座標のpixel位置配列。
    センサー中心からの距離r（四隅=1）に対し gain = 2^(amount/100·1.4·r²)。"""
    crop_left, crop_top, full_width, full_height = geometry
    cx, cy = full_width / 2, full_height / 2
    xs = (np.asarray(xs_px, dtype=np.float32) + crop_left + .5 - cx) / cx
    ys = (np.asarray(ys_px, dtype=np.float32) + crop_top + .5 - cy) / cy
    wx = cx * cx / (cx * cx + cy * cy)
    r2 = np.float32(wx) * xs[None, :] ** 2 + np.float32(1 - wx) * ys[:, None] ** 2
    return np.exp2(np.float32(amount / 100 * 1.4) * r2)


def srgb_encode(values):
    return np.where(values <= .0031308, values * 12.92,
                    1.055 * np.maximum(values, 0) ** (1 / 2.4) - .055)

def local_tone(values, amount, mask, strength):
    amount = max(-1, min(1, amount))
    delta = np.where(amount >= 0, amount * (1 - values), amount * values)
    return values + delta * mask * strength


def contrast_tone(values, amount, pivot=.5):
    """中点pivot基準のS字。pivotは画像の中央輝度（0.25〜0.6にクランプ）。
    固定0.5だと暗めの写真でコントラスト＋が全体を沈める（🚫記録済み）。"""
    amount = max(-.95, min(.95, amount))
    if abs(amount) < .0001:
        return values
    pivot = float(min(.6, max(.25, pivot)))
    power = 1 + amount * 1.5 if amount > 0 else 1 / (1 - amount * 1.5)
    values = np.clip(values, 0, 1)
    below = pivot * (values / np.float32(pivot)) ** np.float32(power)
    above = 1 - (1 - pivot) * ((1 - values) / np.float32(1 - pivot)) ** np.float32(power)
    return np.where(values < pivot, below, above)


def shoulder_tone(level, white=1.0):
    """TONE_KNEEまで恒等、[TONE_KNEE, white]を[TONE_KNEE, 1.0]へ畳むC1連続shoulder。

    黒は黒のまま、中間グレー0.18も動かさず、画像の実白点whiteだけが255に写る。
    white=1.0なら恒等＋clip。旧Reinhard型 x/(x+0.18) はslope 5.6の暗部持ち上げで
    全面が白く濁った（🚫記録済み）。
    """
    span = np.float32(1 - TONE_KNEE)
    width = np.float32(max(white, 1.0) - TONE_KNEE)
    t = np.clip((level - TONE_KNEE) / width, 0, 1)
    return np.where(level <= TONE_KNEE, level,
                    TONE_KNEE + span * (1 - (1 - t) ** np.float32(width / span)))


MIXER_CENTERS = np.array([0, 30, 60, 120, 180, 240, 280, 320], dtype=np.float32)


def mixer_arrays(settings):
    """カラーミキサー設定を8帯×3種のfloat配列へ。全ゼロならNone。"""
    mixer = settings.get("mixer")
    if not isinstance(mixer, dict):
        return None
    arrays = {}
    for kind in ("hue", "sat", "lum"):
        values = mixer.get(kind)
        row = np.zeros(8, dtype=np.float32)
        if isinstance(values, list):
            for index, value in enumerate(values[:8]):
                try:
                    row[index] = max(-100.0, min(100.0, float(value)))
                except (TypeError, ValueError):
                    pass
        arrays[kind] = row
    return arrays if any(row.any() for row in arrays.values()) else None


def bw_mix_array(settings):
    """白黒ミキサー（LRのB&W Mix / PSの白黒相当）: 8色相帯×±100。全ゼロはNone。"""
    values = settings.get("bwMix")
    if not isinstance(values, list):
        return None
    row = np.zeros(8, dtype=np.float32)
    for index, value in enumerate(values[:8]):
        try:
            row[index] = max(-100.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            pass
    return row if row.any() else None


def band_ev(flat, values):
    """画素の色相を8帯へ帰属（隣接帯と円環線形補間・無彩色は保護）し、
    帯ごとの値をブレンドしたper-pixel係数を返す。白黒ミキサー用。"""
    hue, saturation, _ = _hsv_from_rgb(flat)
    positions = hue % 360
    index = (np.searchsorted(MIXER_CENTERS, positions, side="right") - 1) % 8
    following = (index + 1) % 8
    span = (MIXER_CENTERS[following] - MIXER_CENTERS[index]) % 360
    span = np.where(span == 0, np.float32(360), span)
    weight = ((positions - MIXER_CENTERS[index]) % 360) / span
    strength = np.clip(saturation / np.float32(.15), 0, 1)
    return (values[index] * (1 - weight) + values[following] * weight) * strength


def apply_mixer(rgb, mixer):
    """カラーミキサー（LRのHSL相当）。画素の色相を8帯へ帰属させ（隣接帯と
    円環線形補間）、帯ごとの色相±30°・彩度±100%・輝度±0.6EVを適用。
    無彩色に近い画素は動かさない。"""
    shape = rgb.shape
    flat = np.clip(rgb.reshape(-1, 3), 0, 1)
    hue, saturation, value = _hsv_from_rgb(flat)
    positions = hue % 360
    index = (np.searchsorted(MIXER_CENTERS, positions, side="right") - 1) % 8
    following = (index + 1) % 8
    span = (MIXER_CENTERS[following] - MIXER_CENTERS[index]) % 360
    span = np.where(span == 0, np.float32(360), span)
    weight = ((positions - MIXER_CENTERS[index]) % 360) / span

    def blend(values):
        return values[index] * (1 - weight) + values[following] * weight

    strength = np.clip(saturation / np.float32(.15), 0, 1)
    hue = hue + blend(mixer["hue"]) * np.float32(.3) * strength
    saturation = np.clip(
        saturation * (1 + blend(mixer["sat"]) / 100 * strength), 0, 1)
    value = np.clip(
        value * np.exp2(blend(mixer["lum"]) / 100 * np.float32(.6) * strength),
        0, 1)
    return _rgb_from_hsv(hue, saturation, value).reshape(shape).astype(np.float32)


GRADE_RANGES = ("shadows", "midtones", "highlights", "global")
GRADE_LUMA = np.array([.2126, .7152, .0722], dtype=np.float32)


def _hue_rgb(hue):
    """色相角（0〜360）→ 彩度最大のRGB単色（HSVのS=V=1）。"""
    sector = (hue % 360) / 60
    x = 1 - abs(sector % 2 - 1)
    table = [(1, x, 0), (x, 1, 0), (0, 1, x), (0, x, 1), (x, 0, 1), (1, 0, x)]
    return np.asarray(table[int(sector) % 6], dtype=np.float32)


def grading_settings(settings):
    """カラーグレーディング設定を4域×(hue, sat, lum)へ。効果ゼロならNone。"""
    grading = settings.get("grading")
    if not isinstance(grading, dict):
        return None
    result = {}
    active = False
    for name in GRADE_RANGES:
        row = grading.get(name)
        row = row if isinstance(row, dict) else {}
        values = []
        for key, low, high in (("hue", 0.0, 360.0), ("sat", 0.0, 100.0),
                               ("lum", -100.0, 100.0)):
            try:
                value = float(row.get(key, 0))
            except (TypeError, ValueError):
                value = 0.0
            values.append(max(low, min(high, value)))
        result[name] = tuple(values)
        active = active or values[1] > 0 or values[2] != 0
    if not active:
        return None
    result["blending"] = positive_number(settings, "gradeBlending", 50)
    result["balance"] = number(settings, "gradeBalance")
    return result


def apply_grading(rgb, grading):
    """カラーグレーディング（LRの3-way＋全体相当）。輝度からシャドウ/中間調/
    ハイライトの重みを作り、各域の色相方向へ輝度を変えないchroma offsetを加算、
    輝度sliderは±0.6EVの乗算。バランス＋で明部域が広がり、ブレンドを下げると
    域の境目が鋭くなる。白黒の後に置くのでセピア等の調色にも使える。"""
    rgb = np.clip(rgb, 0, 1)
    luminance = np.clip(rgb @ GRADE_LUMA, 0, 1)
    position = luminance ** np.float32(2 ** (-grading["balance"] / 100 * 1.5))
    power = np.float32(1 + (1 - grading["blending"] / 100) * 2)
    weights = {
        "shadows": ((1 - position) ** 2) ** power,
        "highlights": (position ** 2) ** power,
    }
    weights["midtones"] = np.maximum(
        0, 1 - weights["shadows"] - weights["highlights"])
    weights["global"] = np.ones_like(position)
    # 純黒・純白は染めない（channel clipで偽色になるだけのため）
    guard = (np.clip(luminance / np.float32(.03), 0, 1)
             * np.clip((1 - luminance) / np.float32(.03), 0, 1))
    ev = np.zeros_like(position)
    for name in GRADE_RANGES:
        hue, sat, lum = grading[name]
        if sat <= 0 and lum == 0:
            continue
        weight = weights[name]
        if sat > 0:
            color = _hue_rgb(hue)
            chroma = color - np.float32(color @ GRADE_LUMA)  # 輝度0の色方向
            amount = np.float32(sat / 100 * .25) * weight * guard
            rgb = rgb + amount[:, :, None] * chroma
        if lum:
            ev += np.float32(lum / 100 * .6) * weight
    if np.any(ev):
        rgb = rgb * np.exp2(ev)[:, :, None]
    return np.clip(rgb, 0, 1)


MASK_ADJUST_KEYS = ("exposure", "contrast", "highlights", "shadows",
                    "whites", "blacks", "temperature", "tint", "saturation")
# マスクの作業解像度（長辺）。720だと等倍表示で1マス≈10pxの階段になり
# 「鳥居の際まで選択が届かない」（2026-08-11指摘）。preview実寸(1400)に合わせる
MASK_DETAIL = 1400


def mask_shape(entry):
    """マスク形状を検証。brushは非破壊ストローク列を上限内へ正規化する。"""
    if not isinstance(entry, dict):
        return None
    mode = entry.get("mode")
    if mode == "color":
        try:
            x, y = float(entry.get("x")), float(entry.get("y"))
        except (TypeError, ValueError):
            return None
        if not (0 <= x <= 1 and 0 <= y <= 1):
            return None
        return {"mode": "color", "x": x, "y": y,
                "tolerance": positive_number(entry, "tolerance", 30),
                "contiguous": bool(entry.get("contiguous"))}
    if mode == "brush":
        raw_strokes = entry.get("strokes")
        if not isinstance(raw_strokes, list):
            return None
        strokes, total = [], 0
        for raw in raw_strokes[:128]:
            if not isinstance(raw, dict) or total >= 12000:
                continue
            points = []
            for point in (raw.get("points") if isinstance(raw.get("points"), list) else [])[:1024]:
                try:
                    x, y = float(point[0]), float(point[1])
                except (TypeError, ValueError, IndexError, KeyError):
                    continue
                if not (np.isfinite(x) and np.isfinite(y)):
                    continue
                points.append((min(1.0, max(0.0, x)), min(1.0, max(0.0, y))))
                total += 1
                if total >= 12000:
                    break
            if not points:
                continue
            strokes.append({"points": points, "erase": bool(raw.get("erase")),
                            "size": max(.002, min(.3, positive_number(raw, "size", .04, 1))),
                            "hardness": min(1.0, positive_number(raw, "hardness", .7, 1)),
                            "opacity": min(1.0, positive_number(raw, "opacity", 1, 1))})
        return {"mode": "brush", "strokes": strokes}
    raw_points = entry.get("points")
    if not isinstance(raw_points, list):
        return None
    points = []
    for point in raw_points[:200]:
        try:
            px, py = float(point[0]), float(point[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        points.append((min(1.0, max(0.0, px)), min(1.0, max(0.0, py))))
    if len(points) < 3:
        return None
    return {"mode": "path", "points": points}


def mask_settings(settings):
    """部分補正マスクの設定を検証済みlistへ。効果ゼロのマスクは飛ばす。"""
    masks = settings.get("masks")
    if not isinstance(masks, list):
        return []
    result = []
    for entry in masks[:16]:
        shape = mask_shape(entry)
        if shape is None:
            continue
        adjust = entry.get("adjust")
        adjust = adjust if isinstance(adjust, dict) else {}
        if entry.get("enabled") is False:  # オフのマスクは保存だけして適用しない
            continue
        mask = {
            **shape,
            "feather": positive_number(entry, "feather", 25),
            "invert": bool(entry.get("invert")),
            "exposure": number(adjust, "exposure", 3),
            "contrast": number(adjust, "contrast"),
            "highlights": number(adjust, "highlights"),
            "shadows": number(adjust, "shadows"),
            "whites": number(adjust, "whites"),
            "blacks": number(adjust, "blacks"),
            "temperature": number(adjust, "temperature"),
            "tint": number(adjust, "tint"),
            "saturation": number(adjust, "saturation"),
        }
        if any(mask[key] for key in MASK_ADJUST_KEYS):
            result.append(mask)
    return result


def mask_plane(mask, full_size, left, top, right, bottom):
    """正規化多角形→出力座標のfloat32重み。長辺720の小画像へ描いてぼかし
    （feather 100＝長辺5%）、resolve_maskと同じbilinear box切り出しで
    領域を返す＝preview/tile/書き出しが同一のマスクを見る。"""
    width, height = full_size
    scale = MASK_DETAIL / max(width, height)
    sw = max(2, round(width * scale))
    sh = max(2, round(height * scale))
    small = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(small).polygon(
        [(x * (sw - 1), y * (sh - 1)) for x, y in mask["points"]], fill=255)
    radius = mask["feather"] / 100 * max(sw, sh) * .05
    if radius > 0:
        small = small.filter(ImageFilter.GaussianBlur(radius))
    sx, sy = sw / width, sh / height
    region = small.resize((right - left, bottom - top), Image.Resampling.BILINEAR,
                          box=(left * sx, top * sy, right * sx, bottom * sy))
    values = np.asarray(region, dtype=np.float32) / 255
    return 1 - values if mask["invert"] else values


def brush_mask_plane(mask, full_size, left, top, right, bottom):
    """非破壊ブラシ列をMASK_DETAILの重み面へ決定的にラスタライズする。"""
    width, height = full_size
    scale = MASK_DETAIL / max(width, height)
    sw, sh = max(2, round(width * scale)), max(2, round(height * scale))
    weight = np.zeros((sh, sw), dtype=np.float32)
    longest = max(sw, sh)
    for stroke in mask["strokes"]:
        diameter = max(1, round(stroke["size"] * longest))
        coords = [(round(x * (sw - 1)), round(y * (sh - 1)))
                  for x, y in stroke["points"]]
        layer = Image.new("L", (sw, sh), 0)
        draw = ImageDraw.Draw(layer)
        if len(coords) > 1:
            draw.line(coords, fill=255, width=diameter, joint="curve")
        radius = diameter / 2
        for x, y in (coords[0], coords[-1]):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
        softness = (1 - stroke["hardness"]) * diameter * .35
        if softness > .25:
            layer = layer.filter(ImageFilter.GaussianBlur(softness))
        alpha = np.asarray(layer, dtype=np.float32) / 255 * stroke["opacity"]
        weight = weight * (1 - alpha) if stroke["erase"] else weight + (1 - weight) * alpha
    small = Image.fromarray(np.clip(weight * 255 + .5, 0, 255).astype(np.uint8), "L")
    feather = mask.get("feather", 0) / 100 * longest * .05
    if feather > 0:
        small = small.filter(ImageFilter.GaussianBlur(feather))
    sx, sy = sw / width, sh / height
    region = small.resize((right - left, bottom - top), Image.Resampling.BILINEAR,
                          box=(left * sx, top * sy, right * sx, bottom * sy))
    values = np.asarray(region, dtype=np.float32) / 255
    return 1 - values if mask.get("invert") else values


GEOMETRY_KEYS = ("cropAspect", "cropX", "cropY", "angle", "straighten",
                 "lensProfile", "lensAmount")


def color_reference(item, settings):
    """色域マスクの基準画像（ニュートラル現像＋現在の幾何設定・長辺720）。
    編集スライダーに依存しない基準から色を取るので、現像中に選択が流れない。
    幾何（クロップ/回転/レンズ補正）だけ追従させ、itemにcacheする。"""
    geometry = {**NEUTRAL, **{key: settings[key] for key in GEOMETRY_KEYS
                              if key in settings}}
    key = repr([(name, geometry.get(name)) for name in GEOMETRY_KEYS])
    if item.get("color_ref_key") != key:
        linear = source_linear(item, geometry, preview=True)
        image = develop_linear(linear, geometry, item.get("gain", 1.0),
                               item.get("headroom", 1.0))
        scale = min(1.0, MASK_DETAIL / max(image.size))
        item["color_ref"] = image.resize(
            (max(2, round(image.width * scale)),
             max(2, round(image.height * scale))), Image.Resampling.BILINEAR)
        item["color_ref_key"] = key
    return item["color_ref"]


def color_mask_plane(item, settings, mask, full_size, left, top, right, bottom):
    """色域選択（Photoshopの色域指定相当）の重み面。クリック点の色との
    RGB距離を許容量のsoft weight（縁30%をsmoothstep減衰）にする。
    contiguous=隣接のみはクリック点からのflood fill（1px膨張のBFS近似）。
    featherと切り出しはmask_planeと同じ流儀＝preview/tile/書き出しが一致。"""
    width, height = full_size
    scale = MASK_DETAIL / max(width, height)
    sw = max(2, round(width * scale))
    sh = max(2, round(height * scale))
    reference = color_reference(item, settings)
    if reference.size != (sw, sh):
        reference = reference.resize((sw, sh), Image.Resampling.BILINEAR)
    rgb = np.asarray(reference, dtype=np.float32) / 255
    cx = min(sw - 1, max(0, round(mask["x"] * (sw - 1))))
    cy = min(sh - 1, max(0, round(mask["y"] * (sh - 1))))
    seed = np.mean(rgb[max(0, cy - 1):cy + 2,
                       max(0, cx - 1):cx + 2].reshape(-1, 3), axis=0)
    # 色味の違いを明るさの違いより重視した距離。RGB等方距離だと「明るい
    # 薄い色」どうし（薄い空とベージュの地面等）が全部近くなり、青を選んだ
    # のに青くない所まで選ばれる（2026-08-11実写で確認）
    diff = rgb - seed
    luma = diff @ GRADE_LUMA
    chroma = diff - luma[:, :, None]
    distance = np.sqrt(np.float32(.25) * luma * luma
                       + np.float32(2.0) * np.sum(chroma * chroma, axis=2))
    # 換算はR0009029実測で決定: 海と霞んだ街の距離0.087、海の内部変化<0.07。
    # 0.27なら既定30=半径0.081で「海100%・街2%・道と木0%」に分離する
    # （0.75や0.4では既定のまま街まで満点で入った）
    radius = np.float32(max(.02, mask["tolerance"] / 100 * .27))
    edge = np.clip((radius - distance) / (radius * np.float32(.3)), 0, 1)
    weight = edge * edge * (3 - 2 * edge)
    if mask["contiguous"]:
        # 連結判定は720グリッド（1px膨張BFS近似のコスト抑制）。境界の精度は
        # 高解像度weight側が持つので、ゲートは粗くてよい
        gscale = 720 / max(sw, sh)
        gw = max(2, round(sw * gscale))
        gh = max(2, round(sh * gscale))
        coarse = np.asarray(
            Image.fromarray(np.clip(weight * 255 + .5, 0, 255).astype(np.uint8),
                            "L").resize((gw, gh), Image.Resampling.BILINEAR),
            dtype=np.float32) / 255
        inside = coarse > .15
        gx = min(gw - 1, max(0, round(mask["x"] * (gw - 1))))
        gy = min(gh - 1, max(0, round(mask["y"] * (gh - 1))))
        reach = np.zeros((gh, gw), dtype=np.uint8)
        if inside[gy, gx]:
            reach[gy, gx] = 255
        for _ in range(1024):
            grown = np.asarray(Image.fromarray(reach, "L")
                               .filter(ImageFilter.MaxFilter(3)))
            grown = np.where(inside, grown, 0).astype(np.uint8)
            if np.count_nonzero(grown) == np.count_nonzero(reach):
                break
            reach = grown
        gate = Image.fromarray(reach, "L").resize((sw, sh),
                                                  Image.Resampling.BILINEAR)
        weight = np.where(np.asarray(gate) > 64, weight, 0)
    small = Image.fromarray(
        np.clip(weight * 255 + .5, 0, 255).astype(np.uint8), "L")
    blur = mask["feather"] / 100 * max(sw, sh) * .05
    if blur > 0:
        small = small.filter(ImageFilter.GaussianBlur(blur))
    sx, sy = sw / width, sh / height
    region = small.resize((right - left, bottom - top), Image.Resampling.BILINEAR,
                          box=(left * sx, top * sy, right * sx, bottom * sy))
    values = np.asarray(region, dtype=np.float32) / 255
    return 1 - values if mask["invert"] else values


def selected_mask_weight(item, settings):
    """maskIndexで指定したマスクの重み面（MASK_DETAILグリッド）を返す。
    効果ゼロのマスクでも扱えるよう、adjustフィルタを通さず形状だけ検証。
    返り値は (weight[sh,sw], (出力幅, 出力高), (sw, sh))。"""
    prepare_item(item)
    masks = settings.get("masks")
    try:
        index = int(settings.get("maskIndex", -1))
    except (TypeError, ValueError):
        index = -1
    if not isinstance(masks, list) or not 0 <= index < min(len(masks), 16):
        raise ValueError("マスクが見つかりません")
    mask = mask_shape(masks[index])
    if mask is None:
        raise ValueError("マスクの形が不正です")
    mask["feather"] = positive_number(masks[index], "feather", 25)
    mask["invert"] = bool(masks[index].get("invert"))
    width, height = developed_dimensions(item, settings)
    scale = MASK_DETAIL / max(width, height)
    small = (max(2, round(width * scale)), max(2, round(height * scale)))
    # full_sizeに小サイズ自身を渡すと、renderと同じsw/sh計算のまま
    # 等倍の重み面が返る（box切り出しは恒等）
    if mask["mode"] == "color":
        weight = color_mask_plane(item, settings, mask, small,
                                  0, 0, small[0], small[1])
    elif mask["mode"] == "brush":
        weight = brush_mask_plane(mask, small, 0, 0, small[0], small[1])
    else:
        weight = mask_plane(mask, small, 0, 0, small[0], small[1])
    return weight, (width, height), small


def mask_overlay_png(item, settings):
    """選択中マスクの重みを赤の半透明PNG（出力座標系）で返す。
    LRのマスクオーバーレイ相当＝選択範囲の可視化。"""
    weight, _, small = selected_mask_weight(item, settings)
    rgba = np.zeros((small[1], small[0], 4), dtype=np.uint8)
    rgba[:, :, 0] = 235
    rgba[:, :, 1] = 70
    rgba[:, :, 2] = 90
    # 塗りは枠線の内側（重み50%以上）だけ。50%未満の薄い部分まで塗ると
    # 「枠の外が赤い」矛盾に見える（2026-08-11指摘）
    rgba[:, :, 3] = np.where(
        weight >= .5, np.clip(weight * 140 + .5, 0, 255), 0).astype(np.uint8)
    # 選択境界（重み50%の等高線）を白黒の破線で描く＝グラデの赤だけだと
    # どこまで選ばれているか分からない（2026-08-11指摘）
    binary = Image.fromarray(((weight >= .5) * 255).astype(np.uint8), "L")
    inner = binary.filter(ImageFilter.MinFilter(3))  # 輪郭1px（5だと表示で太い）
    edge = (np.asarray(binary, dtype=np.uint8)
            > np.asarray(inner, dtype=np.uint8))
    ys, xs = np.indices(edge.shape)
    dash = ((xs + ys) // 6) % 2 == 0
    rgba[edge & dash] = (250, 250, 250, 255)
    rgba[edge & ~dash] = (25, 25, 25, 255)
    output = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(output, "PNG")
    return output.getvalue()


def trace_contours(binary):
    """2値マスクの境界をmarching squaresで閉ループ列にして返す（グリッド座標）。
    セルの4隅から16caseの辺を作り、始点→終点のdictで繋ぐ。穴も別ループで出る。"""
    grid = np.pad(binary.astype(np.uint8), 1)
    tl = grid[:-1, :-1]
    tr = grid[:-1, 1:]
    bl = grid[1:, :-1]
    br = grid[1:, 1:]
    case = tl * 8 + tr * 4 + br * 2 + bl * 1
    # 各case→辺（セル内の入点→出点・内側が左になる向き）。0.5=辺の中点
    top, right = (0.5, 0.0), (1.0, 0.5)
    bottom, left = (0.5, 1.0), (0.0, 0.5)
    edges_of = {1: [(left, bottom)], 2: [(bottom, right)], 3: [(left, right)],
                4: [(right, top)], 5: [(right, bottom), (left, top)],
                6: [(bottom, top)], 7: [(left, top)],
                8: [(top, left)], 9: [(top, bottom)],
                10: [(top, right), (bottom, left)], 11: [(top, right)],
                12: [(right, left)], 13: [(right, bottom)],
                14: [(bottom, left)]}
    segments = {}
    ys, xs = np.nonzero((case > 0) & (case < 15))
    for y, x in zip(ys.tolist(), xs.tolist()):
        for (ax, ay), (bx, by) in edges_of[int(case[y, x])]:
            segments[(x + ax, y + ay)] = (x + bx, y + by)
    loops = []
    while segments:
        start, point = next(iter(segments.items()))
        loop = [start]
        while point != start and point in segments:
            loop.append(point)
            point = segments.pop(point)
        segments.pop(start, None)
        if len(loop) >= 4:
            loops.append(loop)
    return loops


def chaikin_closed(points, iterations=2):
    """閉ループのコーナーカット平滑化（グリッドの階段を除去）。"""
    pts = np.asarray(points, dtype=np.float64)
    for _ in range(iterations):
        nxt = np.roll(pts, -1, axis=0)
        out = np.empty((len(pts) * 2, 2))
        out[0::2] = pts * .75 + nxt * .25
        out[1::2] = pts * .25 + nxt * .75
        pts = out
    return pts


def rdp_closed(points, epsilon):
    """Douglas-Peucker（閉ループ用: 最遠点2つで開いて両区間へ適用）。"""

    def rdp(pts):
        if len(pts) < 3:
            return pts
        start, end = pts[0], pts[-1]
        line = end - start
        norm = np.hypot(*line)
        if norm < 1e-9:
            dists = np.hypot(*(pts[1:-1] - start).T)
        else:
            delta = pts[1:-1] - start
            # NumPy 2.5は2Dベクトルのnp.crossを受けないため、z成分を明示計算
            dists = np.abs(line[0] * delta[:, 1] - line[1] * delta[:, 0]) / norm
        peak = int(np.argmax(dists))
        if dists[peak] <= epsilon:
            return np.vstack([start, end])
        split = peak + 1
        head = rdp(pts[:split + 1])
        tail = rdp(pts[split:])
        return np.vstack([head[:-1], tail])

    pts = np.asarray(points, dtype=np.float64)
    far = int(np.argmax(np.hypot(*(pts - pts[0]).T)))
    ring = np.vstack([pts[far:], pts[:far + 1]])  # 最遠点始まりで開く
    simplified = rdp(ring)
    return simplified[:-1]  # 終点=始点の重複を落とす


def loop_to_path(points, corner_deg=60):
    """閉ループ点列→SVG cubicパス。角（曲がりがcorner_deg超）は尖らせ、
    それ以外はCatmull-Rom接線で滑らかに繋ぐ。"""
    pts = np.asarray(points, dtype=np.float64)
    count = len(pts)
    prev_pts = np.roll(pts, 1, axis=0)
    next_pts = np.roll(pts, -1, axis=0)
    v_in = pts - prev_pts
    v_out = next_pts - pts
    angle_in = np.arctan2(v_in[:, 1], v_in[:, 0])
    angle_out = np.arctan2(v_out[:, 1], v_out[:, 0])
    turn = np.abs((np.degrees(angle_out - angle_in) + 180) % 360 - 180)
    tangents = (next_pts - prev_pts) / 6.0
    tangents[turn > corner_deg] = 0  # 角は接線ゼロ＝尖ったまま
    parts = [f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"]
    for i in range(count):
        j = (i + 1) % count
        c1 = pts[i] + tangents[i]
        c2 = pts[j] - tangents[j]
        parts.append(f"C {c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} "
                     f"{pts[j][0]:.1f} {pts[j][1]:.1f}")
    parts.append("Z")
    return " ".join(parts)


def mask_outline_svg(item, settings):
    """選択中マスクの50%等高線をベジェのSVGへ（画像は触らない・線だけ）。
    BezierKit/CadKitの「SVG取り込み」にそのまま貼れる素のSVGテキストを返す。"""
    weight, (width, height), (sw, sh) = selected_mask_weight(item, settings)
    loops = trace_contours(weight >= .5)
    if not loops:
        raise ValueError("選択範囲が空です。許容量やマスクを見直してください")
    scale = width / sw
    min_area = (sw * sh) * 4e-5  # ゴミ除去: 面積0.004%未満のループは捨てる
    paths = []
    total_points = 0
    for loop in loops:
        pts = chaikin_closed(loop, 2)
        area = abs(float(np.sum(
            pts[:, 0] * np.roll(pts[:, 1], -1)
            - np.roll(pts[:, 0], -1) * pts[:, 1]))) / 2
        if area < min_area:
            continue
        pts = rdp_closed(pts, 1.1)
        if len(pts) < 3:
            continue
        total_points += len(pts)
        paths.append(loop_to_path(pts * scale))
        if len(paths) >= 64:
            break
    if not paths:
        raise ValueError("輪郭が小さすぎます。許容量を上げてみてください")
    d = " ".join(paths)
    svg = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
           f'<path d="{d}" fill="none" stroke="#121212" '
           f'stroke-width="{max(2, round(width / 700))}"/></svg>')
    return svg, len(paths), total_points


def apply_masks(image, settings, offset=(0, 0), full_size=None, item=None):
    """部分補正（Photoshopの「選択→レイヤーへコピー→色調調整」相当を非破壊で）。
    現像後の画像へ、マスクの重みで露出/色温度/Tint/彩度を混ぜる。
    offset/full_sizeは回転後の出力座標系＝tileと書き出しが一致する。"""
    masks = mask_settings(settings)
    if not masks:
        return image
    height, width = image.shape[:2]
    full_size = full_size or (width, height)
    left, top = offset
    rgb = image.astype(np.float32) / 65535
    for mask in masks:
        if mask.get("mode") == "color":
            if item is None:  # 参照画像を作れない文脈では色マスクは効かせない
                continue
            weight = color_mask_plane(item, settings, mask, full_size, left,
                                      top, left + width, top + height)
        elif mask.get("mode") == "brush":
            weight = brush_mask_plane(mask, full_size, left, top,
                                      left + width, top + height)
        else:
            weight = mask_plane(mask, full_size, left, top,
                                left + width, top + height)
        if not np.any(weight > .004):
            continue
        linear = np.where(rgb <= .04045, rgb / 12.92,
                          ((rgb + .055) / 1.055) ** 2.4)
        gains = wb_gains(mask) * np.float32(2 ** mask["exposure"])
        adjusted = srgb_encode(np.clip(linear * gains, 0, 1)).astype(np.float32)
        if mask["highlights"] or mask["shadows"]:
            # 現像本体と同思想: 明るさに応じた重みでEVを掛ける（画素関数なので
            # tile=書き出し一致は自動）
            lum_now = np.clip(adjusted @ GRADE_LUMA, 0, 1)
            ev = (np.float32(mask["highlights"] / 100 * 1.2) * lum_now ** 2
                  + np.float32(mask["shadows"] / 100 * 1.2) * (1 - lum_now) ** 2)
            adjusted = np.clip(adjusted * np.exp2(ev)[:, :, None], 0, 1)
        if mask["whites"] or mask["blacks"] or mask["contrast"]:
            # 白/黒レベル・コントラストは本体と同じ式をvalue成分へ適用
            value = np.max(adjusted, axis=2)
            new_value = local_tone(value, mask["whites"] / 100, value ** 4, .55)
            blacks = mask["blacks"] / 100
            if blacks > 0:
                new_value = new_value + np.float32(blacks * .18) * (1 - new_value) ** 2
            elif blacks < 0:
                crush = np.float32(-blacks * .12)
                new_value = np.clip((new_value - crush) / (1 - crush), 0, 1)
            if mask["contrast"]:
                new_value = contrast_tone(new_value, mask["contrast"] * .6 / 100)
            adjusted = np.clip(
                adjusted * (new_value / np.maximum(value, 1e-7))[:, :, None], 0, 1)
        if mask["saturation"]:
            luminance = adjusted @ GRADE_LUMA
            adjusted = (luminance[:, :, None]
                        + (adjusted - luminance[:, :, None])
                        * np.float32(1 + mask["saturation"] / 100))
        rgb = rgb + (np.clip(adjusted, 0, 1) - rgb) * weight[:, :, None]
    return np.clip(rgb * 65535 + .5, 0, 65535).astype(np.uint16)


CONTENT_FILL_ALGORITHM = "boundary-copy-v1"


def _normalized_content_fill(entry, require_source=True):
    if not isinstance(entry, dict):
        return None
    if str(entry.get("algorithm", CONTENT_FILL_ALGORITHM)) != CONTENT_FILL_ALGORITHM:
        return None
    raw_points = entry.get("points")
    if not isinstance(raw_points, list):
        return None
    points = []
    for point in raw_points[:512]:
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if np.isfinite(x) and np.isfinite(y):
            points.append((min(1, max(0, x)), min(1, max(0, y))))
    if not points:
        return None
    try:
        size = float(entry.get("size", .03))
        hardness = float(entry.get("hardness", .7))
        opacity = float(entry.get("opacity", 1))
        search = float(entry.get("searchRadius", .25))
    except (TypeError, ValueError):
        return None
    if not all(np.isfinite(v) for v in (size, hardness, opacity, search)):
        return None
    result = {"algorithm": CONTENT_FILL_ALGORITHM, "points": points,
              "size": max(.002, min(.12, size)),
              "hardness": max(0, min(1, hardness)),
              "opacity": max(0, min(1, opacity)),
              "searchRadius": max(.03, min(.5, search))}
    source = entry.get("source")
    try:
        sx, sy = float(source[0]), float(source[1])
    except (TypeError, ValueError, IndexError, KeyError):
        if require_source:
            return None
    else:
        if not (np.isfinite(sx) and np.isfinite(sy)):
            return None
        result["source"] = (min(1, max(0, sx)), min(1, max(0, sy)))
    return result


def content_fill_settings(settings):
    raw = settings.get("contentFills")
    if not isinstance(raw, list):
        return []
    result, total = [], 0
    for entry in raw[:32]:
        if total >= 6000 or (isinstance(entry, dict) and entry.get("enabled") is False):
            continue
        fill = _normalized_content_fill(entry)
        if fill is None:
            continue
        remaining = 6000 - total
        fill["points"] = fill["points"][:remaining]
        if fill["points"]:
            result.append(fill); total += len(fill["points"])
    return result


def _content_fill_mask(fill, size):
    width, height = size
    diameter = max(1, round(fill["size"] * max(width, height)))
    coords = [(round(x * (width - 1)), round(y * (height - 1)))
              for x, y in fill["points"]]
    mask = Image.new("L", size, 0); draw = ImageDraw.Draw(mask)
    if len(coords) > 1:
        draw.line(coords, fill=255, width=diameter, joint="curve")
    radius = diameter / 2
    for x, y in (coords[0], coords[-1]):
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=255)
    return mask, diameter


def _analysis_preview(item, settings, drop=()):
    """コピー元探索用の縮小画（長辺720px）。dropの設定を外した「きれいな」現像。"""
    clean = {**settings, "contentFills": [], "liquifyEdits": [],
             "pixelEdits": [], "grain": 0, "imageLayers": []}
    for key in ("viewport", "contentFillDraft", "healSpot", *drop):
        clean.pop(key, None)
    preview = developed_image(item, clean, preview=True).convert("RGB")
    scale = min(1.0, 720 / max(preview.size))
    if scale < 1:
        preview = preview.resize((max(2, round(preview.width * scale)),
                                  max(2, round(preview.height * scale))),
                                 Image.Resampling.BILINEAR)
    return np.asarray(preview, dtype=np.float32) / 255


def _best_source_offset(rgb, mask_image, diameter, search_radius):
    """塗った範囲（mask）の外周が最も合う平行移動(dx, dy)をpixelで返す。乱数は使わない。
    Content-Aware Fillとスポット修復のコピー元探索で共用。"""
    height, width = rgb.shape[:2]
    target = np.asarray(mask_image, dtype=np.uint8) > 127
    ys, xs = np.nonzero(target)
    if not len(xs):
        raise ValueError("範囲が空です")
    ring_width = max(2, min(15, round(diameter * .35)))
    kernel = ring_width * 2 + 1
    dilated = np.asarray(mask_image.filter(ImageFilter.MaxFilter(kernel))) > 0
    ring_y, ring_x = np.nonzero(dilated & ~target)
    if len(ring_x) < 8:
        raise ValueError("境界を取れません")
    sample_step = max(1, int(np.ceil(len(ring_x) / 4096)))
    ring_y, ring_x = ring_y[::sample_step], ring_x[::sample_step]
    dest = rgb[ring_y, ring_x]
    dest_luma = dest @ GRADE_LUMA
    bx0, bx1, by0, by1 = xs.min(), xs.max(), ys.min(), ys.max()
    search = max(3, round(search_radius * max(width, height)))
    step = max(2, round(diameter * .45),
               int(np.ceil(search * 2 / np.sqrt(2048))))
    offsets = [(dx, dy) for dy in range(-search, search + 1, step)
               for dx in range(-search, search + 1, step)
               if dx or dy if dx*dx + dy*dy <= search*search]
    offsets.sort(key=lambda q: (q[0]*q[0] + q[1]*q[1], q[1], q[0]))
    best = None
    for dx, dy in offsets[:2048]:
        sx0, sx1, sy0, sy1 = bx0 + dx, bx1 + dx, by0 + dy, by1 + dy
        if sx0 < 0 or sy0 < 0 or sx1 >= width or sy1 >= height:
            continue
        if (ring_x.min()+dx < 0 or ring_y.min()+dy < 0
                or ring_x.max()+dx >= width or ring_y.max()+dy >= height):
            continue
        if not (sx1 < bx0 or sx0 > bx1 or sy1 < by0 or sy0 > by1):
            continue
        source = rgb[ring_y + dy, ring_x + dx]
        luma = source @ GRADE_LUMA
        score = (float(np.mean(np.abs(luma - dest_luma))) * .75
                 + float(np.mean(np.abs(source - dest))) * .25
                 + abs(float(np.std(luma) - np.std(dest_luma))) * .05
                 + np.hypot(dx, dy) * 1e-6)
        key = (score, dx*dx + dy*dy, dy, dx)
        if best is None or key < best[0]:
            best = (key, dx, dy)
    if best is None:
        raise ValueError("コピー元を見つけられません。範囲か検索距離を小さくしてください")
    return best[1], best[2]


def plan_content_fill(item, settings):
    """外周が最も合う平行移動sourceを縮小画上で決定する。乱数は使わない。"""
    draft = _normalized_content_fill(settings.get("contentFillDraft"), False)
    if draft is None:
        raise ValueError("Content-Aware Fillの範囲が不正です")
    rgb = _analysis_preview(item, settings)
    height, width = rgb.shape[:2]
    mask_image, diameter = _content_fill_mask(draft, (width, height))
    try:
        dx, dy = _best_source_offset(rgb, mask_image, diameter, draft["searchRadius"])
    except ValueError as error:
        raise ValueError("Content-Aware Fillの" + str(error)
                         if str(error) in ("範囲が空です", "境界を取れません")
                         else str(error)) from None
    px, py = draft["points"][0]
    draft["source"] = (min(1, max(0, px + dx / max(1, width - 1))),
                       min(1, max(0, py + dy / max(1, height - 1))))
    return draft


def plan_heal_source(item, settings):
    """スポット修復のコピー元を自動で選ぶ。修復先の円の外周に色・明るさが合う
    場所を、Content-Aware Fillと同じ探索で決める（以前は右へ半径×2.4の固定位置で、
    中身を見ずに柱や人を貼ってしまった。2026-11-02実測）。"""
    spot = settings.get("healSpot")
    if not isinstance(spot, dict):
        raise ValueError("スポット修復の位置が不正です")
    try:
        x, y = float(spot["x"]), float(spot["y"])
        radius = max(.002, min(.12, float(spot.get("r", .02))))
    except (TypeError, ValueError, KeyError):
        raise ValueError("スポット修復の位置が不正です") from None
    if not (0 <= x <= 1 and 0 <= y <= 1):
        raise ValueError("スポット修復の位置が不正です")
    rgb = _analysis_preview(item, settings, drop=("retouch",))
    height, width = rgb.shape[:2]
    pixel_radius = max(1.5, radius * max(width, height))
    cx, cy = x * (width - 1), y * (height - 1)
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).ellipse((cx - pixel_radius, cy - pixel_radius,
                                  cx + pixel_radius, cy + pixel_radius), fill=255)
    dx, dy = _best_source_offset(rgb, mask, round(pixel_radius * 2), .25)
    return {"sx": min(1, max(0, x + dx / max(1, width - 1))),
            "sy": min(1, max(0, y + dy / max(1, height - 1)))}


def _fetch_content_patch(fetch, x0, y0, x1, y1):
    if fetch is None:
        return None
    output = np.empty((y1-y0, x1-x0, 3), dtype=np.uint16)
    for top in range(y0, y1, 1024):
        for left in range(x0, x1, 1024):
            right, bottom = min(x1, left+1024), min(y1, top+1024)
            part = fetch(left, top, right, bottom)
            if part is None or part.shape[:2] != (bottom-top, right-left):
                return None
            output[top-y0:bottom-y0, left-x0:right-x0] = part
    return output


def apply_content_fills(image, settings, offset=(0, 0), full_size=None, fetch=None):
    fills = content_fill_settings(settings)
    if not fills:
        return image
    full_size = full_size or (image.shape[1], image.shape[0])
    full_w, full_h = full_size; ox, oy = offset
    clean, current = image.copy(), image.copy()
    for fill in fills:
        weight = pixel_stroke_weight(fill, full_size, offset, current.shape)
        ys, xs = np.nonzero(weight > .001)
        if not len(xs):
            continue
        x0, x1, y0, y1 = xs.min(), xs.max()+1, ys.min(), ys.max()+1
        shift_x = round((fill["source"][0] - fill["points"][0][0]) * (full_w-1))
        shift_y = round((fill["source"][1] - fill["points"][0][1]) * (full_h-1))
        sx0, sx1 = ox+x0+shift_x, ox+x1+shift_x
        sy0, sy1 = oy+y0+shift_y, oy+y1+shift_y
        if sx0 < 0 or sy0 < 0 or sx1 > full_w or sy1 > full_h:
            continue
        if sx0 >= ox and sy0 >= oy and sx1 <= ox+clean.shape[1] and sy1 <= oy+clean.shape[0]:
            patch = clean[sy0-oy:sy1-oy, sx0-ox:sx1-ox]
        else:
            patch = _fetch_content_patch(fetch, sx0, sy0, sx1, sy1)
        if patch is None or patch.shape[:2] != (y1-y0, x1-x0):
            continue
        alpha = weight[y0:y1, x0:x1, None]
        region = current[y0:y1, x0:x1].astype(np.float32)
        current[y0:y1, x0:x1] = np.clip(
            region*(1-alpha) + patch.astype(np.float32)*alpha + .5,
            0, 65535).astype(np.uint16)
    return current


LIQUIFY_MODES = {"push", "bloat", "pinch"}


def liquify_edit_settings(settings):
    """Liquify設定を検証し、出力画像基準の正規化座標へ揃える。"""
    raw = settings.get("liquifyEdits")
    if not isinstance(raw, list):
        return []
    result, total = [], 0
    for entry in raw[:128]:
        if not isinstance(entry, dict) or total >= 12000:
            continue
        mode = str(entry.get("mode", ""))
        if mode not in LIQUIFY_MODES:
            continue
        points = []
        source = entry.get("points") if isinstance(entry.get("points"), list) else []
        for point in source[:1024]:
            try:
                x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError, IndexError, KeyError):
                continue
            if not (np.isfinite(x) and np.isfinite(y)):
                continue
            points.append((min(1, max(0, x)), min(1, max(0, y))))
            total += 1
            if total >= 12000:
                break
        minimum = 2 if mode == "push" else 1
        if len(points) < minimum:
            continue
        try:
            size = float(entry.get("size", .03))
            strength = float(entry.get("strength", .5))
        except (TypeError, ValueError):
            continue
        if not (np.isfinite(size) and np.isfinite(strength)):
            continue
        result.append({"mode": mode, "points": points,
                       "size": max(.002, min(.05, size)),
                       "strength": max(0, min(1, strength))})
    return result


def liquify_required_pad(settings, full_size):
    """逐次warp後の画素が参照し得る最大距離。tileの依存領域に使う。"""
    width, height = full_size
    longest = max(width, height)
    distance = 0.0
    for edit in liquify_edit_settings(settings):
        radius = edit["size"] * longest
        if edit["mode"] == "push":
            points = edit["points"]
            distance += sum(min(radius, np.hypot((b[0] - a[0]) * (width - 1),
                                                 (b[1] - a[1]) * (height - 1)))
                            for a, b in zip(points, points[1:])) * edit["strength"]
        else:
            distance += radius * edit["strength"] * len(edit["points"])
    return int(np.ceil(distance + 2)) if distance else 0


def _liquify_warp(image, center, radius, mode, strength, offset, delta=(0, 0)):
    """1操作を逆写像する。center/delta/offsetは出力画像のpixel座標。
    imageを直接書き換える（呼び出し側が最初に1回だけcopyする）。以前は操作ごとに
    画像全体をcopyしていて、24MPで8ストローク≒80回×144MB＝書き出し60〜77秒・
    2.9GBの原因だった（2026-11-02実測）。読み出し（sampled）は代入前に完成するので
    in-placeでも結果は同じ。"""
    if strength <= 0 or radius < 1e-6:
        return image
    ox, oy = offset
    height, width = image.shape[:2]
    cx, cy = center
    x0 = max(ox, int(np.floor(cx - radius)))
    y0 = max(oy, int(np.floor(cy - radius)))
    x1 = min(ox + width, int(np.ceil(cx + radius)) + 1)
    y1 = min(oy + height, int(np.ceil(cy + radius)) + 1)
    if x0 >= x1 or y0 >= y1:
        return image
    gx = np.arange(x0, x1, dtype=np.float32)[None, :]
    gy = np.arange(y0, y1, dtype=np.float32)[:, None]
    vx, vy = gx - np.float32(cx), gy - np.float32(cy)
    normalized = np.hypot(vx, vy) / np.float32(radius)
    falloff = np.square(np.clip(1 - normalized, 0, 1))
    if mode == "push":
        sx = gx - np.float32(delta[0] * strength) * falloff
        sy = gy - np.float32(delta[1] * strength) * falloff
    else:
        direction = -1 if mode == "bloat" else 1
        factor = 1 + np.float32(direction * strength) * falloff
        sx, sy = np.float32(cx) + vx * factor, np.float32(cy) + vy * factor
    sx = np.clip(sx - ox, 0, width - 1)
    sy = np.clip(sy - oy, 0, height - 1)
    xa, ya = np.floor(sx).astype(np.int32), np.floor(sy).astype(np.int32)
    xb, yb = np.minimum(xa + 1, width - 1), np.minimum(ya + 1, height - 1)
    wx, wy = (sx - xa)[:, :, None], (sy - ya)[:, :, None]
    source = image
    sampled = ((source[ya, xa].astype(np.float32) * (1 - wx)
                + source[ya, xb].astype(np.float32) * wx) * (1 - wy)
               + (source[yb, xa].astype(np.float32) * (1 - wx)
                  + source[yb, xb].astype(np.float32) * wx) * wy)
    image[y0 - oy:y1 - oy, x0 - ox:x1 - ox] = np.clip(
        sampled + .5, 0, 65535).astype(np.uint16)
    return image


def apply_liquify(image, settings, offset=(0, 0), full_size=None):
    """push/bloat/pinchをrecipe順に適用する非破壊Liquify。"""
    edits = liquify_edit_settings(settings)
    if not edits:
        return image
    full_size = full_size or (image.shape[1], image.shape[0])
    width, height = full_size
    longest = max(width, height)
    current = np.array(image, dtype=np.uint16, copy=True)  # 1回だけcopy
    for edit in edits:
        radius = edit["size"] * longest
        pixels = [(x * (width - 1), y * (height - 1)) for x, y in edit["points"]]
        if edit["mode"] == "push":
            for start, end in zip(pixels, pixels[1:]):
                dx, dy = end[0] - start[0], end[1] - start[1]
                length = np.hypot(dx, dy)
                if length > radius:
                    scale = radius / length
                    dx, dy = dx * scale, dy * scale
                current = _liquify_warp(current, end, radius, "push",
                                         edit["strength"], offset, (dx, dy))
        else:
            for point in pixels:
                current = _liquify_warp(current, point, radius, edit["mode"],
                                         edit["strength"], offset)
    return current


PIXEL_EDIT_MODES = {"paint", "erase", "clone", "blur"}


def pixel_edit_settings(settings):
    raw = settings.get("pixelEdits")
    if not isinstance(raw, list): return []
    result, total = [], 0
    for entry in raw[:128]:
        if not isinstance(entry, dict) or total >= 12000: continue
        mode = str(entry.get("mode", ""))
        if mode not in PIXEL_EDIT_MODES: continue
        points = []
        for point in (entry.get("points") if isinstance(entry.get("points"), list) else [])[:1024]:
            try: x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError, IndexError, KeyError): continue
            if not (np.isfinite(x) and np.isfinite(y)): continue
            points.append((min(1,max(0,x)), min(1,max(0,y)))); total += 1
            if total >= 12000: break
        if not points: continue
        try:
            size = float(entry.get("size", .03)); hardness = float(entry.get("hardness", .7))
            opacity = float(entry.get("opacity", 1)); strength = float(entry.get("strength", .5))
        except (TypeError, ValueError): continue
        if not all(np.isfinite(v) for v in (size, hardness, opacity, strength)): continue
        edit = {"mode":mode,"points":points,"size":max(.002,min(.1,size)),
                "hardness":max(0,min(1,hardness)),"opacity":max(0,min(1,opacity)),
                "strength":max(0,min(1,strength))}
        if mode == "paint":
            color = str(entry.get("color", "#000000"))
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", color): continue
            edit["color"] = color.lower()
        if mode == "clone":
            source = entry.get("source")
            try: sx, sy = float(source[0]), float(source[1])
            except (TypeError, ValueError, IndexError, KeyError): continue
            if not (np.isfinite(sx) and np.isfinite(sy)): continue
            edit["source"] = (min(1,max(0,sx)), min(1,max(0,sy)))
        # 🔑 選択範囲（部分補正マスク）の内側だけに効かせる指定。
        #    Photoshopの「選択範囲内を塗りつぶす」に相当（2026-08-21 利用者要望）
        try:
            limit = int(entry.get("limitToMask", -1))
        except (TypeError, ValueError):
            limit = -1
        if 0 <= limit < 16:
            edit["limitToMask"] = limit
        result.append(edit)
    return result


def pixel_stroke_weight(stroke, full_size, offset, shape):
    rows, cols = shape[:2]; full_w, full_h = full_size; ox, oy = offset
    diameter = max(1, round(stroke["size"] * max(full_w, full_h)))
    coords = [(round(x*(full_w-1)-ox), round(y*(full_h-1)-oy)) for x,y in stroke["points"]]
    layer = Image.new("L", (cols, rows), 0); draw = ImageDraw.Draw(layer)
    if len(coords)>1: draw.line(coords, fill=255, width=diameter, joint="curve")
    radius=diameter/2
    for x,y in (coords[0],coords[-1]): draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=255)
    softness=(1-stroke["hardness"])*diameter*.35
    if softness>.25: layer=layer.filter(ImageFilter.GaussianBlur(softness))
    return np.asarray(layer,dtype=np.float32)/255*np.float32(stroke["opacity"])


def retouch_settings(settings):
    """スポット修復の設定を検証済みlistへ。座標は出力画像基準の0〜1。"""
    items = settings.get("retouch")
    if not isinstance(items, list):
        return []
    result = []
    for entry in items[:50]:
        if not isinstance(entry, dict):
            continue
        try:
            values = {key: float(entry[key]) for key in ("x", "y", "sx", "sy")}
            radius = float(entry.get("r", .02))
        except (TypeError, ValueError, KeyError):
            continue
        if not all(0 <= value <= 1 for value in values.values()):
            continue
        result.append({**values, "r": max(.002, min(.12, radius)),
                       "mode": "clone" if entry.get("mode") == "clone" else "heal"})
    return result


def apply_retouch(image, settings, offset=(0, 0), full_size=None, fetch=None):
    """スポット修復／コピースタンプ（非破壊）。円形パッチをコピー元から重ねる。
    healはパッチの平均色を修復先の周辺色へ合わせてから混ぜる（LR相当）。
    コピー元は常に「レタッチ前」の画＝tileと書き出しが一致する。
    fetchはtile外のコピー元を取るcallback（全体現像時は不要）。"""
    items = retouch_settings(settings)
    if not items:
        return image
    full_size = full_size or (image.shape[1], image.shape[0])
    width, height = full_size
    left, top = offset
    rgb = image.astype(np.float32)
    clean = rgb.copy()

    def local_fetch(x0, y0, x1, y1):
        if (x0 >= left and y0 >= top and x1 <= left + rgb.shape[1]
                and y1 <= top + rgb.shape[0]):
            return clean[y0 - top:y1 - top, x0 - left:x1 - left]
        return None if fetch is None else fetch(x0, y0, x1, y1)

    longest = max(width, height)
    for item in items:
        radius = item["r"] * longest
        dx, dy = item["x"] * width, item["y"] * height
        x0, x1 = int(np.floor(dx - radius)), int(np.ceil(dx + radius)) + 1
        y0, y1 = int(np.floor(dy - radius)), int(np.ceil(dy + radius)) + 1
        cx0, cy0 = max(x0, left), max(y0, top)
        cx1 = min(x1, left + rgb.shape[1])
        cy1 = min(y1, top + rgb.shape[0])
        if cx0 >= cx1 or cy0 >= cy1:
            continue  # このtileに修復先が無い
        shift_x = int(round(item["sx"] * width - dx))
        shift_y = int(round(item["sy"] * height - dy))
        sx0, sy0 = cx0 + shift_x, cy0 + shift_y
        sx1, sy1 = cx1 + shift_x, cy1 + shift_y
        if sx0 < 0 or sy0 < 0 or sx1 > width or sy1 > height:
            continue  # コピー元が画像外
        patch = local_fetch(sx0, sy0, sx1, sy1)
        if (patch is None or patch.shape[0] != cy1 - cy0
                or patch.shape[1] != cx1 - cx0):
            continue
        patch = patch.astype(np.float32)
        ys = np.arange(cy0, cy1, dtype=np.float32) - dy
        xs = np.arange(cx0, cx1, dtype=np.float32) - dx
        distance = np.hypot(xs[None, :], ys[:, None]) / max(radius, 1e-6)
        weight = np.clip((1 - distance) / .3, 0, 1)  # 縁30%をなじませる
        if not np.any(weight > 0):
            continue
        if item["mode"] == "heal":
            # 修復先の縁の色（傷そのものを含みにくいring）へパッチの平均を合わせる
            ring = (weight > 0) & (weight < .7)
            area = ring if np.any(ring) else weight > 0
            dest_clean = clean[cy0 - top:cy1 - top, cx0 - left:cx1 - left]
            patch = patch + (dest_clean[area].mean(axis=0) - patch[area].mean(axis=0))
        region = rgb[cy0 - top:cy1 - top, cx0 - left:cx1 - left]
        region[:] = (region * (1 - weight)[:, :, None]
                     + np.clip(patch, 0, 65535) * weight[:, :, None])
    return np.clip(rgb + .5, 0, 65535).astype(np.uint16)


def apply_pixel_edits(image, settings, offset=(0,0), full_size=None, fetch=None):
    edits = pixel_edit_settings(settings)
    if not edits: return image
    full_size = full_size or (image.shape[1], image.shape[0]); full_w, full_h = full_size
    ox, oy = offset; clean = image.copy(); current = image.copy()
    masks_all = settings.get("masks") if isinstance(settings.get("masks"), list) else []
    limit_cache = {}
    for edit in edits:
        weight = pixel_stroke_weight(edit, full_size, offset, current.shape)
        if not np.any(weight>.001): continue
        # 選択範囲で閉じ込める（はみ出しても内側だけが変わる）
        limit = edit.get("limitToMask")
        if limit is not None and limit < len(masks_all):
            if limit not in limit_cache:
                shape = mask_shape(masks_all[limit])
                plane = None
                if shape is not None:
                    bounded = {**shape,
                               "feather": positive_number(masks_all[limit], "feather", 25),
                               "invert": bool(masks_all[limit].get("invert"))}
                    right, bottom = ox + current.shape[1], oy + current.shape[0]
                    if shape["mode"] == "brush":
                        plane = brush_mask_plane(bounded, full_size, ox, oy, right, bottom)
                    elif shape["mode"] == "path":
                        plane = mask_plane(bounded, full_size, ox, oy, right, bottom)
                limit_cache[limit] = plane
            plane = limit_cache[limit]
            if plane is not None and plane.shape == weight.shape:
                weight = weight * plane
                if not np.any(weight>.001): continue
        alpha = weight[:,:,None]
        if edit["mode"] == "erase":
            current = np.clip(current.astype(np.float32)*(1-alpha)+clean.astype(np.float32)*alpha+.5,0,65535).astype(np.uint16)
        elif edit["mode"] == "paint":
            color=np.array([int(edit["color"][i:i+2],16) for i in (1,3,5)],dtype=np.float32)/255
            color=np.where(color<=.04045,color/12.92,((color+.055)/1.055)**2.4)
            base=current.astype(np.float32)/65535
            base=np.where(base<=.04045,base/12.92,((base+.055)/1.055)**2.4)
            mixed=base*(1-alpha)+color[None,None,:]*alpha
            current=np.clip(srgb_encode(mixed)*65535+.5,0,65535).astype(np.uint16)
        elif edit["mode"] == "blur":
            radius=max(.5,min(30,edit["size"]*max(full_w,full_h)*.25*edit["strength"]))
            blurred=apply_8bit_guide(current,lambda im:im.filter(ImageFilter.GaussianBlur(radius)))
            current=np.clip(current.astype(np.float32)*(1-alpha)+blurred.astype(np.float32)*alpha+.5,0,65535).astype(np.uint16)
        else:
            ys,xs=np.nonzero(weight>.001)
            if not len(xs): continue
            x0,x1,y0,y1=xs.min(),xs.max()+1,ys.min(),ys.max()+1
            shift_x=round((edit["source"][0]-edit["points"][0][0])*full_w)
            shift_y=round((edit["source"][1]-edit["points"][0][1])*full_h)
            sx0,sx1=ox+x0+shift_x,ox+x1+shift_x;sy0,sy1=oy+y0+shift_y,oy+y1+shift_y
            if sx0<0 or sy0<0 or sx1>full_w or sy1>full_h: continue
            if sx0>=ox and sy0>=oy and sx1<=ox+clean.shape[1] and sy1<=oy+clean.shape[0]:
                patch=clean[sy0-oy:sy1-oy,sx0-ox:sx1-ox]
            else: patch=None if fetch is None else fetch(sx0,sy0,sx1,sy1)
            if patch is None or patch.shape[:2]!=(y1-y0,x1-x0): continue
            a=alpha[y0:y1,x0:x1];region=current[y0:y1,x0:x1].astype(np.float32)
            current[y0:y1,x0:x1]=np.clip(region*(1-a)+patch.astype(np.float32)*a+.5,0,65535).astype(np.uint16)
    return current


def wb_gains(settings):
    """色温度・Tintのチャンネル利得（wbModel 2）。
    ±100で R/G・B/G が各±1段（R/Bで±2段）動く。旧係数（.25/.08/.12）は±100でも
    R/B半段しか動かず、青い影のWBがスポイトで取れなかった（2026-11-02実測）。
    旧recipeの値は読み込み時にmigrate_recipeで換算する。"""
    temperature = number(settings, "temperature") / 100
    tint = number(settings, "tint") / 100
    return np.array([
        2 ** (temperature * WB_TEMP_COEF + tint * WB_TINT_RB_COEF),
        2 ** (-tint * WB_TINT_G_COEF),
        2 ** (-temperature * WB_TEMP_COEF + tint * WB_TINT_RB_COEF),
    ], dtype=np.float32)


def scene_maps(linear, settings, decode_gain, headroom, geometry):
    """局所処理用の2枚の順応マップ（ぼかした周辺値・0〜1の8bit L画像）を返す。

    light: WB/露出後の周辺の明るさ（max channel・sRGB符号化）。シャドウ/ハイライト
           の局所トーンと、コントラストのハイライト保護の基準
    veil : 大気の膜の推定量（min channel＝dark channel近似・white相対のlinear値）。
           かすみ除去はこれを差し引く
    """
    height, width = linear.shape[:2]
    step = max(1, round(max(height, width) / 360))
    sample = linear[::step, ::step].astype(np.float32) / 65535
    vignette = number(settings, "vignette")
    if vignette:
        sample *= vignette_plane(
            np.arange(sample.shape[1], dtype=np.float32) * step,
            np.arange(sample.shape[0], dtype=np.float32) * step,
            geometry, vignette)[:, :, None]
    exposure = number(settings, "exposure", 3)
    sample *= wb_gains(settings) * np.float32(decode_gain * 2 ** exposure)
    white = np.float32(max(1.0, headroom * 2 ** exposure))
    radius = max(2.0, max(sample.shape) / 30)

    def blurred(values):
        encoded = np.clip(values * 255 + .5, 0, 255).astype(np.uint8)
        # GaussianBlurはFモード非対応。ぼかし用途なので8bit Lで十分
        return Image.fromarray(encoded, "L").filter(ImageFilter.GaussianBlur(radius))

    light = srgb_encode(np.clip(np.max(sample, axis=2) / white, 0, 1))
    veil = np.clip(np.min(sample, axis=2) / white, 0, 1)
    return {"light": blurred(light), "veil": blurred(veil)}, (width, height)


def resolve_mask(mask_info, left, top, right, bottom):
    """順応マップから指定領域をfloat32で切り出す（bilinear・座標系は元画像px）。"""
    small, (width, height) = mask_info
    sx, sy = small.width / width, small.height / height
    region = small.resize((right - left, bottom - top), Image.Resampling.BILINEAR,
                          box=(left * sx, top * sy, right * sx, bottom * sy))
    return np.asarray(region, dtype=np.float32) / 255  # 8bit L由来なので0〜1へ


def transform_chunk(source, settings, decode_gain=1.0, headroom=1.0,
                    maps=None, pivot=.5, dcp=None, haze_gain=1.0):
    rgb = source.astype(np.float32) / 65535.0
    if maps and "vignette" in maps:
        rgb *= maps["vignette"][:, :, None]
    exposure = number(settings, "exposure", 3)
    rgb *= wb_gains(settings) * np.float32(decode_gain * 2 ** exposure)
    white = max(1.0, headroom * 2 ** exposure)
    highlights = number(settings, "highlights") / 100
    shadows = number(settings, "shadows") / 100
    dehaze = number(settings, "dehaze") / 100
    light = maps.get("light") if maps else None
    if maps and "veil" in maps and dehaze > 0:
        # かすみ除去: 大気散乱モデル I = J·t + white·(1-t)。膜(veil)相当を中立に
        # 差し引き、1/tで膜の下の局所コントラストと彩度を戻す。
        # 差し引きは画素自身のmin channelの8割まで（暗部を0へ潰さない保護）
        # t下限0.5＝増幅上限2倍。0.3だと白壁（dark channel誤検出面）で
        # ノイズ6倍・青被り4倍になる（2026-08-10実測）
        transmission = np.maximum(
            .5, 1 - np.float32(dehaze * .7) * maps["veil"])
        subtraction = np.minimum(np.float32(white) * (1 - transmission),
                                 np.min(rgb, axis=2) * np.float32(.8))
        rgb = (rgb - subtraction[:, :, None]) / transmission[:, :, None]
        rgb = np.maximum(rgb, 0)
        # 1/tは色の残差も同倍率で増幅し、白壁がラベンダーに転ぶ。
        # chroma成分だけ増幅を半分に減衰する（輝度コントラストは維持）
        mean = np.mean(rgb, axis=2, keepdims=True)
        damp = (transmission + (1 - transmission) * .5)[:, :, None]
        rgb = mean + (rgb - mean) * damp
        # 中間調の明るさを戻す（膜の引き算だけだと「黒く潰れるだけ」の見え方になる）。
        # whiteも同倍率で動かすことでshoulderが上端を再正規化し、
        # 回収済みハイライトは明るさ補償で再白飛びしない
        rgb *= np.float32(haze_gain)
        white *= haze_gain
    elif maps and "veil" in maps and dehaze < 0:
        # 負側は膜を足す（やわらかいフィルム調）
        amount = np.float32(-dehaze * .35) * maps["veil"]
        rgb = rgb * (1 - amount)[:, :, None] + np.float32(white) * amount[:, :, None]
    if light is not None and (highlights or shadows):
        # 局所トーン: 周辺が明るい所だけ回収、暗い所だけ持ち上げる。
        # shoulder前のlinear域で行い、シャドウは±1.8EV。ハイライトの回収幅は
        # 白点に連動させる（露出＋で白点が上がると固定幅では膝下に届かず、
        # スライダーが実質無効になるため。2026-08-10実測）
        ev = np.zeros_like(light)
        if highlights:
            reach = max(1.2, .5 + float(np.log2(max(white, 1.0) / .75)))
            ev += np.float32(highlights * reach) * light ** 2
        if shadows:
            ev += np.float32(shadows * 1.8) * (1 - light) ** 2
        rgb *= np.exp2(ev)[:, :, None]
    level = np.max(rgb, axis=2)
    mapped = shoulder_tone(level, white)
    rgb *= (mapped / np.maximum(level, 1e-7))[:, :, None]
    maximum = np.max(rgb, axis=2)
    rgb /= np.maximum(1, maximum)[:, :, None]
    rgb = np.maximum(rgb, 0)
    if dcp:
        rgb = apply_dcp_encoded(rgb, dcp)  # DCP→sRGBエンコードまでLUTで一度に
    else:
        rgb = srgb_encode(rgb)

    value = np.max(rgb, axis=2)
    value = local_tone(value, number(settings, "whites") / 100, value ** 4, .55)
    blacks = number(settings, "blacks") / 100
    if blacks > 0:
        # 黒レベル＋: 黒の出力床を持ち上げる（フェード方向・LRの黒レベルと同挙動）
        value = value + np.float32(blacks * .18) * (1 - value) ** 2
    elif blacks < 0:
        # 黒レベル−: 入力黒点を上げて締める（下位を黒へクリップ）
        crush = np.float32(-blacks * .12)
        value = np.clip((value - crush) / (1 - crush), 0, 1)
    contrast_amount = number(settings, "contrast") * .42 / 100
    contrasted = contrast_tone(value, contrast_amount, pivot)
    if light is not None and highlights < 0:
        # ハイライト回収済みの明部をコントラストが白側へ押し戻さないよう、
        # 周辺が明るい領域では上方向の押し上げだけ最大70%減衰させる
        protection = np.float32(min(1.0, -highlights) * .7) * light ** 2
        value = np.where(contrasted > value,
                         contrasted + (value - contrasted) * protection,
                         contrasted)
    else:
        value = contrasted

    curve = settings.get("curve", NEUTRAL["curve"])
    if not isinstance(curve, list) or len(curve) != 5:
        curve = NEUTRAL["curve"]
    points = np.clip(np.asarray(curve, dtype=np.float32), 0, 255) / 255
    value = np.interp(np.clip(value, 0, 1), [0, .25, .5, .75, 1], points)
    rgb *= (value / np.maximum(np.max(rgb, axis=2), 1e-7))[:, :, None]

    curve_luts = channel_curve_luts(settings)
    if curve_luts is not None:
        lum_lut, r_lut, g_lut, b_lut = curve_luts
        if lum_lut is not None:
            # 輝度カーブはvalue成分へ（色相・彩度を保つ既存流儀）
            value = np.max(rgb, axis=2)
            mapped = np.interp(value, CURVE_LUT_X, lum_lut)
            rgb *= (mapped / np.maximum(value, 1e-7))[:, :, None]
        for index, lut in ((0, r_lut), (1, g_lut), (2, b_lut)):
            if lut is not None:  # R/G/Bは各channelへ＝PSのチャンネル別カーブ
                rgb[:, :, index] = np.interp(rgb[:, :, index],
                                             CURVE_LUT_X, lut)

    mixer = mixer_arrays(settings)
    if mixer is not None:
        rgb = apply_mixer(rgb, mixer)

    luminance = np.sum(rgb * np.array([.2126, .7152, .0722], dtype=np.float32), axis=2)
    maximum = np.max(rgb, axis=2)
    minimum = np.min(rgb, axis=2)
    saturation = np.zeros_like(maximum)
    np.divide(minimum, maximum, out=saturation, where=maximum > 1e-7)
    saturation = np.where(maximum > 1e-7, 1 - saturation, 0)
    factor = max(0, 1 + number(settings, "saturation") / 100)
    factor += number(settings, "vibrance") / 100 * (1 - saturation) * .7
    rgb = luminance[:, :, None] + (rgb - luminance[:, :, None]) * factor[:, :, None]
    if settings.get("monochrome"):
        bw = bw_mix_array(settings)
        if bw is not None:
            # 白黒ミキサー: 変換前の色相で帯へ帰属し、白黒の明るさを色別に振る
            # （例: ブルー−で空が暗く落ちるモノクロ）。±100=±0.9EV
            ev = band_ev(np.clip(rgb.reshape(-1, 3), 0, 1), bw / 100)
            luminance = np.clip(luminance * np.exp2(
                ev.reshape(luminance.shape) * np.float32(.9)), 0, 1)
        rgb = np.repeat(luminance[:, :, None], 3, axis=2)
    grading = grading_settings(settings)
    if grading is not None:
        rgb = apply_grading(rgb, grading)
    lut = load_lut(settings)
    if lut is not None:
        # ルックLUT（.cube）は仕上げの最後・適用量でblend。画素関数なので
        # tile=書き出し一致は自動
        amount = positive_number(settings, "lutAmount", 100) / 100
        if amount > 0:
            rgb = rgb + (apply_lut3d(rgb, lut) - rgb) * np.float32(amount)
    return np.clip(rgb * 65535 + .5, 0, 65535).astype(np.uint16)


def _core_denoise(channel, radius, threshold):
    """edge保持NR（coring・4次knee）。ぼかしとの差分のうち閾値より小さい成分＝
    ノイズだけ均し、大きい成分＝輪郭・模様は残す。4次にすると2次より切り分けが
    鋭く、閾値の2倍の質感は94%残り、半分のノイズは94%消える。
    thresholdはscalarでも画素ごとの配列でもよい。"""
    blurred = np.asarray(channel.filter(ImageFilter.GaussianBlur(radius)),
                         dtype=np.float32)
    diff = np.asarray(channel, dtype=np.float32) - blurred
    d2 = diff * diff
    t2 = np.square(np.asarray(threshold, dtype=np.float32))
    keep = d2 * d2 / (d2 * d2 + t2 * t2)
    return Image.fromarray(
        np.clip(blurred + diff * keep + .5, 0, 255).astype(np.uint8))


def _detail_guide_8bit(image, settings, reference_longest=None, noise_map=None):
    """NR→シャープ系をYCbCr 1往復で行う。シャープ・テクスチャ・明瞭度は
    輝度のみに掛ける（RGBに掛けるとNR後の色ノイズを再増幅する）。
    noise_mapはdehazeの1/t増幅率（画素ごと）。増幅された場所ほどNR閾値を
    上げ、素の場所は質感を優先する。"""
    longest = reference_longest or max(image.size)
    color_amount = positive_number(settings, "colorNoise", 25)
    luminance_amount = positive_number(settings, "luminanceNoise", 0)
    # 増幅率→ノイズ振幅はシャープ等も乗るため2.5乗で効かせる（空など膜の濃い
    # 領域だけ閾値が上がり、瓦・葉など素の領域は質感優先のまま）
    amplification = 1.0 if noise_map is None else noise_map ** 2.5
    luma, cb, cr = image.convert("YCbCr").split()
    if luminance_amount > 0:
        luma = _core_denoise(luma, 1.4,
                             (1.5 + luminance_amount * .16) * amplification)
    if color_amount > 0:
        radius = 1 + color_amount * .07  # coringが輪郭を守るので大半径でも色階調が残る
        # 色ノイズは暗部ほど振幅が大きく一定閾値では「輪郭」と誤認して残るため、
        # 暗い画素ほど閾値を上げる（最大約4.5倍）
        darkness = 1 - np.asarray(luma, dtype=np.float32) / 255
        threshold = ((3 + color_amount * .15) * amplification
                     * (1 + 3.5 * darkness ** 2))
        cb = _core_denoise(cb.filter(ImageFilter.MedianFilter(3)), radius, threshold)
        cr = _core_denoise(cr.filter(ImageFilter.MedianFilter(3)), radius, threshold)
    # capture sharpening: Lightroom default（適用量40・半径1.0）相当を常時適用
    luma = luma.filter(ImageFilter.UnsharpMask(radius=1.0, percent=40, threshold=2))
    texture = number(settings, "texture")
    clarity = number(settings, "clarity")
    if texture > 0:
        luma = luma.filter(ImageFilter.UnsharpMask(
            radius=1, percent=round(texture * .45), threshold=3))
    elif texture < 0:
        luma = Image.blend(luma, luma.filter(ImageFilter.GaussianBlur(1)),
                           min(.5, -texture / 180))
    broad_radius = min(18, max(4, longest / 500))
    if clarity > 0:
        luma = luma.filter(ImageFilter.UnsharpMask(
            radius=broad_radius, percent=round(clarity * .25), threshold=5))
    elif clarity < 0:
        luma = Image.blend(
            luma, luma.filter(ImageFilter.GaussianBlur(max(1, broad_radius / 3))),
            min(.4, -clarity / 220))
    return Image.merge("YCbCr", (luma, cb, cr)).convert("RGB")


def image8_from_u16(rgb):
    """16bit encoded sRGBを表示・JPEG/PNG用8bitへ最後に量子化する。"""
    values = ((rgb.astype(np.uint32) + 128) // 257).astype(np.uint8)
    return Image.fromarray(values, "RGB")


def apply_8bit_guide(rgb, operation):
    """8bit Pillow filterの補正差だけを16bit RGBへ戻し、元の細階調を残す。"""
    base = ((rgb.astype(np.uint32) + 128) // 257).astype(np.uint8)
    changed = np.asarray(operation(Image.fromarray(base, "RGB")), dtype=np.float32)
    delta = (changed - base.astype(np.float32)) * np.float32(257)
    return np.clip(rgb.astype(np.float32) + delta, 0, 65535).astype(np.uint16)


def apply_detail(rgb, settings, reference_longest=None, noise_map=None):
    return apply_8bit_guide(rgb, lambda image: _detail_guide_8bit(
        image, settings, reference_longest, noise_map))


def needs_maps(settings):
    return bool(number(settings, "highlights") or number(settings, "shadows")
                or number(settings, "dehaze"))


def render_setup(linear, settings, decode_gain, headroom, geometry,
                 left, top, right, bottom):
    """指定領域のmaps（局所マップ・周辺光量ゲイン）とcontrast pivotを返す。
    書き出し・preview・tileが同じ入口を通ることで結果の一致を保つ。"""
    maps = {}
    pivot = .5
    if needs_maps(settings) or number(settings, "contrast"):
        smalls, dims = scene_maps(linear, settings, decode_gain, headroom, geometry)
        pivot = float(np.median(np.asarray(smalls["light"],
                                           dtype=np.float32))) / 255
        if needs_maps(settings):
            maps = {name: resolve_mask((small, dims), left, top, right, bottom)
                    for name, small in smalls.items()}
    vignette = number(settings, "vignette")
    if vignette:
        maps["vignette"] = vignette_plane(
            np.arange(left, right, dtype=np.float32),
            np.arange(top, bottom, dtype=np.float32), geometry, vignette)
    return (maps or None), pivot


def dehaze_gain(linear, settings, decode_gain, headroom, geometry):
    """かすみ除去後に中間調の明るさを戻す補償gain。膜の引き算だけだと
    「黒く潰れるだけ」の見え方になるため、縮小サンプルで中央値の変化を測り
    同じ式で掛け戻す（決定的＝tile/書き出し一致）。"""
    dehaze = number(settings, "dehaze") / 100
    if dehaze <= 0:
        return 1.0
    step = max(1, round(max(linear.shape[:2]) / 240))
    sample = linear[::step, ::step].astype(np.float32) / 65535
    vignette = number(settings, "vignette")
    if vignette:
        sample *= vignette_plane(
            np.arange(sample.shape[1], dtype=np.float32) * step,
            np.arange(sample.shape[0], dtype=np.float32) * step,
            geometry, vignette)[:, :, None]
    exposure = number(settings, "exposure", 3)
    sample *= wb_gains(settings) * np.float32(decode_gain * 2 ** exposure)
    white = np.float32(max(1.0, headroom * 2 ** exposure))
    level = np.max(sample, axis=2)
    veil = np.clip(np.min(sample, axis=2) / white, 0, 1)
    transmission = np.maximum(.5, 1 - np.float32(dehaze * .7) * veil)
    subtraction = np.minimum(white * (1 - transmission), level * .8)
    after = np.maximum((level - subtraction) / transmission, 1e-4)
    before_mid = float(np.median(level))
    after_mid = float(np.median(after))
    if after_mid <= 0 or before_mid <= 0:
        return 1.0
    return float(min(1.6, max(1.0, before_mid / after_mid)))


def _dilate_max(values, radius):
    """2D最大値フィルタ（半径radius・縁は端の値で延長）。縦横に分けた2r+1回の
    np.maximumで、PILのMaxFilter（rankfilter）より約50倍速い（2026-11-02実測）。"""
    if radius <= 0:
        return values
    out = values
    for axis in (0, 1):
        size = out.shape[axis]
        pad_width = [(0, 0), (0, 0)]
        pad_width[axis] = (radius, radius)
        padded = np.pad(out, pad_width, mode="edge")
        acc = out.copy()
        for shift in range(-radius, radius + 1):
            if shift == 0:
                continue
            window = (slice(radius + shift, radius + shift + size) if axis == 0
                      else (slice(None), slice(radius + shift, radius + shift + size)))
            np.maximum(acc, padded[window], out=acc)
        out = acc
    return out


def apply_defringe(rgb16, settings, reference_longest=None):
    """フリンジ軽減（Lightroomの「フリンジ軽減」相当）。白飛びした空と枝の境目などに出る
    紫（倍率色収差・軸上色収差）や緑の縁を、強い輝度エッジのそばだけ無彩色へ寄せる。
    - 色相はR-G／B-Gの平面で見る: 紫＝マゼンタ〜青紫（20〜90°）、緑＝190〜260°
    - 「どこを直すか」はフリンジ幅（原寸で約4px）をまたぐ輝度差と、近くに明るい所が
      あるかで決める。暗い中の紫の模様（服・花）はエッジでなければ触らない
    - 半径は原寸（reference_longest）基準。preview（1400px）・tile・書き出しで同じ式
    - 帯ごとに処理（24MPで一度に浮動小数へ広げると1GB超えるため）。帯の縫い目は
      のりしろ（halo）で隠す＝どこで切っても同じ値になる"""
    purple = positive_number(settings, "defringe", 0, 100) / 100
    green = positive_number(settings, "defringeGreen", 0, 100) / 100
    if purple <= 0 and green <= 0:
        return rgb16
    height, width = rgb16.shape[:2]
    longest = reference_longest or max(height, width)
    radius = max(1, round(longest / 1500))
    halo = radius * 4 + 8
    luma_weights = np.array([.2126, .7152, .0722], dtype=np.float32)
    output = np.array(rgb16, dtype=np.uint16, copy=True)

    def contrast_across(luma):
        """radius幅をまたぐ輝度差（縦・横の大きい方）。解像度が違っても同じ縁で同じ値"""
        pad = np.pad(luma, radius, mode="edge")
        dx = np.abs(pad[radius:-radius, 2 * radius:] - pad[radius:-radius, :-2 * radius])
        dy = np.abs(pad[2 * radius:, radius:-radius] - pad[:-2 * radius, radius:-radius])
        return np.maximum(dx, dy)

    def hue_weight(angle, center, half_width=35.0, soft=12.0):
        distance = np.abs((angle - center + 180) % 360 - 180)
        return np.clip((half_width + soft - distance) / soft, 0, 1)

    for top in range(0, height, 512):
        y0, y1 = max(0, top - halo), min(height, top + 512 + halo)
        rgb = rgb16[y0:y1].astype(np.float32) / 65535
        luma = rgb @ luma_weights
        edge = _dilate_max(contrast_across(luma), radius)
        where = np.clip((edge - .12) / .3, 0, 1)
        bright = _dilate_max(luma, radius + 1)
        where *= .35 + .65 * np.clip((bright - .55) / .35, 0, 1)
        rows, cols = np.nonzero(where > .01)  # 候補はエッジ周りだけ＝色相計算は疎に
        if not len(rows):
            continue
        pixels = rgb[rows, cols]
        a = pixels[:, 0] - pixels[:, 1]
        b = pixels[:, 2] - pixels[:, 1]
        angle = np.degrees(np.arctan2(b, a))  # 赤0°・マゼンタ45°・青90°・緑-135°
        weight = where[rows, cols] * (purple * hue_weight(angle, 55.0)
                                      + green * hue_weight(angle, -135.0))
        weight = np.clip(weight, 0, 1)[:, None]
        neutral = luma[rows, cols][:, None]
        fixed = neutral + (pixels - neutral) * (1 - weight)
        band = rgb16[y0:y1].copy()
        band[rows, cols] = np.clip(fixed * 65535 + .5, 0, 65535).astype(np.uint16)
        start, stop = top - y0, top - y0 + min(512, height - top)
        output[top:top + stop - start] = band[start:stop]
    return output


def render_linear(linear, settings, decode_gain=1.0, headroom=1.0,
                  reference_longest=None, maps=None, pivot=.5, dcp=None,
                  haze_gain=1.0):
    height, width = linear.shape[:2]
    output = np.empty((height, width, 3), dtype=np.uint16)
    for top in range(0, height, 256):
        chunk_maps = (None if maps is None else
                      {name: plane[top:top + 256] for name, plane in maps.items()})
        output[top:top + 256] = transform_chunk(
            linear[top:top + 256], settings, decode_gain, headroom,
            chunk_maps, pivot, dcp, haze_gain)
    output = apply_defringe(output, settings, reference_longest)  # シャープ系の前に縁の色を消す
    noise_map = None
    dehaze = number(settings, "dehaze") / 100
    if maps is not None and "veil" in maps and dehaze > 0:
        noise_map = 1 / np.maximum(.5, 1 - np.float32(dehaze * .7) * maps["veil"])
    return apply_detail(output, settings, reference_longest, noise_map)


def develop_linear_array(linear, settings, decode_gain=1.0, headroom=1.0,
                         dcp=None, item=None):
    linear, geometry = crop_linear(linear, settings)
    maps, pivot = render_setup(linear, settings, decode_gain, headroom, geometry,
                               0, 0, linear.shape[1], linear.shape[0])
    haze_gain = dehaze_gain(linear, settings, decode_gain, headroom, geometry)
    image = render_linear(linear, settings, decode_gain, headroom,
                          maps=maps, pivot=pivot, dcp=dcp, haze_gain=haze_gain)
    angle = int(number(settings, "angle", 360)) % 360
    if angle in {90, 180, 270}:
        image = np.rot90(image, {90: 3, 180: 2, 270: 1}[angle])
    image = apply_retouch(apply_masks(image, settings, item=item), settings)
    image = apply_content_fills(image, settings)
    image = apply_liquify(image, settings)
    image = apply_pixel_edits(image, settings)
    image = apply_grain(image, settings)
    return compose_image_layers(image, settings, item)


def develop_linear(linear, settings, decode_gain=1.0, headroom=1.0,
                   dcp=None, item=None):
    return image8_from_u16(develop_linear_array(
        linear, settings, decode_gain, headroom, dcp, item))


def prepare_item(item):
    if item.get("linear") and Path(item["linear"]).exists():
        return item
    folder = Path(item["dir"])
    linear_path = folder / "linear.npy"
    preview_linear_path = folder / "preview-linear.npy"
    linear, decode_gain = decode_linear(Path(item["source"]))
    headroom = max(1.0, float(np.max(linear)) / 65535 * decode_gain)
    np.save(linear_path, linear, allow_pickle=False)
    preview_linear = resize_linear(linear)
    np.save(preview_linear_path, preview_linear, allow_pickle=False)
    # サムネイル（ライブラリの小さい絵・開いた直後の絵）。RAWは標準カーブ付きで
    # 作り、既定の現像結果と明るさをそろえる
    raw = Path(item["source"]).suffix.lower() in RAW_EXTENSIONS
    preview = develop_linear(preview_linear, NEUTRAL, decode_gain, headroom,
                             dcp=KIT_STANDARD_PROFILE if raw else None)
    preview_path = folder / "preview.png"
    preview.save(preview_path, "PNG", icc_profile=SRGB_PROFILE)
    item.update({"linear": linear_path, "preview_linear": preview_linear_path,
                 "preview": preview_path, "width": linear.shape[1],
                 "height": linear.shape[0],
                 "gain": decode_gain, "headroom": headroom,
                 "focal": _source_focal(Path(item["source"])),
                 "model": camera_model(Path(item["source"])),
                 "fingerprint": item.get(
                     "fingerprint",
                     file_fingerprint(Path(item["source"]).read_bytes())),
                 "fingerprint_v2": item.get(
                     "fingerprint_v2",
                     file_fingerprint_v2(Path(item["source"]).read_bytes())),
                 "lock": item.get("lock", threading.Lock())})
    return item


def convert_preview(source, target):
    item = prepare_item({"source": Path(source), "dir": Path(target).parent})
    with Image.open(item["preview"]) as image:
        image.save(target, "PNG", icc_profile=SRGB_PROFILE)

def is_raw_item(item):
    return Path(item["source"]).suffix.lower() in RAW_EXTENSIONS


def item_dcp(item, settings):
    if not is_raw_item(item):
        return None  # JPEG/PNG/TIFFは現像済み。カメラプロファイルを重ねない
    return load_camera_profile(item.get("model", ""),
                               str(settings.get("cameraProfile", "") or ""))


def developed_array(item, settings, preview=False):
    prepare_item(item)
    linear = source_linear(item, settings, preview)
    return develop_linear_array(linear, settings, item.get("gain", 1.0),
                                item.get("headroom", 1.0), item_dcp(item, settings),
                                item)


def developed_image(item, settings, preview=False):
    return image8_from_u16(developed_array(item, settings, preview))


def developed_dimensions(item, settings):
    prepare_item(item)
    linear = np.load(item["linear"], mmap_mode="r", allow_pickle=False)
    height, width = crop_linear(linear, settings)[0].shape[:2]
    angle = int(number(settings, "angle", 360)) % 360
    return (height, width) if angle in {90, 270} else (width, height)


def _developed_tile_array(item, settings):
    prepare_item(item)
    linear = source_linear(item, settings, lazy=True)  # レンズ補正はtileの領域だけ計算
    cropped, geometry = crop_linear(linear, settings)
    source_height, source_width = cropped.shape[:2]
    angle = int(number(settings, "angle", 360)) % 360
    output_width, output_height = developed_dimensions(item, settings)
    viewport = settings.get("viewport", {})
    try:
        x = max(0, min(output_width - 1, int(viewport.get("x", 0))))
        y = max(0, min(output_height - 1, int(viewport.get("y", 0))))
        width = max(1, min(2048, int(viewport.get("width", 1024)), output_width - x))
        height = max(1, min(2048, int(viewport.get("height", 768)), output_height - y))
    except (TypeError, ValueError):
        raise ValueError("原寸表示の範囲が不正です") from None
    base_pad = min(96, max(32, round(max(output_width, output_height) / 125)))
    pad = max(base_pad, liquify_required_pad(
        settings, (output_width, output_height)))
    ex = max(0, x - pad)
    ey = max(0, y - pad)
    er = min(output_width, x + width + pad)
    eb = min(output_height, y + height + pad)
    ew, eh = er - ex, eb - ey
    if angle == 90:
        rows = slice(source_height - (ex + ew), source_height - ex)
        cols = slice(ey, ey + eh)
        rotation = Image.Transpose.ROTATE_270
    elif angle == 180:
        rows = slice(source_height - (ey + eh), source_height - ey)
        cols = slice(source_width - (ex + ew), source_width - ex)
        rotation = Image.Transpose.ROTATE_180
    elif angle == 270:
        rows = slice(ex, ex + ew)
        cols = slice(source_width - (ey + eh), source_width - ey)
        rotation = Image.Transpose.ROTATE_90
    else:
        rows = slice(ey, ey + eh)
        cols = slice(ex, ex + ew)
        rotation = None
    region = np.asarray(cropped[rows, cols])  # LazyLensならここで領域分だけ計算
    # 順応マップとpivotは書き出しと同じ「クロップ後全体」から作り、同じ領域を
    # 切り出す（tile内だけで作ると周辺文脈が変わり、100%表示と書き出しが一致しない）
    maps, pivot = render_setup(cropped, settings, item.get("gain", 1.0),
                               item.get("headroom", 1.0), geometry,
                               cols.start, rows.start, cols.stop, rows.stop)
    haze_gain = dehaze_gain(cropped, settings, item.get("gain", 1.0),
                            item.get("headroom", 1.0), geometry)
    image = render_linear(region, settings, item.get("gain", 1.0),
                          item.get("headroom", 1.0),
                          max(output_width, output_height), maps, pivot,
                          item_dcp(item, settings), haze_gain)
    if rotation:
        image = np.rot90(image, {Image.Transpose.ROTATE_270: 3,
                                 Image.Transpose.ROTATE_180: 2,
                                 Image.Transpose.ROTATE_90: 1}[rotation])
    # マスク→レタッチは拡張領域（pad込み）へ適用してから最終cropする。
    # レタッチのコピー元がtile外の時は、retouch抜き設定で該当領域を再現像する
    image = apply_masks(image, settings, (ex, ey),
                        (output_width, output_height), item)

    def fetch_region(x0, y0, x1, y1):
        if x0 < 0 or y0 < 0 or x1 > output_width or y1 > output_height:
            return None
        return _developed_tile_array(item, {
            **settings, "retouch": [], "contentFills": [], "liquifyEdits": [],
            "pixelEdits": [],
            "grain": 0, "imageLayers": [],
            "viewport": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}})

    image = apply_retouch(image, settings, (ex, ey),
                          (output_width, output_height), fetch_region)

    def fetch_content_region(x0, y0, x1, y1):
        if x0 < 0 or y0 < 0 or x1 > output_width or y1 > output_height:
            return None
        return _developed_tile_array(item, {
            **settings, "contentFills": [], "liquifyEdits": [], "pixelEdits": [],
            "grain": 0, "imageLayers": [],
            "viewport": {"x": x0, "y": y0, "width": x1-x0, "height": y1-y0}})

    image = apply_content_fills(image, settings, (ex, ey),
                                (output_width, output_height), fetch_content_region)
    image = apply_liquify(image, settings, (ex, ey),
                          (output_width, output_height))

    def fetch_pixel_region(x0,y0,x1,y1):
        if x0<0 or y0<0 or x1>output_width or y1>output_height: return None
        return _developed_tile_array(item,{**settings,"pixelEdits":[],"grain":0,"imageLayers":[],
            "viewport":{"x":x0,"y":y0,"width":x1-x0,"height":y1-y0}})

    image = apply_pixel_edits(image, settings, (ex,ey),
                              (output_width,output_height), fetch_pixel_region)
    image = apply_grain(image, settings, (ex, ey),
                        (output_width, output_height))
    image = compose_image_layers(image, settings, item, (ex, ey),
                                 (output_width, output_height))
    return image[y - ey:y - ey + height, x - ex:x - ex + width]


def developed_tile(item, settings):
    return image8_from_u16(_developed_tile_array(item, settings))


def pick_white_balance(item, settings, px, py):
    """WBスポイト。クリック点（クロップ後・回転前の正規化座標）の周辺9×9を
    平均し、そこが無彩色になるtemperature/tintを既存のwb_gainsモデルから解く。
    R/G比: 2^(t·Ct+ti·Cti)、B/G比: 2^(-t·Ct+ti·Cti)（t,tiは/100値、
    Ct=WB_TEMP_COEF、Cti=WB_TINT_RB_COEF+WB_TINT_G_COEF）。"""
    prepare_item(item)
    linear = source_linear(item, settings, preview=True)
    cropped, _ = crop_linear(linear, settings)
    height, width = cropped.shape[:2]
    cx = min(width - 1, max(0, round(float(px) * (width - 1))))
    cy = min(height - 1, max(0, round(float(py) * (height - 1))))
    window = cropped[max(0, cy - 4):cy + 5,
                     max(0, cx - 4):cx + 5].astype(np.float32)
    red, green, blue = np.mean(window.reshape(-1, 3), axis=0)
    if max(red, green, blue) > 63000:
        raise ValueError("白飛びの場所では測れません。中間調のグレーを選んでください")
    if min(red, green, blue) < 200:
        raise ValueError("暗すぎて測れません。中間調のグレーを選んでください")
    log_rg = float(np.log2(green / red))
    log_bg = float(np.log2(green / blue))
    tint_coef = WB_TINT_RB_COEF + WB_TINT_G_COEF
    temperature = (log_rg - log_bg) / (2 * WB_TEMP_COEF) * 100
    tint = (log_rg + log_bg) / (2 * tint_coef) * 100
    result = {"temperature": round(max(-100, min(100, temperature))),
              "tint": round(max(-100, min(100, tint)))}
    if abs(temperature) > 100 or abs(tint) > 100:
        result["note"] = "色の偏りが大きく、スライダーの端で止めました"
    return result


def apply_grain(image, settings, offset=(0, 0), full_size=None):
    """粒子（フィルムグレイン）。正規化座標のvalueノイズ（決定的hash）を
    輝度へ加える。ノイズ場は出力座標の0〜1で定義するので、preview/tile/
    書き出しが同じ模様を見る＝tile一致は自動。ハイライトは半分に保護。"""
    amount = positive_number(settings, "grain", 0)
    if not amount:
        return image
    full_size = full_size or (image.shape[1], image.shape[0])
    width, height = full_size
    left, top = offset
    rgb = image.astype(np.float32)
    rows, cols = rgb.shape[:2]
    cells = 2400.0  # 長辺7360で約3px粒
    us = (np.arange(left, left + cols, dtype=np.float64) / width) * cells
    vs = (np.arange(top, top + rows, dtype=np.float64) / height
          ) * cells * height / width
    gu, gv = np.floor(us), np.floor(vs)
    fu, fv = (us - gu)[None, :], (vs - gv)[:, None]

    def lattice(iu, iv):
        v = np.sin(iu[None, :] * 12.9898 + iv[:, None] * 78.233) * 43758.5453
        return (v - np.floor(v)).astype(np.float32)

    noise = (lattice(gu, gv) * (1 - fu) * (1 - fv)
             + lattice(gu + 1, gv) * fu * (1 - fv)
             + lattice(gu, gv + 1) * (1 - fu) * fv
             + lattice(gu + 1, gv + 1) * fu * fv)
    luminance = np.clip(rgb @ GRADE_LUMA / 65535, 0, 1)
    protection = 1 - luminance ** 2 * .5
    rgb += ((noise - .5) * np.float32(amount / 100 * 18 * 257)
            * protection)[:, :, None]
    return np.clip(rgb + .5, 0, 65535).astype(np.uint16)


IMAGES_DIR = ROOT / "images"
RECIPE_DIR = IMAGES_DIR / "recipes"
LAYER_ASSET_DIR = IMAGES_DIR / "assets"
LAYER_ASSET_RE = re.compile(r"^[0-9a-f]{64}$")
_LAYER_CACHE = {}
_LAYER_CACHE_LOCK = threading.Lock()


def recipe_path(item):
    return RECIPE_DIR / f"{item['fingerprint_v2']}.json"


def legacy_recipe_path(item):
    stem = re.sub(r"[^\w.-]+", "_", Path(item.get("name", "picture")).stem)
    return IMAGES_DIR / f"{stem}-{item['fingerprint']}.json"


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_bytes(data)
    temp.replace(path)


def clean_keywords(value):
    """キーワードを整える: 文字列へ・前後空白を落とす・空と重複を除く・各40字/最大24件。"""
    if not isinstance(value, (list, tuple)):
        return []
    out, seen = [], set()
    for entry in value:
        text = str(entry).strip()[:40]
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
        if len(out) >= 24:
            break
    return out


def save_recipe(item, settings):
    if settings.get("transient") or "fingerprint_v2" not in item:
        return
    payload = {key: value for key, value in settings.items()
               if key not in ("token", "viewport", "transient")}
    payload.update({"pictureKit": 2, "pipeline": "libraw-linear-v1"})
    if "rating" in payload:  # ライブラリの星（0〜5）。非破壊でrecipeに同居させる
        try:
            payload["rating"] = max(0, min(5, int(round(float(payload["rating"])))))
        except (TypeError, ValueError):
            payload["rating"] = 0
    if "keywords" in payload:
        payload["keywords"] = clean_keywords(payload.get("keywords"))
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    with _RECIPES_LOCK:
        atomic_write(recipe_path(item), encoded)


def migrate_recipe(data):
    """旧recipe（wbModel無し）の色温度・Tintを現在のWB係数へ換算する。
    マスク内のadjustも同じ。換算後はwbModelを付けて二重換算を防ぐ。"""
    if not isinstance(data, dict):
        return data
    try:
        model = int(data.get("wbModel", 1) or 1)
    except (TypeError, ValueError):
        model = 1
    if model >= WB_MODEL:
        return data

    def convert(holder):
        if not isinstance(holder, dict):
            return
        for key, scale in (("temperature", WB_TEMP_SCALE_FROM_V1),
                           ("tint", WB_TINT_SCALE_FROM_V1)):
            try:
                value = float(holder.get(key, 0) or 0)
            except (TypeError, ValueError):
                continue
            if value:
                holder[key] = round(value * scale)

    convert(data)
    for mask in data.get("masks") or []:
        if isinstance(mask, dict):
            convert(mask.get("adjust"))
    data["wbModel"] = WB_MODEL
    return data


def load_recipe(item):
    if "fingerprint_v2" not in item:
        return None
    target = recipe_path(item)
    source = target if target.exists() else legacy_recipe_path(item)
    if not source.exists():
        return None
    try:
        data = migrate_recipe(json.loads(source.read_text(encoding="utf-8")))
        if source != target:
            atomic_write(target, json.dumps(data, ensure_ascii=False).encode("utf-8"))
        return data
    except (OSError, ValueError):
        return None


EXPORT_PRESET_FORMATS = {"jpeg", "png", "tiff", "tiff16"}


def export_presets_path():
    # IMAGES_DIR はテストで差し替えるので、保存先は呼び出し時に解決する
    return IMAGES_DIR / "export-presets.json"


def sanitize_export_preset(entry):
    """書き出しpresetを正規化。不正な形式はjpeg、長辺/品質はkitの範囲へclamp。"""
    if not isinstance(entry, dict):
        return None
    name = str(entry.get("name", "")).strip()[:60]
    if not name:
        return None
    fmt = str(entry.get("format", "jpeg")).lower()
    if fmt not in EXPORT_PRESET_FORMATS:
        fmt = "jpeg"
    try:
        size = max(0, min(20000, int(round(float(entry.get("size", 0) or 0)))))
    except (TypeError, ValueError):
        size = 0
    try:
        quality = max(60, min(100, int(round(float(entry.get("quality", 92) or 92)))))
    except (TypeError, ValueError):
        quality = 92
    pattern = str(entry.get("namePattern", "{name}_developed")).strip()[:120] \
        or "{name}_developed"
    return {"name": name, "format": fmt, "size": size, "quality": quality,
            "sharpen": bool(entry.get("sharpen")), "srgb": True,  # kitは常にsRGB ICC
            "namePattern": pattern}


def _dedup_presets(raw):
    out, seen = [], set()
    for entry in (raw or [])[:50]:
        clean = sanitize_export_preset(entry)
        if clean and clean["name"] not in seen:
            seen.add(clean["name"])
            out.append(clean)
    return out


def load_export_presets():
    try:
        data = json.loads(export_presets_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    raw = data.get("presets") if isinstance(data, dict) else data
    return _dedup_presets(raw if isinstance(raw, list) else [])


def save_export_presets(presets):
    if not isinstance(presets, list):
        raise ValueError("presetsが不正です")
    out = _dedup_presets(presets)
    with _RECIPES_LOCK:
        atomic_write(export_presets_path(),
                     json.dumps({"presets": out}, ensure_ascii=False).encode("utf-8"))
    return out


def layer_asset_path(asset_id):
    if not isinstance(asset_id, str) or not LAYER_ASSET_RE.fullmatch(asset_id):
        raise ValueError("レイヤー素材IDが不正です")
    return LAYER_ASSET_DIR / f"{asset_id}.png"


def save_layer_asset(data, supplied_name):
    suffix = Path(supplied_name).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        raise ValueError("PNG / JPEG / TIFFを選んでください")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as opened:
                if opened.format not in {"PNG", "JPEG", "TIFF"} or getattr(opened, "n_frames", 1) != 1:
                    raise ValueError("単一ページのPNG / JPEG / TIFFだけ使えます")
                if not (1 <= opened.width <= 16_384 and 1 <= opened.height <= 16_384
                        and opened.width * opened.height <= 100_000_000):
                    raise ValueError("レイヤー画像が大きすぎます")
                image = ImageOps.exif_transpose(opened).convert("RGBA")
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("レイヤー画像を読み込めません") from error
    asset_id = hashlib.sha256(data).hexdigest()
    target = layer_asset_path(asset_id)
    if not target.exists():
        output = io.BytesIO()
        image.save(output, "PNG", compress_level=6)
        atomic_write(target, output.getvalue())
    with _LAYER_CACHE_LOCK:
        _LAYER_CACHE[asset_id] = image.copy()
    name = Path(supplied_name).name[:160] or "layer"
    return {"assetId": asset_id, "name": name,
            "width": image.width, "height": image.height}


def load_layer_asset(asset_id):
    path = layer_asset_path(asset_id)
    if not path.is_file():
        return None
    with _LAYER_CACHE_LOCK:
        cached = _LAYER_CACHE.get(asset_id)
        if cached is not None:
            return cached
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
    except OSError:
        return None
    with _LAYER_CACHE_LOCK:
        # 決定: cacheは16件で打ち切る（複製で生成したassetを無制限に抱えて36MP×n枚で落ちた）
        # 根拠=.kiro/steering/projects/picturekit.md
        if len(_LAYER_CACHE) >= 16:
            _LAYER_CACHE.pop(next(iter(_LAYER_CACHE)))
        _LAYER_CACHE[asset_id] = image
    return image


def store_layer_image(image, supplied_name="layer.png"):
    """生成画像をmetadataなしのcanonical PNGとしてcontent-addressed保存する。"""
    image = image.convert("RGBA")
    if not (1 <= image.width <= 16_384 and 1 <= image.height <= 16_384
            and image.width * image.height <= 100_000_000):
        raise ValueError("レイヤー画像が大きすぎます")
    output = io.BytesIO(); image.save(output, "PNG", compress_level=6)
    data = output.getvalue(); asset_id = hashlib.sha256(data).hexdigest()
    target = layer_asset_path(asset_id)
    if not target.exists():
        atomic_write(target, data)
    with _LAYER_CACHE_LOCK:
        if len(_LAYER_CACHE)>=16 and asset_id not in _LAYER_CACHE:
            _LAYER_CACHE.pop(next(iter(_LAYER_CACHE)))
        _LAYER_CACHE[asset_id] = image.copy()
    return {"assetId": asset_id, "name": Path(supplied_name).name[:160] or "layer",
            "width": image.width, "height": image.height}


def import_psd_layers(data):
    """PSDのレイヤーを imageLayers に積める形へ変換する（psd_import.py が本体）。
    🚫 psd-tools は任意インストール。無い環境でPictureKit全体が起動しなくなるのを避けるため
       ここで遅延importして、無ければ導入方法を返す。"""
    if len(data) > 400_000_000:
        raise ValueError("PSDが大きすぎます")
    try:
        from psd_import import import_psd
    except ImportError as error:
        raise ValueError("PSD読み込みには psd-tools が必要です"
                         "（PictureKit/.venv/bin/pip install psd-tools）") from error
    try:
        return import_psd(data, store_layer_image)
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"PSDを読み込めません（{error}）") from error
def blank_layer_asset(item, settings):
    width, height = developed_dimensions(item, settings)
    if width * height > 100_000_000 or max(width, height) > 16_384:
        raise ValueError("空レイヤーが大きすぎます")
    meta = store_layer_image(Image.new("RGBA", (2, 2), (0, 0, 0, 0)),
                             "空の描画レイヤー")
    return {**meta, "width": width, "height": height,
            "aspect": width / max(1, height)}


BLEND_MODES = {"normal", "multiply", "screen", "overlay", "darken", "lighten", "difference"}


def normalized_layer_paint(raw, budget):
    if not isinstance(raw, list):
        return [], 0
    strokes, used = [], 0
    for entry in raw[:128]:
        if not isinstance(entry, dict) or used >= budget:
            continue
        mode = str(entry.get("mode", ""))
        if mode not in {"paint", "erase"}:
            continue
        points = []
        source = entry.get("points") if isinstance(entry.get("points"), list) else []
        for point in source[:min(1024, budget-used)]:
            try:
                x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError, IndexError, KeyError):
                continue
            if np.isfinite(x) and np.isfinite(y):
                points.append((min(1, max(0, x)), min(1, max(0, y))))
        if not points:
            continue
        try:
            size = float(entry.get("size", .03)); hardness = float(entry.get("hardness", .7))
            opacity = float(entry.get("opacity", 1))
        except (TypeError, ValueError):
            continue
        if not all(np.isfinite(v) for v in (size, hardness, opacity)):
            continue
        stroke = {"mode": mode, "points": points, "size": max(.002, min(.3, size)),
                  "hardness": max(0, min(1, hardness)), "opacity": max(0, min(1, opacity))}
        if mode == "paint":
            color = str(entry.get("color", ""))
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                continue
            stroke["color"] = color.lower()
        strokes.append(stroke); used += len(points)
    return strokes, used


def layer_paint_digest(strokes):
    if not strokes:
        return "none"
    return hashlib.sha256(json.dumps(strokes, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()[:16]


def _layer_stroke_region(stroke, size):
    width, height = size; longest = max(width, height)
    diameter = max(1, round(stroke["size"] * longest)); radius = diameter / 2
    softness = (1-stroke["hardness"]) * diameter * .35
    coords = [(round(x*(width-1)), round(y*(height-1))) for x, y in stroke["points"]]
    margin = int(np.ceil(radius + softness*3 + 2))
    x0=max(0,min(x for x,_ in coords)-margin); y0=max(0,min(y for _,y in coords)-margin)
    x1=min(width,max(x for x,_ in coords)+margin+1); y1=min(height,max(y for _,y in coords)+margin+1)
    mask=Image.new("L",(x1-x0,y1-y0),0);draw=ImageDraw.Draw(mask)
    local=[(x-x0,y-y0) for x,y in coords]
    if len(local)>1: draw.line(local,fill=255,width=diameter,joint="curve")
    for x,y in (local[0],local[-1]): draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=255)
    if softness>.25: mask=mask.filter(ImageFilter.GaussianBlur(softness))
    return (x0,y0,x1,y1),np.asarray(mask,dtype=np.float32)/255*stroke["opacity"]


def apply_layer_paint(image, strokes):
    image=image.convert("RGBA")
    for stroke in strokes:
        box,alpha=_layer_stroke_region(stroke,image.size)
        pixels=np.asarray(image.crop(box),dtype=np.float32)/255
        if stroke["mode"]=="erase":
            pixels[:,:,3]*=1-alpha
        else:
            src=np.array([int(stroke["color"][i:i+2],16) for i in (1,3,5)],dtype=np.float32)/255
            sa=alpha;da=pixels[:,:,3];out_a=sa+da*(1-sa)
            premul=src[None,None,:]*sa[:,:,None]+pixels[:,:,:3]*da[:,:,None]*(1-sa[:,:,None])
            pixels[:,:,:3]=premul/np.maximum(out_a[:,:,None],1e-7);pixels[:,:,3]=out_a
        image.paste(Image.fromarray(np.clip(pixels*255+.5,0,255).astype(np.uint8),"RGBA"),box)
    return image


def normalized_bezier_path(raw, limit=200):
    """ベジェパス（mnode列）を検証する。アンカーとハンドルを0〜1に収める。
    3点未満は形にならないので None。"""
    if not isinstance(raw, list):
        return None
    path = []
    for entry in raw[:limit]:
        if not isinstance(entry, dict):
            continue
        try:
            values = [float(entry.get(key, entry.get(key[0], 0)))
                      for key in ("x", "y", "inX", "inY", "outX", "outY")]
        except (TypeError, ValueError):
            continue
        if not all(np.isfinite(v) for v in values):
            continue
        x, y, in_x, in_y, out_x, out_y = (min(1.0, max(0.0, v)) for v in values)
        path.append({"x": x, "y": y, "inX": in_x, "inY": in_y,
                     "outX": out_x, "outY": out_y})
    return path if len(path) >= 3 else None


def normalized_layer_mask(raw, budget):
    if not isinstance(raw, dict):
        return None, 0
    shape = mask_shape({"mode": "brush", "strokes": raw.get("strokes", [])})
    strokes, used = [], 0
    for stroke in (shape["strokes"] if shape else []):
        if used >= budget:
            break
        points = stroke["points"][:budget - used]
        if points:
            strokes.append({**stroke, "points": points}); used += len(points)
    # パスだけ・ブラシだけ・両方・どちらも無し、のどれでも成立させる。
    # 🚫 空（path も strokes も無い）を None にすると、invert だけのマスク＝
    #    「全面を隠す」が効かなくなる（check_image_layers の inverted で落ちた）
    path = normalized_bezier_path(raw.get("path"))
    if path:
        used += len(path)
    return {"enabled": raw.get("enabled") is not False,
            "invert": bool(raw.get("invert")), "strokes": strokes,
            "path": path,
            "pathFeather": min(100.0, positive_number(raw, "pathFeather", 0))}, used


def bezier_fill_plane(path, size, feather=0):
    """ベジェパス（mnode列）を size のグレースケール重み面に塗る。
    🔑 aggdraw でベジェを直接塗る＝多角形近似より境界がなめらか（切り抜きの縁に効く）。
    aggdraw が無い環境では flattenPath 相当の多角形で代替する。"""
    width, height = size
    image = Image.new("L", size, 0)
    try:
        import aggdraw
        draw = aggdraw.Draw(image)
        outline = aggdraw.Path()
        first = path[0]
        outline.moveto(first["x"] * (width - 1), first["y"] * (height - 1))
        for index, a in enumerate(path):
            b = path[(index + 1) % len(path)]
            if (a["outX"] == a["x"] and a["outY"] == a["y"]
                    and b["inX"] == b["x"] and b["inY"] == b["y"]):
                outline.lineto(b["x"] * (width - 1), b["y"] * (height - 1))
            else:
                outline.curveto(a["outX"] * (width - 1), a["outY"] * (height - 1),
                                b["inX"] * (width - 1), b["inY"] * (height - 1),
                                b["x"] * (width - 1), b["y"] * (height - 1))
        outline.close()
        draw.path(outline, aggdraw.Brush(255))
        draw.flush()
    except ImportError:
        points = [(n["x"] * (width - 1), n["y"] * (height - 1)) for n in path]
        if len(points) >= 3:
            ImageDraw.Draw(image).polygon(points, fill=255)
    if feather > 0:
        image = image.filter(ImageFilter.GaussianBlur(
            feather / 100 * max(width, height) * .05))
    return np.asarray(image, dtype=np.float32) / 255


def layer_mask_image(mask, size):
    if not mask or not mask["enabled"]:
        return None
    width, height = size
    # 🔑 パスがあればそれを土台にする（内側=表示）。無ければ全面表示から始めて
    #    ブラシで削る従来の挙動。パスとブラシは併用できる
    #    ＝大枠をパスで取って、はみ出しをブラシの消しゴムで詰める（2026-08-21 利用者要望）
    path = mask.get("path")
    if path and len(path) >= 3:
        weight = bezier_fill_plane(path, size, mask.get("pathFeather", 0))
    else:
        weight = np.ones((height, width), dtype=np.float32)
    longest = max(width, height)
    for stroke in mask["strokes"]:
        diameter = max(1, round(stroke["size"] * longest))
        coords = [(round(x * (width - 1)), round(y * (height - 1)))
                  for x, y in stroke["points"]]
        layer = Image.new("L", size, 0); draw = ImageDraw.Draw(layer)
        if len(coords) > 1: draw.line(coords, fill=255, width=diameter, joint="curve")
        radius = diameter / 2
        for x, y in (coords[0], coords[-1]):
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=255)
        softness = (1 - stroke["hardness"]) * diameter * .35
        if softness > .25: layer = layer.filter(ImageFilter.GaussianBlur(softness))
        alpha = np.asarray(layer, dtype=np.float32) / 255 * stroke["opacity"]
        weight = weight * (1-alpha) if stroke["erase"] else weight + (1-weight) * alpha
    if mask["invert"]: weight = 1-weight
    return Image.fromarray(np.clip(weight*255+.5, 0, 255).astype(np.uint8), "L")


def layer_mask_digest(mask):
    if not mask or not mask["enabled"]: return "off"
    return hashlib.sha256(json.dumps(mask, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def blend_layer_rgb(base, source, mode):
    if mode == "multiply": return base * source
    if mode == "screen": return base + source - base * source
    if mode == "overlay": return np.where(base <= .5, 2*base*source, 1-2*(1-base)*(1-source))
    if mode == "darken": return np.minimum(base, source)
    if mode == "lighten": return np.maximum(base, source)
    if mode == "difference": return np.abs(base-source)
    return source


def image_layer_settings(settings):
    raw = settings.get("imageLayers")
    if not isinstance(raw, list): return []
    result, ids, layer_points = [], set(), 0
    for entry in raw[:64]:
        if not isinstance(entry, dict): continue
        layer_id, asset_id = str(entry.get("id", "")), str(entry.get("assetId", ""))
        if (not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", layer_id)
                or layer_id in ids or not LAYER_ASSET_RE.fullmatch(asset_id)): continue
        try:
            x, y = float(entry.get("x", .5)), float(entry.get("y", .5))
            width, rotation = float(entry.get("width", .5)), float(entry.get("rotation", 0))
            opacity = float(entry.get("opacity", 1)); aspect = float(entry.get("aspect", 0) or 0)
        except (TypeError, ValueError): continue
        if not all(np.isfinite(v) for v in (x, y, width, rotation, opacity, aspect)): continue
        ids.add(layer_id)
        paint, used = normalized_layer_paint(entry.get("paintStrokes", []), max(0,12000-layer_points))
        layer_points += used
        mask, used = normalized_layer_mask(entry.get("mask"), max(0,12000-layer_points))
        layer_points += used
        mode = str(entry.get("blendMode", "normal")).lower()
        result.append({"id":layer_id,"assetId":asset_id,"name":str(entry.get("name","layer"))[:160],
            "visible":entry.get("visible") is not False,"x":max(-1,min(2,x)),"y":max(-1,min(2,y)),
            "width":max(.01,min(1,width)),"rotation":max(-3600,min(3600,rotation)),
            "opacity":max(0,min(1,opacity)),"blendMode":mode if mode in BLEND_MODES else "normal",
            "aspect":max(.01,min(100,aspect)) if aspect>0 else 0,
            "paintStrokes":paint,"mask":mask})
    return result


def layer_target_size(layer, source, full_size):
    target_w=max(1,round(layer["width"]*full_size[0]))
    aspect=layer.get("aspect") or source.width/max(1,source.height)
    target_h=max(1,round(target_w/aspect))
    if target_w*target_h>100_000_000: raise ValueError("変形後のレイヤーが大きすぎます")
    return target_w,target_h


def render_layer_local(layer, full_size):
    source=load_layer_asset(layer["assetId"])
    if source is None: return None
    size=layer_target_size(layer,source,full_size)
    image=source.resize(size,Image.Resampling.LANCZOS)
    image=apply_layer_paint(image,layer.get("paintStrokes",[]))
    local_mask=layer_mask_image(layer.get("mask"),size)
    if local_mask is not None:
        alpha=np.asarray(image.getchannel("A"),dtype=np.float32)
        alpha*=np.asarray(local_mask,dtype=np.float32)/255
        image.putalpha(Image.fromarray(np.clip(alpha+.5,0,255).astype(np.uint8),"L"))
    return image


def transformed_layer(item, layer, full_size):
    source=load_layer_asset(layer["assetId"])
    if source is None: return None
    target_w,target_h=layer_target_size(layer,source,full_size)
    rotation=layer["rotation"]%360
    key=(layer["assetId"],target_w,target_h,round(rotation,3),
         layer_paint_digest(layer.get("paintStrokes")),layer_mask_digest(layer.get("mask")))
    cache=item.setdefault("layer_transform_cache",{}) if item is not None else {}
    if key in cache: return cache[key]
    image=render_layer_local(layer,full_size)
    if abs(rotation)>.001: image=image.rotate(-rotation,Image.Resampling.BICUBIC,expand=True)
    if image.width*image.height>120_000_000: raise ValueError("回転後のレイヤーが大きすぎます")
    if item is not None:
        if len(cache)>=8: cache.pop(next(iter(cache)))
        cache[key]=image
    return image


def copy_layer_selection(item, settings):
    if len(json.dumps(settings))>500_000: raise ValueError("レイヤー設定が大きすぎます")
    layer_id=str(settings.get("layerId",""));layers=image_layer_settings(settings)
    layer=next((value for value in layers if value["id"]==layer_id),None)
    if layer is None: raise ValueError("コピー元レイヤーが見つかりません")
    rect=settings.get("rect")
    try: values=[float(rect[key]) for key in ("x0","y0","x1","y1")]
    except (TypeError,ValueError,KeyError): raise ValueError("コピー範囲が不正です") from None
    if not all(np.isfinite(v) for v in values): raise ValueError("コピー範囲が不正です")
    x0,y0,x1,y1=values;x0,x1=sorted((max(0,min(1,x0)),max(0,min(1,x1))))
    y0,y1=sorted((max(0,min(1,y0)),max(0,min(1,y1))))
    if x1-x0<.002 or y1-y0<.002: raise ValueError("コピー範囲が小さすぎます")
    full_size=developed_dimensions(item,settings);local=render_layer_local(layer,full_size)
    if local is None: raise ValueError("コピー元レイヤーを読めません")
    left=int(np.floor(x0*local.width));top=int(np.floor(y0*local.height))
    right=int(np.ceil(x1*local.width));bottom=int(np.ceil(y1*local.height))
    crop=local.crop((left,top,right,bottom));meta=store_layer_image(crop,f"{layer['name']} のコピー")
    cx,cy=(x0+x1)/2,(y0+y1)/2;dx=(cx-.5)*local.width;dy=(cy-.5)*local.height
    angle=np.deg2rad(layer["rotation"]);rx=np.cos(angle)*dx-np.sin(angle)*dy
    ry=np.sin(angle)*dx+np.cos(angle)*dy
    return {**meta,"x":layer["x"]+rx/full_size[0],"y":layer["y"]+ry/full_size[1],
            "layerWidth":layer["width"]*(x1-x0),"rotation":layer["rotation"],
            "opacity":layer["opacity"],"blendMode":layer["blendMode"],
            "aspect":crop.width/max(1,crop.height)}


def compose_image_layers(base, settings, item=None, offset=(0, 0), full_size=None):
    layers = image_layer_settings(settings)
    if not layers or item is None:
        return base
    full_size = full_size or (base.shape[1], base.shape[0])
    full_w, full_h = full_size
    ox, oy = offset
    out = base.copy()
    for layer in layers:
        if not layer["visible"] or layer["opacity"] <= 0:
            continue
        image = transformed_layer(item, layer, full_size)
        if image is None:
            continue
        left = round(layer["x"] * full_w - image.width / 2)
        top = round(layer["y"] * full_h - image.height / 2)
        x0, y0 = max(ox, left), max(oy, top)
        x1 = min(ox + out.shape[1], left + image.width)
        y1 = min(oy + out.shape[0], top + image.height)
        if x0 >= x1 or y0 >= y1:
            continue
        crop = image.crop((x0 - left, y0 - top, x1 - left, y1 - top))
        source = np.asarray(crop, dtype=np.float32) / 255
        dest = out[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
        for row in range(0, source.shape[0], 256):
            src = source[row:row + 256]
            alpha = src[:, :, 3:4] * np.float32(layer["opacity"])
            if not np.any(alpha > 0):
                continue
            dst = dest[row:row + 256].astype(np.float32) / 65535
            src_linear = np.where(src[:, :, :3] <= .04045,
                src[:, :, :3] / 12.92, ((src[:, :, :3] + .055) / 1.055) ** 2.4)
            dst_linear = np.where(dst <= .04045, dst / 12.92,
                ((dst + .055) / 1.055) ** 2.4)
            blended = blend_layer_rgb(dst_linear, src_linear, layer["blendMode"])
            mixed = blended * alpha + dst_linear * (1 - alpha)
            dest[row:row + 256] = np.clip(srgb_encode(mixed) * 65535 + .5,
                                             0, 65535).astype(np.uint16)
    return out


AUTO_KEEP = ("cameraProfile", "lensProfile", "lensAmount", "cropAspect",
             "cropX", "cropY", "angle", "straighten", "colorNoise")


def auto_settings(item, settings):
    """ヒストグラム駆動の自動補正。プロファイル・レンズ補正・切り抜きは維持し、
    ライト系スライダーを写真ごとに解く。2パス:
    1) ベース画の中央値から露出を決定
    2) 露出込みの実ヒストグラムからハイライト回収・シャドウ・白黒・コントラスト"""
    base = {key: settings.get(key) for key in AUTO_KEEP if key in settings}

    def luminance_of(render_settings):
        image = developed_image(item, render_settings, preview=True)
        return np.asarray(image, dtype=np.float32) @ np.array(
            [.2126, .7152, .0722], dtype=np.float32)

    def clamp(value, low, high):
        return int(round(max(low, min(high, value))))

    median = float(np.median(luminance_of(base)))
    exposure = round(max(-2.0, min(2.0,
                                   float(np.log2(118 / max(median, 1))))), 1)

    lum = luminance_of({**base, "exposure": exposure})
    p1, p5, p50, p95, p99 = (float(v) for v in
                             np.percentile(lum, [1, 5, 50, 95, 99]))
    blown = float(np.mean(lum >= 250))
    result = {"exposure": exposure, "highlights": 0, "shadows": 0,
              "whites": 0, "blacks": 0, "contrast": 0}
    if p99 > 225 or blown > .002:
        # 白飛び・上端の詰まり具合に応じて回収
        result["highlights"] = -clamp((p99 - 225) * 1.8 + blown * 900, 10, 80)
    elif p99 < 230:
        result["whites"] = clamp((232 - p99) * .7, 0, 35)  # 白側の余白を詰める
    if p5 < 28:
        result["shadows"] = clamp((28 - p5) * 1.8, 0, 65)
    if p1 < 4:
        result["blacks"] = clamp((6 - p1) * 3, 0, 25)  # 黒潰れを少し開く
    elif p1 > 18:
        result["blacks"] = -clamp((p1 - 18) * 1.2, 0, 25)  # 黒を締める
    spread = p95 - p5
    if spread < 205:
        result["contrast"] = clamp((205 - spread) * .35, 0, 30)
    return result


def _source_exif(item):
    """元RAW/JPEGの撮影情報を書き出しへ引き継ぐ（LRと同じ挙動）。
    makernote等の巨大ブロックはJPEGの64KB上限を超えるため、主要タグだけの
    最小EXIF（Image.Exif）を組み立てる。無ければNone。"""
    try:
        with Image.open(item["source"]) as opened:
            source = opened.getexif()
            source_ifd = source.get_ifd(34665)
        exif = Image.Exif()
        for tag in (271, 272, 306, 315, 33432):  # Make/Model/日時/作者/著作権
            if tag in source:
                exif[tag] = source[tag]
        ifd = exif.get_ifd(34665)
        for tag in (33434, 33437, 34855, 36867, 36868, 37386, 41989, 42036):
            if tag in source_ifd:  # 露出時間/F値/ISO/撮影日時/焦点距離/レンズ
                ifd[tag] = source_ifd[tag]
        return exif if len(exif) or len(ifd) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _source_exif_bytes(item):
    exif = _source_exif(item)
    if exif is None:
        return None
    try:
        return exif.tobytes()
    except (ValueError, TypeError, struct.error):
        return None


def _tiff_tag_entry(tag, value):
    """EXIF値をTIFFタグ(型, 個数, 生バイト列)へ。対応外の型はNone。"""
    if isinstance(value, str):
        data = value.encode("utf-8", "replace") + b"\0"
        return tag, 2, len(data), data
    if isinstance(value, bytes):
        return tag, 7, len(value), value
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int):
        if 0 <= value < 65536:
            return tag, 3, 1, struct.pack("<H", value)
        if 0 <= value < 2 ** 32:
            return tag, 4, 1, struct.pack("<I", value)
        return None
    numerator = denominator = None
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        numerator, denominator = int(value.numerator), int(value.denominator)
    elif isinstance(value, tuple) and len(value) == 2:
        numerator, denominator = int(value[0]), int(value[1])
    elif isinstance(value, float):
        from fractions import Fraction
        fraction = Fraction(value).limit_denominator(1_000_000)
        numerator, denominator = fraction.numerator, fraction.denominator
    if numerator is None or denominator == 0:
        return None
    if numerator < 0 or denominator < 0:
        return tag, 10, 1, struct.pack("<ii", numerator, denominator)
    return tag, 5, 1, struct.pack("<II", numerator, denominator)


def tiff_with_exif(data, exif):
    """TIFFバイト列に撮影情報（IFD0の基本タグ＋Exif IFD）を足す。
    PillowはlibtiffでExifIFDを書けず、tifffileにもExif IFDのAPIが無いため、
    Exif IFDをファイル末尾に追記し、IFD0をタグ追加のうえ末尾へ複製してヘッダの
    参照先を差し替える（既存entryの絶対オフセットはそのまま有効）。
    classic TIFF・little endianだけ対象。それ以外や失敗時は元のまま返す。"""
    if exif is None or len(data) < 8 or data[:4] != b"II*\0":
        return data
    try:
        ifd0 = struct.unpack_from("<I", data, 4)[0]
        count = struct.unpack_from("<H", data, ifd0)[0]
        old = [data[ifd0 + 2 + 12 * i:ifd0 + 14 + 12 * i] for i in range(count)]
        next_ifd = data[ifd0 + 2 + 12 * count:ifd0 + 6 + 12 * count]
        present = {struct.unpack_from("<H", entry)[0] for entry in old}
        out = bytearray(data)
        if len(out) % 2:
            out += b"\0"

        def append_ifd(entries, next_pointer=b"\0\0\0\0"):
            """entries: (tag, type, count, raw値) か (tag, None, None, 既存entry12byte)。"""
            start = len(out)
            total = len(entries)
            data_offset = start + 2 + 12 * total + 4
            body, tail = bytearray(struct.pack("<H", total)), bytearray()
            for tag, kind, number, raw in sorted(entries, key=lambda entry: entry[0]):
                if kind is None:
                    body += raw
                elif len(raw) <= 4:
                    body += struct.pack("<HHI", tag, kind, number) + raw.ljust(4, b"\0")
                else:
                    body += struct.pack("<HHII", tag, kind, number, data_offset + len(tail))
                    tail += raw
                    if len(tail) % 2:
                        tail += b"\0"
            body += next_pointer
            out.extend(body + tail)
            return start

        exif_items = [item for item in (_tiff_tag_entry(tag, value) for tag, value
                                         in exif.get_ifd(34665).items()) if item]
        extra = [item for item in (_tiff_tag_entry(tag, value) for tag, value
                                    in exif.items() if tag != 34665 and tag not in present)
                 if item]
        if exif_items and 34665 not in present:
            extra.append((34665, 4, 1, struct.pack("<I", append_ifd(exif_items))))
        if not extra:
            return data
        existing = [(struct.unpack_from("<H", entry)[0], None, None, entry) for entry in old]
        struct.pack_into("<I", out, 4, append_ifd(existing + extra, next_ifd))
        return bytes(out)
    except (struct.error, IndexError, ValueError, TypeError):
        return data


def resize_u16_rgb(rgb, size):
    channels = [np.asarray(Image.fromarray(rgb[:, :, channel]).resize(
        size, Image.Resampling.LANCZOS), dtype=np.uint16) for channel in range(3)]
    return np.stack(channels, axis=2)


def tiff16_bytes(rgb, exif=None):
    output = io.BytesIO()
    tifffile.imwrite(output, rgb, photometric="rgb", compression="deflate",
                     metadata=None, rowsperstrip=min(256, rgb.shape[0]),
                     extratags=[(34675, 7, len(SRGB_PROFILE), SRGB_PROFILE, False)])
    return tiff_with_exif(output.getvalue(), exif)


def adjusted_jpeg(item, settings):
    with item.setdefault("lock", threading.Lock()):
        rgb = developed_array(item, settings)
    size = int(positive_number(settings, "exportSize", 0, 20000))
    if size and max(rgb.shape[:2]) > size:
        scale = size / max(rgb.shape[:2])
        target = (max(1, round(rgb.shape[1] * scale)),
                  max(1, round(rgb.shape[0] * scale)))
        rgb = resize_u16_rgb(rgb, target)
    if settings.get("exportSharpen"):
        rgb = apply_8bit_guide(rgb, lambda image: image.filter(
            ImageFilter.UnsharpMask(radius=.6, percent=60, threshold=2)))
    fmt = str(settings.get("exportFormat", "")).lower()
    exif = _source_exif(item)  # 撮影情報は全形式へ引き継ぐ（PNG/TIFFも）
    if fmt == "tiff16":
        return tiff16_bytes(rgb, exif)
    image = image8_from_u16(rgb)
    output = io.BytesIO()
    exif_bytes = None
    if exif is not None:
        try:
            exif_bytes = exif.tobytes()
        except (ValueError, TypeError, struct.error):
            exif_bytes = None
    if fmt == "png":
        image.save(output, "PNG", icc_profile=SRGB_PROFILE,
                   **({"exif": exif_bytes} if exif_bytes else {}))
    elif fmt == "tiff":
        image.save(output, "TIFF", compression="tiff_lzw", icc_profile=SRGB_PROFILE)
        return tiff_with_exif(output.getvalue(), exif)
    else:
        quality = max(60, min(100, int(number(settings, "quality", 100) or 92)))
        image.save(output, "JPEG", quality=quality, subsampling=0,
                   icc_profile=SRGB_PROFILE,
                   **({"exif": exif_bytes} if exif_bytes else {}))
    return output.getvalue()


def screen_png(image):
    """画面表示用PNG。localhostなので圧縮率より速さ（compress_level 6→1で
    1400px previewの符号化 0.09秒→0.03秒。2026-11-02実測）。書き出しは別（adjusted_jpeg）。"""
    output = io.BytesIO()
    image.save(output, "PNG", icc_profile=SRGB_PROFILE, compress_level=1)
    return output.getvalue()


def adjusted_preview(item, settings):
    with item.setdefault("lock", threading.Lock()):
        image = developed_image(item, settings, preview=True)
    return screen_png(image)


def adjusted_tile(item, settings):
    with item.setdefault("lock", threading.Lock()):
        image = developed_tile(item, settings)
    return screen_png(image)


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_bytes(body, "application/json; charset=utf-8", status)

    def send_bytes(self, body, content_type, status=200, disposition=None,
                   extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if disposition:
            self.send_header("Content-Disposition", disposition)
        for name, value in (extra_headers or {}).items():
            self.send_header(name, str(value))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, content_type):
        try:
            body = Path(path).read_bytes()
        except OSError:
            return self.send_error(404)
        self.send_bytes(body, content_type)

    def validate_host(self):
        host = self.headers.get("Host", "").split(":", 1)[0].strip("[]")
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("localhost以外は受け付けません")

    def validate_origin(self):
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("localhost以外からの操作は受け付けません")

    def do_GET(self):
        try:
            self.validate_host()
        except ValueError:
            self.send_error(403)
            return
        route = urlparse(self.path).path
        if route == "/":
            return self.send_file(ROOT / "index.html", "text/html; charset=utf-8")
        if route == "/design-kit.css":
            # 共有のDesignKitがあればそれを、無い環境（単独配布）では同梱の控えを使う
            shared = ROOT.parent / "DesignKit" / "design-kit.css"
            return self.send_file(shared if shared.is_file() else ROOT / "design-kit.css",
                                  "text/css; charset=utf-8")
        if route == "/api/status":
            return self.send_json({"engine": "LibRaw 16bit linear + PictureKit Tone v3",
                                   "cameras": CAMERAS,
                                   "luts": lut_names(),
                                   "lenses": list(lens_profiles())})
        if route == "/api/export-presets":
            return self.send_json({"presets": load_export_presets()})
        if route.startswith("/api/preview/"):
            token = route.rsplit("/", 1)[-1]
            item = FILES.get(token)
            if item:
                return self.send_file(item["preview"], "image/png")
        if route.startswith("/api/layer-asset/"):
            asset_id = route.rsplit("/", 1)[-1]
            try:
                path = layer_asset_path(asset_id)
            except ValueError:
                return self.send_error(404)
            if path.is_file():
                return self.send_file(path, "image/png")
        self.send_error(404)

    def do_POST(self):
        route = urlparse(self.path)
        try:
            self.validate_host()
            self.validate_origin()
            if route.path == "/api/open":
                return self.open_image(parse_qs(route.query).get("name", ["image"])[0])
            if route.path == "/api/render-preview":
                return self.render_preview()
            if route.path == "/api/layer-asset":
                token = parse_qs(route.query).get("token", [""])[0]
                item = FILES.get(token)
                if not item:
                    raise ValueError("写真を開き直してください")
                name = parse_qs(route.query).get("name", ["layer.png"])[0]
                return self.send_json(save_layer_asset(self.read_body(), name))
            if route.path == "/api/psd-import":
                token = parse_qs(route.query).get("token", [""])[0]
                if not FILES.get(token):
                    raise ValueError("写真を開き直してください")
                name = parse_qs(route.query).get("name", ["layers.psd"])[0]
                if not name.lower().endswith(".psd"):
                    raise ValueError(".psdファイルを選んでください")
                return self.send_json(import_psd_layers(self.read_body()))
            if route.path == "/api/layer-blank":
                item, settings = self.read_settings()
                with item.setdefault("lock", threading.Lock()):
                    return self.send_json(blank_layer_asset(item, settings))
            if route.path == "/api/layer-copy":
                item, settings = self.read_settings()
                with item.setdefault("lock", threading.Lock()):
                    return self.send_json(copy_layer_selection(item, settings))
            if route.path == "/api/auto":
                item, settings = self.read_settings()
                with item.setdefault("lock", threading.Lock()):
                    return self.send_json(auto_settings(item, settings))
            if route.path == "/api/content-fill-plan":
                item, settings = self.read_settings()
                with item.setdefault("lock", threading.Lock()):
                    return self.send_json(plan_content_fill(item, settings))
            if route.path == "/api/heal-plan":
                item, settings = self.read_settings()
                with item.setdefault("lock", threading.Lock()):
                    return self.send_json(plan_heal_source(item, settings))
            if route.path == "/api/close":
                item, settings = self.read_settings()
                return self.send_json(close_item(str(settings.get("token", ""))))
            if route.path == "/api/recipe":
                item, settings = self.read_settings()
                recipe = settings.get("recipe")
                if (not isinstance(recipe, dict)
                        or len(json.dumps(recipe)) > 300_000):
                    raise ValueError("recipeが不正です")
                save_recipe(item, recipe)
                return self.send_json({"ok": True})
            if route.path == "/api/wb-pick":
                item, settings = self.read_settings()
                with item.setdefault("lock", threading.Lock()):
                    return self.send_json(pick_white_balance(
                        item, settings,
                        number(settings, "px", 1), number(settings, "py", 1)))
            if route.path == "/api/lut":
                name = Path(parse_qs(route.query).get(
                    "name", ["look.cube"])[0]).name
                if not name.lower().endswith(".cube"):
                    raise ValueError(".cubeファイルを選んでください")
                text = self.read_body().decode("utf-8", errors="replace")
                parse_cube(text)  # 保存前に検証（不正なら400で返す）
                LUT_DIR.mkdir(exist_ok=True)
                safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
                (LUT_DIR / safe).write_text(text, encoding="utf-8")
                return self.send_json({"luts": lut_names(), "saved": safe})
            if route.path == "/api/mask-overlay":
                item, settings = self.read_settings()
                with item.setdefault("lock", threading.Lock()):
                    return self.send_bytes(mask_overlay_png(item, settings),
                                           "image/png")
            if route.path == "/api/mask-outline":
                item, settings = self.read_settings()
                with item.setdefault("lock", threading.Lock()):
                    svg, count, points = mask_outline_svg(item, settings)
                    return self.send_json({"svg": svg, "paths": count,
                                           "points": points})
            if route.path == "/api/render-tile":
                return self.render_tile()
            if route.path == "/api/export":
                return self.export_image()
            if route.path == "/api/export-presets":
                body = json.loads(self.read_body().decode("utf-8"))
                presets = body.get("presets") if isinstance(body, dict) else body
                return self.send_json({"presets": save_export_presets(presets)})
            self.send_error(404)
        except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired,
                json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("空のファイルです（0バイト）。別のファイルを選んでください")
        if length > MAX_BYTES:
            raise ValueError(f"ファイルが大きすぎます（{length / 1048576:.0f}MB）。200MB以下にしてください")
        return self.rfile.read(length)

    def read_settings(self):
        settings = json.loads(self.read_body().decode("utf-8"))
        token = str(settings.get("token", ""))
        item = FILES.get(token)
        if not item:
            raise ValueError("写真を開き直してください")
        return item, settings

    def open_image(self, supplied_name):
        name = Path(supplied_name).name
        suffix = Path(name).suffix.lower()
        if suffix not in ALLOWED:
            raise ValueError("PEF / DNG / JPEG / PNG / TIFFを選んでください")
        token = uuid.uuid4().hex
        folder = WORK / token
        folder.mkdir()
        source = folder / ("original" + suffix)
        body = self.read_body()
        fingerprint = file_fingerprint(body)
        fingerprint_v2 = file_fingerprint_v2(body)
        source.write_bytes(body)
        item = prepare_item({"source": source, "dir": folder, "name": name,
                             "fingerprint": fingerprint,
                             "fingerprint_v2": fingerprint_v2})
        model = item.get("model", "")
        profile = match_camera(model)
        FILES[token] = item
        recipe = load_recipe(item)
        # プロファイルはRAWだけ（JPEG/PNGは現像済み）。同梱の標準を必ず最後に置く
        profiles = []
        if suffix in RAW_EXTENSIONS:
            profiles = list(camera_profiles(model))
            if KIT_STANDARD_PROFILE is not None:
                profiles.append(KIT_STANDARD)
        self.send_json({"token": token, "name": name, "model": model,
                        "camera": profile["name"] if profile else "",
                        "width": item["width"], "height": item["height"],
                        "profiles": profiles,
                        "openLenses": lensfun_lenses(model),
                        "info": _source_info(source),
                        "recipe": recipe if isinstance(recipe, dict) else None,
                        "pipeline": "libraw-linear-v1"})

    def render_preview(self):
        item, settings = self.read_settings()
        width, height = developed_dimensions(item, settings)
        self.send_bytes(adjusted_preview(item, settings), "image/png",
                        extra_headers={"X-Output-Width": width,
                                       "X-Output-Height": height})

    def render_tile(self):
        item, settings = self.read_settings()
        width, height = developed_dimensions(item, settings)
        self.send_bytes(adjusted_tile(item, settings), "image/png",
                        extra_headers={"X-Output-Width": width,
                                       "X-Output-Height": height})

    def export_image(self):
        item, settings = self.read_settings()
        try:
            body = adjusted_jpeg(item, settings)
        finally:
            gc.collect()  # フルサイズの中間配列（24MPで数百MB×数枚）を即返す
        fmt = str(settings.get("exportFormat", "")).lower()
        ext, mime = {"png": ("png", "image/png"),
                     "tiff": ("tif", "image/tiff"),
                     "tiff16": ("tif", "image/tiff")}.get(fmt, ("jpg", "image/jpeg"))
        original = Path(item["name"]).stem
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", original) or "picture"
        # ASCII名はfilename=、日本語などはfilename*=UTF-8''（RFC 5987）で両方渡す
        utf8_name = quote(f"{original}_developed.{ext}", safe="")
        self.send_bytes(body, mime, disposition=
                        f'attachment; filename="{stem}_developed.{ext}"; '
                        f"filename*=UTF-8''{utf8_name}")

    def log_message(self, fmt, *args):
        print(f"PictureKit: {fmt % args}")


def close_item(token):
    """開いた写真を閉じる: 現像cache（1枚175〜260MB）とFILESの項目を消す。"""
    item = FILES.pop(token, None)
    if item is None:
        raise ValueError("その写真はすでに閉じています")
    with item.setdefault("lock", threading.Lock()):
        folder = Path(item.get("dir", ""))
        if folder.is_dir() and WORK in folder.parents:
            shutil.rmtree(folder, ignore_errors=True)
        for key in ("linear", "preview_linear", "preview"):
            item.pop(key, None)
    gc.collect()
    return {"ok": True, "open": len(FILES)}


def cleanup_stale_sessions():
    """前回異常終了で残った session cache（picturekit-*）を消す。
    動いている別のPictureKitのものは owner.pid が生きているので残す。"""
    parent = Path(SESSION.name).parent
    for folder in parent.glob("picturekit-*"):
        if folder == WORK or not folder.is_dir():
            continue
        pid_file = folder / "owner.pid"
        try:
            pid = int(pid_file.read_text().strip()) if pid_file.exists() else 0
        except (OSError, ValueError):
            pid = 0
        alive = False
        if pid > 0:
            try:
                os.kill(pid, 0)
                alive = True
            except ProcessLookupError:
                alive = False
            except PermissionError:
                alive = True
        if not alive:
            shutil.rmtree(folder, ignore_errors=True)


def main():
    migrate_legacy_recipes()
    (WORK / "owner.pid").write_text(str(os.getpid()))
    cleanup_stale_sessions()

    def stop(*_):
        raise KeyboardInterrupt  # Terminalを閉じた(SIGHUP)・killされた(SIGTERM)時もcacheを消す
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, stop)
    server = None
    port = 8765
    for candidate in range(8765, 8785):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError as error:
            if error.errno != errno.EADDRINUSE:
                raise
    if server is None:
        raise RuntimeError("PictureKitで使えるport（8765〜8784）がありません")

    url = f"http://127.0.0.1:{port}"
    if port != 8765:
        print(f"8765は使用中のため、{port}を使います")
    print(f"PictureKit: {url}")
    print("終了: Control-C")
    threading.Timer(.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPictureKitを終了しました")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
