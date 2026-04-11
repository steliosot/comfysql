# ComfySQL

ComfySQL is a SQL-style layer on top of ComfyUI.

Goal: make it easy to mix and match:

- workflows
- models
- presets (technical run settings)
- profiles (style/camera/composition settings)
- reusable assets (`CHARACTER` / `OBJECT`)

ComfySQL assumes your workflows already work in ComfyUI.  
Then you use SQL commands to run and reuse them faster.

## Start Here

- Beginner flow: [STARTERS.md](/Users/stelios/Downloads/ComfyUI-custom/STARTERS.md)
- Full command reference: [COMMANDS.md](/Users/stelios/Downloads/ComfyUI-custom/COMMANDS.md)

## Quick Use

Open SQL terminal:

```bash
comfysql sql remote
```

Typical run:

```sql
SELECT image
FROM txt2img_empty_latent
USING default_run
PROFILE goldenhour_backlight
WHERE prompt='cinematic portrait in central London at sunset'
  AND seed=123
  AND filename_prefix='txt2img_london_123';
```

If you use local images, place them in `input/assets` and copy to server:

```bash
comfysql copy-assets remote --all
```

Compatibility alias:

- `comfy-agent` remains fully supported and runs the same CLI.

CLI UX:

- Colors/styles appear automatically in interactive terminals.
- On known failures, CLI now adds a short `hint:` line with the next command to try.

## OpenClaw Skills

Automation and reusable run packs are in `openclaw/`.

- Skill index: [openclaw/OPENCLAW.md](/Users/stelios/Downloads/ComfyUI-custom/openclaw/OPENCLAW.md)
