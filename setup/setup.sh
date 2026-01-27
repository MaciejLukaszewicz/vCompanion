#!/bin/bash

echo "=========================================="
echo "   vCompanion Setup for Linux"
echo "=========================================="

# Check for Python
if ! command -v python3 &> /dev/null
then
    echo "[ERROR] python3 could not be found. Please install Python 3.12 or later."
    exit 1
fi

# Create Virtual Environment
if [ ! -d "../venv" ]; then
    echo "[INFO] Creating Virtual Environment..."
    python3 -m venv ../venv
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to create venv. Make sure python3-venv is installed."
        exit 1
    fi
else
    echo "[INFO] venv already exists."
fi

# Install Requirements
echo "[INFO] Installing/Updating dependencies..."
source ../venv/bin/activate
pip install --upgrade pip
pip install -r ../requirements.txt

if [ $? -eq 0 ]; then
    echo "[SUCCESS] Setup completed successfully."
    echo "You can now run the application using ./run.sh"
else
    echo "[ERROR] Failed to install requirements."
    exit 1
fi
