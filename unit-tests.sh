#!/bin/bash
set -e

echo "🧪 Running Unit Tests..."

python3 -m venv .test_venv
source .test_venv/bin/activate
pip install -q pytest -r api/requirements.txt

cd api
python3 -m pytest tests/ -v --tb=short
cd ..

deactivate
rm -rf .test_venv
echo "✅ All tests passed!"
