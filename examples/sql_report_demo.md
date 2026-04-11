# SQL Report Demo

## Summary
- Server: `34.132.147.127:80`
- Duration: `29.66s`
- Table: `txt2img_empty_latent`
- Preset: `default_run`
- Profile: `portrait_85mm`
- API Prompt: `/Users/stelios/Downloads/ComfyUI-custom/.state/sql_runs/run_1775898991/statement_001_api_prompt.json`
- Downloaded Outputs: `8`

## SQL
```sql
SELECT image FROM txt2img_empty_latent USING default_run PROFILE portrait_85mm WHERE prompt='cinematic portrait at sunset in a city street' AND seed=321 AND steps=16;
```

## Images
![txt2img_00001_.png](/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00001_.png)

![txt2img_00002_.png](/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00002_.png)

![txt2img_00003_.png](/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00003_.png)

![txt2img_00004_.png](/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00004_.png)

![txt2img_00005_.png](/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00005_.png)

![txt2img_00006_.png](/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00006_.png)

![txt2img_00007_.png](/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00007_.png)

![txt2img_00008_.png](/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00008_.png)

## Raw Result
```json
{
  "action": "select",
  "submitted": true,
  "validation": {
    "status": "ok",
    "nodes": 7,
    "edges": 9,
    "checked_models": [
      {
        "node_id": "4",
        "class_type": "CheckpointLoaderSimple",
        "input": "ckpt_name",
        "category": "checkpoints",
        "model": "sdxl/juggernautXL_version2.safetensors",
        "verification": "unverified_remote_models_endpoint"
      }
    ],
    "checked_assets": []
  },
  "api_prompt_path": "/Users/stelios/Downloads/ComfyUI-custom/.state/sql_runs/run_1775898991/statement_001_api_prompt.json",
  "upload_preflight": {
    "uploaded_count": 0,
    "skipped_existing_count": 0,
    "failed_count": 0,
    "uploaded": [],
    "skipped_existing": [],
    "failed": [],
    "resolved_paths": []
  },
  "prompt_id": "42fcc856-7eb1-4999-b7a3-445677512a89",
  "downloaded_outputs": [
    "/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00001_.png",
    "/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00002_.png",
    "/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00003_.png",
    "/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00004_.png",
    "/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00005_.png",
    "/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00006_.png",
    "/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00007_.png",
    "/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo/txt2img_00008_.png"
  ],
  "downloaded_count": 8,
  "download_failures": [],
  "download_status": "ok",
  "download_dir": "/Users/stelios/Downloads/ComfyUI-custom/output/sql_report_demo"
}
```
