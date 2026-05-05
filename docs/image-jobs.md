# 图片任务与开发对接

本文档收纳 README 中不适合放在项目首页的作图任务、接口和任务分发方对接细节。日常启用 SwitchBoard 只需要看 README；需要接入外部任务分发方或调试图片 API 时再看这里。

## 运行约定

- “作图”页面提供 `auto` 以及 `1:1`、`3:4`、`4:3`、`9:16`、`16:9` 和 `21:9` 预设，并映射到低、中、高三档像素尺寸。
- 后端请求可以传入 `auto` 或任意 `宽x高` 尺寸，只要满足分辨率约束：宽高为正数、两边都能被 16 整除、最长边不超过 3840 px、宽高比不超过 3:1、总像素数在 655,360 到 8,294,400 之间。
- 多图请求会拆成每张图一个队列任务。SwitchBoard 默认最多同时生成 2 张图，每张图都有独立状态、重试、元数据和游廊卡片。
- 作图任务默认由本地主动式 Worker 处理。任务分发方设置页可以配置多个外部任务分发方；每个未暂停分发方都会独立注册为出站 Runner，并独立心跳、轮询、状态上报和结果回传。暂停某个分发方只会停止该分发方对接，不会停止本地作图任务或其他分发方。
- 游廊卡片会展示来源，并支持按全部、本地或已配置任务分发方筛选。
- 图片详情会在可用时展示脱敏后的上游元数据，包括实际上游尺寸、Host 模型、图片模型、token 总量和上游耗时。
- 上游图片请求使用 `store: false`；后续提示词需要自行写明上下文或附上参考图。
- 生成图片和参考图保存在 `SWITCHBOARD_DATA_DIR/images/YYYY/MM/DD/{job_id}/`，并通过需要登录的 `/api/images/files/{file_path}` 返回。
- 任务元数据保存在 `SWITCHBOARD_DATA_DIR/switchboard.sqlite`。每个任务分发方的 token 都独立写入私有 auth vault，不会以明文写入 SQLite。删除分发方会软删除实时配置并清理 token，但历史任务来源和统计归属仍保留。如果 SwitchBoard 在某张图运行中重启，只有这一个单图任务会标记为失败；同批次里仍在排队的图片会在服务恢复后继续生成。

## 浏览器图片接口

| 接口 | 用途 |
| --- | --- |
| `POST /api/images/jobs` | 提交图片生成任务。 |
| `GET /api/images/gallery?page=1&limit={page_size}&source=all` | 获取轻量游廊卡片，可按来源筛选。 |
| `GET /api/images/jobs/statuses?ids={job_id}` | 获取轻量 active/tracked 任务状态，用于状态轮询。 |
| `GET /api/images/jobs?page=1&limit=20` | 获取轻量任务摘要。 |
| `GET /api/images/jobs/{job_id}` | 获取单个任务完整详情。 |
| `POST /api/images/jobs/{job_id}/stop` | 停止排队中或运行中的图片任务。 |
| `DELETE /api/images/jobs/{job_id}/images/{image_index}` | 删除单张生成结果。 |
| `DELETE /api/images/jobs/{job_id}` | 删除整个任务。 |
| `POST /api/images/generations` | 直接同步调用图片生成接口。 |
| `GET /api/images/task-dispatchers` | 读取所有未删除任务分发方、脱敏 token 状态、Runner 状态、累计图片任务数和当前任务。 |
| `POST /api/images/task-dispatchers` | 新增任务分发方并尝试注册 Runner。 |
| `PUT /api/images/task-dispatchers/{dispatcher_id}` | 更新指定分发方名称、API 地址和 token，并尝试重新注册 Runner。 |
| `POST /api/images/task-dispatchers/{dispatcher_id}/test` | 测试指定分发方连接，不保存新 token。 |
| `POST /api/images/task-dispatchers/{dispatcher_id}/register` | 重新注册指定分发方 Runner。 |
| `POST /api/images/task-dispatchers/{dispatcher_id}/pause` | 暂停指定外部任务分发方对接。 |
| `POST /api/images/task-dispatchers/{dispatcher_id}/resume` | 恢复指定分发方注册、轮询和结果回传。 |
| `DELETE /api/images/task-dispatchers/{dispatcher_id}` | 软删除指定分发方；若仍有活跃任务或待回传结果，会返回冲突错误。 |
| `GET /api/images/task-dispatcher/settings` | 兼容旧接口：读取 `default` 分发方设置。 |
| `PUT /api/images/task-dispatcher/settings` | 兼容旧接口：保存 `default` 分发方设置。 |
| `POST /api/images/task-dispatcher/test` | 兼容旧接口：测试 `default` 分发方连接。 |
| `POST /api/images/task-dispatcher/register` | 兼容旧接口：重新注册 `default` Runner。 |
| `POST /api/images/task-dispatcher/pause` | 兼容旧接口：暂停 `default` 分发方。 |
| `POST /api/images/task-dispatcher/resume` | 兼容旧接口：恢复 `default` 分发方。 |
| `GET /api/images/workers/status` | 查看系统 Worker、执行槽、队列、租约和分发方状态。 |

## 任务分发方对接

- Runner 心跳保持轻量；外部任务状态变化会按分发方单独上报到对应状态接口，让分发方无需等待最终回传即可观察排队、租约、运行、成功、失败和取消状态变化。
- 任务分发方状态面板会按分发方展示 Runner 当前持有的外部任务，包括来源任务 ID、运行状态和提示词；执行槽、队列和租约属于系统信息，不归到单个分发方卡片。
- 分发方“图片任务数”按单图 `image_jobs` 统计，多图请求会累计多次；失败、取消、运行中和成功任务都会计入。
- 外部任务分发方的成功结果会以 `multipart/form-data` 回传，包含 `status=succeeded` 以及一个或多个承载图片二进制的 `image` 文件字段。
- 失败或取消的终态结果会以 JSON 回传。
