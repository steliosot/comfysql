# SQL Run Report

## Summary
- Server: `34.132.147.127:80`
- Duration: `134.72s`
- Table: `img2img_controlnet`
- Preset: `char_bets`
- Profile: `goldenhour_backlight`
- API Prompt: `.state/sql_runs/run_1775900254/statement_001_api_prompt.json`
- Downloaded Outputs: `0`

## SQL
```sql
SELECT image FROM img2img_controlnet USING char_bets PROFILE goldenhour_backlight WHERE prompt='cinematic full-body fashion portrait in Soho street, golden hour, natural light, high detail' AND seed=123
```

## Images
No images were available.

## Raw Result
```json
{
  "action": "select",
  "submitted": true,
  "validation": {
    "status": "ok",
    "nodes": 16,
    "edges": 21,
    "checked_models": [
      {
        "node_id": "3",
        "class_type": "CheckpointLoaderSimple",
        "input": "ckpt_name",
        "category": "checkpoints",
        "model": "sdxl/Juggernaut_X_RunDiffusion.safetensors",
        "verification": "unverified_remote_models_endpoint"
      }
    ],
    "checked_assets": [
      {
        "node_id": "11",
        "class_type": "LoadImage",
        "input": "image",
        "folder_type": "input",
        "asset": "bets.png"
      }
    ]
  },
  "api_prompt_path": ".state/sql_runs/run_1775900254/statement_001_api_prompt.json",
  "upload_preflight": {
    "uploaded_count": 0,
    "skipped_existing_count": 1,
    "failed_count": 0,
    "uploaded": [],
    "skipped_existing": [
      {
        "node_id": "11",
        "class_type": "LoadImage",
        "input_name": "image",
        "local_path": "input/assets/bets.png",
        "remote_path": "bets.png"
      }
    ],
    "failed": [],
    "resolved_paths": [
      {
        "node_id": "11",
        "class_type": "LoadImage",
        "input_name": "image",
        "local_path": "input/assets/bets.png",
        "remote_path": "bets.png",
        "status": "skipped_existing"
      }
    ]
  },
  "prompt_id": "3e513e63-a410-46cb-87ff-8ad4069b082e"
}
```
