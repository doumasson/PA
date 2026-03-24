#!/bin/bash
cd /home/admin/pa
set -a && source .env && set +a
source .venv/bin/activate
python3 -m pa
