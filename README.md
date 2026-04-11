```ASN.1
▄▖     ▐▘  ▄▖▄▖▖ 
▌ ▛▌▛▛▌▜▘▌▌▚ ▌▌▌ 
▙▖▙▌▌▌▌▐ ▙▌▄▌█▌▙▖
         ▄▌   ▘  
```

ComfySQL is a SQL-style layer on top of ComfyUI. Its goal is to make it easy to mix and match complex configurations.

## Start Here

- Beginner tutorial: [STARTERS.md](/Users/stelios/Downloads/ComfyUI-custom/STARTERS.md)
- Full command reference: [COMMANDS.md](/Users/stelios/Downloads/ComfyUI-custom/COMMANDS.md)

## Quick Use

Open SQL terminal:

```bash
comfysql sql remote
```

**A typical run with an existing character (Matt) wearing an object (hat), using a preconfigured profile (50mm lens).**

```sql
SELECT image
FROM img2img_2_inputs
CHARACTER char_matt
OBJECT obj_hat
PROFILE lens_50mm
WHERE prompt='cinematic portrait of Matt wearing a summer hat walking in central London in the Trafalgar Square';
```

![matt_gen](output/matt_gen.png)

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
