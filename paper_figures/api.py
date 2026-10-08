"""Text-only API translation. Credentials stay in memory, outside the repo."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import json
import os
import re
from urllib.parse import urlparse

import requests

from .core import DEFAULT_KEEP, check_cancel

PROMPT = """Translate natural-language labels inside a scientific figure into Simplified Chinese.
Keep mathematical notation and technical identifiers unchanged. All __KEEP_N__ tokens must
appear exactly once, unchanged. Use concise labels. Return only a JSON object with a
translations array: {"translations":[{"id":"the input id","text":"Chinese label"}]}.
Return exactly one entry for every input id. No explanations or markdown."""


@dataclass
class APIConfig:
    base_url: str = ""
    model: str = ""
    key: str = field(default="", repr=False)

    def validate(self):
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("API 地址需要是无密钥参数的 http(s) 服务地址。")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("远程 API 请使用 HTTPS。")
        if not self.model.strip() or not self.key.strip():
            raise ValueError("未找到模型或 API 密钥。请读取旧配置或在界面填写。")


def load_local_config(path=None) -> APIConfig:
    """Read only: does not import old source or alter its configuration."""
    config = APIConfig(os.environ.get("OPENAI_BASE_URL", ""), os.environ.get("OPENAI_MODEL", ""), os.environ.get("OPENAI_API_KEY", ""))
    if config.base_url and config.model and config.key:
        return config
    path = Path(path) if path else Path.home() / ".config/PDFMathTranslate/config.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        for name, prefix in [("openailiked", "OPENAILIKED"), ("openai", "OPENAI"), ("deepseek", "DEEPSEEK")]:
            for item in data.get("translators", []):
                if item.get("name") == name:
                    values = item.get("envs", {})
                    candidate = APIConfig(values.get(prefix + "_BASE_URL") or "", values.get(prefix + "_MODEL") or "", values.get(prefix + "_API_KEY") or "")
                    if candidate.base_url and candidate.model and candidate.key:
                        return candidate
    return config


def protect(text, keep):
    values = []
    pattern = r"\b(?:" + "|".join(re.escape(t) for t in sorted(keep, key=len, reverse=True)) + r")\b|\b\d+(?:\.\d+)?\b"

    def replace(match):
        values.append(match.group())
        return f"__KEEP_{len(values) - 1}__"

    return re.sub(pattern, replace, text), values


def restore(text, values):
    found = re.findall(r"__KEEP_\d+__", text)
    expected = [f"__KEEP_{i}__" for i in range(len(values))]
    if sorted(found) != sorted(expected):
        raise ValueError("API 改动了受保护的变量、数字或缩写，已停止回填。")
    for i, value in enumerate(values):
        text = text.replace(f"__KEEP_{i}__", value)
    return text


def validate_batch(content, expected):
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    data = json.loads(content)
    entries = data.get("translations")
    if not isinstance(entries, list):
        raise ValueError("API 没有返回翻译列表。")
    results = {}
    for item in entries:
        if not isinstance(item, dict) or item.get("id") not in expected or item["id"] in results:
            raise ValueError("API 返回了重复或未知标签编号。")
        value = item.get("text")
        if not isinstance(value, str) or not value.strip() or len(value) > 1000:
            raise ValueError("API 返回了空白或异常长的标签。")
        results[item["id"]] = value.strip()
    if set(results) != set(expected):
        raise ValueError("API 返回的标签数量不完整，已停止回填。")
    return results


class Translator:
    def __init__(self, config, cache_path, keep=None, retries=3):
        config.validate()
        self.config = config
        self.keep = DEFAULT_KEEP | set(keep or [])
        self.cache_path = Path(cache_path)
        self.cache = json.loads(self.cache_path.read_text(encoding="utf-8")) if self.cache_path.exists() else {}
        self.retries = retries

    def cache_key(self, text):
        content = json.dumps([self.config.base_url, self.config.model, PROMPT, sorted(self.keep), text], ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()

    def request(self, items, event):
        url = self.config.base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        for attempt in range(self.retries):
            check_cancel(event)
            try:
                response = requests.post(url, headers={"Authorization": "Bearer " + self.config.key, "Content-Type": "application/json"},
                                         json={"model": self.config.model, "temperature": 0, "messages": [
                                             {"role": "system", "content": PROMPT},
                                             {"role": "user", "content": json.dumps(items, ensure_ascii=False)}]}, timeout=(10, 90))
                if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < self.retries:
                    if event:
                        event.wait(attempt + 1)
                    continue
                if not response.ok:
                    raise ValueError(f"翻译 API 请求失败（HTTP {response.status_code}），原文件未修改。")
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                if not isinstance(content, str):
                    raise ValueError("API 未返回文字内容。")
                content = re.sub(r"^<think>.*?</think>\s*", "", content, flags=re.S)
                return validate_batch(content, {item["id"] for item in items})
            except (requests.Timeout, requests.ConnectionError):
                if attempt + 1 == self.retries:
                    raise ValueError("API 连接失败或超时，原文件未修改。") from None
                if event:
                    event.wait(attempt + 1)
        raise ValueError("API 重试次数已用尽。")

    def translate(self, figures, event=None, progress=None):
        for f_index, figure in enumerate(figures):
            check_cancel(event)
            if progress:
                progress(f_index / max(1, len(figures)), f"翻译第 {figure.page} 页图内标签")
            pending = []
            for label in figure.labels:
                if not label.enabled or label.translation.strip():
                    continue
                key = self.cache_key(label.text)
                if key in self.cache:
                    label.translation = self.cache[key]
                else:
                    pending.append(label)
            for start in range(0, len(pending), 20):
                batch = pending[start:start + 20]
                protected = {l.id: protect(l.text, self.keep) for l in batch}
                items = [{"id": l.id, "text": protected[l.id][0]} for l in batch]
                results = self.request(items, event)
                # Validate the entire batch before storing any replacement.
                decoded = {l.id: restore(results[l.id], protected[l.id][1]) for l in batch}
                check_cancel(event)
                for label in batch:
                    label.translation = decoded[label.id]
                    self.cache[self.cache_key(label.text)] = label.translation
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.cache_path.with_suffix(".part")
                temporary.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")
                temporary.replace(self.cache_path)
