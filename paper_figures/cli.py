"""CLI entry point and local browser UI launcher."""
import argparse
import json
from pathlib import Path
import uuid

from .api import Translator, load_local_config
from .core import Scanner, manifest
from .render import export_pdf


def main():
    parser = argparse.ArgumentParser(description="翻译论文 PDF 的图内英文标签")
    parser.add_argument("pdf", nargs="?")
    parser.add_argument("--pages", default="", help="1-3,5")
    parser.add_argument("--regions", help='图框 JSON：[{"page":1,"bbox":[x0,y0,x1,y1]}]')
    parser.add_argument("--model", help="本地 DocLayout ONNX 路径；不会下载模型")
    parser.add_argument("--scan-only", action="store_true", help="只识别、不调用 API")
    parser.add_argument("--config", help="本地旧项目配置路径，不写入仓库")
    parser.add_argument("--background", default="", help="给模型的论文背景与术语说明")
    parser.add_argument("--no-context", action="store_true", help="不发送图注及附近正文")
    parser.add_argument("--output", default="workspace")
    parser.add_argument("--port", type=int, default=7868)
    args = parser.parse_args()
    if not args.pdf:
        from .ui import launch
        launch(args.port)
        return
    directory = Path(args.output).resolve() / uuid.uuid4().hex[:12]
    regions = json.loads(Path(args.regions).read_text(encoding="utf-8")) if args.regions else None
    figures = Scanner(args.model).scan(args.pdf, directory, args.pages, regions)
    (directory / "scan.json").write_text(json.dumps(manifest(figures), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"识别 {len(figures)} 幅图、{sum(len(f.labels) for f in figures)} 个标签。")
    if args.scan_only:
        print(f"图表预览与清单：{directory}")
        return
    Translator(load_local_config(args.config), directory.parent / "translation-cache.json", background=args.background,
               use_context=not args.no_context).translate(figures)
    mono, dual, report, replaced = export_pdf(args.pdf, figures, directory)
    print(f"完成 {replaced} 个标签的回填。\n译文：{mono}\n双语：{dual}\n报告：{report}")


if __name__ == "__main__":
    main()
