# 项目架构文档

## 概述
本项目是一个图片转 PDF 的工具，支持以下功能：
- 递归扫描目录及其子目录中的图片文件
- 自动根据 EXIF 信息校正图片方向
- 使用 OCR 检测文字方向（可选）
- 生成 A4 大小的 PDF 文件，支持横竖页面自动调整
- 支持并行处理多个子目录（多进程加速）
- 可选转换为 PDF/A-1b 格式（通过 Ghostscript）

## 主要文件

### 1. `img2pdf.py`
- **功能**：基础版图片转 PDF 工具。
- **特点**：
  - 单线程处理
  - 支持 EXIF 方向校正
  - 使用 pytesseract 进行 OCR 方向检测
  - 生成 A4 大小的 PDF，自动调整页面方向

### 2. `img2pdf_parallel.py`
- **功能**：并行加速版图片转 PDF 工具。
- **特点**：
  - 多进程并行处理子目录
  - 基础功能与 `img2pdf.py` 相同
  - 通过 `ProcessPoolExecutor` 实现并行加速

### 3. `img2pdf_v0.41.py`
- **功能**：高性能影像归档工具。
- **特点**：
  - 使用 OpenCV 快速检测图片方向（主）
  - pytesseract OCR 作为兜底方案
  - 支持自然排序文件名（避免 1,10,2 的问题）
  - 可选转换为 PDF/A-1b 格式
  - 并行处理多个子文件夹

## 核心模块

### 1. 图像处理模块
- **功能**：
  - 校正 EXIF 方向
  - 检测文字方向（OpenCV 或 OCR）
  - 转换为 RGB 格式并去除透明背景

### 2. PDF 生成模块
- **功能**：
  - 根据图片尺寸自动选择横竖页面
  - 等比缩放并居中图片
  - 生成 PDF 文件

### 3. 并行处理模块
- **功能**：
  - 多进程并行处理多个子目录
  - 通过 `ProcessPoolExecutor` 实现任务分发

## 依赖项
- **Python 库**：
  - `Pillow`：图像处理
  - `reportlab`：PDF 生成
  - `pytesseract`：OCR 方向检测
  - `opencv-python`（可选）：快速方向检测
  - `colorama`：彩色日志输出

- **系统工具**：
  - `Tesseract OCR`（可选）：OCR 方向检测
  - `Ghostscript`（可选）：PDF/A 转换

## 使用说明
1. 运行 `img2pdf.py` 或 `img2pdf_parallel.py` 或 `img2pdf_v0.41.py`。
2. 指定源目录和可选输出目录。
3. 工具会自动处理图片并生成 PDF 文件。