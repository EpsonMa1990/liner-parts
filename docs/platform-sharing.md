# 可选的广场分享协议

本地取件表制作不需要平台登录。选择分享时，桌面端连接 `https://agamaship.com/api/liner`，使用平台账号密码或平台签发的 JWT。JWT 仅保存在本次进程内存，与模型服务 API Key 相互独立；密码不会保存在本机。

## 完成条件

每个已导入页面都要确认校对完成。全部标记须处于 recognized/manual 状态，分类、板件、零件号完整，数量为 1–9999。没有零件的页面要填写原因。修改或重新识别会使本页确认失效。提交还需填写模型名称并确认整个模型已完成；漏导页面和漏框须由作者与平台审核人员核对。

## 接口

所有请求使用 HTTPS，认证头为 `Authorization: Bearer <平台JWT>`。响应采用 `{code:200,data:{...},msg:"..."}`。

| 方法与相对路径 | 用途 |
| --- | --- |
| POST `/auth/password/login` | 提交 `{account,password}`，获取平台会话 |
| GET `/auth/me` | 验证平台身份及账号是否已设置密码 |
| GET `/square/desktop-submissions/capabilities` | 探测 `{version:1,reward_cards:5,max_bytes:134217728}` |
| POST `/square/desktop-submissions` | multipart 字段 `file` 上传完整模型 ZIP |
| GET `/square/desktop-submissions/:id` | 提交者查询审核状态和广场链接 |

记录包含 `id`、`model_name`、`status`（pending/approved/rejected）、`review_note`、`post_id`。重复提交同一账号同一内容应返回原记录。审核通过后由平台负责发布及一次性发放 5 张 AI 生成卡；客户端不签发 JWT，也不自行发卡。奖励及有效期以运营平台实际开放规则为准。

## 分享包 v1

ZIP 包含 `manifest.json`、`pages/0001.png` 等逐页图片与 `crops/0001-0001.png` 等区域截图。清单包含 `format:"liner-desktop-share"`、`version:1`、`model_name`、`all_model_complete:true` 与有序 `pages`。

页面字段：`index`、`image_file`、`confirmed`、`no_parts_reason`、`boxes`。框字段：`sequence`、`crop_file`、归一化 `x/y/width/height`、`category`、`quantity`、`runner`、`part_number`、`status`。

最大 500 页、10000 个框、每页 1000 框；PNG 单图 20 MB，总包及展开文件共 128 MB。不包含原始 PDF、配置、API Key、提示词、密码、JWT 或本地路径。平台须独立校验完成状态、清单白名单、路径、数量、PNG 内容和大小，并执行权限校验及审核奖励的幂等处理。

平台服务实现不属于此桌面开源仓库。自行对接其他平台时需要实现兼容接口并调整 `src/liner_parts/sharing.py` 中的平台地址。平台接口尚未开放、登录失效或服务异常时，不影响本地功能。
