# SQL Run Report

## Summary
- Server: `34.132.147.127:80`
- Duration: `2.62s`
- Table: `img2img_controlnet`
- Preset: `char_nick`
- Profile: `goldenhour_backlight`
- API Prompt: `/Users/stelios/Downloads/ComfyUI-custom/.state/sql_runs/run_1775899194/statement_001_api_prompt.json`
- Downloaded Outputs: `0`

## SQL
```sql
SELECT image FROM img2img_controlnet USING char_nick PROFILE goldenhour_backlight WHERE prompt='cinematic shot in downtown at sunset' AND seed=123
```

## Images
No images were available.

## Raw Result
```json
{
  "action": "compiled",
  "prompt": {
    "1": {
      "inputs": {
        "images": [
          "13",
          0
        ]
      },
      "class_type": "PreviewImage",
      "_meta": {
        "title": "Preview Image"
      }
    },
    "2": {
      "inputs": {
        "samples": [
          "7",
          0
        ],
        "vae": [
          "3",
          2
        ]
      },
      "class_type": "VAEDecode",
      "_meta": {
        "title": "VAE Decode"
      }
    },
    "3": {
      "inputs": {
        "ckpt_name": "sdxl/Juggernaut_X_RunDiffusion.safetensors"
      },
      "class_type": "CheckpointLoaderSimple",
      "_meta": {
        "title": "Load Checkpoint"
      }
    },
    "5": {
      "inputs": {
        "width": 1024,
        "height": 1024,
        "batch_size": 1
      },
      "class_type": "EmptyLatentImage",
      "_meta": {
        "title": "Empty Latent Image"
      }
    },
    "6": {
      "inputs": {
        "text": "cinematic shot in downtown at sunset, shot on 50mm lens, Medium Shot, Eye Level, natural light, lighting direction back, warm, glowing edges light, golden hour",
        "clip": [
          "3",
          1
        ]
      },
      "class_type": "CLIPTextEncode",
      "_meta": {
        "title": "CLIP Text Encode (Prompt)"
      }
    },
    "7": {
      "inputs": {
        "seed": 123,
        "steps": 40,
        "cfg": 7,
        "sampler_name": "euler",
        "scheduler": "simple",
        "denoise": 1,
        "model": [
          "3",
          0
        ],
        "positive": [
          "22",
          0
        ],
        "negative": [
          "22",
          1
        ],
        "latent_image": [
          "5",
          0
        ]
      },
      "class_type": "KSampler",
      "_meta": {
        "title": "KSampler"
      }
    },
    "8": {
      "inputs": {
        "text": "cartoon, anime, illustration, painting, low quality, blurry, overexposed, oversharpened, unrealistic, bad perspective, distorted buildings, floating objects, duplicate structures, watermark, text, logo, artifacts, no colors in the fce",
        "clip": [
          "3",
          1
        ]
      },
      "class_type": "CLIPTextEncode",
      "_meta": {
        "title": "CLIP Text Encode (Prompt)"
      }
    },
    "10": {
      "inputs": {
        "images": [
          "2",
          0
        ]
      },
      "class_type": "PreviewImage",
      "_meta": {
        "title": "Preview Image"
      }
    },
    "11": {
      "inputs": {
        "image": "nick.jpg.avif"
      },
      "class_type": "LoadImage",
      "_meta": {
        "title": "Load Image"
      }
    },
    "13": {
      "inputs": {
        "preprocessor": "DepthAnythingV2Preprocessor",
        "resolution": 1024,
        "image": [
          "11",
          0
        ]
      },
      "class_type": "AIO_Preprocessor",
      "_meta": {
        "title": "AIO Aux Preprocessor"
      }
    },
    "15": {
      "inputs": {
        "preprocessor": "CannyEdgePreprocessor",
        "resolution": 512,
        "image": [
          "11",
          0
        ]
      },
      "class_type": "AIO_Preprocessor",
      "_meta": {
        "title": "AIO Aux Preprocessor"
      }
    },
    "16": {
      "inputs": {
        "images": [
          "15",
          0
        ]
      },
      "class_type": "PreviewImage",
      "_meta": {
        "title": "Preview Image"
      }
    },
    "20": {
      "inputs": {
        "switch_1": "On",
        "controlnet_1": "diffusion_pytorch_model_promax.safetensors",
        "controlnet_strength_1": 0.8,
        "start_percent_1": 0,
        "end_percent_1": 0.6,
        "switch_2": "On",
        "controlnet_2": "diffusion_pytorch_model_promax.safetensors",
        "controlnet_strength_2": 0.9,
        "start_percent_2": 0,
        "end_percent_2": 1,
        "switch_3": "On",
        "controlnet_3": "diffusion_pytorch_model_promax.safetensors",
        "controlnet_strength_3": 0.6,
        "start_percent_3": 0.1,
        "end_percent_3": 0.6,
        "image_1": [
          "13",
          0
        ],
        "image_2": [
          "15",
          0
        ],
        "image_3": [
          "25",
          0
        ]
      },
      "class_type": "CR Multi-ControlNet Stack",
      "_meta": {
        "title": "\ud83d\udd79\ufe0f CR Multi-ControlNet Stack"
      }
    },
    "22": {
      "inputs": {
        "switch": "On",
        "base_positive": [
          "6",
          0
        ],
        "base_negative": [
          "8",
          0
        ],
        "controlnet_stack": [
          "20",
          0
        ]
      },
      "class_type": "CR Apply Multi-ControlNet",
      "_meta": {
        "title": "\ud83d\udd79\ufe0f CR Apply Multi-ControlNet"
      }
    },
    "25": {
      "inputs": {
        "preprocessor": "SAMPreprocessor",
        "resolution": 512,
        "image": [
          "11",
          0
        ]
      },
      "class_type": "AIO_Preprocessor",
      "_meta": {
        "title": "AIO Aux Preprocessor"
      }
    },
    "26": {
      "inputs": {
        "images": [
          "25",
          0
        ]
      },
      "class_type": "PreviewImage",
      "_meta": {
        "title": "Preview Image"
      }
    }
  },
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
        "asset": "nick.jpg.avif"
      }
    ]
  },
  "api_prompt_path": "/Users/stelios/Downloads/ComfyUI-custom/.state/sql_runs/run_1775899194/statement_001_api_prompt.json"
}
```
