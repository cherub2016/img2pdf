# 🖼️ img2pdf.py  
### 智能图片转 A4 PDF 工具（EXIF 校正 + OCR 文字方向检测 + 批量处理）

---

## 📘 项目简介

`img2pdf.py` 是一款基于 Python 的命令行工具，可将指定文件夹及其子文件夹内的图片（`.jpg` / `.jpeg`）自动转换为 **A4 PDF 文件**。

支持：
- 自动递归扫描目录；
- 每个文件夹生成一个 PDF；
- 同时执行 **EXIF 自动方向校正** 与 **OCR 文字方向检测**；
- 自动选择横向或竖向 A4 页面；
- 图片 **等比缩放、居中显示**；
- 命令行彩色日志提示；
- 支持集中输出所有 PDF 文件到指定目录。

---

## 🧩 功能特性

| 功能 | 说明 |
|------|------|
| ✅ 递归扫描 | 自动遍历源目录及其所有子目录 |
| ✅ 批量合并 | 每个子目录生成独立 PDF |
| ✅ EXIF 自动纠正 | 修正相机拍照导致的方向错误 |
| ✅ OCR 智能方向识别 | 自动检测文字方向并旋转至可读方向 |
| ✅ 自动横竖混排 | 自动选择横向或竖向 A4 页面 |
| ✅ 等比缩放居中 | 不裁剪、不拉伸 |
| ✅ 彩色日志 | 直观显示进度与错误信息 |
| ✅ 集中输出 | 可选将所有 PDF 保存到统一目录 |
| ✅ 容错处理 | 跳过损坏图片、文件占用自动提示 |

---

## ⚙️ 环境依赖

### 📦 Python 版本
- Python **3.8+**

### 📚 必要依赖
安装以下库：
```bash
pip install pillow reportlab pytesseract colorama
```

### 🔤 OCR 引擎（必须安装）
`img2pdf.py` 依赖 [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) 进行文字方向检测。

#### Windows 安装方法
1. 下载地址：  
   [https://github.com/tesseract-ocr/tesseract/releases](https://github.com/tesseract-ocr/tesseract/releases)
2. 安装后，将路径（如 `C:\Program Files\Tesseract-OCR`）添加到系统环境变量 `PATH`。
3. 验证是否成功：
   ```bash
   tesseract --version
   ```

#### Linux / macOS
```bash
sudo apt install tesseract-ocr
```
或
```bash
brew install tesseract
```

---

## 🚀 使用方法

### 查看帮助信息
```bash
python img2pdf.py -h
```

输出示例：
```
图片批量转 A4 PDF 工具
用法：
  python img2pdf.py <源目录> [输出目录]

参数说明：
  源目录      必填，包含图片文件的主文件夹。
  输出目录    可选，若省略则 PDF 保存在源目录对应文件夹中。
```

---

### 📁 示例一：PDF 保存在源目录中
```bash
python img2pdf.py "C:\Users\Wangzichen\Desktop\芦一矿\pic"
```
程序行为：
- 递归扫描 `pic` 目录及其所有子文件夹；
- 每个含 `.jpg` / `.jpeg` 图片的文件夹生成一个独立 PDF；
- 生成的 PDF 与图片位于同一目录；
- 文件命名格式：`<目录名>.pdf`。

---

### 📁 示例二：PDF 集中保存到指定目录
```bash
python img2pdf.py "C:\Users\Wangzichen\Desktop\芦一矿\pic" "D:\output_pdfs"
```
程序行为：
- 扫描源目录及子目录中的所有图片；
- 每个子文件夹生成一个独立 PDF；
- **所有 PDF 文件统一保存到 `D:\output_pdfs` 下**；
- 不再创建与源目录相同的层级结构；
- 若存在同名文件将直接覆盖（或提示文件被占用）。

---

## 🧠 智能逻辑说明

### 1️⃣ EXIF 校正  
- 修正相机或手机拍摄时的旋转方向。

### 2️⃣ OCR 文字方向识别  
- 使用 `pytesseract.image_to_osd()` 自动分析文字方向；
- 支持识别 0° / 90° / 180° / 270°；
- 自动顺时针旋转图片，使文字方向正确；
- 若 OCR 识别失败，则默认保持当前方向。

### 3️⃣ 页面横竖自动切换  
- 若图片宽 > 高 → 使用横向 A4；
- 否则使用竖向 A4。

### 4️⃣ 图片缩放与排版  
- 图片按比例缩放，完整显示在 A4 页面内；
- 自动居中显示；
- 不拉伸、不裁剪。

---

## 🖥️ 日志输出示例

```
[INFO] 开始处理源目录：C:\Users\Wangzichen\Desktop\芦一矿\pic
[INFO] 输出目录：D:\output_pdfs
[INFO] 目录: C:\Users\Wangzichen\Desktop\芦一矿\pic\202007-银行-4
[PROC] 处理 1/8: 202007-银行-4_1.jpg
       OCR检测: 横向(90°) | 页面方向: 横版A4 | 缩放后: 1650x1168
[SAVE] 生成 PDF：D:\output_pdfs\202007-银行-4.pdf
[INFO] ✅ 全部处理完成。
```

---

## ⚠️ 注意事项

- **不要打开正在生成的 PDF 文件**，否则可能导致文件被占用；
- OCR 检测时间与图片分辨率和数量有关；
- 若图片文字稀少或模糊，方向识别可能不准确；
- 推荐图片分辨率 ≥ **200 DPI**；
- 仅处理 `.jpg` / `.jpeg` 格式。

---

## 🧾 许可证

本项目采用 **MIT License**。

---

## ✨ 作者信息

**开发者**：Cherub  
**版本**：v3.0 Final  
**最后更新**：2025-10  
**项目定位**：自动化财务影像归档 / 凭证整理辅助工具  
