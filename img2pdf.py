#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
img2pdf.py - 智能图片合并为 A4 PDF（EXIF 校正 + OCR 文字方向检测 + 子目录批量）

用法：
  python img2pdf.py <源目录> [输出目录]

说明：
  - 递归扫描源目录下的所有子目录（包含源目录本身）；
  - 每个含 .jpg/.jpeg 图片的目录生成一个 PDF，文件名为 <该目录名>.pdf（不带 _A4）；
  - 先读取并纠正 EXIF Orientation（若存在），再用 pytesseract.image_to_osd() 检测文字需要旋转的角度；
  - 将图片按需要旋转（使文字朝上），随后根据旋转后图片宽高决定该页为竖向或横向 A4；
  - 图片按比例缩放并居中，不裁剪、不拉伸；
  - 日志带颜色（Windows、Linux 均可），用 colorama；帮助信息用 argparse。
依赖：
  pip install pillow reportlab pytesseract colorama
并安装系统级 Tesseract OCR（https://github.com/tesseract-ocr/tesseract）
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

# 初始化 colorama（在 Windows 上启用颜色）
colorama_init(autoreset=True)

# A4 大小（points）
A4_W, A4_H = A4


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


def correct_exif_orientation(im: Image.Image) -> Image.Image:
    """根据 EXIF Orientation 修正像素方向（仅当 EXIF 存在且需要时）"""
    try:
        exif = im._getexif()
        if not exif:
            return im
        orientation_key = None
        for k, v in ExifTags.TAGS.items():
            if v == "Orientation":
                orientation_key = k
                break
        if orientation_key and orientation_key in exif:
            orientation = exif[orientation_key]
            # 值含义参见 EXIF 标准
            if orientation == 3:
                im = im.rotate(180, expand=True)
            elif orientation == 6:
                im = im.rotate(270, expand=True)  # rotate 270 ccw == 90 cw
            elif orientation == 8:
                im = im.rotate(90, expand=True)
    except Exception:
        # 忽略 EXIF 读取错误
        pass
    return im


def detect_ocr_rotation(im: Image.Image):
    """
    使用 tesseract OSD 检测需要顺时针旋转多少度以使文字正向。
    返回整数角度（0/90/180/270）和 confidence（-1 表示无法识别）。
    """
    try:
        # pytesseract.image_to_osd 返回的字符串中包含 "Rotate: N"
        osd = pytesseract.image_to_osd(im)
        # 解析 Rotate 行
        for line in osd.splitlines():
            if line.startswith("Rotate:"):
                parts = line.split(":")
                if len(parts) >= 2:
                    rot = int(parts[1].strip())
                    # pytesseract 的 Rotate 表示“顺时针需旋转角度”，
                    # 我们返回该角度作为需要顺时针旋转的度数
                    return rot, None
        return 0, None
    except Exception as e:
        # OCR 无法运行或识别时返回 None
        log_warn(f"pytesseract OSD 失败：{e}")
        return 0, None


def ensure_rgb(im: Image.Image) -> Image.Image:
    """去除透明通道并转换为 RGB"""
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


def make_pdf_from_images(img_paths, out_pdf_path):
    """
    将一组 PIL Image 或图片路径生成 PDF（可以为混合横竖页）
    按顺序将每张图片作为一页写入 PDF；为每页动态设置页面方向。
    """
    # 先在输出目录生成临时文件，完成后用 os.replace 原子替换
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
                    # 1) EXIF 校正（物理方向）
                    im = correct_exif_orientation(im)

                    # 2) OCR 检测文字方向（返回需顺时针旋转的角度）
                    rot, _ = detect_ocr_rotation(im)
                    if rot not in (0, 90, 180, 270):
                        rot = 0

                    if rot != 0:
                        # PIL rotate(angle) 是逆时针旋转 angle 度，所以顺时针旋转 rot 度用 -rot
                        im = im.rotate(-rot, expand=True)
                        log_proc(f"  → OCR 建议顺时针旋转 {rot}°；已旋转")

                    # 3) 转 RGB（去掉透明）
                    im = ensure_rgb(im)

                    w, h = im.size
                    # 决定页面方向：旋转后图片宽 > 高 -> 横向页面；否则竖向
                    if w > h:
                        page_size = landscape(A4)
                        page_w, page_h = page_size
                        # 设置当前页尺寸为横向
                        c.setPageSize(page_size)
                        page_dir = "横向"
                    else:
                        page_size = portrait(A4)
                        page_w, page_h = page_size
                        c.setPageSize(page_size)
                        page_dir = "竖向"

                    # 等比缩放并居中
                    scale = min(page_w / w, page_h / h)
                    new_w, new_h = w * scale, h * scale
                    x = (page_w - new_w) / 2
                    y = (page_h - new_h) / 2

                    # 内存流 + ImageReader
                    bio = BytesIO()
                    im.save(bio, format="JPEG")
                    bio.seek(0)
                    ir = ImageReader(bio)

                    log_proc(f"  EXIF/最终像素: {w}x{h} | 页面: {page_dir} | 缩放后: {int(new_w)}x{int(new_h)}")
                    c.drawImage(ir, x, y, new_w, new_h, preserveAspectRatio=True, anchor="c")
                    c.showPage()
                    bio.close()

            except Exception as e_img:
                log_warn(f"跳过图片 {img_name}（处理出错）：{e_img}")
                traceback.print_exc()
                continue

        c.save()

        # 尝试原子替换目标文件
        try:
            os.replace(temp_path, out_pdf_path)
            log_save(f"已生成 PDF：{out_pdf_path}")
        except PermissionError:
            log_err("无法覆盖目标文件（可能被打开）。已保留临时文件：")
            log_err(f"  {temp_path}")
            log_err("请关闭正在打开该 PDF 的程序，然后将临时文件重命名为目标文件，或重新运行脚本。")
        except Exception as e_rep:
            log_err(f"替换输出文件失败：{e_rep}")
            log_err(f"临时文件位于：{temp_path}")

    except Exception as e:
        log_err(f"生成 PDF 时发生致命错误：{e}")
        traceback.print_exc()
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def gather_image_files_in_dir(dir_path):
    """返回目录下所有 jpg/jpeg 文件（不递归），按文件名升序排序"""
    files = []
    for fname in os.listdir(dir_path):
        if not os.path.isfile(os.path.join(dir_path, fname)):
            continue
        if fname.lower().endswith((".jpg", ".jpeg")):
            files.append(os.path.join(dir_path, fname))
    files.sort()
    return files


def process_root_recursive(src_root, out_root=None):
    """
    递归遍历 src_root 的每个子目录（包含 src_root 本身）；
    若目录内含图片，则生成 PDF（若 out_root 指定，则在 out_root 中建立对应结构）。
    """
    if out_root:
        out_root = os.path.abspath(out_root)
        os.makedirs(out_root, exist_ok=True)

    # Walk through directories
    for current_dir, dirs, files in os.walk(src_root):
        rel_path = os.path.relpath(current_dir, src_root)
        # 确定输出目录
        if out_root:
            target_dir = os.path.join(out_root, rel_path) if rel_path != "." else out_root
            os.makedirs(target_dir, exist_ok=True)
        else:
            target_dir = current_dir

        images = gather_image_files_in_dir(current_dir)
        if not images:
            continue

        log_info(f"目录: {current_dir}")
        log_info(f"  发现 {len(images)} 张图片，将生成 PDF")

        # 输出 PDF 名称：目录名.pdf（若为源根目录，使用源根名）
        dir_basename = os.path.basename(os.path.normpath(current_dir))
        pdf_name = f"{dir_basename}.pdf"
        out_pdf_path = os.path.join(target_dir, pdf_name)

        make_pdf_from_images(images, out_pdf_path)


def main():
    parser = argparse.ArgumentParser(
        description="图片批量转 A4 PDF（EXIF 校正 + OCR 文字方向检测），每个含图片的子目录生成一个 PDF。"
    )
    parser.add_argument("src", help="源目录（必填），将递归扫描其子目录。")
    parser.add_argument("out", nargs="?", default=None, help="可选输出目录，若省略则 PDF 生成在源目录对应位置。")
    args = parser.parse_args()

    src = os.path.abspath(args.src)
    if not os.path.isdir(src):
        log_err(f"源目录不存在：{src}")
        sys.exit(2)

    if args.out:
        out_dir = os.path.abspath(args.out)
        if not os.path.exists(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception as e:
                log_err(f"无法创建输出目录：{out_dir}，错误：{e}")
                sys.exit(3)
    else:
        out_dir = None

    log_info(f"开始处理源目录：{src}")
    if out_dir:
        log_info(f"输出目录：{out_dir}")
    else:
        log_info("输出目录未指定，PDF 将生成在各自源子目录中。")

    process_root_recursive(src, out_dir)
    log_info("全部处理完成。")


if __name__ == "__main__":
    main()
