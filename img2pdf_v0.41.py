#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
img2pdf_v0.41.py

高性能影像归档工具（v0.41）
- OpenCV 快速方向检测（主）
- pytesseract OCR 兜底（仅当OpenCV无法判定）
- EXIF Orientation 优先处理
- 并行处理多个子文件夹
- 自然排序文件名（避免 1,10,2 的问题）
- 可选 --pdfa 使用 Ghostscript 转换为 PDF/A-1b

用法:
  python img2pdf_v4.1.py <src_dir> <out_dir> [--pdfa]

依赖:
  pip install pillow reportlab opencv-python pytesseract
系统需安装:
  - Tesseract OCR（仅在 OCR 兜底时使用）
  - Ghostscript（若使用 --pdfa）
"""

import os
import sys
import re
import argparse
import tempfile
import traceback
from io import BytesIO
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
import math

from PIL import Image, ExifTags, ImageOps
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.utils import ImageReader

# OpenCV and pytesseract imports
try:
    import cv2
except Exception:
    cv2 = None

try:
    import pytesseract
except Exception:
    pytesseract = None

# colorama optional
try:
    from colorama import init as colorama_init, Fore, Style

    colorama_init(autoreset=True)
except Exception:

    class _C:
        def __getattr__(self, _):
            return ""

    Fore = Style = _C()

A4_W, A4_H = A4


# ---------------- Logging ----------------
def log_info(msg):
    print(f"{Fore.CYAN}[INFO]{Style.RESET_ALL} {msg}")


def log_proc(msg):
    print(f"{Fore.YELLOW}[PROC]{Style.RESET_ALL} {msg}")


def log_save(msg):
    print(f"{Fore.GREEN}[SAVE]{Style.RESET_ALL} {msg}")


def log_warn(msg):
    print(f"{Fore.MAGENTA}[WARN]{Style.RESET_ALL} {msg}")


def log_err(msg):
    print(f"{Fore.RED}[ERR]{Style.RESET_ALL} {msg}")


# ---------------- Natural sort ----------------
_nat_re = re.compile(r"(\d+)")


def natural_key(s: str):
    parts = _nat_re.split(s)
    key = []
    for p in parts:
        if p.isdigit():
            key.append(int(p))
        else:
            key.append(p.lower())
    return key


# ---------------- EXIF orientation correction ----------------
def correct_exif_orientation(im: Image.Image) -> Image.Image:
    try:
        exif = im._getexif()
        if not exif:
            return im
        orientation_key = next(
            (k for k, v in ExifTags.TAGS.items() if v == "Orientation"), None
        )
        if orientation_key and orientation_key in exif:
            orientation = exif[orientation_key]
            if orientation == 3:
                im = im.rotate(180, expand=True)
            elif orientation == 6:
                im = im.rotate(270, expand=True)
            elif orientation == 8:
                im = im.rotate(90, expand=True)
    except Exception:
        pass
    return im


# ---------------- OpenCV based fast rotation detection ----------------
def detect_rotation_opencv(image_path, debug=False):
    """使用 OpenCV 快速检测图片是否应旋转 90 度（返回角度 0/90/180/270）"""
    if cv2 is None:
        return None  # OpenCV not available
    try:
        import numpy as np

        # 使用 imdecode 方式以支持中文路径
        data = np.fromfile(image_path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        h, w = img.shape[:2]
        # 缩放加速
        max_dim = 1200
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            img = cv2.resize(
                img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA
            )
        # 可选增强
        try:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            img = clahe.apply(img)
        except Exception:
            pass
        edges = cv2.Canny(img, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=math.pi / 180,
            threshold=80,
            minLineLength=30,
            maxLineGap=10,
        )
        if lines is None:
            return None
        angles = []
        for l in lines:
            x1, y1, x2, y2 = l[0]
            dx = x2 - x1
            dy = y2 - y1
            if dx == 0:
                ang = 90.0
            else:
                ang = math.degrees(math.atan2(dy, dx))
            if ang > 90:
                ang -= 180
            if ang <= -90:
                ang += 180
            angles.append(ang)
        if not angles:
            return None
        try:
            import numpy as np

            median_ang = float(np.median(np.array(angles)))
        except Exception:
            s = sorted(angles)
            n = len(s)
            mid = n // 2
            median_ang = s[mid] if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0
        if abs(median_ang) < 30:
            return 0
        elif median_ang > 30:
            return 90
        elif median_ang < -30:
            return 270
        else:
            return 0
    except Exception as e:
        if debug:
            log_warn(f"OpenCV detect error: {e}")
        return None


# ---------------- OCR fallback detection ----------------
def detect_rotation_ocr(image_path):
    """使用 pytesseract 的 OSD 来检测需要顺时针旋转的角度（0/90/180/270）"""
    if pytesseract is None:
        return 0
    try:
        with Image.open(image_path) as im:
            rgb = im.convert("RGB")
            osd = pytesseract.image_to_osd(rgb)
            for line in osd.splitlines():
                if line.strip().startswith("Rotate:"):
                    angle = int(line.split(":")[1].strip())
                    return angle % 360
    except Exception as e:
        log_warn(f"OCR detect failed: {e}")
    return 0


# ---------------- Ensure RGB ----------------
def ensure_rgb(im: Image.Image) -> Image.Image:
    if im.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        try:
            bg.paste(im, mask=im.split()[-1])
        except Exception:
            bg.paste(im)
        im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")
    return im


# ---------------- Make PDF from images ----------------
def make_pdf_from_images(img_paths, out_pdf_path):
    out_dir = os.path.dirname(out_pdf_path)
    base_name = os.path.splitext(os.path.basename(out_pdf_path))[0]
    temp_fd, temp_path = tempfile.mkstemp(
        prefix=base_name + "_", suffix=".pdf", dir=out_dir
    )
    os.close(temp_fd)
    try:
        c = canvas.Canvas(temp_path, pagesize=A4)
        for idx, img_path in enumerate(img_paths, start=1):
            img_name = os.path.basename(img_path)
            log_proc(f"    处理 {idx}/{len(img_paths)}: {img_name}")
            try:
                with Image.open(img_path) as im:
                    im = correct_exif_orientation(im)
                    rot = None
                    if cv2 is not None:
                        rot = detect_rotation_opencv(img_path)
                    if rot is None:
                        rot = detect_rotation_ocr(img_path)
                    if rot not in (0, 90, 180, 270):
                        rot = 0
                    if rot != 0:
                        im = im.rotate(-rot, expand=True)
                        log_proc(f"      已按 {rot}° 旋转（顺时针）")
                    im = ensure_rgb(im)
                    w, h = im.size
                    if w > h:
                        page_size = landscape(A4)
                        page_dir = "横向"
                    else:
                        page_size = portrait(A4)
                        page_dir = "竖向"
                    c.setPageSize(page_size)
                    page_w, page_h = page_size
                    scale = min(page_w / w, page_h / h)
                    new_w, new_h = w * scale, h * scale
                    x = (page_w - new_w) / 2
                    y = (page_h - new_h) / 2
                    bio = BytesIO()
                    im.save(bio, format="JPEG")
                    bio.seek(0)
                    ir = ImageReader(bio)
                    c.drawImage(ir, x, y, new_w, new_h, preserveAspectRatio=True)
                    c.showPage()
                    bio.close()
            except Exception as e_img:
                log_warn(f"      跳过图片 {img_name}（错误：{e_img}）")
                traceback.print_exc()
                continue
        c.save()
        try:
            os.replace(temp_path, out_pdf_path)
        except PermissionError:
            log_err(f"无法覆盖目标文件（可能被打开）：{out_pdf_path}")
            log_err(f"临时文件保留于：{temp_path}")
            return False
        log_save(f"生成 PDF: {out_pdf_path}")
        return True
    except Exception as e:
        log_err(f"生成 PDF 失败：{out_pdf_path} | 错误：{e}")
        traceback.print_exc()
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
        return False


# ---------------- Ghostscript PDF/A conversion ----------------
def convert_to_pdfa_ghostscript(input_pdf, output_pdf):
    import subprocess, shutil

    gs_cmd = "gswin64c" if os.name == "nt" else "gs"
    if not shutil.which(gs_cmd):
        log_err("Ghostscript 未找到，请安装并将其加入 PATH。")
        return False
    cmd = [
        gs_cmd,
        "-dPDFA=1",
        "-dBATCH",
        "-dNOPAUSE",
        "-dNOOUTERSAVE",
        "-dUseCIEColor",
        "-sProcessColorModel=DeviceRGB",
        "-sDEVICE=pdfwrite",
        "-dPDFACompatibilityPolicy=1",
        f"-sOutputFile={output_pdf}",
        input_pdf,
    ]
    log_proc("    调用 Ghostscript 进行 PDF/A 转换...")
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log_save(f"PDF/A 转换成功：{output_pdf}")
        return True
    except subprocess.CalledProcessError as e:
        log_err(
            f"Ghostscript 转换失败：{e}; stderr: {e.stderr.decode(errors='ignore')}"
        )
        return False


# ---------------- Directory utilities ----------------
def gather_image_files_in_dir(dir_path):
    files = []
    for fname in os.listdir(dir_path):
        p = os.path.join(dir_path, fname)
        if os.path.isfile(p) and fname.lower().endswith((".jpg", ".jpeg")):
            files.append(fname)
    files.sort(key=natural_key)
    return [os.path.join(dir_path, f) for f in files]


def collect_dirs_to_process(src_root):
    dirs = []
    for current_dir, _, _ in os.walk(src_root):
        imgs = [
            f
            for f in os.listdir(current_dir)
            if os.path.isfile(os.path.join(current_dir, f))
            and f.lower().endswith((".jpg", ".jpeg"))
        ]
        if imgs:
            dirs.append(current_dir)
    return dirs


def process_one_dir(args_tuple):
    current_dir, out_root, do_pdfa = args_tuple
    try:
        images = gather_image_files_in_dir(current_dir)
        if not images:
            return (current_dir, False, "no_images")
        dir_name = os.path.basename(os.path.normpath(current_dir))
        pdf_name = f"{dir_name}.pdf"
        if out_root:
            os.makedirs(out_root, exist_ok=True)
            out_pdf = os.path.join(out_root, pdf_name)
        else:
            out_pdf = os.path.join(current_dir, pdf_name)
        log_info(f"[{dir_name}] 开始生成 PDF（{len(images)} 张） -> {out_pdf}")
        ok = make_pdf_from_images(images, out_pdf)
        if not ok:
            return (current_dir, False, "make_pdf_failed")
        if do_pdfa:
            tmp_fd, tmp_pdfa = tempfile.mkstemp(
                prefix=dir_name + "_pdfa_", suffix=".pdf", dir=os.path.dirname(out_pdf)
            )
            os.close(tmp_fd)
            converted = convert_to_pdfa_ghostscript(out_pdf, tmp_pdfa)
            if converted:
                try:
                    os.replace(tmp_pdfa, out_pdf)
                except Exception as e:
                    log_warn(f"替换 PDF/A 文件失败：{e}（临时文件保留：{tmp_pdfa}）")
                    return (current_dir, False, "pdfa_replace_failed")
            else:
                try:
                    if os.path.exists(tmp_pdfa):
                        os.remove(tmp_pdfa)
                except Exception:
                    pass
                return (current_dir, False, "pdfa_convert_failed")
        return (current_dir, True, None)
    except Exception as e:
        traceback.print_exc()
        return (current_dir, False, str(e))


def process_recursive_parallel(src_root, out_root=None, do_pdfa=False):
    dirs = collect_dirs_to_process(src_root)
    total = len(dirs)
    log_info(f"共发现 {total} 个含图片的子目录。")
    if total == 0:
        return
    max_workers = min(os.cpu_count() or 1, 8)
    log_info(f"开始并行处理（最大并发数 {max_workers}）")
    tasks = [(d, out_root, do_pdfa) for d in dirs]
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_dir = {executor.submit(process_one_dir, t): t[0] for t in tasks}
        completed = 0
        for future in as_completed(future_to_dir):
            dirpath = future_to_dir[future]
            try:
                current_dir, ok, reason = future.result()
                completed += 1
                if ok:
                    log_save(f"[{completed}/{total}] 完成：{current_dir}")
                else:
                    log_warn(
                        f"[{completed}/{total}] 失败：{current_dir} | 原因：{reason}"
                    )
            except Exception as e:
                completed += 1
                log_err(f"[{completed}/{total}] 子任务异常：{dirpath} | 错误：{e}")


def main():
    parser = argparse.ArgumentParser(
        description="高性能图片转 A4 PDF（EXIF+OpenCV方向检测，OCR兜底，支持PDF/A）"
    )
    parser.add_argument("src", help="源目录（必填）")
    parser.add_argument(
        "out",
        nargs="?",
        default=None,
        help="输出目录（可选），若指定则所有 PDF 保存到此目录",
    )
    parser.add_argument(
        "--pdfa", action="store_true", help="生成后使用 Ghostscript 转为 PDF/A-1b"
    )
    args = parser.parse_args()
    src = os.path.abspath(args.src)
    if not os.path.isdir(src):
        log_err(f"源目录不存在：{src}")
        sys.exit(2)
    out_dir = os.path.abspath(args.out) if args.out else None
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    log_info(f"开始处理源目录：{src}")
    if out_dir:
        log_info(f"输出目录：{out_dir}")
    else:
        log_info("输出目录未指定，PDF 将生成在各自源子目录中。")
    if args.pdfa:
        log_info("已启用 PDF/A 转换（需要 Ghostscript）")
    process_recursive_parallel(src, out_dir, args.pdfa)
    log_info("全部任务完成。")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
