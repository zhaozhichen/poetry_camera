*Inspired by [https://poetry.camera/](https://poetry.camera/) but rewritten from scratch.*

### Initial Setup

1.  **Install Bullseye Raspberry Pi OS**:
      * **Note**: Do *not* use Bookworm, as it lacks the legacy camera setting.
2.  **Enable Legacy Camera**:
    ```bash
    sudo raspi-config
    ```
    Navigate to `Interface Options` -\> `Legacy Camera` and enable it.

### Install Dependencies

```bash
sudo apt update
sudo apt install libjpeg-dev zlib1g-dev libtiff-dev libfreetype6-dev liblcms2-dev libwebp-dev tcl-dev tk-dev
sudo apt install python3.9-dev
sudo apt install python3-rpi.gpio
```

### Set Up Python Virtual Environment

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Running the Script Manually (within the virtual environment)

You must explicitly run this **inside** your virtual environment:

```bash
sudo venv/bin/python3 main.py
```

### Auto-run Script on Startup (Systemd Service)

To run your command automatically on Raspberry Pi startup, the most robust and recommended method is to create a **systemd service**. This allows for easy management, automatic restarts if the script crashes, and centralized logging.

Your command: `cd projects/poetry_camera/ && source venv/bin/activate && sudo venv/bin/python3 main.py` needs to be adapted slightly for a systemd service, as `source` directly in `ExecStart` isn't how systemd works. Instead, we'll directly call the virtual environment's Python and set the working directory. Since your original command includes `sudo`, we'll run the service as the `root` user to ensure it has the necessary permissions for GPIO, camera, and serial port access.

Here's how to set up the systemd service:

**1. Create the Service File**

Open a new service file using `sudo nano`:

```bash
sudo nano /etc/systemd/system/poetry-printer.service
```

**2. Paste the Following Content**

Copy and paste the entire block below into the `nano` editor.

```
[Unit]
Description=Poetry Printer Service
# Start after networking is online and the multi-user target is reached
After=network-online.target multi-user.target

[Service]
# Set the working directory for the script
WorkingDirectory=/home/pi/projects/poetry_camera/

# The command to execute: directly call the venv's python interpreter
# and pass the script. Running as User=root bypasses the need for 'sudo' here.
ExecStart=/home/pi/projects/poetry_camera/venv/bin/python3 /home/pi/projects/poetry_camera/main.py

# Specify the user to run the service as.
# We use 'root' because your original command used 'sudo', implying root privileges are needed.
# This ensures access to GPIO, camera, and serial ports.
User=root

# Redirect standard output and error to the systemd journal for logging
StandardOutput=journal
StandardError=journal

# Restart the service if it fails unexpectedly
Restart=on-failure
RestartSec=5s # Wait 5 seconds before attempting to restart

# Clean up resources when the service stops
# Type=simple is default, but for scripts that might detach or fork, other types may be needed.
# For most Python scripts like this, simple is fine.
Type=simple

[Install]
# This unit should be started when the system reaches multi-user runlevel
WantedBy=multi-user.target
```

**Explanation of the Service File:**

  * **`[Unit]`**: Defines metadata and dependencies.
      * `Description`: A brief description of your service.
      * `After=network-online.target multi-user.target`: Ensures the service starts after the network is up (if your script needs internet for Gemini) and after the system has reached a general multi-user state.
  * **`[Service]`**: Defines how the service runs.
      * `WorkingDirectory`: Sets the current directory for your script, so relative paths within `main.py` work correctly.
      * `ExecStart`: The actual command. We use the absolute path to your virtual environment's Python interpreter and then the absolute path to your `main.py` script.
      * `User=root`: Specifies that the script should run with root privileges, which is necessary for directly accessing hardware like GPIO pins and serial ports without additional `sudo` calls within the script or complex group management.
      * `StandardOutput`/`StandardError`: Directs all output from your script to the systemd journal, making it easy to check logs later.
      * `Restart=on-failure`: If your script crashes, systemd will try to restart it.
      * `RestartSec=5s`: Waits 5 seconds before attempting a restart.
  * **`[Install]`**: Defines when the service should be activated.
      * `WantedBy=multi-user.target`: This means the service will start automatically when the system boots up into its normal operating mode.

**3. Save the File**

  * Press `Ctrl+O` to write out the file.
  * Press `Enter` to confirm the filename.
  * Press `Ctrl+X` to exit `nano`.

**4. Reload Systemd and Enable the Service**

Tell systemd to recognize your new service file:

```bash
sudo systemctl daemon-reload
```

Enable the service to start automatically on boot:

```bash
sudo systemctl enable poetry-printer.service
```

**5. Start and Check the Service (Test Now)**

You can start the service immediately without rebooting to test it:

```bash
sudo systemctl start poetry-printer.service
```

Check the status of your service to ensure it's running correctly:

```bash
sudo systemctl status poetry-printer.service
```

You should see `active (running)` if it started successfully. If it shows `failed` or `inactive (dead)`, check the logs for errors.

**6. View Service Logs (Debugging)**

If your service isn't working as expected, you can view its logs using `journalctl`:

```bash
sudo journalctl -u poetry-printer.service -f
```

The `-f` flag "follows" the logs, showing new output in real-time. Press `Ctrl+C` to exit the log viewer. This will show you any print statements or error messages from your `main.py` script.

**After following these steps, your `main.py` script should execute automatically when your Raspberry Pi starts up.**
