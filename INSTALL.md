# ComfySQL Installation Guide

This guide gets you from zero to a working `comfysql` setup.

Primary CLI: `comfysql`  
Compatibility alias: `comfy-agent`

## 1. Prerequisites

- Python 3.10+ (3.11 recommended)
- A running ComfyUI server
  - local example: `http://127.0.0.1:8188`
  - or remote server URL + auth token

## 2. Create a Virtual Environment (recommended)

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
```

## 3. Install ComfySQL

Install from GitHub:

```bash
python -m pip install "git+https://github.com/steliosot/comfysql.git"
```

Quick update later:

```bash
python -m pip install --upgrade "git+https://github.com/steliosot/comfysql.git"
```

## 4. Create Config File

You need a local `comfy-agent.json` in your working folder.

Option A: generate starter config

```bash
comfysql config init
```

Option B: copy the template file

```bash
cp comfy-agent-copy.json comfy-agent.json
```

Then edit `comfy-agent.json`.

## 5. Configure Server

### Localhost only (simple)

Keep only localhost:

```json
{
  "version": 1,
  "default_server": "localhost",
  "servers": {
    "localhost": {
      "url": "http://127.0.0.1:8188",
      "auth": {
        "header_name": "Authorization",
        "scheme": "Bearer",
        "token": ""
      },
      "timeout": {
        "start_seconds": 300,
        "submit_seconds": 600
      }
    }
  }
}
```

### Remote server

Set remote URL and token:

```json
"remote": {
  "url": "http://YOUR_SERVER_IP:8188",
  "auth": {
    "header_name": "Authorization",
    "scheme": "Bearer",
    "token": "YOUR_TOKEN_HERE"
  },
  "timeout": {
    "start_seconds": 300,
    "submit_seconds": 600
  }
}
```

## 6. Verify Installation

```bash
comfysql -h
comfysql status localhost
comfysql doctor localhost
```

If using remote:

```bash
comfysql status remote
comfysql doctor remote
```

## 7. First SQL Check

```bash
comfysql sql localhost --sql "SHOW TABLES;"
```

Or remote:

```bash
comfysql sql remote --sql "SHOW TABLES;"
```

## 8. (Optional) Copy Local Assets

Put files in `input/assets`, then upload:

```bash
comfysql copy-assets localhost --all
```

Or remote:

```bash
comfysql copy-assets remote --all
```

## 9. Open SQL Terminal

```bash
comfysql sql localhost
```

Or:

```bash
comfysql sql remote
```

Exit with:

```text
.exit
```

## Troubleshooting

- Unknown server alias:
  - run `comfysql config init`
  - check `default_server` and `servers` names in `comfy-agent.json`
- Connectivity/auth issues:
  - run `comfysql doctor <alias>`
- SQL errors:
  - run `EXPLAIN SELECT ...;` first
  - for multiline SQL, end with `;`

