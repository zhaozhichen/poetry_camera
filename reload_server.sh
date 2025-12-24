#!/bin/bash

# --- Shell script to update the Poetry Printer and restart the service ---

# 1. 配置 Configuration
# 你的项目路径
POETRY_PRINTER_DIR="/home/pi/projects/poetry_camera"
# 你的 GitHub 仓库地址
REPO_URL="https://github.com/zhaozhichen/poetry_camera.git"
# 你使用的分支 (通常是 main 或 master)
BRANCH="main"
# Systemd 服务名称
SERVICE_NAME="poetry-printer.service"

echo "=========================================="
echo "Starting Poetry Camera Update Process..."
echo "Target Directory: $POETRY_PRINTER_DIR"
echo "=========================================="

# 2. 检查目录是否存在 Check if directory exists
if [ ! -d "$POETRY_PRINTER_DIR" ]; then
    echo "Directory not found. Cloning the repository for the first time..."
    # 如果目录不存在，直接 Clone
    git clone "$REPO_URL" "$POETRY_PRINTER_DIR"
    
    if [ $? -ne 0 ]; then
        echo "Error: Failed to clone repository. Check your internet connection or URL."
        exit 1
    fi
else
    echo "Directory exists. Updating from remote..."
    cd "$POETRY_PRINTER_DIR" || { echo "Error: Failed to enter directory."; exit 1; }
    
    # 3. 强制更新 Force Update Logic
    # 这一步非常关键：
    # fetch --all: 获取远程所有最新代码
    # reset --hard: 强制覆盖本地所有修改，使其与远程完全一致 (比 git pull 更稳定)
    
    echo "Fetching latest changes..."
    git fetch --all
    
    echo "Resetting local branch to align with remote origin/$BRANCH..."
    git reset --hard origin/$BRANCH
    
    if [ $? -ne 0 ]; then
        echo "Error: Git update failed."
        exit 1
    fi
fi

# 4. (可选) 更新依赖 Optional: Update Python Dependencies
# 如果你的代码更新包含新的库，取消下面几行的注释
# if [ -f "requirements.txt" ]; then
#     echo "Updating Python dependencies..."
#     pip install -r requirements.txt
# fi

echo "Codebase successfully updated to the latest version."

# 5. 重启服务 Restart Service
echo "Restarting the systemd service..."

# Use sudo to stop, daemon-reload, and start the service
if sudo systemctl stop "$SERVICE_NAME"; then
    echo "Service stopped."
else
    echo "Warning: Could not stop service (maybe it wasn't running)."
fi

sudo systemctl daemon-reload
if sudo systemctl start "$SERVICE_NAME"; then
    echo "Service started successfully."
    
    # Check the status
    echo "Current Service Status:"
    sudo systemctl status "$SERVICE_NAME" --no-pager | head -n 10
    
    echo "=========================================="
    echo "✅ Poetry Printer update complete!"
    echo "=========================================="
else
    echo "❌ Error: Failed to start service."
    exit 1
fi
