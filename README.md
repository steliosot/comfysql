# ComfySQL

`ComfySQL` is a SQL-style CLI for running and managing ComfyUI workflows.

## Why

You build a workflow, find a sweet spot, then need to scale variations:
- camera/lens styles
- scheduler/steps/cfg combos
- different dimensions and reusable defaults

Doing this manually in nodes is slow. ComfySQL gives you reusable layers:
- `WORKFLOW TABLE`: imported workflow JSON
- `PRESET`: saved technical defaults for a workflow table
- `PROFILE`: reusable style/spec overrides you can combine at runtime

---

## Requirements

- Python 3.10+
- A running ComfyUI server (`localhost` or remote)
- Workflows and models available on that server

---

## Installation (First User Quickstart)

```bash
python3 -m pip install "git+https://github.com/steliosot/comfysql.git"
```

Update to latest:

```bash
python3 -m pip install --upgrade --force-reinstall "git+https://github.com/steliosot/comfysql.git@main"
```

Create local config:

```bash
comfy-agent config init
```

If you cloned this repo, you can also copy the included sample:

```bash
cp comfy-agent-copy.json comfy-agent.json
```

Edit `comfy-agent.json` and set your server URL + token (if auth is enabled), for example:

```json
{
  "version": 1,
  "default_server": "remote",
  "servers": {
    "remote": {
      "url": "http://34.132.147.127",
      "auth": {
        "header_name": "Authorization",
        "scheme": "Bearer",
        "token": "YOUR_TOKEN"
      }
    }
  }
}
```

Sanity check connection:

```bash
comfy-agent doctor remote
comfy-agent status remote
```

Optional: refresh node/model catalog cache:

```bash
comfy-agent sync remote
```

---

## Quickstart (SQL)

Open SQL terminal:

```bash
comfy-agent sql remote
```

1. Import a workflow:

```sql
CREATE TABLE txt2img_empty AS WORKFLOW '/Users/stelios/Downloads/ComfyUI-custom/input/workflows/txt2img_empty_latent.json';
```

2. Create a basic profile:

```sql
CREATE PROFILE lens_50mm
  WITH width=1344
   AND height=768;
```

3. Create a cinematic profile:

```sql
CREATE PROFILE cinematic_portrait_lens_50mm
  WITH lens='50mm (Standard)'
   AND camera_distance='Medium Close-Up'
   AND camera_angle='Low Angle'
   AND lighting_direction='front, side, back, top'
   AND lighting_type='natural light'
   AND lighting_quality='soft'
   AND lighting_time='golden hour';
```

4. Generate with profile:

```sql
SELECT image FROM txt2img_empty PROFILE lens_50mm
WHERE prompt='a cinematic portrait of a woman' AND seed=100;
```

5. Generate with preset + profile:

```sql
CREATE PRESET txt2img_euler FOR txt2img_empty
WITH ckpt_name='juggernaut_reborn.safetensors'
 AND steps=20
 AND cfg=8
 AND sampler_name='euler'
 AND scheduler='normal';

SELECT image FROM txt2img_empty USING txt2img_euler PROFILE cinematic_portrait_lens_50mm
WHERE prompt='a cinematic portrait of a woman' AND seed=1234;
```

Optional: create a template entry directly from a workflow (captures defaults):

```sql
CREATE TEMPLATE txt2img_template AS WORKFLOW '/Users/stelios/Downloads/ComfyUI-custom/input/workflows/txt2img_empty_latent.json';
CREATE PRESET txt2img_template_defaults FOR txt2img_template AS DEFAULTS;
```

---

## Useful Commands

```sql
SHOW TABLES;
SHOW TABLES workflows;
DESCRIBE WORKFLOW txt2img_empty;
SHOW PRESETS;
SHOW PROFILES;
EXPLAIN SELECT image FROM txt2img_empty USING txt2img_euler WHERE seed=1;
```

Non-interactive examples:

```bash
comfy-agent sql remote --sql "SHOW TABLES;"
comfy-agent sql remote --sql "SELECT image FROM txt2img_empty USING txt2img_euler WHERE prompt='cat' AND seed=1;" --download-output --download-dir ./output
```

---

## Models and Assets

- Pull models from Hugging Face config:

```bash
comfy-agent pull --yes
```

- Copy local assets to remote Comfy input via API:

```bash
comfy-agent copy-assets remote --all
```

- SQL `SELECT` auto-uploads local asset paths for supported fields (`LoadImage.image`, `LoadAudio.audio`).

---

## Full Specification

For full CLI and SQL syntax, see [COMMANDS.md](/Users/stelios/Downloads/ComfyUI-custom/COMMANDS.md).
