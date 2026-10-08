# Paper Figure Translator

为论文 PDF 中的图表翻译内部英文标签，并将中文回填到原图位置。

输入是论文 PDF，输出是包含中文图表的 PDF。核心场景是正文可复制、图内英文为图片像素的混合文档。
同样需要支持 PDF 原生文字标签、矢量示意图和位图混合的架构图。

## 当前状态

**源码调研与设计阶段，尚无可运行的翻译应用。**

本项目依据用户“先参考 GitHub 其他项目实现”的要求先核验处理方法，
不把“支持扫描件 OCR”误认为“支持论文图内翻译”。

- [源码调研与证据](docs/research.md)
- [实现设计与验收标准](docs/design.md)

## 已确定的技术方向

论文 PDF → 定位图表 → 优先提取原生文字，位图标签使用轻量 RapidOCR
→ 翻译 API → 局部擦除与中文排版 → 写回原 PDF。

使用 CPU OCR，不部署本地大语言模型。优先复用用户现有 Windows 包中的依赖。
复杂图表允许检查并修正识别结果；公式、变量、单位和指定缩写需要保护。

## 参考项目

- [PDFMathTranslate](https://github.com/PDFMathTranslate/PDFMathTranslate)
- [pdf2zh-desktop](https://github.com/AaronGIG/pdf2zh-desktop)
- [manga-translator](https://github.com/Antratech-Studios/manga-translator)
- [PDFFigures2](https://github.com/allenai/pdffigures2)
- [translate-academic-pdf](https://github.com/FertayLageeze/translate-academic-pdf)
- [TranslaTHOR](https://github.com/gabsbarreto/TranslaTHOR)

仓库当前只包含原创调研和设计文档，未复制上述项目源码、模型或运行时。
后续如引入源码，将记录来源并遵守相应许可证。
