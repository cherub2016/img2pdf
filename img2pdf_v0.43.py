#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
img2pdf_v4.12.py

影像归档工具（优化版）
- 自动检测方向（EXIF → OpenCV → OCR）
- 自动缩放超大图片防止 MemoryError
- 多进程并行处理多个子目录
- 中文路径兼容（cv2.imdecode）
- 可选 --pdfa 参数调用 Ghostscript 转换 PDF/A-1b
"""

import os, sys, math, argparse, tempfile, traceback, multiprocessing, gc, re, subprocess, shutil
from io import BytesIO
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from PIL import Image, ExifTags
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.utils import ImageReader

try:
    import cv2, numpy as np
except Exception:
    cv2 = np = None
try:
    import pytesseract
except Exception:
    pytesseract = None

MAX_PIXELS = 4000  # 限制单边最大像素
A4_W, A4_H = A4

# 日志输出
def log(c, s): print(f"[{c}] {s}")
def log_info(s): log("INFO", s)
def log_proc(s): log("PROC", s)
def log_warn(s): log("WARN", s)
def log_err(s): log("ERR", s)
def log_save(s): log("SAVE", s)

# 自然排序
_nat = re.compile(r'(\d+)')
def natural_key(s): return [int(t) if t.isdigit() else t.lower() for t in _nat.split(s)]

# EXIF方向纠正
def correct_exif_orientation(im):
    try:
        exif = im._getexif()
        if not exif: return im
        orientation_key = next((k for k, v in ExifTags.TAGS.items() if v=="Orientation"), None)
        if orientation_key and orientation_key in exif:
            o = exif[orientation_key]
            if o == 3: im = im.rotate(180, expand=True)
            elif o == 6: im = im.rotate(270, expand=True)
            elif o == 8: im = im.rotate(90, expand=True)
    except Exception: pass
    return im

# OpenCV方向检测
def detect_rotation_opencv(path):
    if cv2 is None or np is None: return None
    try:
        data = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        if img is None: return None
        h,w = img.shape[:2]
        max_dim=1200
        if max(h,w)>max_dim:
            s=max_dim/max(h,w)
            img=cv2.resize(img,(int(w*s),int(h*s)),interpolation=cv2.INTER_AREA)
        edges=cv2.Canny(img,50,150,apertureSize=3)
        lines=cv2.HoughLinesP(edges,1,math.pi/180,80,minLineLength=30,maxLineGap=10)
        if lines is None: return None
        angs=[]
        for l in lines:
            x1,y1,x2,y2=l[0]
            dx,dy=x2-x1,y2-y1
            ang=90.0 if dx==0 else math.degrees(math.atan2(dy,dx))
            if ang>90: ang-=180
            if ang<=-90: ang+=180
            angs.append(ang)
        if not angs: return None
        med=float(np.median(np.array(angs))) if np is not None else sorted(angs)[len(angs)//2]
        if abs(med)<30: return 0
        return 90 if med>30 else 270
    except Exception: return None

# OCR兜底
def detect_rotation_ocr(path):
    if pytesseract is None: return 0
    try:
        im=Image.open(path).convert("RGB")
        osd=pytesseract.image_to_osd(im)
        for line in osd.splitlines():
            if line.strip().startswith("Rotate:"):
                ang=int(line.split(":")[1].strip())
                return ang%360
    except Exception: pass
    return 0

# 生成PDF
def make_pdf_from_images(imgs, out_pdf):
    c=canvas.Canvas(out_pdf,pagesize=A4)
    for i,p in enumerate(imgs,1):
        name=os.path.basename(p)
        log_proc(f"  处理 {i}/{len(imgs)}: {name}")
        try:
            im=Image.open(p)
            im=correct_exif_orientation(im)
            rot=detect_rotation_opencv(p) or detect_rotation_ocr(p)
            if rot not in (0,90,180,270): rot=0
            if rot!=0: im=im.rotate(-rot,expand=True)
            w,h=im.size
            if max(w,h)>MAX_PIXELS:
                s=MAX_PIXELS/max(w,h)
                im=im.resize((int(w*s),int(h*s)),Image.LANCZOS)
                log_proc(f"    图片缩放至 {im.size[0]}x{im.size[1]}")
            w,h=im.size
            page=landscape(A4) if w>h else portrait(A4)
            c.setPageSize(page)
            pw,ph=page
            s=min(pw/w,ph/h)
            nw,nh=w*s,h*s
            x,y=(pw-nw)/2,(ph-nh)/2
            bio=BytesIO(); im.save(bio,format="JPEG"); bio.seek(0)
            c.drawImage(ImageReader(bio),x,y,nw,nh,preserveAspectRatio=True)
            c.showPage()
            bio.close(); im.close(); gc.collect()
        except MemoryError:
            log_err(f"    内存不足，跳过 {name}")
        except Exception as e:
            log_warn(f"    跳过 {name}: {e}")
    c.save(); log_save(f"生成PDF: {out_pdf}")

# Ghostscript PDF/A转换
def to_pdfa(inpdf,outpdf):
    cmd=["gswin64c" if os.name=="nt" else "gs",
         "-dPDFA=1","-dBATCH","-dNOPAUSE","-dNOOUTERSAVE","-dUseCIEColor",
         "-sProcessColorModel=DeviceRGB","-sDEVICE=pdfwrite","-dPDFACompatibilityPolicy=1",
         f"-sOutputFile={outpdf}",inpdf]
    try:
        subprocess.run(cmd,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        log_save(f"PDF/A: {outpdf}")
    except Exception as e:
        log_err(f"PDF/A失败: {e}")

# 子目录处理
def gather_images(d):
    f=[x for x in os.listdir(d) if x.lower().endswith(('.jpg','.jpeg'))]
    f.sort(key=natural_key)
    return [os.path.join(d,x) for x in f]

def process_dir(args):
    d,out_root,pdfa=args
    imgs=gather_images(d)
    if not imgs: return
    name=os.path.basename(d.rstrip('/\\\\'))
    out=os.path.join(out_root or d,f"{name}.pdf")
    make_pdf_from_images(imgs,out)
    if pdfa:
        tmp=os.path.join(out_root or d,f"{name}_tmp.pdf")
        to_pdfa(out,tmp)
        try: os.replace(tmp,out)
        except Exception as e: log_warn(f"替换PDF/A失败: {e}")

def collect_dirs(root):
    dirs=[]
    for cur,_,_ in os.walk(root):
        if any(x.lower().endswith(('.jpg','.jpeg')) for x in os.listdir(cur)):
            dirs.append(cur)
    return dirs

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out",nargs="?")
    ap.add_argument("--pdfa",action="store_true")
    a=ap.parse_args()
    src=os.path.abspath(a.src); out=os.path.abspath(a.out) if a.out else None
    if out: os.makedirs(out,exist_ok=True)
    dirs=collect_dirs(src)
    log_info(f"共{len(dirs)}个目录")
    maxw=max(2,min((os.cpu_count() or 4)//2,8))
    log_info(f"并行进程数: {maxw}")
    with ProcessPoolExecutor(max_workers=maxw) as ex:
        futs=[ex.submit(process_dir,(d,out,a.pdfa)) for d in dirs]
        for i,f in enumerate(as_completed(futs),1):
            try: f.result(); log_info(f"[{i}/{len(dirs)}] 完成")
            except Exception as e: log_err(f"任务异常: {e}")
    log_info("全部完成")

if __name__=="__main__":
    multiprocessing.freeze_support()
    main()
