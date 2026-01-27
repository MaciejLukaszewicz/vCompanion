#!/bin/bash
echo "=========================================="
echo "   vCompanion Update for Linux"
echo "=========================================="

if ! command -v git &> /dev/null
then
    echo "[ERROR] git could not be found."
    exit 1
fi

echo "[INFO] Pulling latest changes from GitHub..."
pushd .. > /dev/null
git pull

echo "[INFO] Updating dependencies..."
if [ -d "venv" ]; then
    source venv/bin/activate
    pip install -r requirements.txt
else
    echo "[WARNING] venv not found. Run ./setup.sh first."
fi
popd > /dev/null

echo "[SUCCESS] Update process finished."
