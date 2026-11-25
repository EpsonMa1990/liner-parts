from __future__ import annotations

import base64
import json
import re

import httpx

from .stitching import stitch_crops


class RecognitionError(ValueError):
    pass


def parse_result(text, expected):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        raise RecognitionError("模型未返回有效 JSON，请重试或调整提示词。") from None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or len(items) != len(expected):
        raise RecognitionError("识别结果数量与框选数量不一致，本批结果未写入。")
    results = {}
    for item in items:
        if not isinstance(item, dict):
            raise RecognitionError("识别结果结构无效。")
        box_id = item.get("box_id")
        if not isinstance(box_id, str) or box_id not in expected or box_id in results:
            raise RecognitionError("识别结果的框 ID 缺失、重复或不匹配，本批结果未写入。")
        result = {}
        for field in ("raw_text", "runner", "part_number", "note"):
            value = item.get(field)
            if value is None:
                value = ""
            if not isinstance(value, str) or len(value) > 500:
                raise RecognitionError("模型返回了无效字段，编号必须为字符串。")
            result[field] = value.strip()
        status = item.get("status")
        if status not in ("recognized", "review"):
            raise RecognitionError("模型返回了无效的识别状态。")
        if not result["runner"] or not result["part_number"]:
            status = "review"
        result["status"] = status
        results[box_id] = result
    return results


class Recognizer:
    def __init__(self, config, transport=None):
        self.config = config
        headers = {"Authorization": f"Bearer {config['api_key']}"} if config["api_key"] else {}
        self.client = httpx.Client(
            headers=headers,
            timeout=config["timeout"],
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def close(self):
        self.client.close()

    def _post(self, body, cancel):
        for attempt in range(3):
            if cancel.is_set():
                raise RecognitionError("任务已取消。")
            try:
                response = self.client.post(self.config["base_url"] + "/chat/completions", json=body)
            except httpx.TimeoutException:
                raise RecognitionError("模型请求超时，请稍后重试或增加超时时间。") from None
            except httpx.HTTPError:
                raise RecognitionError("无法连接模型接口，请检查 Base URL 和网络。") from None
            if response.status_code == 429 or response.status_code in (500, 502, 503, 504):
                if attempt < 2:
                    cancel.wait(2**attempt)
                    continue
            if response.is_error or response.is_redirect:
                messages = {
                    401: "API Key 无效或已过期。",
                    403: "当前密钥没有访问此模型的权限。",
                    404: "接口或模型不存在，请检查 Base URL 和模型名称。",
                    429: "接口请求过于频繁或额度不足，请稍后重试。",
                    400: "接口不接受当前请求，请检查视觉模型和 JSON 模式设置。",
                }
                raise RecognitionError(
                    messages.get(response.status_code, f"模型接口请求失败（HTTP {response.status_code}）。")
                )
            try:
                data = response.json()
                choice = data["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise RecognitionError("模型输出被截断，请提高服务端输出限制或选择支持更长输出的模型。")
                content = choice["message"]["content"]
                if not isinstance(content, str):
                    raise TypeError()
                return content, data.get("usage", {})
            except RecognitionError:
                raise
            except (ValueError, KeyError, IndexError, TypeError):
                raise RecognitionError("接口返回格式不兼容，需要支持 Chat Completions 的视觉模型。") from None
        raise RecognitionError("模型接口暂时不可用。")

    def recognize(self, crops, cancel):
        image = stitch_crops(crops)
        mapping = {
            "instructions": (
                "本次只有一张纵向拼接图，截图按下列 rows 顺序从上到下排列。"
                "左侧灰色栏的 01、02 等仅为行序号，不是板件或零件号。"
                "逐行识别板件 runner 和零件号 part_number，按 sequence 对应的 box_id 返回。"
                "每行恰好一项，不得遗漏或合并；模糊行也必须返回，status 为 review。"
                "只返回 JSON 对象 items 数组，每项包含 box_id、raw_text、runner、"
                "part_number、status、note；编号使用字符串，status 为 recognized 或 review。"
            ),
            "rows": [{"sequence": index, "box_id": box_id} for index, (box_id, _) in enumerate(crops, 1)],
        }
        content = [
            {"type": "text", "text": json.dumps(mapping, ensure_ascii=False)},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64," + base64.b64encode(image).decode("ascii")},
            },
        ]
        body = {
            "model": self.config["model"],
            "stream": False,
            "messages": [
                {"role": "system", "content": self.config["prompt"]},
                {"role": "user", "content": content},
            ],
        }
        if self.config["json_mode"]:
            body["response_format"] = {"type": "json_object"}
        text, usage = self._post(body, cancel)
        return parse_result(text, {box_id for box_id, _ in crops}), usage

    def models(self):
        try:
            response = self.client.get(self.config["base_url"] + "/models")
            response.raise_for_status()
            return sorted(
                {
                    item["id"]
                    for item in response.json()["data"]
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                }
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise RecognitionError(
                "无法读取模型列表。部分服务不支持此接口，可直接填写视觉模型名称。"
            ) from None
