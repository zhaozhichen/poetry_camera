#!/bin/bash

# --- Shell script to update the Poetry Printer and restart the service ---

# Define the directory of your project
POETRY_PRINTER_DIR="/home/pi/projects/poetry_camera"

# Define the systemd service name
SERVICE_NAME="poetry-printer.service"

echo "Updating Poetry Printer project from Git repository..."

# Navigate to the project directory
cd "$POETRY_PRINTER_DIR" || { echo "Error: Failed to change directory to $POETRY_PRINTER_DIR. Exiting."; exit 1; }

# Pull the latest changes from the main branch
# --rebase is a good practice to avoid merge commits for simple updates
git pull --rebase

# Check if the git pull was successful
if [ $? -eq 0 ]; then
    echo "Git pull successful. Restarting the systemd service..."

    # Use sudo to stop, daemon-reload, and start the service
    sudo systemctl stop "$SERVICE_NAME"
    sudo systemctl daemon-reload
    sudo systemctl start "$SERVICE_NAME"

    # Check the status of the service to confirm it's running
    echo "Checking the status of the service..."
    sudo systemctl status "$SERVICE_NAME" -l --no-pager
    
    echo "Poetry Printer service has been reloaded."
else
    echo "Error: Git pull failed. The service was not restarted."
fi

# End of script
