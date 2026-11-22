#!/usr/bin/env python3
"""PictureKit checks: LibRaw pipeline, image quality, API UI, optional full export."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])

import http.client
import importlib.util
import io
import json
import py_compile
import subprocess
import tempfile
import threading
import time

import numpy as np
from PIL import Image, ImageFilter
BASE = {"curve": [0, 64, 128, 192, 255], "cropAspect": "original", "quality": 100}


def load_picturekit():
    py_compile.compile(str(ROOT / "picturekit.py"), doraise=True)
    json.loads((ROOT / "cameras.json").read_text(encoding="utf-8"))
    required = {line.strip() for line in (ROOT / "requirements.txt").read_text().splitlines()}
    assert required == {"rawpy==0.27.0", "numpy==2.5.2", "Pillow==12.1.1",
                        "lensfunpy==1.18.0", "tifffile==2026.9.15"}
    spec = importlib.util.spec_from_file_location("picturekit_check", ROOT / "picturekit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.rawpy.__version__ == "0.27.0"
    assert module.np.__version__ == "2.5.2"
    return module


def make_item(source):
    work = Path(tempfile.mkdtemp(prefix="picturekit-check-"))
    return {"source": source, "dir": work, "name": source.name}


def developed(module, source, settings):
    body = module.adjusted_jpeg(make_item(source), {**BASE, **settings})
    return Image.open(io.BytesIO(body)).convert("RGB")

def check_channel_curves(module):
    """チャンネル別多点トーンカーブ: Rカーブを下げるとRだけ動き、
    輝度カーブは全体を持ち上げ、恒等カーブは完全no-op。"""
    work = Path(tempfile.mkdtemp(prefix="picturekit-curve-"))
    source = work / "curve.png"
    Image.new("RGB", (64, 64), (120, 120, 120)).save(source)
    # JPEG往復の±1とカラーNRのYCbCr往復の±2を混ぜない（カーブだけを測る）
    png = {"exportFormat": "png", "colorNoise": 0, "luminanceNoise": 0}
    base = np.asarray(developed(module, source, png), dtype=np.float32)
    red_down = np.asarray(developed(module, source, {**png, "curves": {
        "r": [[0, 0], [128, 64], [255, 255]]}}), dtype=np.float32)
    dr = float(np.mean(base[:, :, 0] - red_down[:, :, 0]))
    dg = float(np.mean(np.abs(base[:, :, 1] - red_down[:, :, 1])))
    db = float(np.mean(np.abs(base[:, :, 2] - red_down[:, :, 2])))
    assert dr > 15, f"R curve has no effect: {dr:.1f}"
    # G/Bの±2は常時ONのcapture sharpen（YCbCr 8bit往復）の量子化で、
    # カーブの漏れではない（漏れなら二桁出る）。実測: G 0.00 / B 2.00
    assert dg < 3 and db < 3, f"R curve leaked: G {dg:.2f} B {db:.2f}"
    lifted = np.asarray(developed(module, source, {**png, "curves": {
        "lum": [[0, 0], [96, 160], [255, 255]]}}), dtype=np.float32)
    lift = float(np.mean(lifted) - np.mean(base))
    assert lift > 10, f"lum curve has no effect: {lift:.1f}"
    noop = np.asarray(developed(module, source, {**png, "curves": {
        "lum": [[0, 0], [255, 255]],
        "r": [[0, 0], [128, 128], [255, 255]]}}), dtype=np.float32)
    assert float(np.mean(np.abs(noop - base))) < .5, \
        "identity curves changed the image"
    print(f"CURVES_OK R -{dr:.0f} (leak {max(dg, db):.2f}), lum +{lift:.0f}")


RED_ZERO_CUBE = "LUT_3D_SIZE 2\n" + "\n".join(
    f"0 {g} {b}" for b in (0, 1) for g in (0, 1) for _ in (0, 1))


def check_lut(module):
    """.cube LUT: 適用でRが消えるテストLUT・適用量blend・無いLUTは黙ってskip。"""
    work = Path(tempfile.mkdtemp(prefix="picturekit-lut-"))
    source = work / "lut.png"
    Image.new("RGB", (64, 64), (150, 120, 90)).save(source)
    module.LUT_DIR.mkdir(exist_ok=True)
    lut_path = module.LUT_DIR / "check-tmp.cube"
    lut_path.write_text(RED_ZERO_CUBE, encoding="utf-8")
    try:
        png = {"exportFormat": "png", "colorNoise": 0, "luminanceNoise": 0}
        base = np.asarray(developed(module, source, png), dtype=np.float32)
        looked = np.asarray(developed(module, source, {
            **png, "lut": "check-tmp.cube"}), dtype=np.float32)
        half = np.asarray(developed(module, source, {
            **png, "lut": "check-tmp.cube", "lutAmount": 50}), dtype=np.float32)
        off = np.asarray(developed(module, source, {
            **png, "lut": "check-tmp.cube", "lutAmount": 0}), dtype=np.float32)
        base_r = float(np.mean(base[:, :, 0]))
        assert float(np.mean(looked[:, :, 0])) < 3, "LUT did not apply"
        assert float(np.mean(np.abs(looked[:, :, 1:] - base[:, :, 1:]))) < 3, \
            "LUT leaked into G/B"
        assert abs(float(np.mean(half[:, :, 0])) - base_r / 2) < 8, \
            "lutAmount 50 is not a half blend"
        assert float(np.mean(np.abs(off - base))) < .5, "lutAmount 0 not no-op"
        missing = np.asarray(developed(module, source, {
            **png, "lut": "no-such.cube"}), dtype=np.float32)
        assert float(np.mean(np.abs(missing - base))) < .5, \
            "missing LUT should be skipped silently"
        try:
            module.parse_cube("LUT_1D_SIZE 2\n0 0 0\n1 1 1")
            raise AssertionError("1D LUT was accepted")
        except ValueError:
            pass
        print(f"LUT_OK red {base_r:.0f}->0, half blend ok, missing skip ok")
    finally:
        lut_path.unlink(missing_ok=True)


def check_bw_mix(module):
    """白黒ミキサー: 白黒変換の明るさを色別に振れる（例: ブルー−で空だけ
    暗いモノクロ）。対象外の色とグレーは動かない。"""
    work = Path(tempfile.mkdtemp(prefix="picturekit-bw-"))
    source = work / "bw.png"
    canvas = Image.new("RGB", (96, 96), (128, 128, 128))
    canvas.paste((40, 90, 200), (0, 0, 96, 32))     # 上: 青
    canvas.paste((200, 60, 50), (0, 64, 96, 96))    # 下: 赤
    canvas.save(source)
    png = {"exportFormat": "png", "monochrome": True}
    base = np.asarray(developed(module, source, png), dtype=np.float32)
    mixed = np.asarray(developed(module, source, {
        **png, "bwMix": [0, 0, 0, 0, 0, -80, 0, 0]}), dtype=np.float32)
    blue_drop = float(np.mean(base[4:28] - mixed[4:28]))
    red_shift = float(np.mean(np.abs(base[68:92] - mixed[68:92])))
    gray_shift = float(np.mean(np.abs(base[40:56] - mixed[40:56])))
    assert blue_drop > 15, f"bw mix blue- has no effect: {blue_drop:.1f}"
    assert red_shift < 3, f"bw mix leaked to red: {red_shift:.2f}"
    assert gray_shift < 3, f"bw mix moved neutral gray: {gray_shift:.2f}"
    mono_check = np.asarray(developed(module, source, {
        **png, "bwMix": [60, 0, 0, 0, 0, -80, 0, 0]}), dtype=np.float32)
    channel_spread = float(np.max(np.abs(mono_check[:, :, 0] - mono_check[:, :, 2])))
    assert channel_spread < 2, f"bw mix broke monochrome: {channel_spread:.1f}"
    print(f"BWMIX_OK blue -{blue_drop:.0f}, red leak {red_shift:.2f}, "
          f"gray {gray_shift:.2f}")


def check_shadow_color(module):
    work = Path(tempfile.mkdtemp(prefix="picturekit-color-"))
    source = work / "shadow.png"
    Image.new("RGB", (96, 96), (12, 42, 84)).save(source)
    before = developed(module, source, {})
    after = developed(module, source, {"shadows": 60})
    _, before_s, before_v = before.convert("HSV").getpixel((48, 48))
    _, after_s, after_v = after.convert("HSV").getpixel((48, 48))
    assert after_v > before_v, "shadow slider did not lift brightness"
    assert after_s >= before_s * .9, "shadow slider washed out color"
    print(f"SHADOW_COLOR_OK value {before_v}->{after_v}, saturation {before_s}->{after_s}")


def check_grading(module):
    """カラーグレーディング: シャドウ色は暗部だけ、ハイライト色は明部だけを
    染め、全体の輝度sliderは無彩色でも効く。"""
    work = Path(tempfile.mkdtemp(prefix="picturekit-grade-"))
    source = work / "grade.png"
    image = Image.new("RGB", (96, 96), (40, 40, 40))
    image.paste((215, 215, 215), (0, 48, 96, 96))
    image.save(source)

    def channels(img, y):
        return np.asarray(img, dtype=np.float32)[y, 48]

    base = developed(module, source, {})
    base_dark, base_bright = channels(base, 24), channels(base, 72)

    shadows = developed(module, source,
                        {"grading": {"shadows": {"hue": 240, "sat": 80}}})
    dark, bright = channels(shadows, 24), channels(shadows, 72)
    blue_shift = (dark[2] - dark[0]) - (base_dark[2] - base_dark[0])
    leak = float(np.max(np.abs(bright - base_bright)))
    assert blue_shift > 8, f"shadow grading too weak: {blue_shift:.1f}"
    assert leak < 3, f"shadow grading leaked into highlights: {leak:.1f}"

    highlights = developed(module, source,
                           {"grading": {"highlights": {"hue": 40, "sat": 80}}})
    dark, bright = channels(highlights, 24), channels(highlights, 72)
    warm_shift = (bright[0] - bright[2]) - (base_bright[0] - base_bright[2])
    dark_leak = float(np.max(np.abs(dark - base_dark)))
    assert warm_shift > 8, f"highlight grading too weak: {warm_shift:.1f}"
    assert dark_leak < 3, f"highlight grading leaked into shadows: {dark_leak:.1f}"

    lifted = developed(module, source, {"grading": {"global": {"lum": 50}}})
    assert channels(lifted, 24)[0] > base_dark[0] + 5, "grading lum has no effect"
    print(f"GRADING_OK shadow-blue +{blue_shift:.0f}, highlight-warm "
          f"+{warm_shift:.0f}, leak {max(leak, dark_leak):.1f}")


def check_masks(module):
    """部分補正マスク: 多角形の内側だけ露出/色温度が効き、外側は不変。
    反転で内外が入れ替わる。"""
    work = Path(tempfile.mkdtemp(prefix="picturekit-mask-"))
    source = work / "mask.png"
    Image.new("RGB", (96, 96), (90, 90, 90)).save(source)
    left_half = {"points": [[0, 0], [.5, 0], [.5, 1], [0, 1]], "feather": 0,
                 "adjust": {"exposure": 1, "temperature": 30}}

    base = developed(module, source, {})
    masked = developed(module, source, {"masks": [left_half]})
    base_px = np.asarray(base, dtype=np.float32)
    masked_px = np.asarray(masked, dtype=np.float32)
    inside = float(np.mean(masked_px[:, :40, 0] - base_px[:, :40, 0]))
    outside = float(np.mean(np.abs(masked_px[:, 56:] - base_px[:, 56:])))
    assert inside > 15, f"mask adjust too weak: {inside:.1f}"
    assert outside < 1, f"mask leaked outside: {outside:.2f}"

    inverted = developed(module, source,
                         {"masks": [{**left_half, "invert": True}]})
    inv_px = np.asarray(inverted, dtype=np.float32)
    inv_inside = float(np.mean(np.abs(inv_px[:, :40] - base_px[:, :40])))
    inv_outside = float(np.mean(inv_px[:, 56:, 0] - base_px[:, 56:, 0]))
    assert inv_inside < 1 and inv_outside > 15, "mask invert is broken"

    # 効果ゼロのマスク・オフにしたマスクは完全no-op（保存はされるが適用されない）
    noop = developed(module, source, {"masks": [
        {"points": [[0, 0], [.5, 0], [.5, 1], [0, 1]], "feather": 0,
         "adjust": {}}]})
    assert float(np.mean(np.abs(
        np.asarray(noop, dtype=np.float32) - base_px))) < .5
    off = developed(module, source,
                    {"masks": [{**left_half, "enabled": False}]})
    assert float(np.mean(np.abs(
        np.asarray(off, dtype=np.float32) - base_px))) < .5, \
        "disabled mask still applies"

    # トーン系（本体と同じ語彙）: 明暗2トーン画像で、シャドウ+70は暗部だけ
    # 持ち上げ、ハイライト-70は明部だけ下げる。白/黒/コントラストも反応する
    tone_source = work / "tone.png"
    two_tone = Image.new("RGB", (96, 96), (90, 90, 90))
    two_tone.paste((215, 215, 215), (0, 48, 96, 96))
    two_tone.save(tone_source)
    full_frame = [[0, 0], [1, 0], [1, 1], [0, 1]]
    tone_base = np.asarray(developed(module, tone_source, {}), dtype=np.float32)
    tone = developed(module, tone_source, {"masks": [{
        "points": full_frame, "feather": 0,
        "adjust": {"shadows": 70, "highlights": -70}}]})
    tone_px = np.asarray(tone, dtype=np.float32)
    shadow_lift = float(np.mean(tone_px[:40, :, 0] - tone_base[:40, :, 0]))
    highlight_pull = float(np.mean(tone_base[56:, :, 0] - tone_px[56:, :, 0]))
    assert shadow_lift > 8, f"mask shadows too weak: {shadow_lift:.1f}"
    assert highlight_pull > 8, f"mask highlights too weak: {highlight_pull:.1f}"
    levels = developed(module, tone_source, {"masks": [{
        "points": full_frame, "feather": 0,
        "adjust": {"whites": -60, "blacks": -60, "contrast": 40}}]})
    assert float(np.mean(np.abs(
        np.asarray(levels, dtype=np.float32) - tone_base))) > 3, \
        "mask whites/blacks/contrast have no effect"

    # 色域選択: クリック点と同じ色だけに効き、他の色は不変。
    # contiguous=隣接のみで、離れた同色領域が選択から外れる
    color_source = work / "color.png"
    canvas = Image.new("RGB", (96, 96), (90, 90, 90))
    canvas.paste((200, 60, 60), (8, 8, 40, 40))     # 左上の赤
    canvas.paste((200, 60, 60), (56, 56, 88, 88))   # 右下の赤（非隣接）
    canvas.save(color_source)
    color_mask = {"mode": "color", "x": .25, "y": .25, "tolerance": 30,
                  "contiguous": False, "feather": 0,
                  "adjust": {"exposure": 1.2}}
    cbase = np.asarray(developed(module, color_source, {}), dtype=np.float32)
    both = np.asarray(developed(module, color_source,
                                {"masks": [color_mask]}), dtype=np.float32)
    only = np.asarray(
        developed(module, color_source,
                  {"masks": [{**color_mask, "contiguous": True}]}),
        dtype=np.float32)
    first = float(np.mean(both[12:36, 12:36] - cbase[12:36, 12:36]))
    second = float(np.mean(both[60:84, 60:84] - cbase[60:84, 60:84]))
    ground = float(np.mean(np.abs(both[42:54, :] - cbase[42:54, :])))
    assert first > 10, f"color mask ignores clicked color: {first:.1f}"
    assert second > 10, f"color mask misses same color elsewhere: {second:.1f}"
    assert ground < 2, f"color mask leaked to other colors: {ground:.2f}"
    c_first = float(np.mean(only[12:36, 12:36] - cbase[12:36, 12:36]))
    c_second = float(np.mean(np.abs(only[60:84, 60:84] - cbase[60:84, 60:84])))
    assert c_first > 10, f"contiguous dropped the clicked region: {c_first:.1f}"
    assert c_second < 2, \
        f"contiguous still selects detached region: {c_second:.2f}"

    # 実写の分離キャリブレーション: 海クリック（既定30）で海は満点、
    # 霞んだ白い街と地面は入らない（2026-08-11「街まで入ってる」の再発防止）
    torii = ROOT / "images" / "R0009029.DNG"
    if torii.exists():
        item = make_item(torii)
        module.prepare_item(item)
        reference = module.color_reference(item, {})
        rw, rh = reference.size
        sea_mask = {"mode": "color", "x": .62, "y": .30, "tolerance": 30,
                    "contiguous": False, "feather": 0, "invert": False}
        weight = module.color_mask_plane(item, {}, sea_mask, (rw, rh),
                                         0, 0, rw, rh)
        sea = float(weight[int(.30 * (rh - 1)), int(.62 * (rw - 1))])
        city = float(weight[int(.33 * (rh - 1)), int(.15 * (rw - 1))])
        ground = float(weight[int(.85 * (rh - 1)), int(.45 * (rw - 1))])
        assert sea > .9, f"sea not selected: {sea:.2f}"
        assert city < .3, f"hazy city leaked into selection: {city:.2f}"
        assert ground < .05, f"ground leaked into selection: {ground:.2f}"
        print(f"COLOR_SEP_OK sea {sea:.2f}, city {city:.2f}, "
              f"ground {ground:.2f}")

    # マスクオーバーレイ: 選択範囲だけ赤・非選択は透明のRGBA PNGが返る
    overlay = module.mask_overlay_png(
        make_item(color_source),
        {**BASE, "maskIndex": 0, "masks": [color_mask]})
    overlay_img = Image.open(io.BytesIO(overlay))
    assert overlay_img.mode == "RGBA"
    alpha = np.asarray(overlay_img)[:, :, 3]
    oh, ow = alpha.shape
    assert alpha[oh // 4, ow // 4] > 60, "overlay missing on selected color"
    assert alpha[3 * oh // 4, 3 * ow // 4] > 60, \
        "overlay missing on detached same color"
    assert alpha[oh // 2, ow // 2] < 10, "overlay covers unselected area"
    assert np.any(alpha[oh // 4] == 255), "overlay lacks boundary outline"

    # 輪郭SVG: 50%境界を線だけの編集可能なcubic pathへ変換し、元画像は変更しない
    source_before = source.read_bytes()
    svg, path_count, point_count = module.mask_outline_svg(
        make_item(source), {**BASE, "maskIndex": 0, "masks": [left_half]})
    assert source.read_bytes() == source_before, "outline modified source image"
    assert path_count >= 1 and point_count >= 4
    assert svg.startswith('<?xml version="1.0"') and '<svg ' in svg
    assert '<path d="M ' in svg and ' C ' in svg and svg.count(" Z") >= 1
    assert 'fill="none"' in svg and 'stroke="#121212"' in svg
    assert "<image" not in svg, "outline SVG must not contain the source image"

    print(f"MASK_OK inside +{inside:.0f}, outside {outside:.2f}, invert ok, "
          f"off ok, tone +{shadow_lift:.0f}/-{highlight_pull:.0f}, "
          f"color +{first:.0f}/+{second:.0f} (contiguous +{c_first:.0f}"
          f"/{c_second:.1f})")


def check_brush_masks(module):
    """非破壊brush mask: 加筆・消去・soft edge・opacity・uint16補正。"""
    add = {"points": [[.1, .5], [.9, .5]], "size": .22,
           "hardness": 1, "opacity": 1}
    erase = {"points": [[.5, .5]], "size": .08,
             "hardness": 1, "opacity": 1, "erase": True}
    raw = {"mode": "brush", "strokes": [add, erase], "feather": 0,
           "adjust": {"exposure": 1}}
    shape = module.mask_shape(raw)
    shape.update({"feather": 0, "invert": False})
    weight = module.brush_mask_plane(shape, (200, 100), 0, 0, 200, 100)
    assert weight[50, 30] > .9 and weight[50, 100] < .1
    assert weight[5, 100] < .01
    image = np.full((100, 200, 3), 20000, dtype=np.uint16)
    adjusted = module.apply_masks(image, {"masks": [raw]})
    assert adjusted.dtype == np.uint16
    assert adjusted[50, 30, 0] > image[50, 30, 0]
    assert adjusted[50, 100, 0] == image[50, 100, 0]
    soft = module.mask_shape({"mode": "brush", "strokes": [{
        "points": [[.5, .5]], "size": .2, "hardness": 0, "opacity": .5}]})
    soft.update({"feather": 0, "invert": False})
    sw = module.brush_mask_plane(soft, (200, 100), 0, 0, 200, 100)
    assert .15 < sw[50, 100] < .55 and np.any((sw > .01) & (sw < .15))
    many = module.mask_shape({"mode": "brush", "strokes": [
        {"points": [[i / 200, .5] for i in range(200)], "size": .01}
        for _ in range(130)]})
    assert len(many["strokes"]) <= 128
    assert sum(len(s["points"]) for s in many["strokes"]) <= 12000
    print("BRUSH_MASK_OK add/erase/soft/opacity/uint16/limits")


def check_retouch(module):
    """スポット修復: 傷（黒四角）がコピー元の色で消え、他は不変。
    コピー元が画像外の項目は安全にskipされる。"""
    work = Path(tempfile.mkdtemp(prefix="picturekit-heal-"))
    source = work / "heal.png"
    image = Image.new("RGB", (96, 96), (120, 120, 120))
    image.paste((10, 10, 10), (58, 42, 70, 54))  # 傷: 中心(.667, .5)
    image.save(source)
    base_px = np.asarray(developed(module, source, {}), dtype=np.float32)
    spot = {"x": .667, "y": .5, "r": .1, "sx": .25, "sy": .5, "mode": "heal"}

    healed = developed(module, source, {"retouch": [spot]})
    healed_px = np.asarray(healed, dtype=np.float32)
    blemish = healed_px[44:52, 60:68, 0]
    assert float(np.mean(np.abs(blemish - 120))) < 12, \
        f"heal did not remove blemish: {np.mean(blemish):.0f}"
    untouched = float(np.mean(np.abs(healed_px[:, :40] - base_px[:, :40])))
    assert untouched < 1, f"heal leaked outside: {untouched:.2f}"

    cloned = developed(module, source, {"retouch": [{**spot, "mode": "clone"}]})
    cloned_blemish = np.asarray(cloned, dtype=np.float32)[44:52, 60:68, 0]
    assert float(np.mean(np.abs(cloned_blemish - 120))) < 12, "clone has no effect"

    # コピー元が画像外へはみ出す設定はskip＝画は不変（誤適用より安全側）
    outside = developed(module, source,
                        {"retouch": [{**spot, "sx": .01, "sy": .01, "r": .12}]})
    diff = float(np.mean(np.abs(np.asarray(outside, dtype=np.float32) - base_px)))
    assert diff < .5, f"out-of-bounds source was applied: {diff:.2f}"
    print(f"RETOUCH_OK blemish {np.mean(blemish):.0f}≈120, leak {untouched:.2f}")


def check_wb_pick(module):
    """WBスポイト: 色被りしたグレーを選ぶと、返ってきたtemperature/tintの適用で
    その場所が無彩色になる。"""
    work = Path(tempfile.mkdtemp(prefix="picturekit-wb-"))
    source = work / "cast.png"
    Image.new("RGB", (96, 96), (150, 145, 135)).save(source)
    picked = module.pick_white_balance(make_item(source), dict(BASE), .5, .5)
    assert picked["temperature"] != 0 or picked["tint"] != 0
    corrected = developed(module, source, picked)
    center = np.asarray(corrected, dtype=np.float32)[48, 48]
    spread = float(np.max(center) - np.min(center))
    assert spread < 4, f"wb pick did not neutralize: {center} spread {spread:.1f}"
    print(f"WB_PICK_OK temp {picked['temperature']} tint {picked['tint']}, "
          f"spread {spread:.1f}")


def check_grain(module):
    """粒子: 決定的（同設定は同結果）で、量に応じて質感が付き、0では無変化。"""
    work = Path(tempfile.mkdtemp(prefix="picturekit-grain-"))
    source = work / "grain.png"
    Image.new("RGB", (96, 96), (128, 128, 128)).save(source)
    base_px = np.asarray(developed(module, source, {}), dtype=np.float32)
    grained = np.asarray(developed(module, source, {"grain": 60}),
                         dtype=np.float32)
    again = np.asarray(developed(module, source, {"grain": 60}),
                       dtype=np.float32)
    difference = grained - base_px
    assert float(np.std(difference)) > 1.5, "grain has no effect"
    assert float(np.mean(np.abs(difference))) < 12, "grain too strong"
    assert np.array_equal(grained, again), "grain is not deterministic"
    print(f"GRAIN_OK std {np.std(difference):.1f}")


def image_metrics(image):
    pixels = np.asarray(image, dtype=np.uint8)
    luminance = np.sum(pixels * np.array([.2126, .7152, .0722]), axis=2)
    white = np.mean(np.all(pixels >= 250, axis=2))
    cyan = np.mean((pixels[:, :, 0] <= 5) &
                   (pixels[:, :, 1] >= 250) & (pixels[:, :, 2] >= 250))
    return pixels, luminance, white, cyan


def check_real_dng(module, full=False):
    # 検証用DNGはroot直下またはimages/（写真置き場）のどちらでも見つける
    source = next((path for path in (ROOT / "IMGP6613.DNG",
                                     ROOT / "images" / "IMGP6613.DNG")
                   if path.exists()), None)
    if source is None:
        print("DNG_SKIP IMGP6613.DNG not found")
        return
    assert module.camera_model(source) == "PENTAX K-1"
    item = make_item(source)
    started = time.perf_counter()
    module.prepare_item(item)
    elapsed = time.perf_counter() - started
    full_linear = np.load(item["linear"], mmap_mode="r", allow_pickle=False)
    preview_linear = np.load(item["preview_linear"], mmap_mode="r", allow_pickle=False)
    assert full_linear.dtype == np.uint16 and full_linear.shape == (4912, 7360, 3)
    assert preview_linear.dtype == np.uint16 and max(preview_linear.shape[:2]) == 1400
    assert np.max(full_linear) < 65535, "linear RAW headroom was clipped"

    neutral = module.developed_image(item, {}, preview=True)
    pixels, luminance, white, cyan = image_metrics(neutral)
    median = float(np.median(luminance))
    sky = luminance[:round(luminance.shape[0] * .38)]
    neighbor_detail = float(np.mean(np.abs(np.diff(sky, axis=1))))
    # 忠実表示: 中間調はカメラJPEG相当の暗め(実測54)、黒は黒く、白飛び空は白く出る
    assert 35 <= median <= 90, f"midtone outside target: {median:.1f}"
    assert float(np.percentile(luminance, 0.5)) < 25, "blacks are lifted (washed out)"
    assert cyan < .001, f"channel-clip cyan: {cyan:.3%}"
    assert np.std(sky) > 25 and neighbor_detail > 2, "sky/cloud detail is too flat"

    # 雲のheadroom回収: ハイライト-70で白飛び表示がほぼ消え、中間調は動かない
    # （BaselineExposure+0.45適用で既定が明るくなり、-50では2.99%残るのが正）
    recovered = module.developed_image(item, {"highlights": -70}, preview=True)
    _, rec_lum, _, _ = image_metrics(recovered)
    rec_sky = rec_lum[:round(rec_lum.shape[0] * .38)]
    assert np.mean(rec_sky >= 250) < .02, "highlights slider cannot recover clouds"
    assert abs(float(np.median(rec_lum)) - median) < 6, "highlight recovery moved midtones"

    # 局所性: シャドウ+80は暗部だけ持ち上げ、空（明部）を動かさない
    dark_band = round(luminance.shape[0] * .62)
    lifted = module.developed_image(item, {"shadows": 80}, preview=True)
    _, lift_lum, _, _ = image_metrics(lifted)
    dark_before = float(np.percentile(luminance[dark_band:], 10))
    dark_after = float(np.percentile(lift_lum[dark_band:], 10))
    sky_shift = abs(float(np.median(lift_lum[:round(lift_lum.shape[0] * .38)])) -
                    float(np.median(sky)))
    assert dark_after - dark_before > 8, \
        f"shadows slider too weak: {dark_before:.1f}->{dark_after:.1f}"
    assert sky_shift < 4, f"shadows slider leaked into highlights: {sky_shift:.1f}"

    # かすみ除去: 空を白側へ押し出さず（旧実装の欠陥）、膜の下の彩度が戻る
    hazed = module.developed_image(item, {"dehaze": 60}, preview=True)
    hazed_pixels, hazed_lum, _, _ = image_metrics(hazed)
    hazed_sky = hazed_lum[:round(hazed_lum.shape[0] * .38)]
    assert np.mean(hazed_sky >= 250) <= np.mean(sky >= 250) + .01, "dehaze blows out sky"

    def mean_saturation(rgb_pixels):
        top = np.max(rgb_pixels, axis=2).astype(np.float32)
        bottom = np.min(rgb_pixels, axis=2).astype(np.float32)
        return float(np.mean(np.divide(top - bottom, top,
                                       out=np.zeros_like(top), where=top > 1)))
    assert mean_saturation(hazed_pixels) > mean_saturation(pixels) + .05, \
        "dehaze did not restore color under the veil"

    # コントラストはハイライト回収を打ち消さない
    fought = module.developed_image(
        item, {"highlights": -70, "contrast": 60}, preview=True)
    _, fought_lum, _, _ = image_metrics(fought)
    fought_sky = fought_lum[:round(fought_lum.shape[0] * .38)]
    assert np.mean(fought_sky >= 250) < .04, "contrast cancels highlight recovery"

    # コントラストの中点は画像中央輝度: 暗めの写真で+60しても全体が沈まない
    contrasted = module.developed_image(item, {"contrast": 60}, preview=True)
    _, con_lum, _, _ = image_metrics(contrasted)
    assert abs(float(np.median(con_lum)) - median) < 10, \
        f"contrast shifts overall brightness: {median:.1f}->{np.median(con_lum):.1f}"

    # 黒レベル: ＋で黒が持ち上がり、−で締まる
    p2 = float(np.percentile(luminance, 2))
    _, lifted_lum, _, _ = image_metrics(
        module.developed_image(item, {"blacks": 60}, preview=True))
    _, crushed_lum, _, _ = image_metrics(
        module.developed_image(item, {"blacks": -60}, preview=True))
    assert float(np.percentile(lifted_lum, 2)) - p2 > 8, "blacks+ has no effect"
    assert p2 - float(np.percentile(crushed_lum, 2)) > 5, "blacks- has no effect"

    # 周辺光量補正: 四隅だけ明るくなり、中央は動かない
    height_px, width_px = luminance.shape

    def corner_mean(lum):
        return float(np.mean([
            lum[:height_px // 10, :width_px // 10].mean(),
            lum[:height_px // 10, -width_px // 10:].mean(),
            lum[-height_px // 10:, :width_px // 10].mean(),
            lum[-height_px // 10:, -width_px // 10:].mean()]))

    def center_mean(lum):
        return float(lum[4 * height_px // 10:6 * height_px // 10,
                         4 * width_px // 10:6 * width_px // 10].mean())

    _, vig_lum, _, _ = image_metrics(
        module.developed_image(item, {"vignette": 60}, preview=True))
    assert corner_mean(vig_lum) - corner_mean(luminance) > 6, "vignette has no effect"
    assert abs(center_mean(vig_lum) - center_mean(luminance)) < 2, \
        "vignette leaked into center"

    # カメラプロファイル(DCP): 彩度が乗り、白が255へ届く（DCPがあるMacのみ）
    camera_names = list(module.camera_profiles("PENTAX K-1"))
    if "Camera Natural" in camera_names:
        assert not any(n.startswith("Mark") for n in camera_names), \
            "K-1 profile list contains Mark II entries"
        profiled_img = module.developed_image(
            item, {"cameraProfile": "Camera Natural"}, preview=True)
        profiled_pixels, prof_lum, _, prof_cyan = image_metrics(profiled_img)
        assert prof_cyan < .001
        assert mean_saturation(profiled_pixels) > mean_saturation(pixels) + .05, \
            "camera profile did not enrich color"
        assert float(np.percentile(prof_lum, 98)) > 250, \
            "camera profile curve does not reach white"
        print(f"DCP_OK Camera Natural sat {mean_saturation(pixels):.3f}->"
              f"{mean_saturation(profiled_pixels):.3f}")
        # Adobe Standard: カーブ無しDCPにはACR標準カーブが適用され、
        # 中間調が持ち上がる（無いと暗くフラット＝2026-08-10の実症状）
        assert (ROOT / "acr-tone-curve.json").exists(), "acr-tone-curve.json missing"
        standard = module.developed_image(
            item, {"cameraProfile": "Adobe Standard"}, preview=True)
        std_pixels, std_lum, _, std_cyan = image_metrics(standard)
        assert std_cyan < .001
        assert float(np.median(std_lum)) > median + 8, \
            "Adobe Standard lacks ACR base curve (renders flat/dark)"
        # Kit Vivid: satScale中立化前のAdobe Standard発色（利用者指名で保存）。
        # Adobe Standardより明確に彩度が乗る
        assert "Kit Vivid" in camera_names, "Kit Vivid profile missing"
        vivid = module.developed_image(
            item, {"cameraProfile": "Kit Vivid"}, preview=True)
        vivid_pixels, _, _, vivid_cyan = image_metrics(vivid)
        assert vivid_cyan < .001
        assert mean_saturation(vivid_pixels) > mean_saturation(std_pixels) + .08, \
            (f"Kit Vivid is not more saturated: "
             f"{mean_saturation(vivid_pixels):.3f} vs "
             f"{mean_saturation(std_pixels):.3f}")
        print(f"KITVIVID_OK sat {mean_saturation(std_pixels):.3f}->"
              f"{mean_saturation(vivid_pixels):.3f}")
    else:
        print("DCP_SKIP no Adobe camera profiles on this machine")

    # 輝度ノイズ低減(coring): 100%等倍で粒が減り、強い輪郭は残る
    def tile_region(extra, x, y):
        viewport = {"x": x, "y": y, "width": 600, "height": 400}
        return np.asarray(module.developed_tile(
            item, {"shadows": 60, "dehaze": 50, "viewport": viewport, **extra}),
            dtype=np.float32)

    def grain_of(arr):
        lum = arr @ np.array([.2126, .7152, .0722], dtype=np.float32)
        smooth = np.asarray(Image.fromarray(lum.astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(2)), dtype=np.float32)
        return float(np.std(lum - smooth))

    def edge_of(arr):
        lum = arr @ np.array([.2126, .7152, .0722], dtype=np.float32)
        return float(np.percentile(np.abs(np.diff(lum, axis=1)), 97))

    # 空の領域は(4200,150)。(1200,300)は松の木で、葉の質感をノイズと
    # 誤計測していた（2026-08-10）
    sky_plain = grain_of(tile_region({"luminanceNoise": 0}, 4200, 150))
    sky_reduced = grain_of(tile_region({"luminanceNoise": 40}, 4200, 150))
    roof_plain = edge_of(tile_region({"luminanceNoise": 0}, 2600, 1900))
    roof_reduced = edge_of(tile_region({"luminanceNoise": 40}, 2600, 1900))
    assert sky_reduced < sky_plain * .85, \
        f"luminance NR too weak: {sky_plain:.1f}->{sky_reduced:.1f}"
    assert roof_reduced > roof_plain * .6, \
        f"luminance NR destroys detail: {roof_plain:.1f}->{roof_reduced:.1f}"
    print(f"NR_OK grain {sky_plain:.1f}->{sky_reduced:.1f}, "
          f"edge kept {roof_reduced / roof_plain:.0%}")

    # カラーミキサー: イエロー＋グリーン帯の彩度-100で木だけ無彩色化し、空は動かない
    # （黄緑の葉は両帯に折半帰属するため片方だけでは半分しか効かない＝LRと同じ）
    mixed = module.developed_image(
        item, {"mixer": {"sat": [0, 0, -100, -100, 0, 0, 0, 0]}}, preview=True)
    mixed_pixels = np.asarray(mixed, dtype=np.uint8)
    tree = (slice(round(luminance.shape[0] * .25), round(luminance.shape[0] * .5)),
            slice(0, round(luminance.shape[1] * .25)))
    tree_before = mean_saturation(pixels[tree])
    tree_after = mean_saturation(mixed_pixels[tree])
    # 空は上端中央（左右端の上部には松の枝が写り込むため純粋な空だけ見る）
    pure_sky = (slice(0, round(luminance.shape[0] * .15)),
                slice(round(luminance.shape[1] * .35),
                      round(luminance.shape[1] * .65)))
    sky_shift_mix = float(np.mean(np.abs(
        mixed_pixels[pure_sky].astype(np.float32)
        - pixels[pure_sky].astype(np.float32))))
    assert tree_after < tree_before * .45, \
        f"mixer green desat too weak: {tree_before:.3f}->{tree_after:.3f}"
    assert sky_shift_mix < 2, f"mixer leaked into sky: {sky_shift_mix:.2f}"
    print(f"MIXER_OK green sat {tree_before:.3f}->{tree_after:.3f}, "
          f"sky shift {sky_shift_mix:.2f}")

    # 自動補正: ヒストグラム駆動で、適用後に中間調が範囲内・白飛びが回収される
    auto = module.auto_settings(item, {})
    assert auto["highlights"] <= -10, f"auto did not recover sky: {auto}"
    _, auto_lum, _, _ = image_metrics(
        module.developed_image(item, auto, preview=True))
    auto_median = float(np.median(auto_lum))
    auto_blown = float(np.mean(auto_lum >= 250))
    assert 60 <= auto_median <= 140, f"auto midtone off: {auto_median:.0f}"
    assert auto_blown < .04, f"auto leaves blown sky: {auto_blown:.1%}"
    print(f"AUTO_OK {auto} -> median {auto_median:.0f}, blown {auto_blown:.1%}")

    # 角度補正: 2°回転で寸法は不変・画は変わる・四隅が欠けない（自動内接スケール）
    straightened = module.developed_image(item, {"straighten": 2}, preview=True)
    straight_pixels = np.asarray(straightened, dtype=np.uint8)
    assert straight_pixels.shape == pixels.shape
    assert float(np.mean(np.abs(straight_pixels.astype(np.float32)
                                - pixels.astype(np.float32)))) > 1, \
        "straighten has no effect"
    corner_size = 8
    for corner in [(slice(0, corner_size), slice(0, corner_size)),
                   (slice(0, corner_size), slice(-corner_size, None)),
                   (slice(-corner_size, None), slice(0, corner_size)),
                   (slice(-corner_size, None), slice(-corner_size, None))]:
        assert float(np.mean(straight_pixels[corner])) > .5, \
            "straighten left empty corners"

    # レンズプロファイル歪曲補正: 中央は不変・周辺は動く（LCPがあるMacのみ）
    lenses = [name for name in module.lens_profiles() if "28-105" in name]
    if lenses:
        _, lens_lum, _, _ = image_metrics(
            module.developed_image(item, {"lensProfile": lenses[0]}, preview=True))
        center_shift = float(np.mean(np.abs(
            lens_lum[4 * height_px // 10:6 * height_px // 10,
                     4 * width_px // 10:6 * width_px // 10]
            - luminance[4 * height_px // 10:6 * height_px // 10,
                        4 * width_px // 10:6 * width_px // 10])))
        edge_shift = float(np.mean(np.abs(
            lens_lum[-height_px // 12:] - luminance[-height_px // 12:])))
        assert center_shift < 3, f"lens profile moved center: {center_shift:.1f}"
        assert edge_shift > 8, f"lens profile has no effect on edges: {edge_shift:.1f}"
        print(f"LENS_OK {lenses[0][:40]}… center {center_shift:.1f} edge {edge_shift:.1f}")
    else:
        print("LENS_SKIP no Adobe LCP on this machine")

    # オープンDB（lensfun）の歪曲補正: Adobe LCPと実用同等の補正になる
    open_names = [n for n in module.lensfun_lenses("PENTAX K-1") if "28-105" in n]
    assert open_names, "lensfun DB missing HD 28-105"
    open_img = module.developed_image(
        item, {"lensProfile": "lf:" + open_names[0]}, preview=True)
    _, open_lum, _, _ = image_metrics(open_img)
    open_center = float(np.mean(np.abs(
        open_lum[4 * height_px // 10:6 * height_px // 10,
                 4 * width_px // 10:6 * width_px // 10]
        - luminance[4 * height_px // 10:6 * height_px // 10,
                    4 * width_px // 10:6 * width_px // 10])))
    open_edge = float(np.mean(np.abs(
        open_lum[-height_px // 12:] - luminance[-height_px // 12:])))
    assert open_center < 3, f"lensfun moved center: {open_center:.1f}"
    assert open_edge > 8, f"lensfun has no effect on edges: {open_edge:.1f}"
    if lenses:
        _, adobe_lum, _, _ = image_metrics(module.developed_image(
            item, {"lensProfile": lenses[0]}, preview=True))
        agreement = float(np.mean(np.abs(open_lum.astype(np.float32)
                                         - adobe_lum.astype(np.float32))))
        # 両者は同一レンズの独立実測。四隅で対角の0.6%（±50px/8849px）程度の
        # キャリブレーション差があり、テクスチャ上では輝度差~10として現れる
        assert agreement < 15, f"lensfun deviates from Adobe LCP: {agreement:.1f}"
        print(f"OPENLENS_OK edge {open_edge:.1f}, Adobe一致 {agreement:.2f}")
    else:
        print(f"OPENLENS_OK edge {open_edge:.1f}")

    settings = {
        "exposure": .8, "temperature": 42, "tint": 33, "contrast": 10,
        "highlights": -20, "shadows": 20, "whites": 8, "blacks": -8,
        "dehaze": 30, "vignette": 40,
        "curves": {"lum": [[0, 6], [110, 130], [255, 250]],
                   "r": [[0, 0], [128, 118], [255, 255]]},
        "grading": {"shadows": {"hue": 240, "sat": 25}},
        "masks": [{"points": [[.2, .2], [.8, .2], [.8, .8], [.2, .8]],
                   "feather": 30,
                   "adjust": {"exposure": .5, "temperature": 20}},
                  {"mode": "color", "x": .5, "y": .2, "tolerance": 35,
                   "feather": 20, "adjust": {"saturation": 25}}],
        "retouch": [{"x": .45, "y": .5, "r": .02, "sx": .48, "sy": .5,
                     "mode": "heal"}],
        "grain": 15,
    }
    if lenses:
        settings["lensProfile"] = lenses[0]
    if "Camera Natural" in camera_names:
        settings["cameraProfile"] = "Camera Natural"
    adjusted = module.developed_image(item, {**BASE, **settings}, preview=True)
    adjusted_pixels, _, adjusted_white, adjusted_cyan = image_metrics(adjusted)
    grays = len(np.unique(np.round(np.mean(adjusted_pixels, axis=2)).astype(np.uint8)))
    assert adjusted_cyan < .001, f"combined settings caused channel clip: {adjusted_cyan:.3%}"
    assert grays > 150, f"combined settings crushed gradation: {grays}"
    cache_started = time.perf_counter()
    module.prepare_item(item)
    assert time.perf_counter() - cache_started < .1, "RAW cache was not reused"
    print(f"DNG_LINEAR_OK {elapsed:.2f}s, median {median:.1f}, "
          f"white {white:.3%}, sky-detail {neighbor_detail:.2f}")

    if full:
        started = time.perf_counter()
        result = module.adjusted_jpeg(item, {**BASE, **settings})
        exported = Image.open(io.BytesIO(result))
        assert exported.size == (7360, 4912) and exported.format == "JPEG"
        _, _, full_white, full_cyan = image_metrics(exported.copy().resize((700, 467)))
        # 複合設定にはマスク+0.5EV等が含まれ空が正当に白くなるため、絶対値でなく
        # 「previewとfullの一致」を検査する（乖離＝pipeline不整合の検出）
        assert full_cyan < .001
        assert abs(full_white - adjusted_white) < .03, \
            f"preview/full white mismatch: {adjusted_white:.3%} vs {full_white:.3%}"
        # 100%表示(tile)は書き出しと同一pixelであること（ドットバイドット確認用の根拠）
        viewport = {"x": 3000, "y": 2200, "width": 800, "height": 600}
        tile = module.developed_tile(item, {**BASE, **settings, "viewport": viewport})
        crop = exported.convert("RGB").crop((3000, 2200, 3800, 2800))
        difference = float(np.mean(np.abs(
            np.asarray(tile, dtype=np.float32) - np.asarray(crop, dtype=np.float32))))
        # EXIF引き継ぎ: 書き出しJPEGに撮影情報が残る（ISO 34855 / 焦点距離 37386）
        exported_exif = exported.getexif().get_ifd(34665)
        assert exported_exif.get(34855), "export lost ISO EXIF"
        assert exported_exif.get(37386), "export lost focal length EXIF"
        assert tile.size == (800, 600) and difference < 2.5, \
            f"tile differs from export: {difference:.2f}"
        print(f"DNG_FULL_OK {time.perf_counter() - started:.1f}s, "
              f"{len(result) / 1e6:.1f}MB, tile-diff {difference:.2f}")

def check_content_fill(module):
    """自動source計画、soft合成、入力制限、uint16、tile外sourceを検証。"""
    height, width = 120, 180
    x = np.arange(width, dtype=np.uint16)[None, :]
    base = np.empty((height, width, 3), dtype=np.uint16)
    base[:, :, 0] = x * 250
    base[:, :, 1] = np.arange(height, dtype=np.uint16)[:, None] * 300
    base[:, :, 2] = 12000
    fill = {"algorithm": "boundary-copy-v1", "points": [[.75, .5]],
            "size": .08, "hardness": 1, "opacity": 1,
            "searchRadius": .3, "source": [.2, .5]}
    output = module.apply_content_fills(base, {"contentFills": [fill]})
    assert output.dtype == np.uint16 and np.any(output != base)
    assert output[60, 134, 0] < base[60, 134, 0]
    assert np.array_equal(output[5, 5], base[5, 5])
    invalid = [{"points": [[.5, .5]], "source": [float("nan"), .5]},
               {"algorithm": "unknown", "points": [[.5, .5]], "source": [.2, .2]}]
    assert module.content_fill_settings({"contentFills": invalid}) == []
    many = module.content_fill_settings({"contentFills": [
        {**fill, "points": [[i / 512, .5] for i in range(512)]}
        for _ in range(40)]})
    assert len(many) <= 32 and sum(len(v["points"]) for v in many) <= 6000
    work = Path(tempfile.mkdtemp(prefix="picturekit-content-fill-")); source = work / "base.png"
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 0] = (np.arange(width)[None, :] % 24) * 5 + 60
    image[:, :, 1] = (np.arange(height)[:, None] % 20) * 4 + 70
    image[:, :, 2] = 90; image[50:70, 80:100] = [250, 0, 0]
    Image.fromarray(image).save(source)
    item = make_item(source); module.prepare_item(item)
    draft = {"points": [[.5, .5]], "size": .12, "hardness": .7,
             "opacity": 1, "searchRadius": .4}
    planned = module.plan_content_fill(item, {**BASE, "colorNoise": 0,
                                               "contentFillDraft": draft})
    again = module.plan_content_fill(item, {**BASE, "colorNoise": 0,
                                             "contentFillDraft": draft})
    assert planned["source"] == again["source"]
    settings = {**BASE, "colorNoise": 0, "contentFills": [fill]}
    full = module.developed_array(item, settings)
    vp = {"x": 110, "y": 35, "width": 60, "height": 55}
    tile = module._developed_tile_array(item, {**settings, "viewport": vp})
    crop = full[35:90, 110:170]
    diff = float(np.mean(np.abs(np.asarray(module.image8_from_u16(tile), np.float32)
                                - np.asarray(module.image8_from_u16(crop), np.float32))))
    assert diff < 2.5, f"content fill tile differs: {diff:.2f}"
    print(f"CONTENT_FILL_OK plan/deterministic/limits/uint16/tile {diff:.2f}")


def check_liquify(module):
    """3変形の方向、入力制限、16bit、full/tile一致を検証。"""
    ramp = np.arange(180, dtype=np.uint16) * 300
    base = np.repeat(ramp[None, :, None], 120, axis=0)
    base = np.repeat(base, 3, axis=2)
    edits = [
        {"mode": "push", "points": [[.35, .5], [.4, .5]],
         "size": .05, "strength": 1},
        {"mode": "bloat", "points": [[.6, .5]],
         "size": .05, "strength": .8},
        {"mode": "pinch", "points": [[.75, .5]],
         "size": .05, "strength": .8}]
    outputs = [module.apply_liquify(base, {"liquifyEdits": [edit]})
               for edit in edits]
    assert all(out.dtype == np.uint16 and np.any(out != base) for out in outputs)
    assert outputs[0][60, 72, 0] < base[60, 72, 0]
    assert outputs[1][60, 113, 0] < base[60, 113, 0]
    assert outputs[2][60, 140, 0] > base[60, 140, 0]
    invalid = [{"mode": "bad", "points": [[.5, .5]]},
               {"mode": "push", "points": [[.5, .5]]},
               {"mode": "bloat", "points": [[float("nan"), .5]]}]
    assert module.liquify_edit_settings({"liquifyEdits": invalid}) == []
    many = module.liquify_edit_settings({"liquifyEdits": [
        {"mode": "bloat", "points": [[i / 200, .5] for i in range(200)],
         "size": .03, "strength": .5} for _ in range(130)]})
    assert len(many) <= 128 and sum(len(e["points"]) for e in many) <= 12000
    work = Path(tempfile.mkdtemp(prefix="picturekit-liquify-")); source = work / "base.png"
    image = np.repeat((np.arange(180, dtype=np.uint8)[None, :]), 120, axis=0)
    Image.fromarray(np.dstack((image, image, image))).save(source)
    item = make_item(source); module.prepare_item(item)
    settings = {**BASE, "colorNoise": 0, "liquifyEdits": edits}
    full = module.developed_array(item, settings)
    vp = {"x": 45, "y": 30, "width": 100, "height": 65}
    tile = module._developed_tile_array(item, {**settings, "viewport": vp})
    crop = full[30:95, 45:145]
    diff = float(np.mean(np.abs(tile.astype(np.int32) - crop.astype(np.int32))))
    assert diff < 2 and module.liquify_required_pad(settings, (180, 120)) > 0
    print(f"LIQUIFY_OK push/bloat/pinch/limits/uint16/tile {diff:.2f}")


def check_pixel_edits(module):
    base=np.full((100,120,3),20000,dtype=np.uint16)
    paint={"mode":"paint","points":[[.2,.5],[.8,.5]],"size":.1,"hardness":1,"opacity":1,"color":"#ff0000"}
    erase={"mode":"erase","points":[[.5,.5]],"size":.08,"hardness":1,"opacity":1}
    painted=module.apply_pixel_edits(base,{"pixelEdits":[paint]})
    assert painted.dtype==np.uint16 and painted[50,60,0]>painted[50,60,1]
    assert np.array_equal(painted[5,5],base[5,5])
    restored=module.apply_pixel_edits(base,{"pixelEdits":[paint,erase]})
    assert np.array_equal(restored[50,60],base[50,60])
    pattern=base.copy();pattern[:,:40]=[50000,1000,1000]
    clone={"mode":"clone","points":[[.75,.5]],"source":[.2,.5],"size":.08,"hardness":1,"opacity":1}
    cloned=module.apply_pixel_edits(pattern,{"pixelEdits":[clone]})
    assert cloned[50,90,0]>40000
    noisy=(np.indices((100,120)).sum(0)%2*65535).astype(np.uint16);noisy=np.repeat(noisy[:,:,None],3,2)
    blur={"mode":"blur","points":[[.5,.5]],"size":.1,"hardness":1,"opacity":1,"strength":1}
    blurred=module.apply_pixel_edits(noisy,{"pixelEdits":[blur]})
    assert np.std(blurred[45:55,55:65])<np.std(noisy[45:55,55:65])
    many=module.pixel_edit_settings({"pixelEdits":[{"mode":"paint","color":"#000000","points":[[i/200,.5] for i in range(200)]} for _ in range(130)]})
    assert len(many)<=128 and sum(len(s["points"]) for s in many)<=12000
    work=Path(tempfile.mkdtemp(prefix="picturekit-pixel-"));source=work/"base.png"
    image=Image.new("RGB",(160,120),(40,60,80));image.paste((230,20,20),(0,0,50,120));image.save(source)
    item=make_item(source);module.prepare_item(item);settings={**BASE,"colorNoise":0,"pixelEdits":[clone]}
    full=module.developed_array(item,settings);vp={"x":90,"y":35,"width":55,"height":50}
    tile=module._developed_tile_array(item,{**settings,"viewport":vp});crop=full[35:85,90:145]
    diff=float(np.mean(np.abs(np.asarray(module.image8_from_u16(tile),dtype=np.float32)-np.asarray(module.image8_from_u16(crop),dtype=np.float32))))
    assert diff<2.5,f"pixel tile differs: {diff:.2f}"
    print(f"PIXEL_EDITS_OK paint/erase/clone/blur/uint16/tile {diff:.2f}")


def check_image_layers(module):
    """画像layerの素材保存、順序、透明度、回転、階調、tile、recipeを検証。"""
    root = Path(tempfile.mkdtemp(prefix="picturekit-layers-"))
    old = (module.IMAGES_DIR, module.RECIPE_DIR, module.LAYER_ASSET_DIR)
    module.IMAGES_DIR, module.RECIPE_DIR = root, root / "recipes"
    module.LAYER_ASSET_DIR = root / "assets"
    module._LAYER_CACHE.clear()
    try:
        def asset(color, size=(40, 20)):
            data = io.BytesIO(); Image.new("RGBA", size, color).save(data, "PNG")
            return module.save_layer_asset(data.getvalue(), "layer.png")
        red, blue = asset((255, 0, 0, 128)), asset((0, 0, 255, 255), (20, 40))
        blank = module.store_layer_image(Image.new("RGBA", (2, 2), (0, 0, 0, 0)), "blank")
        paint = {"mode":"paint","color":"#00ff00","size":.2,"hardness":1,
                 "opacity":1,"points":[[.5,.5]]}
        erase_paint = {"mode":"erase","size":.08,"hardness":1,
                       "opacity":1,"points":[[.5,.5]]}
        paint_layer = {"id":"paint","assetId":blank["assetId"],"name":"paint",
            "visible":True,"x":.5,"y":.5,"width":.5,"aspect":2,
            "rotation":0,"opacity":1,"blendMode":"normal","paintStrokes":[paint]}
        normalized = module.image_layer_settings({"imageLayers":[paint_layer]})[0]
        painted_local = module.render_layer_local(normalized, (200,100))
        assert painted_local.size == (100,50) and painted_local.getpixel((50,25))[1] > 240
        erased_local = module.render_layer_local({**normalized,
            "paintStrokes":[paint,erase_paint]}, (200,100))
        assert erased_local.getpixel((50,25))[3] < painted_local.getpixel((50,25))[3]
        cache_item = {}; first_paint = module.transformed_layer(cache_item, normalized, (200,100))
        changed_paint = module.transformed_layer(cache_item, {**normalized,
            "paintStrokes":[{**paint,"color":"#ff0000"}]}, (200,100))
        assert first_paint.getpixel((50,25)) != changed_paint.getpixel((50,25))
        def layer(meta, layer_id, **extra):
            return {"id": layer_id, "assetId": meta["assetId"], "name": layer_id,
                    "visible": True, "x": .5, "y": .5, "width": .4,
                    "rotation": 0, "opacity": 1, **extra}
        base = np.full((100, 200, 3), 32768, dtype=np.uint16)
        red_layer, blue_layer = layer(red, "red"), layer(blue, "blue", width=.2)
        one = module.compose_image_layers(base, {"imageLayers": [red_layer]}, {})
        assert one.dtype == np.uint16 and one[50, 100, 0] > one[50, 100, 1]
        assert np.array_equal(one[0, 0], base[0, 0])
        assert np.array_equal(module.compose_image_layers(base, {"imageLayers": [{**red_layer, "visible": False}]}, {}), base)
        top_blue = module.compose_image_layers(base, {"imageLayers": [red_layer, blue_layer]}, {})
        top_red = module.compose_image_layers(base, {"imageLayers": [blue_layer, red_layer]}, {})
        assert top_blue[50, 100, 2] > top_blue[50, 100, 0]
        assert top_red[50, 100, 0] > top_red[50, 100, 2]
        modes = {mode: module.compose_image_layers(base, {"imageLayers": [
            {**red_layer, "blendMode": mode, "opacity": 1}]}, {})[50, 100]
            for mode in module.BLEND_MODES}
        cb = np.array([[[.2, .6, .8]]], dtype=np.float32)
        cs = np.array([[[.7, .4, .1]]], dtype=np.float32)
        expected = {"normal": cs, "multiply": cb*cs,
            "screen": cb+cs-cb*cs,
            "overlay": np.where(cb<=.5, 2*cb*cs, 1-2*(1-cb)*(1-cs)),
            "darken": np.minimum(cb,cs), "lighten": np.maximum(cb,cs),
            "difference": np.abs(cb-cs)}
        for mode, value in expected.items():
            assert np.allclose(module.blend_layer_rgb(cb, cs, mode), value)
        erase = {"enabled": True, "invert": False, "strokes": [{
            "erase": True, "size": .3, "hardness": 1, "opacity": 1,
            "points": [[.5, .5]]}]}
        masked = module.compose_image_layers(base, {"imageLayers": [
            {**red_layer, "mask": erase}]}, {})
        assert np.array_equal(masked[50, 100], base[50, 100])
        disabled = module.compose_image_layers(base, {"imageLayers": [
            {**red_layer, "mask": {**erase, "enabled": False}}]}, {})
        assert np.array_equal(disabled[50, 100], one[50, 100])
        inverted = module.compose_image_layers(base, {"imageLayers": [
            {**red_layer, "mask": {"enabled": True, "invert": True, "strokes": []}}]}, {})
        assert np.array_equal(inverted, base)
        restored_mask = {"enabled": True, "invert": False, "strokes": [
            erase["strokes"][0], {"erase": False, "size": .12, "hardness": 1,
            "opacity": 1, "points": [[.5, .5]]}]}
        restored_layer = module.compose_image_layers(base, {"imageLayers": [
            {**red_layer, "mask": restored_mask}]}, {})
        assert restored_layer[50, 100, 0] > masked[50, 100, 0]
        rotated = module.transformed_layer({}, {**blue_layer, "rotation": 90}, (200, 100))
        assert rotated.width > rotated.height
        ramp = np.linspace(0, 65535, 4096, dtype=np.uint16)
        gradient = np.repeat(ramp[None, :, None], 3, axis=2)
        layered = module.compose_image_layers(gradient, {"imageLayers": [{**red_layer, "width": .8}]}, {})
        assert len(np.unique(layered[0, :, 1])) > 1000
        source = root / "base.png"; Image.new("RGB", (160, 120), (60, 80, 100)).save(source)
        item = make_item(source); module.prepare_item(item)
        copy_source = {**red_layer,"id":"copy-source","width":.6,
            "paintStrokes":[{"mode":"paint","color":"#00ff00","size":.1,
            "hardness":1,"opacity":1,"points":[[.5,.5]]}]}
        copied = module.copy_layer_selection(item,{**BASE,"imageLayers":[copy_source],
            "layerId":"copy-source","rect":{"x0":.25,"y0":.2,"x1":.75,"y1":.8}})
        copied_asset = module.load_layer_asset(copied["assetId"])
        assert copied_asset and copied_asset.width > 1 and copied_asset.height > 1
        assert 0 < copied["layerWidth"] < copy_source["width"]
        settings = {**BASE, "colorNoise": 0, "imageLayers": [
            {**red_layer, "x": .55, "y": .45, "width": .5, "rotation": 23,
             "blendMode": "overlay", "paintStrokes": [paint],
             "mask": {"enabled": True, "invert": False,
             "strokes": [{"erase": True, "size": .12, "hardness": .5,
                           "opacity": .7, "points": [[.2, .3], [.4, .5]]}]}}]}
        full = module.developed_array(item, settings)
        viewport = {"x": 35, "y": 25, "width": 80, "height": 55}
        tile = module._developed_tile_array(item, {**settings, "viewport": viewport})
        crop = full[25:80, 35:115]
        diff = float(np.mean(np.abs(np.asarray(module.image8_from_u16(tile), dtype=np.float32)
                                    - np.asarray(module.image8_from_u16(crop), dtype=np.float32))))
        assert diff < 2.5, f"layer tile differs: {diff:.2f}"
        raw = source.read_bytes()
        common = {"fingerprint": module.file_fingerprint(raw),
                  "fingerprint_v2": module.file_fingerprint_v2(raw)}
        first = {**common, "name": "before.png"}
        second = {**common, "name": "renamed.png"}
        module.save_recipe(first, {"imageLayers": [red_layer]})
        restored = module.load_recipe(second)
        assert restored["imageLayers"][0]["assetId"] == red["assetId"]
        print(f"IMAGE_LAYERS_OK 7blend/mask/paint/erase/copy/order/rotation/uint16/tile {diff:.2f}/rename")
    finally:
        module.IMAGES_DIR, module.RECIPE_DIR, module.LAYER_ASSET_DIR = old
        module._LAYER_CACHE.clear()

def _make_test_psd(path, layers, size=(400, 300)):
    """検査用のPSDを組む。🚫 Pillowもpsd-toolsもPSDを書けないので自前で組む。
    長さの計算に注意＝layer_and_mask = 4 + layer_info + 4(global mask)。
    ここを +4+4 にすると後続の読み取り位置がずれて「Invalid signature」になる（実際に踏んだ）。"""
    import io
    import struct
    import numpy as np
    from PIL import Image
    W, H = size
    be = lambda n, v: v.to_bytes(n, "big")
    out = io.BytesIO()
    out.write(b"8BPS" + be(2, 1) + b"\0" * 6 + be(2, 3)
              + be(4, H) + be(4, W) + be(2, 8) + be(2, 3))
    out.write(be(4, 0)); out.write(be(4, 0))
    li = io.BytesIO(); li.write(be(2, len(layers))); planes = []
    for box, col, name, mode, opacity, visible in layers:
        l, t, r, b = box
        arr = np.asarray(Image.new("RGBA", (r - l, b - t), col))
        data = [(cid, be(2, 0) + arr[:, :, 3 if cid == -1 else cid].tobytes())
                for cid in (-1, 0, 1, 2)]
        li.write(be(4, t) + be(4, l) + be(4, b) + be(4, r) + be(2, 4))
        for cid, raw in data:
            li.write(struct.pack(">h", cid) + be(4, len(raw)))
        li.write(b"8BIM" + mode + be(1, opacity) + be(1, 0)
                 + be(1, 0 if visible else 2) + be(1, 0))
        nm = name.encode("mac_roman"); pad = (4 - ((1 + len(nm)) % 4)) % 4
        extra = be(4, 0) + be(4, 0) + be(1, len(nm)) + nm + b"\0" * pad
        li.write(be(4, len(extra)) + extra); planes.append(data)
    for data in planes:
        for cid, raw in data:
            li.write(raw)
    lib = li.getvalue()
    if len(lib) % 2:
        lib += b"\0"
    out.write(be(4, 4 + len(lib) + 4)); out.write(be(4, len(lib)) + lib); out.write(be(4, 0))
    flat = np.asarray(Image.new("RGB", (W, H), (255, 255, 255)))
    out.write(be(2, 0))
    for c in range(3):
        out.write(flat[:, :, c].tobytes())
    Path(path).write_bytes(out.getvalue())


def check_path_mask(module):
    """レイヤー切り抜き（ベジェのパスマスク）とパス＋ブラシ併用、
    そして選択範囲の内側だけ塗る限定塗りを検証する。"""
    # 中央を囲む四角（0.25〜0.75）。コーナー＝ハンドルが自分と同じ座標
    def corner(x, y):
        return {"x": x, "y": y, "inX": x, "inY": y, "outX": x, "outY": y}
    square = [corner(.25, .25), corner(.75, .25), corner(.75, .75), corner(.25, .75)]

    # ① パスだけのマスク: 内側は残り、外側は消える
    mask, used = module.normalized_layer_mask(
        {"enabled": True, "path": square, "strokes": []}, 12000)
    assert mask is not None and len(mask["path"]) == 4, mask
    assert used == 4, used
    plane = np.asarray(module.layer_mask_image(mask, (200, 200)), dtype=np.float32) / 255
    assert plane[100, 100] > .95, f"内側が残らない {plane[100, 100]:.3f}"
    assert plane[10, 10] < .05, f"外側が消えない {plane[10, 10]:.3f}"

    # ② ベジェの曲線が効く（ハンドルを引いた形は直線の四角と面積が変わる）
    curved = [dict(n) for n in square]
    curved[0].update(outX=.25, outY=-.2)   # 上辺を外へ膨らませる
    curved[1].update(inX=.75, inY=-.2)
    mask2, _ = module.normalized_layer_mask(
        {"enabled": True, "path": curved, "strokes": []}, 12000)
    plane2 = np.asarray(module.layer_mask_image(mask2, (200, 200)), dtype=np.float32) / 255
    assert plane2.sum() > plane.sum() * 1.05, "ハンドルを引いても形が変わらない（直線近似になっている）"

    # ③ パス＋ブラシの消しゴムを併用（大枠をパスで取り、内側をブラシで削る）
    mask3, _ = module.normalized_layer_mask({"enabled": True, "path": square, "strokes": [
        {"erase": True, "size": .1, "hardness": 1, "opacity": 1, "points": [[.5, .5]]}]}, 12000)
    plane3 = np.asarray(module.layer_mask_image(mask3, (200, 200)), dtype=np.float32) / 255
    assert plane3[100, 100] < .1, f"ブラシで削れていない {plane3[100, 100]:.3f}"
    assert plane3[100, 60] > .8, f"パスの他の部分が消えた {plane3[100, 60]:.3f}"

    # ④ 空のマスク＋invert は全面非表示（既存挙動を壊していないこと）
    empty, _ = module.normalized_layer_mask(
        {"enabled": True, "invert": True, "strokes": []}, 12000)
    assert empty is not None, "空マスクが捨てられている（invertだけのマスクが効かなくなる）"
    plane4 = np.asarray(module.layer_mask_image(empty, (40, 40)), dtype=np.float32) / 255
    assert plane4.max() < .02, f"invertで全面非表示にならない {plane4.max():.3f}"

    # ⑤ 選択範囲の内側だけ塗る（limitToMask）
    # 🔑 size は長辺比で上限0.1にクランプされる＝200pxなら中心±10px。
    #    選択範囲をそれより小さく取って、はみ出しが止まることを測る
    base = np.full((200, 200, 3), 30000, dtype=np.uint16)
    stroke = {"mode": "paint", "color": "#ff0000", "size": .1, "hardness": 1,
              "opacity": 1, "points": [[.5, .5]]}
    region = {"points": [[.5, .5], [.56, .5], [.56, .56], [.5, .56]],
              "feather": 0, "invert": False, "enabled": True,
              "adjust": {"exposure": 0}}
    free = module.apply_pixel_edits(base.copy(), {"pixelEdits": [stroke]})
    assert not np.array_equal(free[100, 100], base[100, 100]), "塗りが効いていない"
    assert not np.array_equal(free[95, 95], base[95, 95]), "筆の範囲内が塗れていない"
    limited = module.apply_pixel_edits(
        base.copy(), {"pixelEdits": [{**stroke, "limitToMask": 0}], "masks": [region]})
    assert not np.array_equal(limited[102, 102], base[102, 102]), "選択範囲の内側が塗れていない"
    assert np.array_equal(limited[95, 95], base[95, 95]), "選択範囲の外にはみ出している"
    print("PATH_MASK_OK 切り抜き/曲線/パス＋消しゴム/空invert維持/選択範囲限定塗り")


def check_psd_import(module):
    """PSD読み込み: 座標・サイズ・ブレンド・不透明度の変換と、取り込めないものの警告。"""
    try:
        import psd_tools  # noqa: F401
    except ImportError:
        print("PSD_IMPORT_SKIP psd-toolsが未導入（.venv/bin/pip install psd-tools）")
        return
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        psd = Path(tmp) / "t.psd"
        _make_test_psd(psd, [
            ((0, 0, 200, 150), (230, 60, 60, 255), "red-box", b"norm", 255, True),
            ((120, 90, 380, 280), (60, 120, 230, 180), "blue-box", b"mul ", 204, True),
            ((50, 50, 250, 200), (60, 200, 120, 255), "soft-light", b"sLit", 255, True),
            ((10, 10, 100, 100), (0, 0, 0, 255), "hidden", b"norm", 255, False),
        ])
        result = module.import_psd_layers(psd.read_bytes())
    # 非表示1枚は取り込まない
    assert result["count"] == 3, f"取り込み枚数={result['count']}（期待3）"
    assert result["canvas"] == {"width": 400, "height": 300}, result["canvas"]
    by_name = {layer["name"]: layer for layer in result["layers"]}
    assert "hidden" not in by_name, "非表示レイヤーを取り込んでいる"
    # PSDの絶対座標 → PictureKitの相対座標（中心基準）
    red = by_name["red-box"]
    assert abs(red["x"] - .25) < .002 and abs(red["y"] - .25) < .002, red
    assert abs(red["width"] - .5) < .002, red["width"]
    blue = by_name["blue-box"]
    assert blue["blendMode"] == "multiply", blue["blendMode"]
    assert abs(blue["opacity"] - 204 / 255) < .01, blue["opacity"]
    # PictureKitに無いブレンドは normal に落とし、理由を notes に残す
    assert by_name["soft-light"]["blendMode"] == "normal"
    assert any("SOFT_LIGHT" in note for note in result["notes"]), result["notes"]
    # サーバーが受け取る形（正規化）を通過できること
    normalized = module.image_layer_settings({"imageLayers": result["layers"]})
    assert len(normalized) == 3, f"正規化後={len(normalized)}枚"
    for layer in result["layers"]:
        assert module.layer_asset_path(layer["assetId"]).is_file(), layer["name"]
    print(f"PSD_IMPORT_OK {result['count']}枚/非表示除外/座標・乗算80%・"
          f"非対応ブレンドの警告{len(result['notes'])}件")


def check_high_precision(module):
    """色調整から最終出力まで16bit階調を保持し、TIFFへ格納する。"""
    ramp = np.linspace(0, 65535, 4096, dtype=np.uint16)
    linear = np.repeat(ramp[None, :, None], 3, axis=2)
    transformed = module.transform_chunk(linear, {"colorNoise": 0})
    assert transformed.dtype == np.uint16 and transformed.nbytes == transformed.size * 2
    assert len(np.unique(transformed[:, :, 0])) > 1000, "tone pipeline collapsed to 8bit"
    detailed = module.apply_detail(transformed, {"colorNoise": 0}, 4096)
    assert detailed.dtype == np.uint16 and len(np.unique(detailed[:, :, 0])) > 1000
    body = module.tiff16_bytes(detailed)
    decoded = module.tifffile.imread(io.BytesIO(body))
    assert decoded.dtype == np.uint16 and decoded.shape == detailed.shape
    with module.tifffile.TiffFile(io.BytesIO(body)) as tif:
        page = tif.pages[0]
        bits = page.bitspersample
        assert bits == 16 or tuple(bits) == (16, 16, 16)
        assert 34675 in page.tags, "sRGB ICC profile missing"
    print(f"PRECISION16_OK levels={len(np.unique(decoded[:, :, 0]))} bytes={len(body)}")


def check_ui(module):
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'fetch("/api/render-preview"' in html
    assert 'fetch("/api/render-tile"' in html and 'id="zoom100"' in html
    assert 'value="tiff16"' in html
    assert 'fetch("/api/mask-overlay"' in html
    assert 'fetch("/api/mask-outline"' in html and 'id="maskOutline"' in html
    assert all(f'id="{name}"' in html for name in ("maskBrushAdd", "maskBrushSize",
        "maskBrushHardness", "maskBrushOpacity", "maskBrushErase", "maskBrushClear"))
    assert 'mode:"brush"' in html and 'strokes' in html
    assert all(f'id="{name}"' in html for name in ("layerSurface", "layerFile",
        "layerSelect", "layerTools", "layerVisible", "layerSize", "layerRotation",
        "layerOpacity", "layerBlend", "layerDown", "layerUp", "layerDelete",
        "layerMaskAdd", "layerMaskEdit", "layerMaskEnabled", "layerMaskInvert",
        "layerMaskSize", "layerMaskHardness", "layerMaskOpacity", "layerMaskErase",
        "layerMaskClear", "layerMaskRemove", "layerBlank", "layerDuplicate",
        "layerCopySelect", "layerPaste", "layerPaintEdit", "layerPaintErase",
        "layerPaintColor", "layerPaintSize", "layerPaintHardness", "layerPaintOpacity",
        "layerPaintUndo", "layerPaintClear"))
    assert "serializeImageLayers" in html and "syncLayerSurface" in html
    assert all(f'id="{name}"' in html for name in ("contentFillActive", "contentFillSize",
        "contentFillHardness", "contentFillOpacity", "contentFillSearch",
        "contentFillUndo", "contentFillClear"))
    assert "serializeContentFills" in html and "contentFillDraft" in html
    assert 'fetch("/api/content-fill-plan"' in html
    assert all(f'id="{name}"' in html for name in ("liquifyActive", "liquifyMode",
        "liquifySize", "liquifyStrength", "liquifyUndo", "liquifyClear"))
    assert "serializeLiquifyEdits" in html and "liquifyDraft" in html
    assert all(f'id="{name}"' in html for name in ("pixelEditActive","pixelMode","pixelSize","pixelHardness","pixelOpacity","pixelColor","pixelBlurStrength","pixelCloneSource","pixelUndo","pixelClear"))
    assert "serializePixelEdits" in html and "pixelEditDrag" in html
    assert all(f'id="{name}"' in html for name in ("panelRaw", "panelEdit", "rawQuick", "resetHint"))
    assert "PANEL_LAYOUTS" in html and "setPanelMode" in html and "picturekitPanelMode" in html
    # ホイール自由ズーム（fit未満へは潜らない・ドラッグでパン）
    assert 'addEventListener("wheel"' in html and "applyZoom" in html
    # 井桁グリッド＋角度調整のCSS即時プレビュー
    assert 'id="gridToggle"' in html and "drawGrid" in html
    assert "renderedStraighten" in html
    # 書き出し中のスピナー表示（ボタンが無反応に見えない）
    assert "setBusy" in html and "pkspin" in html
    # チャンネル別多点トーンカーブ（輝度/R/G/Bタブ・単調3次補間・タブは1列）
    assert html.count('data-ch="') == 4 and "curvetabs" in html
    assert "curveLut" in html and "sanitizeCurve" in html
    assert ".curvetabs{grid-template-columns:1fr 1fr 1fr 1fr}" in html
    # 白黒ミキサー（白黒ON時にカラーミキサーと入れ替わる）
    assert 'id="bwRows"' in html and "refreshMixerMode" in html
    # ルックLUT（.cube読込・適用量・アップロード）
    assert 'id="lutSelect"' in html and 'id="lutAmount"' in html
    assert 'fetch("/api/lut?name="' in html
    assert 'id="lensProfile"' in html and 'id="cameraProfile"' in html
    assert 'id="mixerRows"' in html and 'id="gradeRows"' in html
    assert 'id="photoInfo"' in html and 'id="cameras"' not in html
    assert 'id="strip"' in html and 'id="exportAll"' in html
    assert ('id="exportSize"' in html and 'id="exportFormat"' in html
            and 'id="exportSharpen"' in html)
    # ライブラリの絞り込み（星0〜5・キーワード・撮影日・機種）とキーボード星付け
    assert all(f'id="{name}"' in html for name in ("filterRating", "filterKeyword",
        "filterCamera", "filterDateFrom", "filterDateTo", "filterClear",
        "rateStars", "photoKeywords"))
    assert "photoVisible" in html and "function setRating" in html and "clampRating" in html
    # 書き出しプリセットと、絞り込んだ写真の一括書き出し（進み具合・中止）
    assert all(f'id="{name}"' in html for name in ("exportPreset", "exportPresetSave",
        "exportPresetDelete", "exportNamePattern", "exportBatch", "batchCancel",
        "batchProgress", "batchBarFill"))
    assert 'fetch("/api/export-presets"' in html
    # カードUI: sectionの開閉が揃っている（BezierKit骨格の暗色版）
    assert html.count('<section class="card">') == html.count("</section>") == 19
    assert html.count('type="file" multiple') == 2  # 複数選択（ライブラリ）
    assert "webkitdirectory" in html and "webkitGetAsEntry" in html  # フォルダ対応
    assert "recordHistory" in html and "applyHistory" in html  # Cmd+Z undo/redo
    assert 'fetch("/api/auto"' in html
    assert "createImageBitmap" in html
    assert 'pictureKit:2,pipeline:"libraw-linear-v1"' in html
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    storage = Path(tempfile.mkdtemp(prefix="picturekit-api-"))
    old_storage = (module.IMAGES_DIR, module.RECIPE_DIR, module.LAYER_ASSET_DIR)
    module.IMAGES_DIR, module.RECIPE_DIR = storage, storage / "recipes"
    module.LAYER_ASSET_DIR = storage / "assets"; module._LAYER_CACHE.clear()
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sample = io.BytesIO()
        Image.new("RGB", (64, 48), (24, 48, 96)).save(sample, "PNG")
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=30)
        origin = f"http://127.0.0.1:{server.server_port}"
        connection.request("POST", "/api/open?name=sample.png", sample.getvalue(),
                           {"Content-Type": "application/octet-stream", "Origin": origin})
        response = connection.getresponse()
        opened = json.loads(response.read())
        assert response.status == 200 and opened["pipeline"] == "libraw-linear-v1"
        blank_payload = json.dumps({"token": opened["token"], **BASE}).encode()
        connection.request("POST", "/api/layer-blank", blank_payload,
                           {"Content-Type":"application/json", "Origin":origin})
        response = connection.getresponse(); blank_meta = json.loads(response.read())
        assert response.status == 200 and blank_meta["width"] == 64 and blank_meta["height"] == 48
        assert len(blank_meta["assetId"]) == 64 and blank_meta["aspect"] > 1
        layer_data = io.BytesIO(); Image.new("RGBA", (24, 12), (240, 20, 30, 180)).save(layer_data, "PNG")
        connection.request("POST", "/api/layer-asset?token=" + opened["token"] + "&name=logo.png",
                           layer_data.getvalue(), {"Origin": origin})
        response = connection.getresponse(); layer_meta = json.loads(response.read())
        assert response.status == 200 and len(layer_meta["assetId"]) == 64
        connection.request("GET", "/api/layer-asset/" + layer_meta["assetId"])
        response = connection.getresponse(); layer_png = response.read()
        assert response.status == 200 and layer_png.startswith(b"\x89PNG")
        assert response.getheader("X-Content-Type-Options") == "nosniff"
        connection.request("GET", "/api/layer-asset/" + "0" * 64)
        assert connection.getresponse().status == 404
        connection.request("POST", "/api/layer-asset?token=" + opened["token"] + "&name=fake.png",
                           b"<html>", {"Origin": origin})
        assert connection.getresponse().status == 400
        api_layer = {"id": "api-layer", "assetId": layer_meta["assetId"],
            "name": "logo", "visible": True, "x": .5, "y": .5,
            "width": .5, "rotation": 17, "opacity": .8, "blendMode": "screen",
            "paintStrokes": [{"mode":"paint","color":"#00ff00","size":.1,
                "hardness":.7,"opacity":1,"points":[[.5,.5]]}],
            "mask": {"enabled": True, "invert": False, "strokes": [{
                "erase": True, "size": .12, "hardness": .6, "opacity": .8,
                "points": [[.1, .1], [.2, .1]]}]}}
        copy_payload = json.dumps({"token":opened["token"],**BASE,
            "imageLayers":[api_layer],"layerId":"api-layer",
            "rect":{"x0":.2,"y0":.2,"x1":.8,"y1":.8}}).encode()
        connection.request("POST","/api/layer-copy",copy_payload,
                           {"Content-Type":"application/json","Origin":origin})
        response=connection.getresponse();copy_meta=json.loads(response.read())
        assert response.status==200 and len(copy_meta["assetId"])==64
        assert copy_meta["layerWidth"]>0 and copy_meta["width"]>1
        api_liquify = {"mode": "push", "points": [[.35, .5], [.45, .5]],
                        "size": .04, "strength": .7}
        fill_draft = {"points": [[.5, .5]], "size": .08, "hardness": .7,
                      "opacity": 1, "searchRadius": .4}
        fill_plan_payload = json.dumps({"token": opened["token"], **BASE,
                                        "contentFillDraft": fill_draft}).encode()
        plans = []
        for _ in range(2):
            connection.request("POST", "/api/content-fill-plan", fill_plan_payload,
                               {"Content-Type": "application/json", "Origin": origin})
            response = connection.getresponse(); plans.append(json.loads(response.read()))
            assert response.status == 200 and "source" in plans[-1]
        assert plans[0]["source"] == plans[1]["source"]
        api_fill = plans[0]
        payload = json.dumps({"token": opened["token"], **BASE}).encode()
        connection.request("POST", "/api/render-preview", payload,
                           {"Content-Type": "application/json", "Origin": origin})
        response = connection.getresponse()
        preview = response.read()
        assert response.status == 200 and preview.startswith(b"\x89PNG")
        # 選択マスクの輪郭は画像を含まないSVGテキストとして返る
        outline_payload = json.dumps({
            "token": opened["token"], **BASE, "maskIndex": 0,
            "masks": [{"points": [[0, 0], [.5, 0], [.5, 1], [0, 1]],
                       "feather": 0}]}).encode()
        connection.request("POST", "/api/mask-outline", outline_payload,
                           {"Content-Type": "application/json", "Origin": origin})
        response = connection.getresponse()
        outlined = json.loads(response.read())
        assert response.status == 200 and outlined["paths"] >= 1
        assert '<path d="M ' in outlined["svg"] and 'fill="none"' in outlined["svg"]
        assert "<image" not in outlined["svg"]
        brush_mask = {"mode": "brush", "strokes": [{"erase": False,
            "size": .18, "hardness": .7, "opacity": .8,
            "points": [[.1, .5], [.9, .5]]}], "feather": 0,
            "adjust": {"exposure": 1}}
        brush_payload = json.dumps({"token": opened["token"], **BASE,
            "maskIndex": 0, "masks": [brush_mask]}).encode()
        connection.request("POST", "/api/mask-overlay", brush_payload,
                           {"Content-Type": "application/json", "Origin": origin})
        response = connection.getresponse()
        brush_overlay = Image.open(io.BytesIO(response.read())).convert("RGBA")
        assert response.status == 200 and np.max(np.asarray(brush_overlay)[:, :, 3]) > 60
        connection.request("POST", "/api/mask-outline", brush_payload,
                           {"Content-Type": "application/json", "Origin": origin})
        response = connection.getresponse()
        brush_outline = json.loads(response.read())
        assert response.status == 200 and brush_outline["paths"] >= 1
        # recipe永続化: brush strokesを含めて保存→同じ写真を開き直すと返る
        recipe_payload = json.dumps({"token": opened["token"],
                                     "recipe": {**BASE, "exposure": 1.5,
                                                "masks": [brush_mask],
                                                "contentFills": [api_fill],
                                                "liquifyEdits": [api_liquify],
                                                "pixelEdits": [{"mode":"paint","points":[[.4,.5],[.6,.5]],"size":.08,"hardness":1,"opacity":1,"color":"#00ff00"}],
                                                "imageLayers": [api_layer]}}).encode()
        connection.request("POST", "/api/recipe", recipe_payload,
                           {"Content-Type": "application/json", "Origin": origin})
        assert connection.getresponse().status == 200
        connection.request("POST", "/api/open?name=renamed.png", sample.getvalue(),
                           {"Content-Type": "application/octet-stream",
                            "Origin": origin})
        reopened = json.loads(connection.getresponse().read())
        assert reopened["recipe"]["exposure"] == 1.5, "recipe was not restored"
        restored_brush = reopened["recipe"]["masks"][0]
        assert restored_brush["mode"] == "brush"
        assert restored_brush["strokes"][0]["points"] == [[.1, .5], [.9, .5]]
        restored_layer = reopened["recipe"]["imageLayers"][0]
        assert restored_layer["assetId"] == layer_meta["assetId"]
        assert restored_layer["blendMode"] == "screen"
        assert restored_layer["mask"]["strokes"][0]["erase"] is True
        assert restored_layer["paintStrokes"][0]["color"] == "#00ff00"
        assert reopened["recipe"]["contentFills"][0]["source"] == api_fill["source"]
        assert reopened["recipe"]["liquifyEdits"][0]["mode"] == "push"
        assert reopened["recipe"]["pixelEdits"][0]["mode"] == "paint"
        # 書き出し強化: 長辺リサイズ＋PNG＋出力シャープ
        export_payload = json.dumps({"token": opened["token"], **BASE,
                                     "exportSize": 32, "exportFormat": "png",
                                     "exportSharpen": True}).encode()
        connection.request("POST", "/api/export", export_payload,
                           {"Content-Type": "application/json", "Origin": origin})
        response = connection.getresponse()
        exported = response.read()
        assert response.status == 200 and exported.startswith(b"\x89PNG")
        assert "image/png" in str(response.getheader("Content-Type"))
        small = Image.open(io.BytesIO(exported))
        assert max(small.size) == 32, f"export resize failed: {small.size}"
        layer_export = json.dumps({"token": opened["token"], **BASE,
            "exportFormat": "png", "imageLayers": [api_layer]}).encode()
        connection.request("POST", "/api/export", layer_export,
                           {"Content-Type": "application/json", "Origin": origin})
        response = connection.getresponse(); composed = Image.open(io.BytesIO(response.read())).convert("RGB")
        center = composed.getpixel((composed.width // 2, composed.height // 2))
        assert response.status == 200 and center[1] > center[0] and center[1] > center[2], center
        pixel_export=json.dumps({"token":opened["token"],**BASE,"exportFormat":"png","pixelEdits":[{"mode":"paint","points":[[.4,.5],[.6,.5]],"size":.1,"hardness":1,"opacity":1,"color":"#00ff00"}]}).encode()
        connection.request("POST","/api/export",pixel_export,{"Content-Type":"application/json","Origin":origin})
        response=connection.getresponse();pixel_img=Image.open(io.BytesIO(response.read())).convert("RGB")
        pc=pixel_img.getpixel((pixel_img.width//2,pixel_img.height//2));assert response.status==200 and pc[1]>pc[0],pc
        liquify_export = json.dumps({"token": opened["token"], **BASE,
            "exportFormat": "png", "liquifyEdits": [api_liquify]}).encode()
        connection.request("POST", "/api/export", liquify_export,
                           {"Content-Type": "application/json", "Origin": origin})
        response = connection.getresponse(); liquify_png = response.read()
        assert response.status == 200 and liquify_png.startswith(b"\x89PNG")
        fill_export = json.dumps({"token": opened["token"], **BASE,
            "exportFormat": "png", "contentFills": [api_fill]}).encode()
        connection.request("POST", "/api/export", fill_export,
                           {"Content-Type": "application/json", "Origin": origin})
        response = connection.getresponse(); fill_png = response.read()
        assert response.status == 200 and fill_png.startswith(b"\x89PNG")
        # TIFF書き出し（無劣化・LZW）＋任意サイズ（プリセットに無い値）
        tiff_payload = json.dumps({"token": opened["token"], **BASE,
                                   "exportSize": 40,
                                   "exportFormat": "tiff"}).encode()
        connection.request("POST", "/api/export", tiff_payload,
                           {"Content-Type": "application/json", "Origin": origin})
        response = connection.getresponse()
        tiff_bytes = response.read()
        assert response.status == 200 and tiff_bytes[:2] in (b"II", b"MM")
        assert "image/tiff" in str(response.getheader("Content-Type"))
        assert ".tif" in str(response.getheader("Content-Disposition"))
        tiff_image = Image.open(io.BytesIO(tiff_bytes))
        assert tiff_image.format == "TIFF" and max(tiff_image.size) == 40
        tiff16_payload = json.dumps({"token": opened["token"], **BASE,
                                     "exportSize": 40,
                                     "exportFormat": "tiff16"}).encode()
        connection.request("POST", "/api/export", tiff16_payload,
                           {"Content-Type": "application/json", "Origin": origin})
        response = connection.getresponse()
        tiff16_bytes = response.read()
        tiff16 = module.tifffile.imread(io.BytesIO(tiff16_bytes))
        assert response.status == 200 and tiff16.dtype == np.uint16
        assert max(tiff16.shape[:2]) == 40
        # LUTアップロード: 検証つき保存→一覧に載る
        connection.request("POST", "/api/lut?name=check-upload.cube",
                           RED_ZERO_CUBE.encode(),
                           {"Content-Type": "application/octet-stream",
                            "Origin": origin})
        lut_response = json.loads(connection.getresponse().read())
        assert lut_response.get("saved") == "check-upload.cube"
        assert "check-upload.cube" in lut_response.get("luts", [])
        (ROOT / "luts" / "check-upload.cube").unlink(missing_ok=True)
        # 切り抜き拡大: 選んだ比率のまま内側へ切り込む（100=2倍）
        crop_payload = json.dumps({"token": opened["token"], **BASE,
                                   "cropAspect": "16:9",
                                   "cropZoom": 100}).encode()
        connection.request("POST", "/api/export", crop_payload,
                           {"Content-Type": "application/json", "Origin": origin})
        response = connection.getresponse()
        disposition = response.getheader("Content-Disposition") or ""
        cropped = Image.open(io.BytesIO(response.read()))
        # 元64×48 → 16:9最大=64×36 → 2倍切り込み=32×18
        assert cropped.size == (32, 18), f"cropZoom failed: {cropped.size}"
        assert 'filename="sample_developed.jpg"' in disposition and "filename*=UTF-8''" in disposition, disposition
        # 星・キーワードはrecipeへ非破壊で乗り、開き直すと返る（サーバーで0〜5・文字列へ正規化）
        meta_payload = json.dumps({"token": opened["token"],
            "recipe": {**BASE, "rating": 4, "keywords": ["夕焼け", "海", "海"]}}).encode()
        connection.request("POST", "/api/recipe", meta_payload,
                           {"Content-Type": "application/json", "Origin": origin})
        assert connection.getresponse().status == 200
        connection.request("POST", "/api/open?name=rated.png", sample.getvalue(),
                           {"Content-Type": "application/octet-stream", "Origin": origin})
        rated = json.loads(connection.getresponse().read())["recipe"]
        assert rated["rating"] == 4 and rated["keywords"] == ["夕焼け", "海"], rated
        clamp_payload = json.dumps({"token": opened["token"],
            "recipe": {**BASE, "rating": 9, "keywords": ["  空  ", "空", 42, ""]}}).encode()
        connection.request("POST", "/api/recipe", clamp_payload,
                           {"Content-Type": "application/json", "Origin": origin})
        assert connection.getresponse().status == 200
        connection.request("POST", "/api/open?name=rated2.png", sample.getvalue(),
                           {"Content-Type": "application/octet-stream", "Origin": origin})
        clamped = json.loads(connection.getresponse().read())["recipe"]
        assert clamped["rating"] == 5 and clamped["keywords"] == ["空", "42"], clamped
        # 書き出しpreset: 保存→読み込み、不正値はclamp/既定へ
        preset_body = json.dumps({"presets": [{"name": "Web JPEG", "format": "jpeg",
            "size": 2048, "quality": 88, "sharpen": True, "srgb": True,
            "namePattern": "{name}_web"}]}).encode()
        connection.request("POST", "/api/export-presets", preset_body,
                           {"Content-Type": "application/json", "Origin": origin})
        saved_presets = json.loads(connection.getresponse().read())["presets"]
        assert saved_presets[0]["name"] == "Web JPEG" and saved_presets[0]["size"] == 2048
        connection.request("GET", "/api/export-presets")
        loaded_presets = json.loads(connection.getresponse().read())["presets"]
        assert (loaded_presets[0]["namePattern"] == "{name}_web"
                and loaded_presets[0]["quality"] == 88), loaded_presets
        bad_body = json.dumps({"presets": [{"name": "変な値", "format": "bmp",
            "size": 999999, "quality": 5, "namePattern": "x"}]}).encode()
        connection.request("POST", "/api/export-presets", bad_body,
                           {"Content-Type": "application/json", "Origin": origin})
        fixed = json.loads(connection.getresponse().read())["presets"][0]
        assert (fixed["format"] == "jpeg" and fixed["size"] <= 20000
                and fixed["quality"] >= 60 and fixed["srgb"] is True), fixed
        # 一括書き出し: 3枚を1つのpresetで出し、出力枚数と長辺pxが合う
        batch_tokens = []
        for index, (bw, bh) in enumerate([(80, 40), (40, 90), (60, 60)]):
            buf = io.BytesIO()
            Image.new("RGB", (bw, bh), (30 + index * 10, 60, 90)).save(buf, "PNG")
            connection.request("POST", f"/api/open?name=batch{index}.png", buf.getvalue(),
                               {"Content-Type": "application/octet-stream", "Origin": origin})
            batch_tokens.append(json.loads(connection.getresponse().read())["token"])
        long_edges = []
        for batch_token in batch_tokens:
            batch_export = json.dumps({"token": batch_token, **BASE,
                "exportFormat": "jpeg", "exportSize": 48}).encode()
            connection.request("POST", "/api/export", batch_export,
                               {"Content-Type": "application/json", "Origin": origin})
            long_edges.append(max(Image.open(io.BytesIO(connection.getresponse().read())).size))
        assert len(long_edges) == 3 and all(edge == 48 for edge in long_edges), long_edges
        connection.close()
        if not chrome.exists():
            print("UI_API_OK; Chrome DOM check skipped")
            return
        result = subprocess.run(
            [str(chrome), "--headless=new", "--disable-gpu", "--no-sandbox",
             "--virtual-time-budget=1200", "--dump-dom",
             f"http://127.0.0.1:{server.server_port}"],
            capture_output=True, text=True, timeout=30, check=False
        )
        assert result.returncode == 0 and 'id="exposureNumber"' in result.stdout
        # CONTROLS 28本（+切り抜き拡大+LUT適用量+フリンジ軽減2本）＋書き出し任意サイズ入力の29
        assert result.stdout.count('class="number"') == 29
        assert 'id="defringeNumber"' in result.stdout and 'id="defringeGreenNumber"' in result.stdout
        assert 'id="cropZoomNumber"' in result.stdout
        assert 'id="exportCustom"' in result.stdout
        assert 'value="tiff"' in result.stdout and 'value="tiff16"' in result.stdout
        assert 'id="straightenNumber"' in result.stdout
        assert 'id="luminanceNoiseNumber"' in result.stdout
        assert 'id="colorNoiseNumber"' in result.stdout
        assert 'id="vignetteNumber"' in result.stdout
        assert 'id="lensAmountNumber"' in result.stdout
        assert 'id="copyRecipe"' in result.stdout
        assert result.stdout.count('class="mixrange"') == 16  # カラー8+白黒8
        assert result.stdout.count('class="graderange') == 3
        # マスクは共通スライダー方式: 専用rangeはぼかし＋許容量の2本、対象chipsがある
        assert result.stdout.count('class="maskrange"') == 2
        assert result.stdout.count('class="brushrange"') == 3
        assert result.stdout.count('class="layerrange"') == 3
        assert result.stdout.count('class="layermaskrange"') == 3
        assert result.stdout.count('class="layerpaintrange"') == 3
        assert result.stdout.count('class="pixelrange"') == 4
        assert 'id="contentFillActive"' in result.stdout and 'id="contentFillSearch"' in result.stdout
        assert 'id="pixelMode"' in result.stdout and 'id="pixelCloneSource"' in result.stdout
        assert 'id="layerBlend"' in result.stdout and 'id="layerMaskEdit"' in result.stdout
        assert 'id="layerFile"' in result.stdout and 'id="layerSurface"' in result.stdout
        assert 'id="maskColorAdd"' in result.stdout
        assert 'id="maskBrushAdd"' in result.stdout
        assert 'id="maskBrushErase"' in result.stdout
        assert 'id="maskTolerance"' in result.stdout
        assert 'id="maskContiguous"' in result.stdout
        assert 'id="maskShowOverlay"' in result.stdout
        # マスク選択はプルダウン（位置と色の自動ラベル付き・チップ廃止）
        assert 'id="maskScope"' in result.stdout and 'id="maskTools"' in result.stdout
        assert "maskLabel" in result.stdout
        assert 'id="maskEnabled"' in result.stdout
        assert 'id="maskAdd"' in result.stdout and 'id="overlay"' in result.stdout
        assert 'id="healAdd"' in result.stdout
        assert result.stdout.count('class="healrange"') == 1
        assert 'id="wbPick"' in result.stdout and 'id="grainNumber"' in result.stdout
        assert 'id="gradeBlendingNumber"' in result.stdout
        assert 'id="gradeBalanceNumber"' in result.stdout
        assert "LibRaw 16bit linear" in result.stdout
        print("UI_OK server preview + 25 numeric controls + 8 mixer bands"
              " + 3 grading rows")
        check_preset_js(server.server_port)
        check_new_features_js(server.server_port)
        check_library_js(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        module.IMAGES_DIR, module.RECIPE_DIR, module.LAYER_ASSET_DIR = old_storage
        module._LAYER_CACHE.clear()


def check_preset_js(port):
    """プリセット選択で色の状態が取り残されないこと（実ブラウザでonchangeを発火して確認）。
    以前は白黒プリセットの後に別のプリセットを選んでも白黒が解除されなかった。"""
    cdp_path = Path(__file__).resolve().parent.parent / "BezierKit" / "cdp-check.py"
    if not cdp_path.exists():
        print("PRESET_JS skipped (BezierKit/cdp-check.py が無い)")
        return
    spec = importlib.util.spec_from_file_location("pk_cdp", cdp_path)
    cdp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cdp)
    chrome, sock = cdp.boot(f"http://127.0.0.1:{port}",
                            "typeof PRESETS!=='undefined' && typeof applyRecipe==='function'")
    try:
        data = json.loads(cdp.ev(sock, """JSON.stringify((()=>{
          const $$=id=>document.getElementById(id);
          const pick=v=>{const s=$$('preset');s.value=v;s.dispatchEvent(new Event('change'));};
          const snap=()=>({mono:$$('monochrome').checked,
            sat:mixer.sat.reduce((a,b)=>a+Math.abs(b),0),
            bw:bwMix.reduce((a,b)=>a+Math.abs(b),0),
            grade:GRADE_RANGES.reduce((a,r)=>a+grading[r].hue+grading[r].sat+Math.abs(grading[r].lum),0),
            contrast:+$$('contrast').value,
            straighten:+$$('straighten').value,cropZoom:+$$('cropZoom').value,
            quality:+$$('quality').value,lensAmount:+$$('lensAmount').value,
            selectValue:$$('preset').value,
            labelColor:$$('monochrome').closest('label').style.color,
            layers:imageLayers.length,blend:imageLayers[0]?.blendMode,
            maskPoints:imageLayers[0]?.mask?.strokes?.[0]?.points?.length||0,
            fillCount:contentFills.length,fillAlgorithm:contentFills[0]?.algorithm,
            liquifyCount:liquifyEdits.length,liquifyMode:liquifyEdits[0]?.mode,
            pixelCount:pixelEdits.length,pixelMode:pixelEdits[0]?.mode});
          // 画像layerと色系を作ってからpresetを当てる。presetはlayerを保持する
          applyRecipe({masks:[{points:[[.1,.1],[.2,.1],[.2,.2]],feather:0,adjust:{exposure:1}}],retouch:[{x:.5,y:.5,sx:.2,sy:.5,r:.03,mode:'heal'}],contentFills:[{algorithm:'boundary-copy-v1',points:[[.5,.5]],source:[.2,.5],size:.03,hardness:.7,opacity:1,searchRadius:.25}],liquifyEdits:[{mode:'push',points:[[.2,.3],[.4,.3]],size:.03,strength:.6}],pixelEdits:[{mode:'paint',points:[[.2,.3]],size:.03,hardness:.7,opacity:1,color:'#ff0000'}],imageLayers:[{id:'keep-layer',assetId:'a'.repeat(64),name:'keep',visible:true,x:.5,y:.5,width:.3,rotation:0,opacity:1,blendMode:'multiply',paintStrokes:[{mode:'paint',color:'#00ff00',size:.1,hardness:.7,opacity:1,points:[[.3,.3],[.4,.4]]}],mask:{enabled:true,invert:false,strokes:[{erase:true,size:.1,hardness:.7,opacity:1,points:[[.2,.3],[.4,.5]]}]}}]});
          const cardKey=new Map(Object.entries(panelCards).map(([key,card])=>[card,key]));
          const visibleKeys=()=>[...document.querySelectorAll('.right > .card')].filter(card=>card.style.display!=='none').map(card=>cardKey.get(card));
          setPanelMode('raw');const rawOrder=visibleKeys();
          setPanelMode('edit',true);const editOrder=visibleKeys(),editQuickHidden=$$('rawQuick').hidden,storedMode=localStorage.getItem('picturekitPanelMode');
          const panelRetained={layers:imageLayers.length,retouch:retouches.length,fills:contentFills.length,liquify:liquifyEdits.length,pixels:pixelEdits.length};
          layerIndex=0;$$('layerDuplicate').click();const duplicateAssetShared=imageLayers.length===2&&imageLayers[1].assetId===imageLayers[0].assetId;
          imageLayers[1].paintStrokes[0].points[0][0]=.9;imageLayers[1].mask.strokes[0].points[0][0]=.8;
          const duplicateIndependent=imageLayers[0].paintStrokes[0].points[0][0]===.3&&imageLayers[0].mask.strokes[0].points[0][0]===.2;
          imageLayers.splice(1,1);layerIndex=0;refreshLayerUI();
          setPanelMode('raw',true);const rawQuickVisible=!$$('rawQuick').hidden;
          mixer.sat=Array(8).fill(40);bwMix=Array(8).fill(30);
          GRADE_RANGES.forEach(r=>{grading[r]={hue:200,sat:50,lum:10};});
          $$('straighten').value=2.5;$$('cropZoom').value=40;$$('quality').value=80;$$('lensAmount').value=120;
          pick('mono');const afterMono=snap();const monoStatus=$$('status').textContent;
          pick('vivid');const afterVivid=snap();
          setPanelMode('raw');$$('exposure').value=1.2;const rawResetLabel=$$('reset').textContent;$$('reset').click();
          const rawReset={exposure:+$$('exposure').value,quality:+$$('quality').value,masks:masks.length,layers:imageLayers.length,retouch:retouches.length,fills:contentFills.length,liquify:liquifyEdits.length,pixels:pixelEdits.length,status:$$('status').textContent};
          applyRecipe({exposure:1.3,masks:[{points:[[.1,.1],[.2,.1],[.2,.2]],feather:0,adjust:{exposure:1}}]});
          setPanelMode('edit');const editResetLabel=$$('reset').textContent;$$('reset').click();
          const editReset={exposure:+$$('exposure').value,quality:+$$('quality').value,masks:masks.length,layers:imageLayers.length,retouch:retouches.length,fills:contentFills.length,liquify:liquifyEdits.length,pixels:pixelEdits.length,status:$$('status').textContent};
          return {afterMono,afterVivid,monoStatus,rawOrder,editOrder,editQuickHidden,rawQuickVisible,storedMode,panelRetained,duplicateAssetShared,duplicateIndependent,rawResetLabel,editResetLabel,rawReset,editReset};})())"""))
        mono, vivid = data["afterMono"], data["afterVivid"]
        assert mono["mono"] is True, f"白黒プリセットで白黒にならない: {mono}"
        assert mono["contrast"] == 20, f"白黒プリセットの値が入らない: {mono}"
        assert mono["labelColor"], f"白黒ONでチェックが強調されない: {mono}"
        assert "白黒" in data["monoStatus"], f"白黒プリセットの案内が出ない: {data['monoStatus']}"
        assert data["rawOrder"] == ["profile", "wb", "light", "curve", "color", "mixer",
            "grading", "lut", "detail", "lens", "crop", "mask", "retouch", "settings", "export"], data["rawOrder"]
        assert data["editOrder"] == ["layers", "retouch", "contentFill", "pixel", "liquify",
            "settings", "export"], data["editOrder"]
        assert data["editQuickHidden"] and data["rawQuickVisible"] and data["storedMode"] == "edit"
        assert data["panelRetained"] == {"layers": 1, "retouch": 1, "fills": 1, "liquify": 1, "pixels": 1}
        assert data["duplicateAssetShared"] and data["duplicateIndependent"], "layer duplicate shared mutable state"
        assert data["rawResetLabel"] == "RAW現像をリセット" and data["editResetLabel"] == "画像編集をリセット"
        raw_reset, edit_reset = data["rawReset"], data["editReset"]
        assert raw_reset["exposure"] == 0 and raw_reset["masks"] == 0 and raw_reset["quality"] == 80, raw_reset
        assert all(raw_reset[key] == 1 for key in ("layers", "retouch", "fills", "liquify", "pixels")), raw_reset
        assert "画像編集は保持" in raw_reset["status"]
        assert edit_reset["exposure"] == 1.3 and edit_reset["masks"] == 1 and edit_reset["quality"] == 80, edit_reset
        assert all(edit_reset[key] == 0 for key in ("layers", "retouch", "fills", "liquify", "pixels")), edit_reset
        assert "RAW現像は保持" in edit_reset["status"]
        # ここが本体の回帰: 別プリセットを選んだら白黒・ミキサー・白黒ミキサー・グレーディングが戻る
        assert vivid["mono"] is False, f"別プリセットを選んでも白黒が解除されない: {vivid}"
        assert vivid["sat"] == 0, f"カラーミキサーが取り残される: {vivid}"
        assert vivid["bw"] == 0, f"白黒ミキサーが取り残される: {vivid}"
        assert vivid["grade"] == 0, f"カラーグレーディングが取り残される: {vivid}"
        assert vivid["contrast"] == 18, f"鮮やかプリセットの値が入らない: {vivid}"
        assert not vivid["labelColor"], f"白黒OFFで強調が消えない: {vivid}"
        assert vivid["selectValue"] == "", f"プリセット選択が空に戻らない: {vivid}"
        # 幾何・レンズ補正・書き出し品質はプリセットで動かさない
        for snapshot in (mono, vivid):
            assert abs(snapshot["straighten"] - 2.5) < 1e-6, f"水平補正がプリセットで消える: {snapshot}"
            assert snapshot["cropZoom"] == 40, f"切り抜き拡大がプリセットで消える: {snapshot}"
            assert snapshot["quality"] == 80, f"書き出し品質がプリセットで戻る: {snapshot}"
            assert snapshot["lensAmount"] == 120, f"レンズ補正量がプリセットで戻る: {snapshot}"
            assert snapshot["layers"] == 1, f"プリセットで画像layerが消えた: {snapshot}"
            assert snapshot["blend"] == "multiply" and snapshot["maskPoints"] == 2, f"プリセットでblend/maskが消えた: {snapshot}"
            assert snapshot["fillCount"] == 1 and snapshot["fillAlgorithm"] == "boundary-copy-v1", f"プリセットでContent Fillが消えた: {snapshot}"
            assert snapshot["liquifyCount"] == 1 and snapshot["liquifyMode"] == "push", f"プリセットでLiquifyが消えた: {snapshot}"
            assert snapshot["pixelCount"] == 1 and snapshot["pixelMode"] == "paint", f"プリセットでpixel editが消えた: {snapshot}"
        print("PRESET_JS_OK 白黒→別プリセットで色が戻り、切り抜き・水平・レンズ補正・品質は保たれる")
    finally:
        chrome.terminate()


def _cdp_wait(cdp, sock, expression, label, attempts=150):
    for _ in range(attempts):
        if cdp.ev(sock, expression): return
        time.sleep(.1)
    raise AssertionError(f"{label}: {cdp.ev(sock, '$(`status`)?.textContent||``')}")


def _cdp_drag(cdp, sock, selector, start, end):
    rect = json.loads(cdp.ev(sock, f"JSON.stringify(document.querySelector('{selector}').getBoundingClientRect())"))
    def point(p): return rect["x"]+rect["width"]*p[0], rect["y"]+rect["height"]*p[1]
    x0,y0=point(start);x1,y1=point(end)
    cdp.call(sock,"Input.dispatchMouseEvent",{"type":"mousePressed","x":x0,"y":y0,"button":"left","buttons":1,"clickCount":1})
    for i in range(1,6):
        t=i/5;cdp.call(sock,"Input.dispatchMouseEvent",{"type":"mouseMoved","x":x0+(x1-x0)*t,"y":y0+(y1-y0)*t,"button":"left","buttons":1})
    cdp.call(sock,"Input.dispatchMouseEvent",{"type":"mouseReleased","x":x1,"y":y1,"button":"left","buttons":0,"clickCount":1})


def check_new_features_js(port):
    cdp_path=Path(__file__).resolve().parent.parent/"BezierKit"/"cdp-check.py"
    if not cdp_path.exists(): print("NEW_FEATURES_JS skipped");return
    spec=importlib.util.spec_from_file_location("pk_e2e_cdp",cdp_path);cdp=importlib.util.module_from_spec(spec);spec.loader.exec_module(cdp)
    chrome,sock=cdp.boot(f"http://127.0.0.1:{port}","typeof openFiles==='function' && typeof finishContentFill==='function'")
    try:
        loaded=cdp.ev(sock,"""(async()=>{const cv=document.createElement('canvas');cv.width=320;cv.height=240;const c=cv.getContext('2d');c.fillStyle='#64788c';c.fillRect(0,0,320,240);for(let y=0;y<240;y+=20){c.fillStyle=y%40?'#708498':'#586c80';c.fillRect(0,y,320,10);}c.fillStyle='#d02030';c.fillRect(140,100,40,40);const blob=await new Promise(r=>cv.toBlob(r,'image/png'));await openFiles([new File([blob],'e2e.png',{type:'image/png'})]);for(let i=0;i<200&&!sourcePixels;i++)await new Promise(r=>setTimeout(r,20));return!!sourcePixels;})()""",await_promise=True)
        assert loaded,"browser photo load failed"
        cdp.ev(sock,"setPanelMode('raw',true);$('maskBrushAdd').click();true")
        _cdp_drag(cdp,sock,"#overlay",(.2,.25),(.35,.35))
        assert cdp.ev(sock,"masks.at(-1)?.strokes?.[0]?.points?.length>1")
        cdp.ev(sock,"setPanelMode('edit',true);$('contentFillSearch').value=50;$('contentFillActive').click();true")
        _cdp_drag(cdp,sock,"#overlay",(.46,.46),(.54,.54))
        _cdp_wait(cdp,sock,"!contentFillPlanning","content fill planning")
        assert cdp.ev(sock,"contentFills.length===1")
        cdp.ev(sock,"$('liquifyActive').click();true");_cdp_drag(cdp,sock,"#overlay",(.35,.5),(.48,.5))
        assert cdp.ev(sock,"liquifyEdits.length===1&&liquifyEdits[0].points.length>1")
        cdp.ev(sock,"$('pixelEditActive').click();$('pixelMode').value='paint';$('pixelMode').dispatchEvent(new Event('change'));true")
        _cdp_drag(cdp,sock,"#overlay",(.2,.7),(.35,.7))
        cdp.ev(sock,"$('pixelMode').value='erase';$('pixelMode').dispatchEvent(new Event('change'));true");_cdp_drag(cdp,sock,"#overlay",(.3,.7),(.32,.7))
        cdp.ev(sock,"$('pixelMode').value='clone';$('pixelMode').dispatchEvent(new Event('change'));$('pixelCloneSource').click();true")
        _cdp_drag(cdp,sock,"#overlay",(.15,.15),(.15,.15));_cdp_drag(cdp,sock,"#overlay",(.65,.2),(.72,.2))
        cdp.ev(sock,"$('pixelMode').value='blur';$('pixelMode').dispatchEvent(new Event('change'));true");_cdp_drag(cdp,sock,"#overlay",(.7,.7),(.76,.7))
        assert json.loads(cdp.ev(sock,"JSON.stringify(pixelEdits.map(s=>s.mode))"))==["paint","erase","clone","blur"]
        cdp.ev(sock,"stopPixelEdit();$('layerBlank').click();true")
        _cdp_wait(cdp,sock,"imageLayers.length===1&&!!document.querySelector('#layerSurface canvas[data-layer-index=\"0\"]')","blank layer")
        cdp.ev(sock,"$('layerPaintEdit').click();true");_cdp_drag(cdp,sock,"#layerSurface canvas[data-layer-index=\"0\"]",(.25,.3),(.55,.45))
        cdp.ev(sock,"$('layerPaintErase').checked=true;true");_cdp_drag(cdp,sock,"#layerSurface canvas[data-layer-index=\"0\"]",(.45,.4),(.48,.4))
        assert cdp.ev(sock,"imageLayers[0].paintStrokes.map(s=>s.mode).join(',')==='paint,erase'")
        cdp.ev(sock,"$('layerDuplicate').click();true")
        _cdp_wait(cdp,sock,"imageLayers.length===2&&!!document.querySelector('#layerSurface canvas[data-layer-index=\"1\"]')","duplicate layer")
        cdp.ev(sock,"$('layerCopySelect').click();true");_cdp_drag(cdp,sock,"#layerSurface canvas[data-layer-index=\"1\"]",(.15,.15),(.8,.8))
        _cdp_wait(cdp,sock,"!!layerClipboard","layer copy")
        cdp.ev(sock,"$('layerPaste').click();true")
        _cdp_wait(cdp,sock,"imageLayers.length===3&&!!document.querySelector('#layerSurface canvas[data-layer-index=\"2\"]')","layer paste")
        cdp.ev(sock,"$('layerMaskAdd').click();true");_cdp_drag(cdp,sock,"#layerSurface canvas[data-layer-index=\"2\"]",(.3,.3),(.6,.4))
        result=json.loads(cdp.ev(sock,"JSON.stringify({mask:masks.at(-1).strokes.length,fill:contentFills.length,liquify:liquifyEdits.length,pixels:pixelEdits.map(s=>s.mode),layers:imageLayers.length,paint:imageLayers[0].paintStrokes.map(s=>s.mode),duplicate:imageLayers[1].assetId===imageLayers[0].assetId,pasteMask:imageLayers[2].mask?.strokes?.length||0,recipePaint:settings().imageLayers[0].paintStrokes.length})"))
        assert result=={"mask":1,"fill":1,"liquify":1,"pixels":["paint","erase","clone","blur"],"layers":3,"paint":["paint","erase"],"duplicate":True,"pasteMask":1,"recipePaint":2},result
        print("NEW_FEATURES_JS_OK mask/content-fill/liquify/pixel4/blank/paint/erase/duplicate/copy-paste/layer-mask")
    finally: chrome.terminate()


def check_library_js(port):
    """ライブラリの絞り込み（星・キーワード・機種・撮影日）とキーボード星付けを実ブラウザで確認。"""
    cdp_path = Path(__file__).resolve().parent.parent / "BezierKit" / "cdp-check.py"
    if not cdp_path.exists():
        print("LIBRARY_JS skipped (BezierKit/cdp-check.py が無い)")
        return
    spec = importlib.util.spec_from_file_location("pk_lib_cdp", cdp_path)
    cdp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cdp)
    chrome, sock = cdp.boot(f"http://127.0.0.1:{port}",
                            "typeof openFiles==='function' && typeof photoVisible==='function'")
    try:
        loaded = cdp.ev(sock, """(async()=>{
          const mk=(w,h,c)=>new Promise(r=>{const cv=document.createElement('canvas');cv.width=w;cv.height=h;const x=cv.getContext('2d');x.fillStyle=c;x.fillRect(0,0,w,h);cv.toBlob(b=>r(new File([b],'lib-'+c.slice(1)+'.png',{type:'image/png'})));});
          const files=await Promise.all([mk(80,40,'#114488'),mk(40,90,'#228844'),mk(60,60,'#aa5522')]);
          await openFiles(files);for(let i=0;i<200&&photos.length<3;i++)await new Promise(r=>setTimeout(r,20));return photos.length;})()""",
                         await_promise=True)
        assert loaded == 3, f"3枚開けなかった: {loaded}"
        data = json.loads(cdp.ev(sock, """JSON.stringify((()=>{
          photos.forEach((p,i)=>{p.model=i<2?'RICOH GR III':'SIGMA fp';p.info={date:['2026/08/01 10:00:00','2026/08/15 10:00:00','2026/09/20 10:00:00'][i]};});
          renderStrip();
          selectPhoto(0);document.dispatchEvent(new KeyboardEvent('keydown',{key:'3'}));const r0=photos[0].rating;
          setRating(5);selectPhoto(1);setRating(2);selectPhoto(2);setRating(5);
          photos[0].keywords=['海','夕焼け'];photos[1].keywords=['山'];photos[2].keywords=['海'];
          const vis=()=>photos.map(p=>photoVisible(p));
          const set=(id,v,ev)=>{document.getElementById(id).value=v;document.getElementById(id).dispatchEvent(new Event(ev||'input'));};
          set('filterRating','5');const byStar=vis();
          set('filterRating','0');set('filterKeyword','海');const byKw=vis();
          set('filterKeyword','');set('filterCamera','SIGMA fp');const byCam=vis();
          set('filterCamera','');set('filterDateFrom','2026-08-10');set('filterDateTo','2026-08-31');const byDate=vis();
          document.getElementById('filterClear').click();const afterClear=vis();
          const shown=[...document.querySelectorAll('#strip .shot')].filter(s=>s.style.display!=='none').length;
          return {r0,ratings:photos.map(p=>p.rating),byStar,byKw,byCam,byDate,afterClear,shown};})())"""))
        assert data["r0"] == 3, f"キーボード3で星3にならない: {data}"
        assert data["ratings"] == [5, 2, 5], data["ratings"]
        assert data["byStar"] == [True, False, True], data["byStar"]
        assert data["byKw"] == [True, False, True], data["byKw"]
        assert data["byCam"] == [False, False, True], data["byCam"]
        assert data["byDate"] == [False, True, False], data["byDate"]
        assert data["afterClear"] == [True, True, True] and data["shown"] == 3, data
        print("LIBRARY_JS_OK 星/キーワード/機種/撮影日の絞り込み＋キーボード星付け")
    finally:
        chrome.terminate()


def check_fixes_2026_11_02(module):
    """2026-11-02の修正: WB係数の拡大とrecipe換算、DCPのLUT化、非RAWにプロファイルを
    掛けない、TIFFへのEXIF、スポット修復のコピー元探索、写真を閉じる、Liquifyのin-place化。"""
    import tifffile
    from PIL import ImageDraw
    migrated = module.migrate_recipe({"temperature": -40, "tint": 10,
                                      "masks": [{"adjust": {"temperature": 20}}]})
    assert (migrated["temperature"] == -10 and migrated["tint"] == 4
            and migrated["masks"][0]["adjust"]["temperature"] == 5
            and migrated["wbModel"] == module.WB_MODEL), migrated
    assert module.migrate_recipe({"temperature": -40, "wbModel": 2})["temperature"] == -40
    gains = module.wb_gains({"temperature": 100})
    assert abs(gains[0] / gains[2] - 4) < 1e-3, "±100でR/Bが2段動くこと"
    dcp = (module.load_camera_profile("RICOH GR III", "Adobe Standard")
           or module.load_camera_profile("PENTAX K-1", "Adobe Standard"))
    if dcp is not None:
        rng = np.random.default_rng(1)
        linear = (rng.random((64, 64, 3), dtype=np.float32) ** 2).astype(np.float32)
        direct = module.srgb_encode(module.apply_dcp(linear, dcp))
        error = np.abs(direct - module.apply_dcp_encoded(linear, dcp)) * 255
        assert error.mean() < .5 and error.max() < 6, \
            f"DCP LUT deviates: mean {error.mean():.2f} max {error.max():.2f}"
    assert module.load_camera_profile("", module.KIT_STANDARD) is module.KIT_STANDARD_PROFILE
    work = Path(tempfile.mkdtemp(prefix="picturekit-fix-"))
    flat = work / "flat.png"
    Image.new("RGB", (64, 64), (120, 120, 120)).save(flat)
    item = make_item(flat)
    module.prepare_item(item)
    assert module.item_dcp(item, {"cameraProfile": "Adobe Standard"}) is None, \
        "JPEG/PNGにカメラプロファイルを掛けない"
    exif = Image.Exif()
    exif[272] = "PictureKit Test"
    ifd = exif.get_ifd(34665)
    ifd[34855] = 400
    ifd[33434] = (1, 250)
    ifd[37386] = (183, 10)
    rgb16 = np.full((8, 8, 3), 30000, dtype=np.uint16)
    tiff_bytes = module.tiff16_bytes(rgb16, exif)
    back = Image.open(io.BytesIO(tiff_bytes)).getexif()
    assert back.get(272) == "PictureKit Test" and back.get_ifd(34665).get(34855) == 400
    assert abs(float(back.get_ifd(34665).get(33434)) - .004) < 1e-9
    assert int(tifffile.imread(io.BytesIO(tiff_bytes)).max()) == 30000, "TIFFの画素が無傷"
    canvas = Image.new("RGB", (240, 160), (120, 130, 140))
    ImageDraw.Draw(canvas).ellipse((110, 70, 130, 90), fill=(30, 30, 30))
    spotted = work / "spot.png"
    canvas.save(spotted)
    plan = module.plan_heal_source(make_item(spotted),
                                   {**BASE, "healSpot": {"x": .5, "y": .5, "r": .06}})
    assert 0 <= plan["sx"] <= 1 and 0 <= plan["sy"] <= 1
    assert np.hypot((plan["sx"] - .5) * 240, (plan["sy"] - .5) * 160) > 14, \
        "コピー元は修復先と重ならない"
    module.FILES["fix-token"] = {"dir": module.WORK / "fix-token", "lock": threading.Lock()}
    (module.WORK / "fix-token").mkdir(exist_ok=True)
    (module.WORK / "fix-token" / "x.npy").write_bytes(b"0")
    assert module.close_item("fix-token")["ok"]
    assert "fix-token" not in module.FILES and not (module.WORK / "fix-token").exists()
    base = np.full((60, 80, 3), 20000, dtype=np.uint16)
    base[20:40, 30:50] = 50000
    before = base.copy()
    edit = {"mode": "push", "points": [[.4, .5], [.6, .5]], "size": .2, "strength": .8}
    out = module.apply_liquify(base, {"liquifyEdits": [edit]})
    assert np.array_equal(base, before), "apply_liquifyは入力を書き換えない"
    assert out.shape == base.shape and not np.array_equal(out, base)
    # 100%表示のレンズ補正は領域だけ計算（LazyLens）。全面cacheと画素が一致すること
    gradient = Image.fromarray(np.dstack([np.tile(np.linspace(0, 255, 160, dtype=np.uint8), (120, 1)),
                                          np.tile(np.linspace(255, 0, 120, dtype=np.uint8)[:, None], (1, 160)),
                                          np.full((120, 160), 128, np.uint8)]), "RGB")
    lens_src = work / "lens.png"
    gradient.save(lens_src)
    lens_item = make_item(lens_src)
    module.prepare_item(lens_item)
    tilt = {**BASE, "straighten": 3}
    lazy = module.source_linear(lens_item, tilt, lazy=True)
    assert isinstance(lazy, module.LazyLens) and lazy.shape == (120, 160, 3)
    full = module.source_linear(lens_item, tilt)
    assert np.array_equal(np.asarray(lazy[20:70, 30:140]), np.asarray(full[20:70, 30:140]))
    assert np.array_equal(lazy[::7, ::9], np.asarray(full[::7, ::9]))
    assert isinstance(module.source_linear(lens_item, tilt, lazy=True), np.ndarray), \
        "全面cacheがあればlazyでもcacheを使う"
    tile = module.developed_tile(lens_item, {**tilt, "viewport": {"x": 20, "y": 10, "width": 80, "height": 60}})
    whole = module.developed_image(lens_item, tilt)
    tile_diff = np.abs(np.asarray(tile, dtype=np.int16) - np.asarray(whole.crop((20, 10, 100, 70)), dtype=np.int16))
    assert tile_diff.max() <= 2, f"tile differs from full: {tile_diff.max()}"
    # フリンジ軽減: 白い円の紫の縁（薄い3px）は消え、エッジから離れた紫の面は変わらない
    scene = Image.new("RGB", (480, 320), (60, 70, 40))
    draw = ImageDraw.Draw(scene)
    draw.ellipse((60, 80, 200, 220), fill=(180, 60, 200))
    draw.ellipse((300, 70, 440, 250), fill=(190, 110, 230))
    draw.ellipse((303, 73, 437, 247), fill=(255, 255, 255))
    rgb16 = (np.asarray(scene, dtype=np.float32) / 255 * 65535).astype(np.uint16)
    cleaned = module.apply_defringe(rgb16, {"defringe": 100}, 480)
    def chroma(arr, y, x):
        pixel = arr[y, x].astype(np.int32)
        return int(pixel.max() - pixel.min())
    assert chroma(cleaned, 160, 301) < chroma(rgb16, 160, 301) * .35, "purple ring was not reduced"
    assert chroma(cleaned, 150, 130) == chroma(rgb16, 150, 130), "purple object away from edges changed"
    assert np.array_equal(module.apply_defringe(rgb16, {"defringe": 0}, 480), rgb16)
    assert module.libraw_message(Exception(b"Unsupported file format or not RAW file")).startswith("RAWとして読めません")
    assert "LibRaw" in module.libraw_message(Exception(b"Something odd"))
    print("FIXES_OK wbModel換算/DCP LUT/非RAWプロファイル無し/TIFF EXIF/heal探索/閉じる/liquify in-place/LazyLens/LibRaw文言/フリンジ軽減")


def main():
    module = load_picturekit()
    check_shadow_color(module)
    check_channel_curves(module)
    check_bw_mix(module)
    check_lut(module)
    check_grading(module)
    check_masks(module)
    check_brush_masks(module)
    check_retouch(module)
    check_wb_pick(module)
    check_grain(module)
    check_content_fill(module)
    check_liquify(module)
    check_pixel_edits(module)
    check_image_layers(module)
    check_path_mask(module)
    check_psd_import(module)
    check_high_precision(module)
    check_fixes_2026_11_02(module)
    check_real_dng(module, "--full" in sys.argv)
    check_ui(module)
    print("PICTUREKIT_CHECK_OK")


if __name__ == "__main__":
    main()
