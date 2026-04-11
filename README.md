```ASN.1
▄▖     ▐▘  ▄▖▄▖▖ 
▌ ▛▌▛▛▌▜▘▌▌▚ ▌▌▌ 
▙▖▙▌▌▌▌▐ ▙▌▄▌█▌▙▖
         ▄▌   ▘  
```

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](tests)

ComfySQL is a SQL-style layer on top of ComfyUI. Its goal is to make it easy to mix and match complex configurations.

## About

- Description: SQL-first workflow orchestration layer for ComfyUI (workflows, presets, profiles, characters, objects).
- Website: use this repository README/docs (or set your project website in GitHub Settings if you have one).
- Suggested topics: `comfyui`, `sql`, `image-generation`, `automation`, `workflow`, `python`, `cli`.

## Project Standards

- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Contributing Guide](CONTRIBUTING.md)
- [License](LICENSE)

## Quick Install

```bash
python -m pip install "git+https://github.com/steliosot/comfysql.git"
```

This installs the CLI commands:

- `comfysql` (primary)
- `comfy-agent` (compatibility alias)

## Quick Update

```bash
python -m pip install --upgrade "git+https://github.com/steliosot/comfysql.git"
```

## Start Here

- Installation guide: [INSTALL.md](INSTALL.md)
- Beginner tutorial: [STARTERS.md](STARTERS.md)
- Full command reference: [COMMANDS.md](COMMANDS.md)

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

ComfySQL customizes your ComfyUI workflows with characters, objects, shooting profiles, and configurations, making production easy and reproducible at scale.

![Group 6](output/matt_gen_group.png)

So you can keep customizing as you like!

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

- Skill index: [openclaw/OPENCLAW.md](openclaw/OPENCLAW.md)
