# maybeai-video-app

`opencli` 侧负责：

- 自然语言识别具体 video app
- 从自然语言和 flags 里组合结构化参数
- 直接串联 MaybeAI video workflows：storyboard → clip generation → concat

当前首版已接入仓库内已有的关键 workflow 链路：

- `key-workflow/2-video-prompt-gen.json`
- `key-workflow/4-generate-video-from-image.json`
- `key-workflow/5-concat-video.json`

同时 `video-remake` 使用 CLI-only tool-chain：

- `/v1/tool/video/generate`
- `/api/v1/tool/function_call`

## 常用命令

先只看识别结果，不真正执行：

```bash
opencli maybeai-video-app select "给这个商品生成一条 TikTok 短视频 https://example.com/product.jpg" \
  --platform TikTokShop \
  --market "North America"
```

直接执行：

```bash
opencli maybeai-video-app run "给这个商品生成一条 TikTok 短视频 https://example.com/product.jpg https://example.com/model.jpg" \
  --platform TikTokShop \
  --market "North America" \
  --ratio 9:16 \
  --duration 15 \
  --playground-url https://play-be.omnimcp.ai \
  --auth-token $MAYBEAI_AUTH_TOKEN \
  --user-id $MAYBEAI_USER_ID
```

视频翻拍：

```bash
opencli maybeai-video-app run "翻拍这个参考视频" \
  --app video-remake \
  --product https://example.com/product.jpg \
  --person https://example.com/model.jpg \
  --reference-video https://example.com/reference.mp4 \
  --ratio 9:16 \
  --duration 5 \
  --playground-url https://play-be.omnimcp.ai \
  --fastest-api-url https://api.fastest.ai \
  --auth-token $MAYBEAI_AUTH_TOKEN \
  --user-id $MAYBEAI_USER_ID
```

图生视频：

```bash
opencli maybeai-video-app run "让这张图动起来 https://example.com/cover.jpg" \
  --app image-to-video \
  --prompt "slow push-in, soft studio motion, fabric gently moving" \
  --duration 5 \
  --ratio 9:16 \
  --playground-url https://play-be.omnimcp.ai \
  --auth-token $MAYBEAI_AUTH_TOKEN \
  --user-id $MAYBEAI_USER_ID
```

只看将要执行的选择和输入：

```bash
opencli maybeai-video-app run "生成一条种草视频 https://example.com/product.jpg" --dry-run
```

查看 shell 前端对齐后的步骤、用户操作和每步入参/出参：

```bash
opencli maybeai-video-app flow video-remake
opencli maybeai-video-app review video-remake --input-file 01-script.output.json
opencli maybeai-video-app review video-remake --raw-file 04-shot-video.single-s01.output.raw
```

拆开执行单个阶段：

```bash
opencli maybeai-video-app stage video-remake script --input-file script-input.json --debug
opencli maybeai-video-app stage video-remake main-image --input-file main-image-input.json --debug
opencli maybeai-video-app stage video-remake shot-image --input-file shot-image-input.json --shot-ids S01_tracking_shot,S03_medium_full_shot --debug
opencli maybeai-video-app stage video-remake shot-video --input-file shot-video-input.json --shot-ids S01_tracking_shot,S03_medium_full_shot --debug
opencli maybeai-video-app stage video-remake concat --input-file concat-input.json --debug
```

阶段输入约定：

- `script`：传商品图、模特图、参考视频、比例、时长、prompt；输出 `shots_count`、`shot_ids`、`shot_summaries`
- `main-image`：在上一阶段基础上补 `main_image_prompt` 或 `script_result.main_image_prompt`
- `shot-image`：补 `shots` 或 `script_result.shots`，可选 `main_image`；支持 `--shot-ids` 只生成指定镜头；每个返回项都会带 `task_id`、`shot_id`、`prompt`、`image_url`
- `shot-video`：传 `items[{ shot, image_url }]`，可选 `main_image`；支持 `--shot-ids` 只生成指定镜头视频；每个返回项都会带 `task_id`、`shot_id`、`prompt`、`video_url`
- `concat`：传 `video_urls` 或 `items[].video_url`

常见调试/重生方式：

```bash
# 1) 先看 script 拆出了多少个 shot
opencli maybeai-video-app stage video-remake script --input-file script-input.json --debug

# 2) 只给某几个 shot 生图
opencli maybeai-video-app stage video-remake shot-image \
  --input-file shot-image-input.json \
  --shot-ids S01_tracking_shot,S04_profile_medium_shot \
  --debug

# 3) 对不满意的 shot 单独重生视频
opencli maybeai-video-app stage video-remake shot-video \
  --input-file shot-video-input.json \
  --shot-ids S04_profile_medium_shot \
  --debug

# 4) 用快捷命令重跑单个 shot，不用手改 JSON
opencli maybeai-video-app rerun-shot video-remake shot-video \
  --input-file shot-video-input.json \
  --shot-id S04_profile_medium_shot \
  --prompt "your custom video prompt" \
  --debug
```

修改 prompt 的方式：

```bash
# 改主图 prompt：直接修改 main-image.input.json 里的 main_image_prompt

# 改某个 shot 的生图 prompt：在 shot-image.input.json 里传
{
  "shot_image_prompt_overrides": {
    "S01_tracking_shot": "your custom image prompt"
  }
}

# 改某个 shot 的生视频 prompt：在 shot-video.input.json 里传
{
  "shot_video_prompt_overrides": {
    "S01_tracking_shot": "your custom video prompt"
  }
}
```

错误调试方式：

- `shot-image` / `shot-video` 某个镜头失败时，CLI 错误会明确带上对应 `shot_id` 和 `task_id`
- 重新生成时可继续只传这个 `shot_id`

可直接复制的模板在：

```text
clis/maybeai-video-app/templates/video-remake-stage/
```

如果你直接拿 shell `fuse-videos` 表单 JSON 来跑，`opencli` 现在也接受这些 alias：

- `productImage -> product`
- `referenceImage -> person`
- `referenceVideo -> reference_video`
- `userDescription -> prompt`
- `aspectRatio -> ratio`
- `llmModel -> engine`
- `generateAudio -> generate_audio`

## 推荐规则

- 自然语言入口优先用 `run`
- 需要调试识别逻辑时用 `select`
- 已知 app 和完整结构化参数时用 `generate`
- `payload` 用来预览多步 workflow 变量
- 当前首版重点覆盖：
  - `product-ad-video`
  - `listing-video`
  - `ugc-ad-video`
  - `image-to-video`
  - `video-remake`
