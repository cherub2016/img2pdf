"""
img2pdf.py（带自动纠正方向）

功能：
  - 读取目录中所有 .jpg 图片（按文件名升序）
  - 自动识别 EXIF 方向标签并纠正
  - 合并成 A4 页面 PDF（等比缩放、居中、不强制旋转）

依赖：
  pip install pillow reportlab
"""

import os
import sys
from io import BytesIO
from PIL import Image, ExifTags
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
import tempfile
import traceback

A4_W, A4_H = A4


def correct_orientation(im: Image.Image) -> Image.Image:
    """自动根据 EXIF 纠正图片方向"""
    try:
        exif = im._getexif()
        if not exif:
            return im
        for tag, value in exif.items():
            if ExifTags.TAGS.get(tag, None) == "Orientation":
                orientation = value
                if orientation == 3:
                    im = im.rotate(180, expand=True)
                elif orientation == 6:
                    im = im.rotate(270, expand=True)
                elif orientation == 8:
                    im = im.rotate(90, expand=True)
                break
    except Exception:
        pass
    return im


def image_to_pdf(img_dir):
    if not os.path.isdir(img_dir):
        print(f"❌ 错误：目录不存在：{img_dir}")
        return

    imgs = [f for f in os.listdir(img_dir) if f.lower().endswith(".jpg")]
    if not imgs:
        print("⚠️  未在目录中找到 .jpg 文件。")
        return

    imgs.sort()
    print(f"✅ 发现 {len(imgs)} 张图片。")

    base_name = os.path.basename(os.path.normpath(img_dir))
    pdf_name = base_name + ".pdf"
    pdf_path = os.path.join(img_dir, pdf_name)
    temp_fd, temp_pdf = tempfile.mkstemp(suffix=".pdf", prefix=base_name + "_", dir=img_dir)
    os.close(temp_fd)

    try:
        c = canvas.Canvas(temp_pdf, pagesize=A4)

        for idx, img_name in enumerate(imgs, start=1):
            img_path = os.path.join(img_dir, img_name)
            print(f"🖼️  正在处理 {idx}/{len(imgs)}: {img_name}")
            try:
                with Image.open(img_path) as im:
                    # 自动纠正方向
                    im = correct_orientation(im)

                    # 统一为RGB（去掉透明度）
                    if im.mode in ("RGBA", "LA"):
                        bg = Image.new("RGB", im.size, (255, 255, 255))
                        bg.paste(im, mask=im.split()[-1])
                        im = bg
                    elif im.mode != "RGB":
                        im = im.convert("RGB")

                    w, h = im.size
                    scale = min(A4_W / w, A4_H / h)
                    new_w, new_h = w * scale, h * scale
                    x = (A4_W - new_w) / 2
                    y = (A4_H - new_h) / 2

                    # 转内存流再绘制
                    img_bytes = BytesIO()
                    im.save(img_bytes, format="JPEG")
                    img_bytes.seek(0)
                    ir = ImageReader(img_bytes)
                    c.drawImage(ir, x, y, new_w, new_h, preserveAspectRatio=True, anchor='c')
                    c.showPage()
                    img_bytes.close()
            except Exception as e_img:
                print(f"⚠️  处理 {img_name} 时出错：{e_img}")
                traceback.print_exc()

        c.save()
        try:
            os.replace(temp_pdf, pdf_path)
            print(f"🎉 合并完成：{pdf_path}")
        except PermissionError:
            print("❗ 无法覆盖目标文件（可能被打开）。")
            print(f" - 临时文件已保存：{temp_pdf}")
        except Exception as e_rep:
            print(f"⚠️ 替换输出文件时发生错误：{e_rep}")
            print(f"临时文件位于：{temp_pdf}")

    except Exception as e:
        print(f"❌ 处理时发生错误：{e}")
        traceback.print_exc()
        if os.path.exists(temp_pdf):
            try:
                os.remove(temp_pdf)
            except Exception:
                pass


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python img2pdf.py <图片目录>")
        sys.exit(1)
    image_to_pdf(sys.argv[1])
