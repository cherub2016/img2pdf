#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
img2pdf.py - 智能图片转 A4 PDF 工具（EXIF 校正 + OCR 文字方向检测 + 批量处理）

用法：
  python img2pdf.py <源目录> [输出目录]

说明：
  - 递归扫描源目录及其子目录；
  - 每个含图片的目录生成一个 PDF，文件名为 <目录名>.pdf；
  - 若指定输出目录，则所有 PDF 文件统一保存在输出目录下；
  - 先 EXIF 校正，再 OCR 检测方向；
  - 自动横竖页面、等比缩放、居中；
  - 命令行日志彩色输出。
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

# 初始化 colorama
colorama_init(autoreset=True)
A4_W, A4_H = A4


# ========= 日志输出函数 =========
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


# ========= 图像处理函数 =========
def correct_exif_orientation(im: Image.Image) -> Image.Image:
    """根据 EXIF Orientation 修正图像方向"""
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


def detect_ocr_rotation(im: Image.Image):
    """使用 pytesseract 检测文字方向（返回需顺时针旋转角度）"""
    try:
        osd = pytesseract.image_to_osd(im)
        for line in osd.splitlines():
            if line.startswith("Rotate:"):
                angle = int(line.split(":")[1].strip())
                return angle, None
        return 0, None
    except Exception as e:
        log_warn(f"OCR 方向检测失败：{e}")
        return 0, None


def ensure_rgb(im: Image.Image) -> Image.Image:
    """转换为 RGB 并去除透明背景"""
    if im.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")
    return im


# ========= PDF 生成核心函数 =========
def make_pdf_from_images(img_paths, out_pdf_path):
    """将图片序列写入 PDF"""
    out_dir = os.path.dirname(out_pdf_path)
    base_name = os.path.splitext(os.path.basename(out_pdf_path))[0]
    temp_fd, temp_path = tempfile.mkstemp(prefix=base_name + "_", suffix=".pdf", dir=out_dir)
    os.close(temp_fd)

    try:
        c = canvas.Canvas(temp_path, pagesize=A4)

        for idx, img_path in enumerate(img_paths, start=1):
            img_name = os.path.basename(img_path)
            log_proc(f"处理 {idx}/{len(img_paths)}: {img_name}")

            try:
                with Image.open(img_path) as im:
                    # Step 1: EXIF 校正
                    im = correct_exif_orientation(im)

                    # Step 2: OCR 检测文字方向
                    rot, _ = detect_ocr_rotation(im)
                    if rot not in (0, 90, 180, 270):
                        rot = 0
                    if rot != 0:
                        im = im.rotate(-rot, expand=True)
                        log_proc(f"  OCR 建议顺时针旋转 {rot}° → 已调整")

                    im = ensure_rgb(im)
                    w, h = im.size

                    # Step 3: 页面方向
                    if w > h:
                        page_size = landscape(A4)
                        page_dir = "横向"
                    else:
                        page_size = portrait(A4)
                        page_dir = "竖向"
                    c.setPageSize(page_size)
                    page_w, page_h = page_size

                    # Step 4: 等比缩放并居中
                    scale = min(page_w / w, page_h / h)
                    new_w, new_h = w * scale, h * scale
                    x = (page_w - new_w) / 2
                    y = (page_h - new_h) / 2

                    bio = BytesIO()
                    im.save(bio, format="JPEG")
                    bio.seek(0)
                    ir = ImageReader(bio)

                    log_proc(f"  尺寸 {w}x{h} → {int(new_w)}x{int(new_h)} | 页面: {page_dir}")
                    c.drawImage(ir, x, y, new_w, new_h, preserveAspectRatio=True)
                    c.showPage()
                    bio.close()

            except Exception as e_img:
                log_warn(f"跳过图片 {img_name}（错误：{e_img}）")
                traceback.print_exc()

        c.save()
        os.replace(temp_path, out_pdf_path)
        log_save(f"生成 PDF：{out_pdf_path}")

    except PermissionError:
        log_err("无法覆盖目标文件（可能被打开）")
    except Exception as e:
        log_err(f"PDF 生成失败：{e}")
        traceback.print_exc()
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


# ========= 工具函数 =========
def gather_image_files_in_dir(dir_path):
    """返回目录中所有 jpg/jpeg 文件（按名称升序）"""
    imgs = [
        os.path.join(dir_path, f)
        for f in os.listdir(dir_path)
        if os.path.isfile(os.path.join(dir_path, f))
        and f.lower().endswith((".jpg", ".jpeg"))
    ]
    imgs.sort()
    return imgs


def process_recursive(src_root, out_root=None):
    """递归扫描目录并生成 PDF"""
    for current_dir, dirs, files in os.walk(src_root):
        images = gather_image_files_in_dir(current_dir)
        if not images:
            continue

        log_info(f"目录: {current_dir}")
        log_info(f"  发现 {len(images)} 张图片")

        dir_name = os.path.basename(os.path.normpath(current_dir))
        pdf_name = f"{dir_name}.pdf"

        if out_root:
            os.makedirs(out_root, exist_ok=True)
            out_pdf = os.path.join(out_root, pdf_name)
        else:
            out_pdf = os.path.join(current_dir, pdf_name)

        make_pdf_from_images(images, out_pdf)


# ========= 主函数 =========
def main():
    parser = argparse.ArgumentParser(
        description="图片批量转 A4 PDF（EXIF 校正 + OCR 文字方向检测）。"
    )
    parser.add_argument("src", help="源目录（必填）")
    parser.add_argument("out", nargs="?", default=None, help="可选输出目录，若省略则保存到源目录。")
    args = parser.parse_args()

    src = os.path.abspath(args.src)
    if not os.path.isdir(src):
        log_err(f"源目录不存在：{src}")
        sys.exit(2)

    out_dir = None
    if args.out:
        out_dir = os.path.abspath(args.out)
        os.makedirs(out_dir, exist_ok=True)

    log_info(f"开始处理源目录：{src}")
    if out_dir:
        log_info(f"输出目录：{out_dir}")
    else:
        log_info("输出目录未指定，PDF 将保存到各自子目录中。")

    process_recursive(src, out_dir)
    log_info("✅ 全部处理完成。")


if __name__ == "__main__":
    main()
