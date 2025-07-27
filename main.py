import sys
import os
import time
import base64
import json
import subprocess
import picamera
from PIL import Image
from escpos.printer import Serial
import RPi.GPIO as GPIO
import logging # Import the logging module

# Suppress GPIO warnings about channels already in use.
# This is safe to do if you are confident in your GPIO setup.
GPIO.setwarnings(False) 

# --- Configuration for Logging ---
# Define the path for the main log file
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "poetry_printer.log")

# Set the logging level (e.g., logging.INFO for general info, logging.DEBUG for more verbose output)
LOG_LEVEL = logging.INFO 

# Get the root logger
root_logger = logging.getLogger()
root_logger.setLevel(LOG_LEVEL)

# Clear any existing handlers to prevent duplicate output (important for service restarts)
if root_logger.hasHandlers():
    root_logger.handlers.clear()

# Create a formatter for the log messages
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Add a FileHandler to write logs to the specified file
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

# Add a StreamHandler to write logs to the console (stdout), captured by journalctl
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)
root_logger.addHandler(stream_handler)

# Suppress PIL (Pillow) library's INFO messages if they are too noisy,
# as they are often not relevant for application-level debugging.
logging.getLogger('PIL').setLevel(logging.WARNING)

# --- Log the resolved path of the main log file at script startup ---
logging.info(f"Script started. Expected poetry_printer.log path: {LOG_FILE}")


# --- Configuration for Gemini API ---
# API Key will be read from a hidden file for security reasons.
API_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".api_key")
API_KEY = None # Initialize API_KEY to None

try:
    # Attempt to open and read the API key from the hidden file.
    with open(API_KEY_FILE, 'r') as f:
        API_KEY = f.readline().strip() # Read the first line and remove whitespace/newline characters.
    if not API_KEY:
        # Log a warning if the API key file is empty.
        logging.warning(f"Warning: .api_key file is empty. Please ensure your Gemini API key is in {API_KEY_FILE}")
except FileNotFoundError:
    # Log an error and exit if the API key file is not found.
    logging.error(f"Error: .api_key file not found at {API_KEY_FILE}. Please create it and add your Gemini API key.")
    sys.exit(1) # Exit the script if this critical file is missing.

# Gemini API Endpoint URL for content generation.
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
# Prompt string for instructing Gemini to generate a poem based on an image.
POEM_GENERATION_PROMPT = "Write a short, descriptive, elegant, humorous poem about the scene in this picture. Start the poem with a title."

# --- Configuration for Thermal Printer ---
SERIAL_PORT = '/dev/serial0' # Default serial port on Raspberry Pi for many thermal printers.
BAUD_RATE = 9600

# Common Serial Port Settings (adjust if your printer's manual says otherwise)
BYTESIZE = 8
PARITY = 'N' # No parity bit.
STOPBITS = 1
TIMEOUT = 1.00 # Read timeout in seconds for serial communication.

# Flow Control: Set to False as per successful test_printer.py
DSRDTR = False # Data Set Ready/Data Terminal Ready flow control
RTSCTS = False # Request To Send/Clear To Send flow control


# --- Configuration for Button and LED ---
BUTTON_PIN = 23 # GPIO pin connected to the button (using BCM numbering).
LED_PIN = 18    # GPIO pin connected to the button's ring LED (using BCM numbering).

# Set up GPIO mode to BCM numbering scheme.
GPIO.setmode(GPIO.BCM)
# Configure button pin as input with an internal pull-up resistor.
# This means the pin will be HIGH by default and LOW when the button is pressed (connected to GND).
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
# Configure LED pin as output.
GPIO.setup(LED_PIN, GPIO.OUT)

# --- Global variable for software debounce ---
last_poetry_action_time = 0
COOLDOWN_TIME_SECONDS = 15 # Cooldown period to prevent multiple triggers from a single button press.

# --- Function to Take a Picture ---
def take_picture(filename="image.jpg"):
    """
    Captures a picture using the Raspberry Pi Camera and saves it to a file.
    Handles potential camera errors and logs the process.
    """
    try:
        with picamera.PiCamera() as camera:
            logging.info("Camera warming up...")
            time.sleep(1) # Give camera time to warm up and adjust exposure/white balance.
            camera.resolution = (2592, 1944) # Set the desired camera resolution.
            
            # Determine the current script's directory and create a 'pictures' subdirectory
            # to store captured images.
            current_dir = os.path.dirname(os.path.abspath(__file__))
            save_dir = os.path.join(current_dir, "pictures")
            os.makedirs(save_dir, exist_ok=True) # Create the directory if it doesn't exist.
            
            filepath = os.path.join(save_dir, filename)
            logging.info(f"Taking picture and saving to: {filepath}")
            camera.capture(filepath) # Capture the image and save it to the specified path.
            logging.info("Picture taken successfully!")
            return filepath
    except picamera.PiCameraError as e:
        # Log specific errors related to camera access (e.g., not connected, not enabled).
        logging.error(f"Error: Could not access the camera. Make sure it's connected and enabled in raspi-config. Details: {e}")
        return None
    except Exception as e:
        # Catch any other unexpected errors that might occur during camera operation.
        logging.error(f"An unexpected error occurred during camera operation: {e}")
        return None

# --- Function to Generate Poem with Gemini via curl ---
def generate_poem_from_image_via_curl(image_path, api_key):
    """
    Sends an image to the Google Gemini API via a curl subprocess to generate a poem.
    The image is base64-encoded and sent as part of a JSON payload.
    """
    if not os.path.exists(image_path):
        logging.error(f"Error: Image file not found at {image_path}")
        return None
    if not api_key:
        logging.error("Error: Gemini API Key is not set or loaded. Check .api_key file.")
        return None
    try:
        logging.info(f"Reading image and encoding for Gemini...")
        with open(image_path, "rb") as image_file:
            encoded_image = base64.b64encode(image_file.read()).decode('utf-8') # Encode image to base64 string.
        
        # Construct the JSON payload required by the Gemini API for image and text input.
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": POEM_GENERATION_PROMPT}, # The text prompt for the poem generation.
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg", # Specify the MIME type of the image.
                                "data": encoded_image        # The base64 encoded image data.
                            }
                        }
                    ]
                }
            ]
        }
        
        # Construct the curl command as a list of arguments.
        curl_command = [
            "curl",
            "-X", "POST",
            "-H", "Content-Type: application/json",
            "--data", "@-", # Instruct curl to read request body from stdin.
            f"{GEMINI_API_URL}?key={api_key}" # Append the API key to the endpoint URL.
        ]
        logging.info(f"Sending request to Gemini via curl...")
        
        # Execute the curl command as a subprocess.
        process = subprocess.run(
            curl_command,
            input=json.dumps(payload), # Pass the JSON payload as stdin to curl.
            capture_output=True,       # Capture stdout and stderr of the curl command.
            text=True,                 # Decode stdout/stderr as text (UTF-8 by default).
            check=True                 # Raise a CalledProcessError if curl returns a non-zero exit code.
        )
        
        response_json = json.loads(process.stdout) # Parse the JSON response from Gemini.
        
        # Extract the generated poem from the API response structure.
        if 'candidates' in response_json and response_json['candidates']:
            first_candidate = response_json['candidates'][0]
            if 'content' in first_candidate and 'parts' in first_candidate['content']:
                for part in first_candidate['content']['parts']:
                    if 'text' in part:
                        poem = part['text']
                        logging.info("\n--- Generated Poem ---")
                        logging.info(poem)
                        logging.info("----------------------")
                        return poem
            elif 'safetyRatings' in first_candidate:
                # Log a warning if the response was blocked by Gemini's safety settings.
                logging.warning("Warning: Response blocked by safety settings.")
                for rating in first_candidate['safetyRatings']:
                    logging.warning(f"  {rating['category']}: {rating['probability']}")
                return None
        if 'error' in response_json:
            # Log specific API errors returned by Gemini.
            logging.error(f"API Error: {response_json['error']['message']}")
            return None
        
        # Log if the expected poem content was not found in the response or if the format was unexpected.
        logging.error("Error: Could not find poem in Gemini response or unexpected response format.")
        logging.error(f"Full response: {response_json}")
        return None
    except subprocess.CalledProcessError as e:
        # Log errors specifically from the curl command execution (e.g., network issues, invalid URL).
        logging.error(f"Error executing curl command: {e}")
        logging.error(f"Curl stdout: {e.stdout}")
        logging.error(f"Curl stderr: {e.stderr}")
        return None
    except json.JSONDecodeError as e:
        # Log errors that occur during JSON parsing of the Gemini response.
        logging.error(f"Error parsing Gemini response JSON: {e}")
        logging.error(f"Raw response: {process.stdout if 'process' in locals() else 'N/A'}")
        return None
    except Exception as e:
        # Catch any other unexpected errors that might occur during the Gemini API call process.
        logging.error(f"An unexpected error occurred during Gemini API call: {e}")
        return None

# --- Function to Print Poem on Thermal Printer ---
def print_poem_on_thermal_printer(poem_text):
    """
    Prints the given poem text on the thermal printer connected via serial port.
    Handles potential printer connection and printing errors.
    """
    if not poem_text:
        logging.warning("No poem text to print.")
        return
    try:
        logging.info("Adding a small delay before attempting to open serial port...")
        time.sleep(2) # Give the serial port a moment to be fully ready

        # Initialize serial printer connection with specified parameters.
        p = Serial(
            devfile=SERIAL_PORT,
            baudrate=BAUD_RATE,
            bytesize=BYTESIZE,
            parity=PARITY,
            stopbits=STOPBITS,
            timeout=TIMEOUT,
            dsrdtr=DSRDTR, # Now False
            rtscts=RTSCTS  # Now False
        )
        logging.info(f"Attempting to connect to printer on port {SERIAL_PORT} with baud rate {BAUD_RATE} for printing poem...")
        
        # Set printer alignment and font for the header.
        p.set(align='center', font='b', height=1, width=1)
        p.text("\n--- Your AI Poem ---\n")
        
        # Set alignment for the main poem text.
        p.set(align='left', font='a', height=1, width=1)
        # Print each line of the poem.
        for line in poem_text.split('\n'):
            p.text(line + '\n')
        
        # Add a footer text.
        p.text("\n----------------------\n")
        p.set(align='center')
        p.text("Generated by Gemini on Raspberry Pi\n")
        p.text("Thank you!\n")
        p.cut() # Send command to cut the paper.
        logging.info("Poem printed successfully!")
    except Exception as e:
        # Log printer-specific errors and provide common troubleshooting tips.
        logging.error(f"Error printing poem: {e}")
        logging.error("Please ensure the printer is connected, powered on, and you have the correct serial port and baud rate.")
        logging.error("On Linux (Raspberry Pi), you might need to add your user to the 'dialout' group or run the script with sudo for serial port access.")
    finally:
        # Ensure the printer connection is closed, even if errors occurred during printing.
        if 'p' in locals() and p: # Check if 'p' (printer object) was successfully created.
            try:
                p.close()
                logging.info("Printer connection closed.")
            except Exception as e:
                logging.error(f"Error closing printer connection: {e}")

# --- Main Logic to be triggered by button ---
def run_poetry_printer(channel):
    """
    This function is registered as a callback for the button press event.
    It orchestrates the entire process: taking a photo, generating a poem, and printing it.
    """
    # --- Wrap the entire function content in a try-except block ---
    # This catches any unhandled exceptions within the callback and logs them.
    try:
        # --- Log entry point of the function ---
        logging.info(f"--- run_poetry_printer entered for channel {channel} ---")

        global last_poetry_action_time
        current_time = time.time()

        # --- SOFTWARE DEBOUNCE LOGIC ---
        # This prevents multiple triggers from a single, slightly bouncy button press.
        if (current_time - last_poetry_action_time) < COOLDOWN_TIME_SECONDS:
            logging.debug(f"Button press ignored due to cooldown. Time elapsed: {current_time - last_poetry_action_time:.2f}s (Min {COOLDOWN_TIME_SECONDS}s needed)")
            return
        
        # Check current actual state of the button pin RIGHT NOW before proceeding.
        # This helps filter out false triggers if the button state isn't truly LOW.
        if GPIO.input(channel) == GPIO.HIGH: # If it's HIGH, it's not actually pressed (assuming PUD_UP).
            logging.debug(f"Callback triggered for GPIO {channel} but pin is currently HIGH. Ignoring false trigger.")
            return

        # If we get here, the press is considered valid, so update the last action time.
        last_poetry_action_time = current_time
        # --- END SOFTWARE DEBOUNCE LOGIC ---

        logging.info(f"Callback triggered for GPIO {channel}! Initiating poetry process.")
        # Turn off LED while processing to indicate a busy state.
        GPIO.output(LED_PIN, GPIO.LOW)

        timestamp = time.strftime("%Y%m%d-%H%M%S")
        picture_name = f"poetry_picture_{timestamp}.jpg"
        
        # 1. Take the picture.
        captured_filepath = take_picture(picture_name)

        if captured_filepath:
            # 2. If picture was taken successfully, generate a poem using Gemini.
            poem = generate_poem_from_image_via_curl(captured_filepath, API_KEY)    

            if poem:
                # 3. If poem was generated successfully, print it.
                print_poem_on_thermal_printer(poem)
            else:
                logging.error("Poem generation failed, cannot print.")
        else:
            logging.error("Failed to capture picture, so cannot generate or print a poem.")
            
        # Turn LED back on after processing is complete.
        GPIO.output(LED_PIN, GPIO.HIGH)
        # Log the ready message again at the end of the process.
        logging.info(f"Poetry Printer ready! Button LED is ON. Press the button connected to GPIO {BUTTON_PIN} to start.")

    except Exception as e:
        # Catch any unexpected errors within the button callback and log them as critical.
        logging.critical(f"UNEXPECTED CRITICAL ERROR in run_poetry_printer: {e}", exc_info=True)


# --- Main Execution Flow (Button Listener) ---
if __name__ == "__main__":
    # Variable to store the previous button state to detect changes for console output (debugging).
    last_displayed_button_state = None

    try:
        # Initial setup: turn on the LED and log the ready message.
        GPIO.output(LED_PIN, GPIO.HIGH)
        logging.info(f"Poetry Printer ready! Button LED is ON. Press the button connected to GPIO {BUTTON_PIN} to start.")
        
        # Add event detection for the button press on the falling edge (button pressed).
        # bouncetime helps prevent multiple triggers from a single physical press.
        GPIO.add_event_detect(BUTTON_PIN, GPIO.FALLING, callback=run_poetry_printer, bouncetime=300)

        logging.info("Monitoring button state (HIGH = not pressed, LOW = pressed)...")
        # Keep the script running indefinitely in a loop to monitor button presses.
        while True:
            current_button_state = GPIO.input(BUTTON_PIN)
            
            # Log button state changes (for console/journalctl) for debugging purposes.
            if current_button_state != last_displayed_button_state:
                logging.debug(f"Button state: {'LOW (Pressed)' if current_button_state == GPIO.LOW else 'HIGH (Not Pressed)'}")
                last_displayed_button_state = current_button_state
            
            time.sleep(0.1) # Short delay to prevent excessive CPU usage in the loop.

    except KeyboardInterrupt:
        # Handle graceful exit if Ctrl+C is pressed in the console.
        logging.info("\nExiting program due to KeyboardInterrupt.")
    finally:
        # Clean up GPIO settings when the script exits to release resources.
        GPIO.output(LED_PIN, GPIO.LOW) # Ensure LED is turned off on exit.
        GPIO.cleanup() # Release GPIO resources.
        logging.info("GPIO cleaned up.")
        logging.shutdown() # Ensure all buffered log messages are written to file before exiting.
