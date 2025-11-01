# 🖼️ img2pdf.py  
### 高性能影像归档工具（EXIF 方向校正 + OCR 方向检测 + PDF/A 支持）

---

## 📘 项目简介

`img2pdf.py` 是一款基于 Python 的命令行工具，可将指定文件夹及其子文件夹内的图片（`.jpg` / `.jpeg`）自动转换为 **A4 PDF 文件**。

支持：
- 自动递归扫描目录；
- 每个文件夹生成一个 PDF；
- **EXIF 方向优先**，OCR 方向检测作为兜底；
- 自动选择横向或竖向 A4 页面；
- 图片 **等比缩放、居中显示**；
- 命令行彩色日志提示；
- 支持集中输出所有 PDF 文件到指定目录；
- 可选转换为合规的 **PDF/A-1b** 格式。

---

## 🧩 功能特性

| 功能 | 说明 |
|------|------|
| ✅ 递归扫描 | 自动遍历源目录及其所有子目录 |
| ✅ 批量合并 | 每个子目录生成独立 PDF |
| ✅ EXIF 优先 | 优先使用 EXIF 信息修正方向 |
| ✅ OCR 兜底 | Tesseract OCR 作为方向检测补充（可选） |
| ✅ 自动横竖混排 | 自动选择横向或竖向 A4 页面 |
| ✅ 等比缩放居中 | 不裁剪、不拉伸 |
| ✅ 彩色日志 | 直观显示进度与错误信息 |
| ✅ 集中输出 | 可选将所有 PDF 保存到统一目录 |
| ✅ PDF/A 支持 | 可选转换为合规的 PDF/A-1b |
| ✅ 容错处理 | 跳过损坏图片、保留临时文件便于恢复 |

---

## ⚙️ 环境依赖

### 📦 Python 版本
- Python **3.8+**

### 📚 必要依赖
安装以下库：
```bash
pip install pillow reportlab pytesseract
```

### 🛠️ 系统工具（可选）
1. **Tesseract OCR**：用于图片方向检测（可选）
   - Windows: [https://github.com/UB-Mannheim/tesseract/wiki](https://github.com/UB-Mannheim/tesseract/wiki)
   - Linux: `sudo apt install tesseract-ocr`
   - macOS: `brew install tesseract`

2. **Ghostscript**：用于生成 PDF/A（仅在使用 --pdfa 时需要）
   - Windows: [Ghostscript 官网](https://www.ghostscript.com/releases/gsdnld.html)
   - Linux: `sudo apt install ghostscript`
   - macOS: `brew install ghostscript`

---

## 🚀 使用方法

### 查看帮助信息
```bash
python img2pdf.py -h
```

输出示例：
```
高性能图片转 A4 PDF（EXIF+OCR方向检测，支持PDF/A）

用法：
  python img2pdf.py <源目录> [输出目录] [--pdfa]

参数说明：
  源目录      必填，包含图片文件的主文件夹
  输出目录    可选，若省略则 PDF 保存在源目录对应文件夹中
  --pdfa     可选，生成符合 PDF/A-1b 标准的文档（需要 Ghostscript）
```

---

### 📁 示例一：基本用法（PDF 保存在源目录）
```bash
python img2pdf.py "D:\扫描文件"
```
程序行为：
- 递归扫描 `扫描文件` 目录及其所有子文件夹；
- 每个含 `.jpg` / `.jpeg` 图片的文件夹生成一个独立 PDF；
- 生成的 PDF 与图片位于同一目录；
- 文件命名格式：`<目录名>.pdf`。

---

### 📁 示例二：PDF 集中输出
```bash
python img2pdf.py "D:\扫描文件" "D:\PDF输出"
```
程序行为：
- 扫描源目录及子目录中的所有图片；
- 每个子文件夹生成一个独立 PDF；
- **所有 PDF 文件统一保存到指定目录**；
- 若存在同名文件将尝试覆盖（文件被占用时保留临时文件）。

---

### 📁 示例三：生成 PDF/A 文档
```bash
python img2pdf.py "D:\扫描文件" "D:\PDF输出" --pdfa
```
程序行为：
- 除了基本的 PDF 生成外；
- 使用 Ghostscript 将生成的 PDF 转换为 PDF/A-1b；
- 确保长期保存的文档合规性。

---

## 🧠 智能处理逻辑

### 1️⃣ 方向校正（两级策略）
- **第一级**：EXIF 方向信息
  - 优先读取图片的 EXIF Orientation 标签
  - 根据标签值自动旋转（0°/90°/180°/270°）
- **第二级**：OCR 方向检测（兜底）
  - 当 EXIF 信息不存在或无效时启用
  - 使用 Tesseract OCR 分析文字方向
  - 支持检测 0°/90°/180°/270°
  - 检测失败时保持原始方向

### 2️⃣ 页面布局自适应
- 基于图片比例自动选择页面方向：
  - 宽 > 高：使用横向 A4
  - 高 ≥ 宽：使用竖向 A4
- 自动计算最佳缩放比例
- 居中放置，确保美观

### 3️⃣ 并行处理策略
- 自动检测 CPU 核心数（最多使用 8 个）
- 多进程并行处理不同目录
- 每个子进程独立处理一个目录的图片

---

## 🖥️ 日志输出示例

```
[INFO] 开始处理源目录：D:\扫描文件
[INFO] 输出目录：D:\PDF输出
[INFO] 共发现 3 个含图片的子目录
[INFO] 开始并行处理（最大并发数 4）
[PROC] 处理 1/5: scan001.jpg
[PROC]   已按 90° 旋转（顺时针）
[SAVE] 生成 PDF: D:\PDF输出\文件夹1.pdf
[INFO] 全部任务完成。
```

---

## ⚠️ 注意事项

1. **运行环境**
   - 确保 Python 3.8+ 环境
   - 安装必要的 Python 包
   - OCR 检测需要 Tesseract
   - PDF/A 转换需要 Ghostscript

2. **输入/输出**
   - 仅支持 .jpg/.jpeg 格式图片
   - 确保源目录读取权限
   - 确保目标目录写入权限
   - 不要打开正在生成的 PDF

3. **资源使用**
   - 并行处理会占用较多内存
   - 建议预留足够磁盘空间
   - PDF/A 转换需要额外处理时间

4. **错误处理**
   - 单个图片错误不影响整体处理
   - 文件占用时会保留临时文件
   - 详细日志帮助定位问题

---

## 🧾 许可证

本项目采用 **MIT License**。

---

## ✨ 作者信息

**开发者**：Cherub  
**版本**：v0.42  
**最后更新**：2025-11  
**项目定位**：企业影像归档与文档标准化工具