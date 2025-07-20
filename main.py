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

# --- Configuration for Gemini API ---
# API Key will now be read from a hidden file
API_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".api_key")
API_KEY = None # Initialize to None

try:
    with open(API_KEY_FILE, 'r') as f:
        API_KEY = f.readline().strip() # Read the first line and remove whitespace/newline
    if not API_KEY:
        print(f"Warning: .api_key file is empty. Please ensure your Gemini API key is in {API_KEY_FILE}", file=sys.stderr)
except FileNotFoundError:
    print(f"Error: .api_key file not found at {API_KEY_FILE}. Please create it and add your Gemini API key.", file=sys.stderr)
    sys.exit(1) # Exit if the API key file is missing

# Gemini API Endpoint
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
POEM_GENERATION_PROMPT = "Write a Haiku about the scene in this picture."

# --- Configuration for Thermal Printer ---
SERIAL_PORT = '/dev/serial0'
BAUD_RATE = 9600
BYTESIZE = 8
PARITY = 'N' # No parity
STOPBITS = 1
TIMEOUT = 1.00 # Read timeout in seconds
DSRDTR = True # Data Set Ready/Data Terminal Ready flow control

# --- Configuration for Button and LED ---
BUTTON_PIN = 23 # GPIO pin connected to the button (BCM numbering)
LED_PIN = 18    # GPIO pin connected to the button's ring LED (BCM numbering)

# Set up GPIO mode
GPIO.setmode(GPIO.BCM)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(LED_PIN, GPIO.OUT)

# --- Global variable for software debounce ---
last_poetry_action_time = 0
COOLDOWN_TIME_SECONDS = 5 # Adjust this value as needed

# --- Function to Take a Picture (Unchanged) ---
def take_picture(filename="image.jpg"):
    try:
        with picamera.PiCamera() as camera:
            print("Camera warming up...")
            time.sleep(1) # Give camera time to warm up
            camera.resolution = (2592, 1944)
            current_dir = os.path.dirname(os.path.abspath(__file__))
            save_dir = os.path.join(current_dir, "pictures")
            os.makedirs(save_dir, exist_ok=True)
            filepath = os.path.join(save_dir, filename)
            print(f"Taking picture and saving to: {filepath}")
            camera.capture(filepath)
            print("Picture taken successfully!")
            return filepath
    except picamera.PiCameraError as e:
        print(f"Error: Could not access the camera. Make sure it's connected and enabled in raspi-config.")
        print(f"Details: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"An unexpected error occurred during camera operation: {e}", file=sys.stderr)
        return None

# --- Function to Generate Poem with Gemini via curl ---
def generate_poem_from_image_via_curl(image_path, api_key):
    """
    Generates a poem about the given image using the Gemini model via a curl command.
    """
    if not os.path.exists(image_path):
        print(f"Error: Image file not found at {image_path}", file=sys.stderr)
        return None

    # This check now relies on the API_KEY variable populated from the file
    if not api_key: # We already handled FileNotFoundError and empty file during setup
        print("Error: Gemini API Key is not set or loaded. Check .api_key file.", file=sys.stderr)
        return None

    try:
        print(f"Reading image and encoding for Gemini...")
        with open(image_path, "rb") as image_file:
            encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": POEM_GENERATION_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": encoded_image
                            }
                        }
                    ]
                }
            ]
        }
        curl_command = [
            "curl",
            "-X", "POST",
            "-H", "Content-Type: application/json",
            "--data", "@-",
            f"{GEMINI_API_URL}?key={api_key}"
        ]
        print(f"Sending request to Gemini via curl...")
        process = subprocess.run(
            curl_command,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=True
        )
        response_json = json.loads(process.stdout)
        if 'candidates' in response_json and response_json['candidates']:
            first_candidate = response_json['candidates'][0]
            if 'content' in first_candidate and 'parts' in first_candidate['content']:
                for part in first_candidate['content']['parts']:
                    if 'text' in part:
                        poem = part['text']
                        print("\n--- Generated Poem ---")
                        print(poem)
                        print("----------------------")
                        return poem
            elif 'safetyRatings' in first_candidate:
                print("Warning: Response blocked by safety settings.")
                for rating in first_candidate['safetyRatings']:
                    print(f"  {rating['category']}: {rating['probability']}")
                return None
        if 'error' in response_json:
            print(f"API Error: {response_json['error']['message']}", file=sys.stderr)
            return None
        print("Error: Could not find poem in Gemini response or unexpected response format.", file=sys.stderr)
        print(f"Full response: {response_json}", file=sys.stderr)
        return None
    except subprocess.CalledProcessError as e:
        print(f"Error executing curl command: {e}", file=sys.stderr)
        print(f"Curl stdout: {e.stdout}", file=sys.stderr)
        print(f"Curl stderr: {e.stderr}", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"Error parsing Gemini response JSON: {e}", file=sys.stderr)
        print(f"Raw response: {process.stdout if 'process' in locals() else 'N/A'}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"An unexpected error occurred during Gemini API call: {e}", file=sys.stderr)
        return None

# --- Function to Print Poem on Thermal Printer (Unchanged) ---
def print_poem_on_thermal_printer(poem_text):
    if not poem_text:
        print("No poem text to print.", file=sys.stderr)
        return
    try:
        p = Serial(
            devfile=SERIAL_PORT,
            baudrate=BAUD_RATE,
            bytesize=BYTESIZE,
            parity=PARITY,
            stopbits=STOPBITS,
            timeout=TIMEOUT,
            dsrdtr=DSRDTR
        )
        print(f"Attempting to connect to printer on port {SERIAL_PORT} with baud rate {BAUD_RATE} for printing poem...")
        p.set(align='center', font='b', height=1, width=1)
        # p.text("\n--- Your AI Poem ---\n")
        p.set(align='left', font='a', height=1, width=1)
        for line in poem_text.split('\n'):
            p.text(line + '\n')
        p.text("\n----------------------\n")
        p.set(align='center')
        # p.text("Generated by Gemini on Raspberry Pi\n")
        # p.text("Thank you!\n")
        p.cut()
        print("Poem printed successfully!")
    except Exception as e:
        print(f"Error printing poem: {e}", file=sys.stderr)
        print("Please ensure the printer is connected, powered on, and you have the correct serial port and baud rate.", file=sys.stderr)
        print("On Linux (Raspberry Pi), you might need to add your user to the 'dialout' group or run the script with sudo for serial port access.", file=sys.stderr)
    finally:
        if 'p' in locals() and p:
            try:
                p.close()
                print("Printer connection closed.")
            except Exception as e:
                print(f"Error closing printer connection: {e}", file=sys.stderr)

# --- Main Logic to be triggered by button ---
def run_poetry_printer(channel):
    global last_poetry_action_time
    current_time = time.time()

    # --- SOFTWARE DEBOUNCE LOGIC ---
    if (current_time - last_poetry_action_time) < COOLDOWN_TIME_SECONDS:
        print(f"\n[DEBUG] Button press ignored due to cooldown. Time elapsed: {current_time - last_poetry_action_time:.2f}s (Min {COOLDOWN_TIME_SECONDS}s needed)")
        return
    last_poetry_action_time = current_time
    # --- END SOFTWARE DEBOUNCE LOGIC ---

    print(f"\n[DEBUG] Callback triggered for GPIO {channel}!")
    GPIO.output(LED_PIN, GPIO.LOW) # Turn off LED while processing

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    picture_name = f"poetry_picture_{timestamp}.jpg"
    
    captured_filepath = take_picture(picture_name)

    if captured_filepath:
        poem = generate_poem_from_image_via_curl(captured_filepath, API_KEY) # Pass the loaded API_KEY

        if poem:
            print_poem_on_thermal_printer(poem)
        else:
            print("Poem generation failed, cannot print.", file=sys.stderr)
    else:
        print("Failed to capture picture, so cannot generate or print a poem.", file=sys.stderr)
        
    GPIO.output(LED_PIN, GPIO.HIGH) # Turn LED back on
    print(f"Poetry Printer ready! Button LED is ON. Press the button connected to GPIO {BUTTON_PIN} to start.")


# --- Main Execution Flow (Button Listener) ---
if __name__ == "__main__":
    try:
        GPIO.output(LED_PIN, GPIO.HIGH)
        print(f"Poetry Printer ready! Button LED is ON. Press the button connected to GPIO {BUTTON_PIN} to start.")
        
        GPIO.add_event_detect(BUTTON_PIN, GPIO.FALLING, callback=run_poetry_printer, bouncetime=300)

        print("Monitoring button state (HIGH = not pressed, LOW = pressed)...")
        while True:
            current_button_state = GPIO.input(BUTTON_PIN)
            print(f"Button state: {'LOW (Pressed)' if current_button_state == GPIO.LOW else 'HIGH (Not Pressed)'}", end='\r')
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nExiting program.")
    finally:
        GPIO.output(LED_PIN, GPIO.LOW)
        GPIO.cleanup()
        print("GPIO cleaned up.")
