"""Local-only PDF workflow: find figures, review labels, translate, export."""
from pathlib import Path
import threading
import uuid

import gradio as gr
import pymupdf as fitz

from .api import APIConfig, Translator, load_local_config
from .core import Scanner, Cancelled, pix_array
from .render import export_pdf

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "workspace"
SCANNER = Scanner()
EVENTS = {}


def rows(figures):
    return [[l.enabled, l.id, l.text, l.translation, f.page, l.source, l.reason] for f in figures for l in f.labels]


def apply_rows(figures, data):
    labels = {l.id: l for f in figures for l in f.labels}
    if data is None:
        return
    seen = set()
    for row in data:
        ident = str(row[1])
        if ident not in labels or ident in seen:
            raise gr.Error("标签编号不可修改或重复。请重新识别。")
        seen.add(ident)
        label = labels[ident]
        label.enabled = row[0] is True or str(row[0]).lower() == "true"
        label.text = str(row[2] or "").strip()
        label.translation = str(row[3] or "").strip()
        if "旋转标签" in label.reason:
            label.enabled = False
    if seen != set(labels):
        raise gr.Error("请不要删除标签行；取消勾选即可跳过。")


def preview(pdf, page_number):
    if not pdf:
        return None, None
    with fitz.open(pdf) as doc:
        if doc.needs_pass:
            raise gr.Error("请先解密 PDF。")
        number = int(page_number)
        if not 1 <= number <= len(doc):
            raise gr.Error(f"该 PDF 共 {len(doc)} 页。")
        page = doc[number - 1]
        page.set_rotation(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), colorspace=fitz.csRGB, alpha=False)
        return pix_array(pix), {"page": number, "scale": 1.5, "x": pix.x, "y": pix.y}


def select_corner(meta, corners, regions, evt: gr.SelectData):
    if not meta:
        return [], regions, "请先打开论文页面。"
    x, y = evt.index
    point = [(x + meta["x"]) / meta["scale"], (y + meta["y"]) / meta["scale"]]
    if not corners or corners[0]["page"] != meta["page"]:
        return [{"page": meta["page"], "point": point}], regions, "已选第一个角。再点击图表的对角，完成框选。"
    other = corners[0]["point"]
    box = [min(point[0], other[0]), min(point[1], other[1]), max(point[0], other[0]), max(point[1], other[1])]
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return [], regions, "区域太小，请重新点击两个对角。"
    updated = list(regions) + [{"page": meta["page"], "bbox": box}]
    return [], updated, f"已框选 {len(updated)} 个图表区域。可继续翻页添加。"


def scan(pdf, pages, manual_only, regions, request: gr.Request, progress=gr.Progress()):
    if not pdf:
        raise gr.Error("请先上传论文 PDF。")
    if manual_only and not regions:
        raise gr.Error("请先在论文预览上点击图表的两个对角。")
    event = threading.Event()
    EVENTS[request.session_hash] = event
    directory = WORKSPACE / uuid.uuid4().hex
    try:
        figures = SCANNER.scan(pdf, directory, pages, regions if manual_only else None, event, progress)
    except (ValueError, Cancelled) as exc:
        raise gr.Error(str(exc)) from None
    job = {"pdf": pdf, "directory": str(directory), "figures": figures}
    gallery = [(f.preview, f"第 {f.page} 页 · {f.id}") for f in figures]
    eligible = sum(l.enabled for f in figures for l in f.labels)
    warning = "" if SCANNER.detector.path.exists() or manual_only else " 未找到本地版面模型，目前仅定位嵌入图片；矢量图请框选。"
    return job, gallery, rows(figures), f"找到 {len(figures)} 幅图，{eligible} 个标签待翻译。请检查原文，可取消勾选或直接填写中文。{warning}", None, None, None


def translate(job, data, base, model, key, background, use_context, request: gr.Request, progress=gr.Progress()):
    if not job:
        raise gr.Error("请先识别图内文字。")
    apply_rows(job["figures"], data)
    local = load_local_config()
    config = APIConfig(base.strip() or local.base_url, model.strip() or local.model, key.strip() or local.key)
    event = threading.Event()
    EVENTS[request.session_hash] = event
    try:
        pending = any(l.enabled and not l.translation for f in job["figures"] for l in f.labels)
        if pending:
            Translator(config, WORKSPACE / "translation-cache.json", background=background,
                       use_context=use_context).translate(job["figures"], event, progress)
        mono, dual, report, replaced = export_pdf(job["pdf"], job["figures"], job["directory"], event, progress)
    except (ValueError, Cancelled) as exc:
        raise gr.Error(str(exc)) from None
    return job, rows(job["figures"]), mono, dual, report, f"完成 {replaced} 个标签的回填。复杂背景、线条交叠或放不下的标签保留原文，详情见报告。"


def cancel(request: gr.Request):
    event = EVENTS.get(request.session_hash)
    if event:
        event.set()
    return "已请求停止；正在进行的 API 请求返回或超时后停止，原 PDF 不会被覆盖。"


def launch(port=7868, inbrowser=True):
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    local = load_local_config()
    with gr.Blocks(title="论文图内翻译", theme=gr.themes.Soft()) as app:
        gr.Markdown("# 论文图内翻译\n让论文架构图、流程图中的英文回填为中文。OCR 在本机运行，翻译 API 只接收标签文字。")
        job = gr.State(None)
        meta, corners, regions = gr.State(None), gr.State([]), gr.State([])
        pdf = gr.File(label="论文 PDF", file_types=[".pdf"], type="filepath")
        with gr.Row():
            pages = gr.Textbox(label="处理页码", placeholder="留空为全部，或填写 1-3,5")
            manual_only = gr.Checkbox(label="仅处理我框选的图表", value=False)
        with gr.Accordion("论文预览与手工框选（自动定位遗漏时使用）", open=False):
            gr.Markdown("页面以正向显示，坐标会写回原 PDF。依次点击一幅图的两个对角，可跨页添加多幅图。框选时避开正文和图外说明。")
            with gr.Row():
                page_number = gr.Number(label="预览页码", value=1, precision=0, minimum=1)
                show = gr.Button("显示这一页")
                clear = gr.Button("清空框选")
            page_image = gr.Image(label="点击图表的两个对角", interactive=False, type="numpy")
            region_status = gr.Textbox(label="框选状态", interactive=False)
        with gr.Accordion("翻译 API（自动读取旧 pdf2zh 的本地配置）", open=False):
            base = gr.Textbox(label="API 地址", value=local.base_url, placeholder="https://服务地址/v1")
            model = gr.Textbox(label="模型名称", value=local.model)
            key = gr.Textbox(label="密钥（留空复用旧项目配置，不保存）", type="password")
        with gr.Accordion("论文上下文与术语", open=True):
            use_context = gr.Checkbox(label="翻译时附上图注与附近少量正文，帮助模型理解术语", value=True)
            background = gr.Textbox(label="补充背景（可选）", lines=3,
                                    placeholder="例如：这是机器人控制论文，ViT 指 Vision Transformer，保留缩写；action expert 译为动作专家。")
        with gr.Row():
            find_button = gr.Button("1. 定位图表并识别文字", variant="primary")
            translate_button = gr.Button("2. 翻译并写回 PDF", variant="primary")
            stop_button = gr.Button("停止")
        status = gr.Textbox(label="处理状态", interactive=False)
        gallery = gr.Gallery(label="检测到的论文图表", columns=2, height=340)
        table = gr.Dataframe(headers=["翻译", "编号", "原文（可校正）", "中文（清空可重译）", "页码", "来源", "说明"],
                             datatype=["bool", "str", "str", "str", "number", "str", "str"], type="array", interactive=True, wrap=True)
        with gr.Row():
            mono = gr.File(label="图内中文版 PDF")
            dual = gr.File(label="原文与译文双语 PDF")
            report = gr.File(label="替换与跳过详情")
        show.click(preview, [pdf, page_number], [page_image, meta])
        page_image.select(select_corner, [meta, corners, regions], [corners, regions, region_status])
        clear.click(lambda: ([], [], "已清空框选"), outputs=[corners, regions, region_status])
        pdf.change(lambda: (None, [], [], None, [], [], "", None, None, None),
                   outputs=[job, corners, regions, page_image, gallery, table, status, mono, dual, report])
        find_button.click(scan, [pdf, pages, manual_only, regions], [job, gallery, table, status, mono, dual, report])
        translate_button.click(translate, [job, table, base, model, key, background, use_context], [job, table, mono, dual, report, status])
        stop_button.click(cancel, outputs=[status], queue=False)
    app.queue(default_concurrency_limit=1).launch(server_name="127.0.0.1", server_port=port, share=False, inbrowser=inbrowser,
                                                 allowed_paths=[str(WORKSPACE)], show_error=False)


if __name__ == "__main__":
    launch()
