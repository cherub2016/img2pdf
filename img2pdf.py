#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高性能影像归档工具 (v0.47)

批量将图片转换为A4格式PDF，支持EXIF方向校正、OCR文字检测、
压缩包自动解压、并行处理、PDF/A标准转换等功能。

详细文档请参考 README.md
"""

import os
import sys
import re
import argparse
import tempfile
import traceback
import time
import zipfile
from io import BytesIO
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import multiprocessing

from PIL import Image, ExifTags
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.utils import ImageReader

# pytesseract import
try:
    import pytesseract  # type: ignore[import-untyped]
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


# ---------------- Archive extraction ----------------
ARCHIVE_EXTENSIONS = ('.zip', '.rar', '.7z', '.tar', '.tar.gz', '.tar.bz2')


def is_archive(filename):
    """检查文件是否为支持的压缩包格式"""
    return filename.lower().endswith(ARCHIVE_EXTENSIONS)


def get_extract_folder_name(archive_path):
    """
    获取解压目标文件夹名称
    
    示例：
    - 报销单.zip -> 报销单
    - 发票2024.rar -> 发票2024
    - archive.tar.gz -> archive
    """
    basename = os.path.basename(archive_path)
    
    # 处理双扩展名
    if basename.lower().endswith('.tar.gz'):
        return basename[:-7]
    elif basename.lower().endswith('.tar.bz2'):
        return basename[:-8]
    else:
        return os.path.splitext(basename)[0]


def is_safe_extract_path(path, base_dir):
    """检查解压路径是否安全（防止路径遍历攻击）"""
    abs_path = os.path.abspath(os.path.join(base_dir, path))
    abs_base = os.path.abspath(base_dir)
    return abs_path.startswith(abs_base)


def extract_zip(archive_path, target_dir):
    """解压 ZIP 文件"""
    try:
        with zipfile.ZipFile(archive_path, 'r') as zf:
            # 安全检查：防止路径遍历攻击
            for name in zf.namelist():
                if '..' in name or name.startswith('/') or name.startswith('\\'):
                    return (False, f"不安全的文件路径: {name}")
            
            # 检查解压后总大小（防止 Zip Bomb）
            total_size = sum(info.file_size for info in zf.infolist())
            if total_size > 10 * 1024 * 1024 * 1024:  # 10GB
                return (False, "解压后文件过大（可能是 Zip Bomb）")
            
            zf.extractall(target_dir)
        
        return (True, None)
    except zipfile.BadZipFile:
        return (False, "损坏的ZIP文件")
    except Exception as e:
        return (False, str(e))


def extract_archive(archive_path, target_dir):
    """
    统一解压接口
    
    当前仅支持 ZIP 格式（Python 内置，无需额外依赖）
    未来可扩展支持 RAR、7Z 等格式
    """
    ext = os.path.splitext(archive_path.lower())[1]
    
    if ext == '.zip':
        return extract_zip(archive_path, target_dir)
    else:
        return (False, f"暂不支持的格式: {ext}（当前仅支持 .zip）")


def extract_all_archives(src_dir):
    """
    批量解压源目录中的所有压缩包
    
    返回：(成功数, 跳过数, 失败数, 映射字典)
    """
    archives = []
    
    # 递归查找所有压缩包
    for root, _, files in os.walk(src_dir):
        for file in files:
            if is_archive(file):
                archives.append(os.path.join(root, file))
    
    if not archives:
        log_info("未发现压缩包，跳过解压步骤")
        return (0, 0, 0, {})
    
    log_info(f"发现 {len(archives)} 个压缩包")
    
    success_count = 0
    skip_count = 0
    fail_count = 0
    archive_mapping = {}  # 文件夹 -> 压缩包 映射
    
    for archive_path in archives:
        archive_name = os.path.basename(archive_path)
        folder_name = get_extract_folder_name(archive_path)
        parent_dir = os.path.dirname(archive_path)
        target_dir = os.path.join(parent_dir, folder_name)
        
        # 检查目标文件夹是否已存在
        if os.path.exists(target_dir):
            log_info(f"⏭️  跳过：{archive_name}（文件夹已存在）")
            skip_count += 1
            # 即使跳过，也记录映射关系（可能需要后续删除）
            archive_mapping[target_dir] = archive_path
            continue
        
        log_proc(f"📦 解压：{archive_name} -> {folder_name}/")
        
        success, error_msg = extract_archive(archive_path, target_dir)
        
        if success:
            # 验证解压结果
            if not os.path.exists(target_dir) or not os.listdir(target_dir):
                log_warn(f"❌ 解压失败：{archive_name}（目标目录为空）")
                fail_count += 1
            else:
                file_count = len(os.listdir(target_dir))
                log_save(f"✅ 解压完成：{folder_name}/ ({file_count} 个文件)")
                success_count += 1
                # 记录映射关系
                archive_mapping[target_dir] = archive_path
        else:
            log_warn(f"❌ 解压失败：{archive_name}（{error_msg}）")
            fail_count += 1
    
    log_info(f"解压统计：成功 {success_count}, 跳过 {skip_count}, 失败 {fail_count}")
    return (success_count, skip_count, fail_count, archive_mapping)


def find_source_archive(extracted_dir, archive_mapping):
    """
    查找解压目录对应的原始压缩包
    
    优先使用映射字典，如果找不到则尝试自动查找
    """
    # 优先使用映射字典
    if extracted_dir in archive_mapping:
        return archive_mapping[extracted_dir]
    
    # 备用方案：尝试自动查找
    parent_dir = os.path.dirname(extracted_dir)
    folder_name = os.path.basename(extracted_dir)
    
    for ext in ['.zip', '.rar', '.7z', '.tar', '.tar.gz', '.tar.bz2']:
        archive_path = os.path.join(parent_dir, folder_name + ext)
        if os.path.isfile(archive_path):
            return archive_path
    
    return None


def safe_delete_archive(archive_path, pdf_path):
    """
    安全删除压缩包（带验证）
    
    检查：
    1. PDF 文件存在
    2. PDF 文件大小 > 1KB
    """
    # 检查 PDF 是否存在
    if not os.path.isfile(pdf_path):
        log_warn(f"PDF不存在，跳过删除压缩包：{os.path.basename(archive_path)}")
        return False
    
    # 检查 PDF 大小
    pdf_size = os.path.getsize(pdf_path)
    if pdf_size < 1024:
        log_warn(f"PDF文件过小（{pdf_size} 字节），跳过删除压缩包：{os.path.basename(archive_path)}")
        return False
    
    # 删除压缩包
    try:
        os.remove(archive_path)
        archive_size = os.path.getsize(archive_path) if os.path.exists(archive_path) else 0
        log_save(f"🗑️  已删除压缩包：{os.path.basename(archive_path)}")
        return True
    except Exception as e:
        log_warn(f"删除压缩包失败：{os.path.basename(archive_path)} ({e})")
        return False


# ---------------- EXIF orientation correction ----------------
def correct_exif_orientation(im: Image.Image) -> Image.Image:
    try:
        exif = im.getexif()
        if not exif:
            return im
        # 使用新API直接获取Orientation，值为274 (0x0112)
        orientation = exif.get(0x0112)
        if orientation:
            if orientation == 3:
                im = im.rotate(180, expand=True)
            elif orientation == 6:
                im = im.rotate(270, expand=True)
            elif orientation == 8:
                im = im.rotate(90, expand=True)
    except (AttributeError, ValueError, TypeError) as e:
        log_warn(f"EXIF 方向校正失败: {e}")
    return im


# ---------------- Tesseract OCR based rotation detection ----------------
def detect_ocr_rotation(im: Image.Image):
    """使用 Tesseract OCR 检测图片方向（返回需顺时针旋转角度）"""
    if pytesseract is None:
        return 0  # 统一返回0而不是None
    try:
        # 确保图像为RGB格式以提高OCR准确性
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        osd = pytesseract.image_to_osd(im)
        for line in osd.splitlines():
            if line.startswith("Rotate:"):
                angle = int(line.split(":")[1].strip())
                return angle % 360
        return 0
    except pytesseract.TesseractError as e:
        # 仅记录简短错误信息，不输出堆栈
        err_msg = str(e).split("\n")[0] if "\n" in str(e) else str(e)
        if "Too few characters" in err_msg:
            log_warn("OCR 方向检测：图片文字太少，跳过")
        else:
            log_warn(f"OCR 方向检测失败：{err_msg}")
        return 0
    except Exception as e:
        log_warn(f"OCR 方向检测异常：{e.__class__.__name__}")
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
    # 记录开始时间
    start_time = time.time()
    out_dir = os.path.dirname(out_pdf_path)
    base_name = os.path.splitext(os.path.basename(out_pdf_path))[0]
    # 使用上下文管理器确保临时文件正确处理
    with tempfile.NamedTemporaryFile(
        prefix=base_name + "_", suffix=".pdf", dir=out_dir, delete=False
    ) as temp_file:
        temp_path = temp_file.name
    try:
        c = canvas.Canvas(temp_path, pagesize=A4)
        for idx, img_path in enumerate(img_paths, start=1):
            img_name = os.path.basename(img_path)
            log_proc(f"    处理 {idx}/{len(img_paths)}: {img_name}")
            try:
                with Image.open(img_path) as im:
                    im = correct_exif_orientation(im)
                    # 使用OCR检测旋转角度（已处理所有异常情况）
                    rot = detect_ocr_rotation(im)
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
                    
                    # 横向页面增加边距（15mm ≈ 42.5磅），竖向页面不加边距
                    if w > h:
                        margin = 42.5
                        available_w = page_w - 2 * margin
                        available_h = page_h - 2 * margin
                    else:
                        margin = 0
                        available_w = page_w
                        available_h = page_h
                    
                    # 限制缩放比例不超过1.0，避免小图片被放大失真
                    scale = min(available_w / w, available_h / h, 1.0)
                    new_w, new_h = w * scale, h * scale
                    x = (page_w - new_w) / 2
                    y = (page_h - new_h) / 2
                    # 使用上下文管理器确保 BytesIO 资源正确释放
                    with BytesIO() as bio:
                        im.save(bio, format="JPEG", quality=85)  # 添加质量参数减少文件大小
                        bio.seek(0)
                        ir = ImageReader(bio)
                        c.drawImage(ir, x, y, new_w, new_h, preserveAspectRatio=True)
                        c.showPage()
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
        # 计算并记录处理时间
        elapsed_time = time.time() - start_time
        log_save(f"生成 PDF: {out_pdf_path} (耗时: {elapsed_time:.2f}秒)")
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

    # 验证输入文件存在
    if not os.path.isfile(input_pdf):
        log_err(f"输入PDF文件不存在：{input_pdf}")
        return False
    
    # 规范化路径以防止路径遍历
    input_pdf = os.path.abspath(input_pdf)
    output_pdf = os.path.abspath(output_pdf)
    
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
    # 支持更多常见图像格式
    supported_extensions = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif")
    for fname in os.listdir(dir_path):
        p = os.path.join(dir_path, fname)
        if os.path.isfile(p) and fname.lower().endswith(supported_extensions):
            files.append(fname)
    files.sort(key=natural_key)
    return [os.path.join(dir_path, f) for f in files]


def collect_dirs_to_process(src_root):
    dirs = []
    # 支持更多常见图像格式
    supported_extensions = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif")
    for current_dir, _, _ in os.walk(src_root):
        imgs = [
            f
            for f in os.listdir(current_dir)
            if os.path.isfile(os.path.join(current_dir, f))
            and f.lower().endswith(supported_extensions)
        ]
        if imgs:
            dirs.append(current_dir)
    return dirs


def process_one_dir(args_tuple):
    # 记录单个目录处理开始时间
    dir_start_time = time.time()
    current_dir, src_root, out_root, do_pdfa, delete_archive, archive_mapping, keep_structure = args_tuple
    try:
        images = gather_image_files_in_dir(current_dir)
        if not images:
            return (current_dir, False, "no_images")
        dir_name = os.path.basename(os.path.normpath(current_dir))
        pdf_name = f"{dir_name}.pdf"
        
        if out_root:
            if keep_structure:
                # 保持目录结构：计算相对路径
                rel_path = os.path.relpath(current_dir, src_root)
                out_dir = os.path.join(out_root, rel_path)
                os.makedirs(out_dir, exist_ok=True)
                out_pdf = os.path.join(out_dir, pdf_name)
            else:
                # 扁平化输出：所有PDF到同一目录
                os.makedirs(out_root, exist_ok=True)
                out_pdf = os.path.join(out_root, pdf_name)
        else:
            # 未指定输出目录，PDF保存在源目录
            out_pdf = os.path.join(current_dir, pdf_name)
        
        # 检查目标PDF是否已存在
        if os.path.exists(out_pdf):
            log_info(f"[{dir_name}] 跳过：PDF 已存在 -> {out_pdf}")
            return (current_dir, True, "skipped_existing")
        
        log_info(f"[{dir_name}] 开始生成 PDF（{len(images)} 张） -> {out_pdf}")
        ok = make_pdf_from_images(images, out_pdf)
        if not ok:
            return (current_dir, False, "make_pdf_failed")
        if do_pdfa:
            # 使用上下文管理器确保临时文件正确处理
            with tempfile.NamedTemporaryFile(
                prefix=dir_name + "_pdfa_", suffix=".pdf", dir=os.path.dirname(out_pdf), delete=False
            ) as tmp_file:
                tmp_pdfa = tmp_file.name
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
        
        # ✅ PDF生成成功，删除对应的压缩包（如果启用）
        if delete_archive:
            archive_path = find_source_archive(current_dir, archive_mapping)
            if archive_path and os.path.isfile(archive_path):
                safe_delete_archive(archive_path, out_pdf)
        
        # 计算并记录单个目录处理时间
        dir_elapsed_time = time.time() - dir_start_time
        dir_name = os.path.basename(os.path.normpath(current_dir))
        log_save(f"[{dir_name}] 处理完成 (耗时: {dir_elapsed_time:.2f}秒)")
        return (current_dir, True, None)
    except Exception as e:
        traceback.print_exc()
        return (current_dir, False, str(e))


def process_recursive_parallel(src_root, out_root=None, do_pdfa=False, delete_archive=False, archive_mapping=None, keep_structure=False):
    # 记录总处理开始时间
    total_start_time = time.time()
    dirs = collect_dirs_to_process(src_root)
    total = len(dirs)
    log_info(f"共发现 {total} 个含图片的子目录。")
    if total == 0:
        return
    
    # 如果没有提供映射字典，使用空字典
    if archive_mapping is None:
        archive_mapping = {}
    
    max_workers = min(os.cpu_count() or 1, 8)
    log_info(f"开始并行处理（最大并发数 {max_workers}）")
    
    # 如果保持目录结构，显示提示信息
    if keep_structure and out_root:
        log_info("输出模式：保持源目录结构")
    elif out_root:
        log_info("输出模式：扁平化（所有PDF到同一目录）")
    
    tasks = [(d, src_root, out_root, do_pdfa, delete_archive, archive_mapping, keep_structure) for d in dirs]
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_dir = {executor.submit(process_one_dir, t): t[0] for t in tasks}
        completed = 0
        for future in as_completed(future_to_dir):
            dirpath = future_to_dir[future]
            try:
                current_dir, ok, reason = future.result()
                completed += 1
                if ok:
                    if reason == "skipped_existing":
                        log_info(f"[{completed}/{total}] 跳过：{current_dir}")
                    else:
                        log_save(f"[{completed}/{total}] 完成：{current_dir}")
                else:
                    log_warn(
                        f"[{completed}/{total}] 失败：{current_dir} | 原因：{reason}"
                    )
            except Exception as e:
                completed += 1
                log_err(f"[{completed}/{total}] 子任务异常：{dirpath}")
                log_err(f"详细错误：{e}")
                log_err(f"堆栈跟踪：{traceback.format_exc()}")
    
    # 计算并记录总处理时间
    total_elapsed_time = time.time() - total_start_time
    log_info(f"所有任务完成，总耗时: {total_elapsed_time:.2f}秒")


def main():
    parser = argparse.ArgumentParser(
        description="高性能图片转 A4 PDF（EXIF+OCR方向检测，支持PDF/A）"
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
    parser.add_argument(
        "--extract",
        action="store_true",
        help="自动解压源目录中的压缩包（ZIP）到同名文件夹"
    )
    parser.add_argument(
        "--delete-archive",
        action="store_true",
        help="PDF生成成功后删除原压缩包（需配合 --extract 使用）"
    )
    parser.add_argument(
        "--keep-structure",
        action="store_true",
        help="保持源目录结构输出PDF（默认为扁平化输出）"
    )
    args = parser.parse_args()
    src = os.path.abspath(args.src)
    if not os.path.isdir(src):
        log_err(f"源目录不存在：{src}")
        sys.exit(2)
    
    # 检查目录可读权限
    if not os.access(src, os.R_OK):
        log_err(f"源目录无读取权限：{src}")
        sys.exit(3)
        
    out_dir = os.path.abspath(args.out) if args.out else None
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        # 检查输出目录可写权限
        if not os.access(out_dir, os.W_OK):
            log_err(f"输出目录无写入权限：{out_dir}")
            sys.exit(4)
    
    log_info(f"开始处理源目录：{src}")
    if out_dir:
        log_info(f"输出目录：{out_dir}")
    else:
        log_info("输出目录未指定，PDF 将生成在各自源子目录中。")
    if args.pdfa:
        log_info("已启用 PDF/A 转换（需要 Ghostscript）")
    
    # 阶段1：解压压缩包（如果启用）
    archive_mapping = {}
    if args.extract:
        log_info("=" * 60)
        log_info("阶段 1：解压压缩包")
        log_info("=" * 60)
        success, skipped, failed, archive_mapping = extract_all_archives(src)
        if args.delete_archive:
            log_info("已启用：PDF生成成功后将自动删除原压缩包")
    
    # 阶段2：生成PDF
    log_info("=" * 60)
    log_info("阶段 2：生成 PDF")
    log_info("=" * 60)
    process_recursive_parallel(src, out_dir, args.pdfa, args.delete_archive, archive_mapping, args.keep_structure)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
