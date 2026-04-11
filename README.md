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

A typical run with an existing character (Matt) wearing an object (hat), using a preconfigured profile (50mm lens):

```sql
SELECT image
FROM img2img_2_inputs
CHARACTER char_matt
OBJECT obj_hat
PROFILE lens_50mm
WHERE prompt='cinematic portrait of Matt wearing a summer hat walking in central London';
```

**ComfySQL customizes your ComfyUI workflows with characters, objects, shooting profiles, and configurations, making production easy and reproducible at scale.**

![Group 6](output/matt_gen_group.png)

So you can keep customizing as you like.

```sql
SELECT image
FROM img2img_2_inputs
CHARACTER char_bets
OBJECT obj_hat
PROFILE lens_50mm
WHERE prompt='cinematic portrait of Betts wearing a summer hat walking in central London';
```

![bets_gen](output/bets_gen.png)

## OpenClaw Skills

Automation and reusable run packs are in `openclaw/`.

- Skill index: [openclaw/OPENCLAW.md](/Users/stelios/Downloads/ComfyUI-custom/openclaw/OPENCLAW.md)
