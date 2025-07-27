
# Poetry Camera

*Inspired by [https://poetry.camera/](https://poetry.camera/) but rewritten from scratch.*
*Thermal printer reference: https://www.adafruit.com/product/1289*

### Initial Setup

1.  **Install Bullseye Raspberry Pi OS**:
    * **Note**: Do *not* use Bookworm, as it lacks the legacy camera setting.
2.  **Configure Raspberry Pi Settings (`sudo raspi-config`)**:
    ```bash
    sudo raspi-config
    ```
    Navigate through the menus and make the following critical changes:

    * **Enable Legacy Camera**:
        Navigate to `Interface Options` -> `Legacy Camera` and enable it.

    * **Configure Serial Port**:
        Navigate to `Interface Options` -> `P6 Serial Port`.
        "Would you like a login shell to be accessible over serial?" -> Select **No** (IMPORTANT, DON'T CHOOSE Yes)
        "Would you like the serial port hardware to be enabled?" -> Select **Yes**

    * **Increase GPU Memory**:
        Navigate to `Performance Options` -> `GPU Memory`.
        Set the GPU memory to **192MB** or **256MB**. This is crucial for high-resolution camera operations to prevent `ENOSPC` errors.

    * **Reboot** your Raspberry Pi when prompted after making changes.

### Install Dependencies

```bash
sudo apt update
sudo apt install libjpeg-dev zlib1g-dev libtiff-dev libfreetype6-dev liblcms2-dev libwebp-dev tcl-dev tk-dev
sudo apt install python3.9-dev
sudo apt install python3-rpi.gpio
````

### Set Up Python Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**`requirements.txt` content:**
(Create this file in your project root if it doesn't exist)

```
picamera
Pillow
python-escpos
pyserial
requests
```

### Configure User Permissions

The `pi` user (which will run your service) needs specific group memberships to access hardware.

1.  **Add `pi` user to necessary groups:**
    ```bash
    sudo usermod -a -G dialout pi # For serial port access (printer)
    sudo usermod -a -G video pi   # For camera access
    sudo usermod -a -G gpio pi    # For GPIO access (button, LED)
    ```
2.  **Reboot** your Raspberry Pi immediately after adding a user to groups for changes to take effect:
    ```bash
    sudo reboot
    ```
3.  **Ensure project directory permissions:**
    The `pi` user needs full read/write/execute permissions on your project directory to create log files and store pictures.
    ```bash
    sudo chown -R pi:pi /home/pi/projects/poetry_camera/
    sudo chmod -R u+rwx /home/pi/projects/poetry_camera/
    ```

### Running the Script Manually (for testing)

You must explicitly run this **inside** your virtual environment:

```bash
cd /home/pi/projects/poetry_camera/
sudo systemctl stop poetry-printer.service # Stop the service if it's active
source venv/bin/activate
python3 main.py
```

*(Note: Running with `sudo python3` is necessary for direct hardware access outside of the systemd service context configured for the `pi` user.)*

### Auto-run Script on Startup (Systemd Service)

To run your command automatically on Raspberry Pi startup, the most robust and recommended method is to create a **systemd service**. This allows for easy management, automatic restarts if the script crashes, and centralized logging.

Your command: `cd projects/poetry_camera/ && source venv/bin/activate && sudo venv/bin/python3 main.py` needs to be adapted slightly for a systemd service, as `source` directly in `ExecStart` isn't how systemd works. Instead, we'll directly call the virtual environment's Python and set the working directory.

Here's how to set up the systemd service:

**1. Create the Service File**

Open a new service file using `sudo nano`:

```bash
sudo nano /etc/systemd/system/poetry-printer.service
```

**2. Paste the Following Content**

Copy and paste the entire block below into the `nano` editor.

```ini
[Unit]
Description=Poetry Printer Service
Wants=network-online.target
After=network-online.target

[Service]
ExecStart=/home/pi/projects/poetry_camera/venv/bin/python3 /home/pi/projects/poetry_camera/main.py
WorkingDirectory=/home/pi/projects/poetry_camera/
Restart=always
StandardOutput=journal
StandardError=journal
User=pi
Group=pi

[Install]
WantedBy=multi-user.target
```

**Explanation of the Service File:**

  * **`[Unit]`**: Defines metadata and dependencies.
      * `Description`: A brief description of your service.
      * `Wants=network-online.target`: Indicates that the service would prefer the network to be online, but will start even if it's not.
      * `After=network-online.target`: Ensures the service starts after the network is up (important for Gemini API calls). `graphical.target` has been removed to prevent ordering cycles.
  * **`[Service]`**: Defines how the service runs.
      * `ExecStart`: The actual command. We use the absolute path to your virtual environment's Python interpreter and then the absolute path to your `main.py` script.
      * `WorkingDirectory`: Sets the current directory for your script, so relative paths within `main.py` work correctly.
      * `Restart=always`: If your script exits (for any reason), systemd will try to restart it automatically.
      * `StandardOutput`/`StandardError`: Directs all output from your script to the systemd journal, making it easy to check logs later.
      * `User=pi`: Specifies that the script should run as the `pi` user.
      * `Group=pi`: Specifies that the script should run with the `pi` group.
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
sudo systemctl status poetry-printer.service -l
```

You should see `active (running)` if it started successfully. If it shows `failed` or `inactive (dead)`, check the logs for errors.

**6. View Service Logs (Debugging)**

If your service isn't working as expected, you can view its logs using `journalctl`:

```bash
sudo journalctl -u poetry-printer.service -f
```

The `-f` flag "follows" the logs, showing new output in real-time. Press `Ctrl+C` to exit the log viewer. This will show you any print statements or error messages from your `main.py` script.

Additionally, your script writes detailed logs to a file:

```bash
tail -f /home/pi/projects/poetry_camera/poetry_printer.log
```

### Usage

Once the service is running and the LED on your button is lit, the Poetry Printer is ready:

1.  **Press the button once.**
2.  The LED will turn off, indicating processing.
3.  The camera will take a picture.
4.  The script will send the image to the Gemini API.
5.  A poem will be generated and printed on your thermal printer.
6.  The LED will turn back on, indicating readiness for the next poem.

The debounce logic is configured to ensure that one physical button press results in one poem being printed, even if the button has some electrical "bounce." There might be a slight delay for the very first press after a fresh boot as the system settles, but subsequent presses should be reliable.

```
```
