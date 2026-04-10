#### 0) We now have a custom ComfyUI server that runs standalone

Its very simple. No comfy server is required. This command uses a minimal comfyUI setup and start a comfy backend server.

```bash
comfy-agent restart
```

You can run commands using cli or SQL terminal.

Example of a direct command

```bash
comfy-agent submit /absolute/path/workflow.json
```

#### 1) Using the SQL terminal

```bash
comfy-agent sql
comfysql>
```

Everything saved as a table. We have 3 types:

- dynamic node tables (from Comfy `/object_info`)
- template tables (built-ins)
- workflow tables you create via CREATE TABLE ... AS WORKFLOW ...

#### 2) Create template from JSON

- **Template**: a predefined workflow shape (for example `img2img_process`). Think “recipe type.”

```sql
CREATE TABLE txt2img_empty AS WORKFLOW '/Users/stelios/Downloads/s_txt2img_empty_latent.json';
```

#### 3) Create a profile

- **Profile**: reusable style/cinematic metadata (lens, camera, lighting) applied on top of a query.

Create a profile

```sql
CREATE PROFILE lens_50mm
  AND width=1344
  AND height=768;
```

Create a profle (reusing a profile)

```sql
CREATE PROFILE cinematic_portrait
  WITH lens='50mm (Standard)'
    AND camera_distance='Medium Close-Up'
    AND camera_angle='Low Angle'
    AND lighting_direction='front, side, back, top'
    AND lighting_type='natural light'
    AND lighting_quality='soft'
    AND lighting_time='golden hour';
```

### 4) Create a preset (desk) for this template

* A preset is a saved set of technical parameters for a specific template/workflow table.

```sql
CREATE PRESET zehra_1 FOR txt2img_empty
  WITH ckpt_name='juggernaut_reborn.safetensors'
    AND steps=20
    AND cfg=8
    AND sampler_name='euler'
    AND scheduler='normal'
    AND denoise=1
    AND width=1024
    AND height=1024
    AND batch_size=1
    AND negative_prompt='bad hands, blurry, low quality'
    AND filename_prefix='zehra';
```

### 5) Run with preset + profile
```sql
SELECT image FROM txt2img_empty USING zehra_1 PROFILE cinematic_portrait
	WHERE prompt='a cinematic portrait of a woman' AND seed=12345;
```

> save command as `.sql` and run it.
>
> ```bash
> comfy-agent sql --sql-file /absolute/path/my_query.sql
> ```

> `my_query.sql` comes with `SKILL.md`.

### 6) Run with no preset (fully explicit)

```sql
SELECT image FROM txt2img_empty
  WHERE ckpt_name='juggernaut_reborn.safetensors'
    AND steps=20
    AND cfg=8
    AND sampler_name='euler'
    AND scheduler='normal'
    AND denoise=1
    AND width=1024
    AND height=1024
    AND batch_size=1
    AND prompt='a cinematic portrait of a woman'
    AND negative_prompt='bad hands, blurry, low quality'
    AND seed=12345
    AND filename_prefix='zehra';
```

## Recommended to start

**12 templates (starter set):**

1. txt2img_basic
2. img2img_basic
3. inpaint_basic
4. outpaint_basic
5. upscale_image
6. controlnet_txt2img
7. controlnet_img2img
8. image_variation
9. image_blend_2to1 (combine 2 images)

1. txt2video_basic
2. img2video_basic
3. txt2audio_basic

**Recommended 10 profiles (cinematic/style layer):**

1. wide_24mm
2. natural_35mm
3. standard_50mm
4. portrait_85mm
5. closeup_soft_light
6. mediumshot_natural
7. dramatic_low_angle
8. high_angle_overcast
9. studio_hard_side

1. goldenhour_backlight

**Recommended 6 presets:**

1. fast_preview
2. balanced_default
3. high_quality
4. photoreal
5. anime_style
6. video_safe_lowmem

## Base Models

- FLUX.1-schnell

**Speed LoRA**

- FLUX-Turbo-Alpha

**Style LoRAs**

- cinematic-film-lora
- portrait-lighting-lora
- anime-style-lora

**Video**

- LTX-Video

**Audio**

- bark