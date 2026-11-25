from __future__ import annotations

import hashlib
import ipaddress
import json
import threading
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import keyring

from .stitching import BATCH_SIZE


def normalize_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parts = urlsplit(value)
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("请填写有效的 Base URL，不要包含密钥、查询参数或片段。")
    try:
        local = ipaddress.ip_address(parts.hostname).is_loopback
    except ValueError:
        local = parts.hostname == "localhost"
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ValueError("远程接口需要 HTTPS；本机模型服务可以使用 HTTP。")
    path = parts.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    if not path:
        path = "/v1"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


class Settings:
    def __init__(self, root: Path):
        self.path = root / "settings.json"
        self.account = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]
        self.lock = threading.RLock()
        self.session_keys = {}
        self.defaults = {
            "base_url": "https://api.openai.com/v1",
            "model": "",
            "timeout": 90,
            "batch_size": BATCH_SIZE,
            "json_mode": False,
            "remember_key": True,
            "prompt": "",
        }
        self.data = dict(self.defaults)
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                self.data.update({k: v for k, v in loaded.items() if k in self.defaults})
            except (ValueError, OSError):
                pass
        # Older installations used small multi-image batches. Always migrate to one 10-crop image.
        self.data["batch_size"] = BATCH_SIZE
        self.default_prompt = (Path(__file__).parent / "prompts" / "recognition.txt").read_text("utf-8")

    def _credential(self, url):
        return self.account + ":" + hashlib.sha256(url.encode()).hexdigest()[:20]

    def key(self, url=None):
        with self.lock:
            url = url or self.data["base_url"]
            if url in self.session_keys:
                return self.session_keys[url]
            if self.data["remember_key"]:
                try:
                    return keyring.get_password("liner-parts", self._credential(url)) or ""
                except Exception:
                    return ""
            return ""

    def public(self):
        with self.lock:
            return {**self.data, "has_key": bool(self.key()), "default_prompt": self.default_prompt}

    def snapshot(self):
        with self.lock:
            return {
                **self.data,
                "api_key": self.key(),
                "prompt": self.data["prompt"].strip() or self.default_prompt,
            }

    def save(self, payload):
        with self.lock:
            data = {k: payload.get(k, v) for k, v in self.data.items()}
            data["base_url"] = normalize_url(str(data["base_url"]))
            data["model"] = str(data["model"]).strip()[:200]
            data["prompt"] = str(data["prompt"]).strip()
            if len(data["prompt"]) > 20000:
                raise ValueError("提示词请控制在 20000 字符以内。")
            data["batch_size"] = BATCH_SIZE
            for field, low, high in [("timeout", 15, 300)]:
                try:
                    data[field] = int(data[field])
                except (TypeError, ValueError):
                    raise ValueError("超时时间需要填写整数。") from None
                if not low <= data[field] <= high:
                    raise ValueError(f"{field} 需要在 {low} 到 {high} 之间。")
            for field in ("remember_key", "json_mode"):
                if not isinstance(data[field], bool):
                    raise ValueError("开关配置无效。")
            key = str(payload.get("api_key", "")).strip()
            if "\n" in key or "\r" in key or len(key) > 4096:
                raise ValueError("API Key 格式无效。")
            url = data["base_url"]
            notice = ""
            existing = self.key(url)
            if payload.get("clear_key"):
                key = ""
                self.session_keys.pop(url, None)
                try:
                    keyring.delete_password("liner-parts", self._credential(url))
                except keyring.errors.PasswordDeleteError:
                    pass
                except Exception:
                    raise ValueError(
                        "系统凭据无法删除，请在系统凭据管理器中移除 liner-parts 凭据。"
                    ) from None
            else:
                key = key or existing
                if key:
                    self.session_keys[url] = key
                if data["remember_key"] and key:
                    try:
                        keyring.set_password("liner-parts", self._credential(url), key)
                    except Exception:
                        data["remember_key"] = False
                        notice = "系统凭据存储不可用，密钥仅在本次运行中保留。"
                elif not data["remember_key"]:
                    try:
                        keyring.delete_password("liner-parts", self._credential(url))
                    except keyring.errors.PasswordDeleteError:
                        pass
                    except Exception:
                        if existing:
                            raise ValueError(
                                "无法清除已保存的系统凭据，请先在系统凭据管理器中删除。"
                            ) from None
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(self.path)
            self.data = data
            return {**self.public(), "notice": notice}
