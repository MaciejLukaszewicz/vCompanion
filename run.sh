#!/bin/bash

# Navigate to the script's directory
cd "$(dirname "$0")"

# Activate virtual environment
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "Virtual environment not found. Please create one in 'venv' folder."
    echo "Example: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Launch browser script in background. It will wait for the server to be ready.
# Note: launch_browser.py will exit once browser is opened or timeout is reached.
python3 launch_browser.py &

# Main loop for restarts
while true; do
    echo "Starting vCompanion..."
    python3 main.py
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 123 ]; then
        echo "Restart initiated by application. Restarting in 1s..."
        sleep 1
    else
        echo "vCompanion exited with code $EXIT_CODE"
        break
    fi
done

echo "Press Enter to close..."
read
