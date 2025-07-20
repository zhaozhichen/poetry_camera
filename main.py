import sys
import os
import time
import base64
import json
import subprocess
import picamera
from PIL import Image # Used by poetry_camera_curl.py for image handling (e.g., opening for base64 encoding)
from escpos.printer import Serial # For thermal printer via serial
import RPi.GPIO as GPIO # Import the RPi.GPIO library for button input

# --- Configuration for Gemini API ---
# IMPORTANT: Replace "YOUR_GEMINI_API_KEY_HERE" with your actual Google Gemini API key!
API_KEY = "YOUR_GEMINI_API_KEY_HERE" 

# Gemini API Endpoint (using gemini-2.5-pro as per poetry_camera_curl.py)
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# POEM_GENERATION_PROMPT = "Write a short, descriptive, elegant, humorous poem about the scene in this picture. Start the poem with a title."
POEM_GENERATION_PROMPT = "Write a Haiku about the scene in this picture." # Changed to Haiku

# --- Configuration for Thermal Printer ---
# For Raspberry Pi GPIO serial, typically use '/dev/serial0' or '/dev/ttyS0'
SERIAL_PORT = '/dev/serial0' 
BAUD_RATE = 9600 # Changed: Reverted baud rate to 9600 as per working thermal_printer_serial.py

# Optional: Serial port settings (usually default is fine)
BYTESIZE = 8
PARITY = 'N' # No parity
STOPBITS = 1
TIMEOUT = 1.00 # Read timeout in seconds
DSRDTR = True # Data Set Ready/Data Terminal Ready flow control (often needed for these printers)

# --- Configuration for Button and LED ---
BUTTON_PIN = 23 # GPIO pin connected to the button (BCM numbering)
LED_PIN = 18    # GPIO pin connected to the button's ring LED (BCM numbering)

# Set up GPIO mode (BCM for GPIO numbers, BOARD for physical pin numbers)
GPIO.setmode(GPIO.BCM)
# Set the button pin as an input with a pull-up resistor
# This means the pin will be HIGH by default, and go LOW when the button is pressed (connected to GND)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
# Set the LED pin as an output
GPIO.setup(LED_PIN, GPIO.OUT)

# --- Function to Take a Picture ---
def take_picture(filename="image.jpg"):
    """
    Takes a picture using the Raspberry Pi camera and saves it to the local directory.

    Args:
        filename (str): The name of the file to save the picture as.

    Returns:
        str: The full path to the saved picture file, or None if an error occurred.
    """
    try:
        with picamera.PiCamera() as camera:
            print("Camera warming up...")
            time.sleep(1) # Give camera time to warm up

            # Set resolution (adjust as needed for your camera module)
            # For Camera Module V1.3 (5MP OV5647 sensor), (2592, 1944) is max.
            # For Camera Module V2.1 (8MP Sony IMX219 sensor), (3280, 2464) is max.
            camera.resolution = (2592, 1944) 
            
            # Create a 'pictures' folder if it doesn't exist
            current_dir = os.path.dirname(os.path.abspath(__file__))
            save_dir = os.path.join(current_dir, "pictures") 
            os.makedirs(save_dir, exist_ok=True)
            
            # Construct the full path for the image
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

    Args:
        image_path (str): The path to the image file.
        api_key (str): Your Google Gemini API key.

    Returns:
        str: The generated poem, or None if an error occurred.
    """
    if not os.path.exists(image_path):
        print(f"Error: Image file not found at {image_path}", file=sys.stderr)
        return None

    if not api_key or api_key == API_KEY: # Check for placeholder API key
        print("Error: Gemini API Key is not set. Please update the API_KEY variable in the script.", file=sys.stderr)
        return None

    try:
        # Read image and base64 encode it
        print(f"Reading image and encoding for Gemini...")
        with open(image_path, "rb") as image_file:
            encoded_image = base64.b64encode(image_file.read()).decode('utf-8')

        # Construct the JSON payload
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": POEM_GENERATION_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg", # Assuming JPEG output from picamera
                                "data": encoded_image
                            }
                        }
                    ]
                }
            ]
        }

        # Construct the curl command
        # Using '--data @-' to send payload via stdin, avoiding ARG_MAX limit
        curl_command = [
            "curl",
            "-X", "POST",
            "-H", "Content-Type: application/json",
            "--data", "@-", # This tells curl to read data from stdin
            f"{GEMINI_API_URL}?key={api_key}"
        ]
        
        print(f"Sending request to Gemini via curl...")
        # Execute the curl command, passing the JSON payload to stdin
        process = subprocess.run(
            curl_command,
            input=json.dumps(payload), # Pass the JSON string as input to stdin
            capture_output=True,
            text=True, # Decode stdout/stderr as text
            check=True # Raise an exception for non-zero exit codes
        )

        response_json = json.loads(process.stdout)
        
        # Extract the poem
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

        # Handle cases where no candidates or text parts are found, or other API errors
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

# --- Function to Print Poem on Thermal Printer ---
def print_poem_on_thermal_printer(poem_text):
    """
    Connects to the serial thermal printer and prints the given poem text.
    """
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

        # Set alignment and font for the poem
        p.set(align='center', font='b', height=1, width=1)
        p.text("\n--- Your AI Poem ---\n")
        p.set(align='left', font='a', height=1, width=1)
        
        # Print the poem line by line to ensure proper wrapping/formatting
        for line in poem_text.split('\n'):
            p.text(line + '\n')
        
        p.text("\n----------------------\n")
        p.set(align='center')
        p.text("Generated by Gemini on Raspberry Pi\n")
        p.text("Thank you!\n")

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
    """
    This function will be called when the button is pressed.
    It encapsulates the entire workflow: take picture, generate poem, print.
    """
    print(f"\n[DEBUG] Callback triggered for GPIO {channel}!") # Debug print
    # Optionally, turn off LED while processing to indicate busy state
    # GPIO.output(LED_PIN, GPIO.LOW) 

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    picture_name = f"poetry_picture_{timestamp}.jpg"
    
    # 1. Take the picture
    captured_filepath = take_picture(picture_name)

    if captured_filepath:
        # 2. If picture was taken successfully, generate a poem using Gemini
        poem = generate_poem_from_image_via_curl(captured_filepath, API_KEY) 

        if poem:
            # 3. If poem was generated successfully, print it
            print_poem_on_thermal_printer(poem)
        else:
            print("Poem generation failed, cannot print.", file=sys.stderr)
    else:
        print("Failed to capture picture, so cannot generate or print a poem.", file=sys.stderr)
    
    # Turn LED back on after processing is complete
    # GPIO.output(LED_PIN, GPIO.HIGH)


# --- Main Execution Flow (Button Listener) ---
if __name__ == "__main__":
    try:
        # Turn on the LED to indicate the script is ready
        GPIO.output(LED_PIN, GPIO.HIGH)
        print(f"Poetry Printer ready! Button LED is ON. Press the button connected to GPIO {BUTTON_PIN} to start.")
        
        # Add event detection for the button.
        # bouncetime is to prevent multiple triggers from a single press.
        GPIO.add_event_detect(BUTTON_PIN, GPIO.FALLING, callback=run_poetry_printer, bouncetime=300)

        # Add a loop to continuously print the button state for debugging
        print("Monitoring button state (HIGH = not pressed, LOW = pressed)...")
        while True:
            # Print current state of the button pin
            # This helps confirm if the physical button press is being registered by the GPIO
            current_button_state = GPIO.input(BUTTON_PIN)
            print(f"Button state: {'LOW (Pressed)' if current_button_state == GPIO.LOW else 'HIGH (Not Pressed)'}", end='\r')
            time.sleep(0.1) # Check frequently

    except KeyboardInterrupt:
        print("\nExiting program.")
    finally:
        GPIO.output(LED_PIN, GPIO.LOW) # Ensure LED is turned off on exit
        GPIO.cleanup() # Clean up GPIO settings on exit
        print("GPIO cleaned up.")

