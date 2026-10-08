# 论文 PDF 图内翻译：源码调研

核对日期：2026-10-08。这里区分源码阅读结论、文档说明和待验证设计。
没有运行参考项目的完整翻译任务，未用星数或 README 功能名称代替实际能力判断。

## 1. PDFMathTranslate：新增 OCR 仍保护插图

来源：[PR #1185](https://github.com/PDFMathTranslate/PDFMathTranslate/pull/1185)。
阅读版本：合并提交 `8c34c76` 的 `pdf2zh/high_level.py` 与 `pdf2zh/ocr.py`。

- `_ocr_pages` 遇到非空 PDF 文字层就跳过。
- `ocr_paragraphs` 排除 figure、table、isolate_formula、formula_caption 区域中的词。
- 扫描正文采用本地 Tesseract OCR、区域内段落重组、白底覆盖、中文字号缩放。

**结论：没有实现本次要求的混合页图内位图文字翻译。**
借鉴字号自适应、页码范围、取消机制与双语输出的原页保留。

版本核对：本地与最新 GitHub 正式 Windows release 都是 1.9.11；main 的版本字段是 1.9.12。
源码更新与安装包更新需要区分。

## 2. pdf2zh-desktop：有图注后处理，也有独立扫描管线

阅读提交：`a53eae31555c49571e75ad072f6e3b324e72ac65`。

已读：

- [high_level.py](https://github.com/AaronGIG/pdf2zh-desktop/blob/a53eae31555c49571e75ad072f6e3b324e72ac65/core/site-packages/pdf2zh/high_level.py)
- [ocr_pipeline.py](https://github.com/AaronGIG/pdf2zh-desktop/blob/a53eae31555c49571e75ad072f6e3b324e72ac65/core/site-packages/pdf2zh/ocr_pipeline.py)
- [translate_worker.py](https://github.com/AaronGIG/pdf2zh-desktop/blob/a53eae31555c49571e75ad072f6e3b324e72ac65/ui/translate_worker.py)

`_postprocess_figures` 从原 PDF 的 `get_text("dict")` 遍历文字行，
在目标位置没有文字时才尝试补译。它并非对图片像素进行 OCR 的专用图内处理器。

`_ocr_preprocess` 的普通模式也会跳过已有文字层的页面。
强制模式可先栅格化选定页面，但这不是只处理图表区域的方案。

独立 `ScannedPdfTranslator` 使用 RapidOCR、版面分区及段落排版。
`_OCR_KEEP_CLASSES` 含 table、figure、isolate_formula，译文页会贴回这些保留区域的原图。

**结论：适合借鉴桌面任务调度、进度/取消、页码限制、OCR 复用、中文字体；
读取到的流程没有完整覆盖本次混合论文页的图内英文像素替换。**
不能因为存在 `translate_figures` 参数就认定已满足需求。

## 3. manga-translator：真正的图内擦除与回填

阅读提交：`a33ee0627590359399afd3eb98d60459fc6cfe5f`。

已读：

- [manga_translator.py](https://github.com/Antratech-Studios/manga-translator/blob/a33ee0627590359399afd3eb98d60459fc6cfe5f/manga_translator/manga_translator.py)
- [inpainting/__init__.py](https://github.com/Antratech-Studios/manga-translator/blob/a33ee0627590359399afd3eb98d60459fc6cfe5f/manga_translator/inpainting/__init__.py)
- [rendering/__init__.py](https://github.com/Antratech-Studios/manga-translator/blob/a33ee0627590359399afd3eb98d60459fc6cfe5f/manga_translator/rendering/__init__.py)

主流程把文字检测、OCR、文字行合并、翻译、掩膜细化、背景修补、回填排版分成独立步骤。
修补输入是文字掩膜，而不只是一个粗矩形。
可缓存修补器实例；默认 AOT 与 LaMa/SD 等选项带有模型依赖。

**结论：可参考图内处理的模块边界与掩膜机制，不能直接替代论文 PDF 的图表定位和写回。**
首版不引入其完整漫画模型栈，改用已带的 RapidOCR 和不需要模型的局部填补/修补。
模型修补是否改善科研箭头和细线，必须靠实际样本比较。

## 4. PDFFigures2：论文图表区域定位

阅读提交：`3d7ad46753d4a315cccd1c2bcab398380e88c534`。
已读：[FigureExtractor.scala](https://github.com/allenai/pdffigures2/blob/3d7ad46753d4a315cccd1c2bcab398380e88c534/src/main/scala/org/allenai/pdffigures2/FigureExtractor.scala)。

它从文本、版面、图注候选和图形区域出发抽取图表，提供区域元数据及栅格化结果。
这能解释为什么 `get_images()` 无法代表全部论文插图：矢量绘图和 PDF 文字也可能共同组成一张图。

**结论：借鉴“以完整 figure 区域为单位”，不把提取出的单个图片对象当成整幅图。**
它不是翻译器，且采用 Scala/JVM；首版不新增这套运行时。
优先验证已有版面检测模型，保留人工修正图框作为兜底。

## 5. translate-academic-pdf：原生文字和人工校正标签

阅读提交：`1cdaf0ab320802fefdd5ecf784e6fbad29dc4ce9`。

已读：

- [translate_academic_pdf.py](https://github.com/FertayLageeze/translate-academic-pdf/blob/1cdaf0ab320802fefdd5ecf784e6fbad29dc4ce9/scripts/translate_academic_pdf.py)
- [translate_inplace_babeldoc.py](https://github.com/FertayLageeze/translate-academic-pdf/blob/1cdaf0ab320802fefdd5ecf784e6fbad29dc4ce9/scripts/translate_inplace_babeldoc.py)

`--translate-figure-labels` 控制原生文字块的标签过滤。
`replace_literal_labels` 可针对给定标签映射，在文字层中定位、删除并按方向插入中文。
使用 `apply_redactions(images=0, graphics=0)` 保留图片与矢量图形。

**结论：适合参考原生文字优先、方向处理、术语保护、校正映射和质量报告。**
它的这些处理依赖可提取文字，不能直接识别图片像素里的标签。

## 6. TranslaTHOR：本轮只核对文档

来源：[项目 README](https://github.com/gabsbarreto/TranslaTHOR)。
本轮未对其完整源码作审查。文档明确说明当前图表作为原图保留，
图外 caption 可以翻译，内部坐标轴、图例与注释仍保留原语言。

**结论：根据文档，不是本次图内翻译的现成替代方案。**

## 本地可复用资源

用户原项目位于 `G:\pdf2zh-v1.9.11-win64\pdf2zh`。
包内已核验 RapidOCR 1.4.4、ONNX Runtime 1.22.1、OpenCV 4.11.0 和 PyMuPDF 1.25.2。
RapidOCR 三个模型合计约 15.44 MiB，不代表运行内存占用。

根目录与 `build/site-packages/pdf2zh` 两份源码中 `translator.py` 已有差异。
新项目单独建库，不覆盖用户原翻译 API 改动；也不上传用户论文、密钥、缓存或模型。
