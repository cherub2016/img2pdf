#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
img2pdf_parallel.py - 并行加速版（EXIF 校正 + OCR 文字方向检测 + 多进程子目录处理）

用法：
  python img2pdf_parallel.py <源目录> [输出目录]
"""

import os
import sys
import argparse
import tempfile
import traceback
from io import BytesIO
from PIL import Image, ExifTags
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.utils import ImageReader
import pytesseract
from colorama import init as colorama_init, Fore, Style
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

# 初始化颜色
colorama_init(autoreset=True)
A4_W, A4_H = A4


# ========= 日志函数 =========
def log_info(msg): print(f"{Fore.CYAN}[INFO]{Style.RESET_ALL} {msg}")
def log_proc(msg): print(f"{Fore.YELLOW}[PROC]{Style.RESET_ALL} {msg}")
def log_save(msg): print(f"{Fore.GREEN}[SAVE]{Style.RESET_ALL} {msg}")
def log_warn(msg): print(f"{Fore.MAGENTA}[WARN]{Style.RESET_ALL} {msg}")
def log_err(msg): print(f"{Fore.RED}[ERR]{Style.RESET_ALL} {msg}")


# ========= 图像处理 =========
def correct_exif_orientation(im: Image.Image) -> Image.Image:
    try:
        exif = im._getexif()
        if not exif: return im
        orientation_key = next((k for k, v in ExifTags.TAGS.items() if v == "Orientation"), None)
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


def detect_ocr_rotation(im: Image.Image):
    try:
        osd = pytesseract.image_to_osd(im)
        for line in osd.splitlines():
            if line.startswith("Rotate:"):
                angle = int(line.split(":")[1].strip())
                return angle
        return 0
    except Exception:
        return 0


def ensure_rgb(im: Image.Image) -> Image.Image:
    if im.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")
    return im


# ========= PDF 生成 =========
def make_pdf_from_images(img_paths, out_pdf_path):
    out_dir = os.path.dirname(out_pdf_path)
    base_name = os.path.splitext(os.path.basename(out_pdf_path))[0]
    temp_fd, temp_path = tempfile.mkstemp(prefix=base_name + "_", suffix=".pdf", dir=out_dir)
    os.close(temp_fd)

    try:
        c = canvas.Canvas(temp_path, pagesize=A4)

        for idx, img_path in enumerate(img_paths, start=1):
            with Image.open(img_path) as im:
                im = correct_exif_orientation(im)
                rot = detect_ocr_rotation(im)
                if rot not in (0, 90, 180, 270):
                    rot = 0
                if rot != 0:
                    im = im.rotate(-rot, expand=True)

                im = ensure_rgb(im)
                w, h = im.size

                # 页面方向
                if w > h:
                    page_size = landscape(A4)
                else:
                    page_size = portrait(A4)
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

        c.save()
        os.replace(temp_path, out_pdf_path)
        print(f"{Fore.GREEN}[OK]{Style.RESET_ALL} {out_pdf_path}")

    except Exception as e:
        log_err(f"生成 PDF 失败：{out_pdf_path} | 错误：{e}")
        traceback.print_exc()
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except Exception: pass


# ========= 工具函数 =========
def gather_image_files_in_dir(dir_path):
    imgs = [os.path.join(dir_path, f)
            for f in os.listdir(dir_path)
            if os.path.isfile(os.path.join(dir_path, f))
            and f.lower().endswith((".jpg", ".jpeg"))]
    imgs.sort()
    return imgs


def process_one_dir(current_dir, out_root):
    images = gather_image_files_in_dir(current_dir)
    if not images:
        return
    dir_name = os.path.basename(os.path.normpath(current_dir))
    pdf_name = f"{dir_name}.pdf"
    out_pdf = os.path.join(out_root, pdf_name) if out_root else os.path.join(current_dir, pdf_name)
    make_pdf_from_images(images, out_pdf)


# ========= 并行主逻辑 =========
def process_recursive_parallel(src_root, out_root=None):
    all_dirs = []
    for current_dir, _, _ in os.walk(src_root):
        imgs = gather_image_files_in_dir(current_dir)
        if imgs:
            all_dirs.append(current_dir)

    total = len(all_dirs)
    log_info(f"共发现 {total} 个含图片的子目录。")
    if total == 0:
        return

    max_workers = min(os.cpu_count(), 8)
    log_info(f"并行处理，最大并发数：{max_workers}")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_one_dir, d, out_root): d for d in all_dirs}
        for i, future in enumerate(as_completed(futures), 1):
            d = futures[future]
            try:
                future.result()
                log_save(f"[{i}/{total}] 完成：{d}")
            except Exception as e:
                log_err(f"[{i}/{total}] 子目录处理失败：{d} | 错误：{e}")


# ========= 主函数 =========
def main():
    parser = argparse.ArgumentParser(description="并行版图片转 A4 PDF（EXIF + OCR 方向检测）")
    parser.add_argument("src", help="源目录（必填）")
    parser.add_argument("out", nargs="?", default=None, help="输出目录（可选）")
    args = parser.parse_args()

    src = os.path.abspath(args.src)
    if not os.path.isdir(src):
        log_err(f"源目录不存在：{src}")
        sys.exit(2)

    out_dir = os.path.abspath(args.out) if args.out else None
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        log_info(f"输出目录：{out_dir}")

    log_info(f"开始处理：{src}")
    process_recursive_parallel(src, out_dir)
    log_info("✅ 全部任务完成。")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
