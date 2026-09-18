# video-remake stage templates

Use these templates with `opencli maybeai-video-app stage video-remake <stage>`.

Recommended order:

```bash
opencli maybeai-video-app stage video-remake script --input-file clis/maybeai-video-app/templates/video-remake-stage/01-script.input.json --debug
opencli maybeai-video-app stage video-remake main-image --input-file clis/maybeai-video-app/templates/video-remake-stage/02-main-image.input.json --debug
opencli maybeai-video-app stage video-remake shot-image --input-file clis/maybeai-video-app/templates/video-remake-stage/03-shot-image.input.json --debug
opencli maybeai-video-app stage video-remake shot-video --input-file clis/maybeai-video-app/templates/video-remake-stage/04-shot-video.input.json --debug
opencli maybeai-video-app stage video-remake concat --input-file clis/maybeai-video-app/templates/video-remake-stage/05-concat.input.json --debug
```

Keep the same `task_id` across all five files when debugging a single run.

Data to copy between stages:

- `01-script` output `main_image_prompt` -> `02-main-image.main_image_prompt` and `03-shot-image.main_image_prompt`
- `01-script` output `shots` -> `03-shot-image.shots`
- `02-main-image` output `main_image` -> `03-shot-image.main_image` and `04-shot-video.main_image`
- `03-shot-image` output `items[].image_url` plus `items[].shot` -> `04-shot-video.items[]`
- `04-shot-video` output `items[].video_url` -> `05-concat.video_urls[]`
