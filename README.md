# s3smart

[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)](#)
[![Build](https://img.shields.io/badge/build-passing-brightgreen.svg)](#)
[![AWS](https://img.shields.io/badge/AWS-S3-orange.svg)](https://aws.amazon.com/s3/)

> **Fast, reliable S3 copy and sync utility** with parallel uploads/downloads, resumable transfers, checksum validation, and interactive browse mode.


A high-throughput, intelligent S3 copy/sync utility.

## Features
- Parallel multipart uploads & downloads (resume-ready architecture)
- Resume support
- ETA shown in progress bar
- Sync local <-> S3 and S3 <-> S3
- Opt-in checksum validation (`--checksum`)
- Summary report after each run
- Works with AWS S3 and S3-compatible storage
- s3smart supports all standard AWS authentication methods — including SSO profiles, named profiles, and temporary credentials

## Install

```bash
git clone https://github.com/getjaleel/s3smart.git
cd s3smart
pip install -e .
```

## Setting the Profile via Environment Variable
macOS / Linux (bash / zsh):
```
export AWS_PROFILE=my-sso-profile
s3smart browse

```
Windows PowerShell:
```
$env:AWS_PROFILE = "my-sso-profile"
s3smart browse

```
To make it permanent:
```
[System.Environment]::SetEnvironmentVariable('AWS_PROFILE', 'my-sso-profile', 'User')
```
Windows CMD:
```
set AWS_PROFILE=my-sso-profile
s3smart browse

```

## Profiles
```
s3smart browse --profile my-sso-profile
```
or equivalent:
```
s3smart --profile my-sso-profile browse
```
## Upload a folder
```
s3smart upload ./data s3://mybucket/test/
```
## Download from S3
```
s3smart download s3://mybucket/test/ ./data
```

## Sync folder to and from

# Local → S3
```
s3smart sync ./data s3://mybucket/test/
```
# S3 → Local
```
s3smart sync s3://mybucket/test ./data
```
## Interactive browse
```
s3smart browse
```

## Project layout
```
s3smart/
├── pyproject.toml
├── setup.cfg
├── Makefile
├── README.md
└── s3smart/
    ├── __init__.py
    └── cli.py
```

## JSON File settings explained
```

Setting 
|-- **browse_part_size_mb**  
    Description : The size (in MB) of each upload/download part used in **interactive browse mode**. Smaller values show progress more frequently but increase API calls. 
    When to Adjust : Lower this if your network is slow or unstable (e.g., 64 MB). Increase it if copying large files over a fast link. 
|-- **default_part_size_mb** 
    Description : The default part size (in MB) for bulk **upload/download/sync** commands. Larger parts mean fewer S3 API calls but higher memory usage per thread.      
    When to Adjust: Use 64–128 MB for general use; 256 MB+ for large data pipelines or fast instances.                                 
|-- **default_workers**      
    Description : Default n| Number of concurrent threads for parallel transfers. Controls how many files or S3 parts are handled at once.                        
    When to Adjust : Decrease on low-memory or throttled systems (e.g., 8–12). Increase to 18–32 for compute-optimized EC2s.            
```