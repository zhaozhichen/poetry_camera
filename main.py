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
import requests  # Added for web app upload

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, will read .env manually if needed

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


# --- Configuration Loading from .env file ---
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

def load_env_file():
    """Load environment variables from .env file manually if python-dotenv is not available"""
    env_vars = {}
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        env_vars[key] = value
        except Exception as e:
            logging.warning(f"Error reading .env file: {e}")
    return env_vars

# Load .env file manually if python-dotenv didn't load it
if 'dotenv' not in sys.modules:
    env_vars = load_env_file()
    for key, value in env_vars.items():
        os.environ[key] = value

# --- Configuration for Gemini API ---
# API Key will be read from .env file (GEMINI_API_KEY) or fallback to .api_key file
API_KEY = os.getenv('GEMINI_API_KEY')

# Fallback to .api_key file if not in .env
if not API_KEY:
    API_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".api_key")
    try:
        with open(API_KEY_FILE, 'r') as f:
            API_KEY = f.readline().strip()
        if API_KEY:
            logging.info("Loaded Gemini API key from .api_key file (fallback)")
    except FileNotFoundError:
        pass

if not API_KEY:
    logging.error(f"Error: GEMINI_API_KEY not found in .env file or .api_key file. Please set GEMINI_API_KEY in .env file.")
    sys.exit(1) # Exit the script if this critical key is missing.

# Gemini API Endpoint URL for content generation.
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-preview:generateContent"
# Prompt string for instructing Gemini to generate a poem based on an image.
POEM_GENERATION_PROMPT = (
    "First, carefully analyze the environment, theme, background, and atmosphere of the picture. "
    "Based on this visual analysis, write a short, descriptive, elegant, and humorous poem in English. "
    "Ensure the poem's style and imagery deeply resonate with the specific mood of the scene. "
    "Start the poem with a title, adorned with three tildes (~~~ ) on each side. "
    "Add a single empty line after the title."
)
# Comment this line out if you don't want Chinese translation.
POEM_GENERATION_PROMPT += (
    "\n\nNext, compose an ORIGINAL poem in Chinese about the same scene. "
    "IMPORTANT: Do not translate the English poem. Instead, create a distinct piece that captures "
    "the image's spirit using imagery and phrasing natural to Chinese poetic expression. "
    "The Chinese poem should also closely reflect the photo's unique atmosphere. "
    "Place this directly following the English version after a single empty line, "
    "and also adorn the Chinese title with three tildes (~~~ ) on each side, "
    "followed by a single empty line before the Chinese poem body."
)

# --- Configuration for Web App Upload ---
# Read from .env file
WEB_APP_URL = os.getenv('WEB_APP_URL', 'https://poetry.ktizo.io')  # Default URL
WEB_APP_API_KEY = os.getenv('WEB_APP_API_KEY')

# Fallback to old file-based config if not in .env
if not WEB_APP_API_KEY:
    WEB_APP_API_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".web_app_api_key")
    try:
        with open(WEB_APP_API_KEY_FILE, 'r') as f:
            WEB_APP_API_KEY = f.readline().strip()
        if WEB_APP_API_KEY:
            logging.info("Loaded Web App API key from .web_app_api_key file (fallback)")
    except FileNotFoundError:
        pass

if not WEB_APP_API_KEY:
    logging.warning("Warning: WEB_APP_API_KEY not found in .env file. Web app upload will be skipped.")

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

# --- Function to Get Style Settings from Web App ---
def get_poem_styles_from_webapp():
    """
    从 Web 应用获取当前的诗歌风格设置
    
    Returns:
        dict: 包含 'english' 和 'chinese' 风格设置的字典，如果获取失败则返回 None
    """
    if not WEB_APP_API_KEY:
        logging.info("Web app API key not configured. Using default styles.")
        return None
    
    try:
        logging.info("Fetching poem styles from web app...")
        headers = {
            "X-API-Key": WEB_APP_API_KEY,
            "Content-Type": "application/json"
        }
        
        response = requests.get(
            f"{WEB_APP_URL}/api/styles",
            headers=headers,
            timeout=5
        )
        
        if response.status_code == 200:
            styles = response.json()
            logging.info(f"Retrieved styles from web app: English={styles.get('english')}, Chinese={styles.get('chinese')}")
            return styles
        else:
            logging.warning(f"Failed to get styles from web app: {response.status_code}. Using default styles.")
            return None
    
    except requests.exceptions.Timeout:
        logging.warning("Timeout while fetching styles from web app. Using default styles.")
        return None
    except requests.exceptions.ConnectionError:
        logging.warning("Connection error while fetching styles from web app. Using default styles.")
        return None
    except Exception as e:
        logging.warning(f"Error fetching styles from web app: {str(e)}. Using default styles.")
        return None


# --- Function to Build Prompt with Style ---
def build_prompt_with_style(base_prompt, english_style=None, chinese_style=None):
    """
    根据风格设置构建完整的 prompt
    
    Args:
        base_prompt: 基础 prompt（默认风格，如果风格获取失败则使用此 prompt）
        english_style: 英文诗歌风格（可选，如果为 None 则不添加风格说明，使用默认）
        chinese_style: 中文诗歌风格（可选，如果为 None 则不添加风格说明，使用默认）
    
    Returns:
        str: 包含风格信息的完整 prompt。如果 english_style 和 chinese_style 都为 None，
             则返回原始的 base_prompt（默认风格）
    """
    prompt = base_prompt
    
    logging.info("Building prompt with style:")
    logging.info(f"  Base prompt length: {len(base_prompt)} characters")
    logging.info(f"  English style to apply: {english_style if english_style else '(None - will use default)'}")
    logging.info(f"  Chinese style to apply: {chinese_style if chinese_style else '(None - will use default)'}")
    
    # Add English style instruction if provided
    if english_style:
        logging.info(f"  Applying English style: '{english_style}'")
        style_instruction = f"\n\nIMPORTANT: Write the English poem in the '{english_style}' style. "
        if english_style == 'classic':
            style_instruction += "Use traditional poetic forms, formal language, and timeless themes."
        elif english_style == 'romantic':
            style_instruction += "Emphasize emotion, nature, beauty, and personal feelings."
        elif english_style == 'modern':
            style_instruction += "Use contemporary language, free verse, and modern perspectives."
        elif english_style == 'haiku':
            style_instruction += "Write in haiku format: three lines with 5-7-5 syllables, focusing on nature and moments."
        elif english_style == 'sonnet':
            style_instruction += "Write in sonnet form: 14 lines with iambic pentameter, following traditional sonnet structure."
        elif english_style == 'humorous':
            style_instruction += "Make it witty, playful, and lighthearted with humor and clever wordplay."
        elif english_style == 'absurd':
            style_instruction += "Create something surreal, unexpected, and delightfully absurd."
        elif english_style == 'cyberpunk':
            style_instruction += "Blend technology, dystopian themes, and futuristic imagery."
        elif english_style == 'gothic':
            style_instruction += "Use dark, mysterious, and atmospheric imagery with gothic themes."
        elif english_style == 'zen':
            style_instruction += "Write with simplicity, mindfulness, and contemplative depth."
        else:
            # Custom style
            style_instruction += f"Write in the style of: {english_style}"
        
        logging.info(f"  English style instruction: {style_instruction[:100]}...")
        
        old_text = "write a short, descriptive, elegant, and humorous poem in English."
        new_text = f"write a short, descriptive, elegant poem in English.{style_instruction}"
        
        if old_text in prompt:
            prompt = prompt.replace(old_text, new_text)
            logging.info("  ✓ English style instruction successfully inserted into prompt")
        else:
            logging.warning(f"  ⚠ Could not find target text '{old_text}' in prompt. Style may not be applied correctly.")
    else:
        logging.info("  No English style specified - using default")
    
    # Add Chinese style instruction if provided
    if chinese_style:
        logging.info(f"  Applying Chinese style: '{chinese_style}'")
        style_instruction = f"\n\nIMPORTANT: Write the Chinese poem in the '{chinese_style}' style. "
        if chinese_style == 'classic':
            style_instruction += "使用古典诗词的格律、用典和传统意象。"
        elif chinese_style == 'tang':
            style_instruction += "采用唐诗的格律（五言或七言），注重对仗、平仄和意境。"
        elif chinese_style == 'song':
            style_instruction += "采用宋词的词牌风格，注重韵律、节奏和情感表达。"
        elif chinese_style == 'modern':
            style_instruction += "使用现代汉语，自由体，表达现代人的感受和思考。"
        elif chinese_style == 'free':
            style_instruction += "使用自由体，不受传统格律限制，注重情感和意象的表达。"
        elif chinese_style == 'humorous':
            style_instruction += "写得幽默风趣，轻松活泼，带有巧思和趣味。"
        elif chinese_style == 'absurd':
            style_instruction += "创作超现实、荒诞、出人意料的作品。"
        elif chinese_style == 'cyberpunk':
            style_instruction += "融合科技、赛博朋克元素，展现未来感和反乌托邦色彩。"
        elif chinese_style == 'zen':
            style_instruction += "写得简洁、禅意，富有冥想和沉思的深度。"
        elif chinese_style == 'minimalist':
            style_instruction += "极简风格，用最少的文字表达最深的意境。"
        else:
            # Custom style
            style_instruction += f"按照以下风格创作：{chinese_style}"
        
        logging.info(f"  Chinese style instruction: {style_instruction[:100]}...")
        
        old_text = "compose an ORIGINAL poem in Chinese about the same scene."
        new_text = f"compose an ORIGINAL poem in Chinese about the same scene.{style_instruction}"
        
        if old_text in prompt:
            prompt = prompt.replace(old_text, new_text)
            logging.info("  ✓ Chinese style instruction successfully inserted into prompt")
        else:
            logging.warning(f"  ⚠ Could not find target text '{old_text}' in prompt. Style may not be applied correctly.")
    else:
        logging.info("  No Chinese style specified - using default")
    
    logging.info(f"  Final prompt length: {len(prompt)} characters")
    return prompt


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
    
    # Get style settings from web app (optional - if this fails, we use default prompt)
    # This should not block poem generation even if network is unavailable
    try:
        styles = get_poem_styles_from_webapp()
        english_style = styles.get('english') if styles else None
        chinese_style = styles.get('chinese') if styles else None
        
        # Log the retrieved styles for debugging
        logging.info("=" * 80)
        logging.info("STYLE RETRIEVAL RESULT:")
        logging.info(f"  English style: {english_style if english_style else '(None - using default)'}")
        logging.info(f"  Chinese style: {chinese_style if chinese_style else '(None - using default)'}")
        logging.info("=" * 80)
        
        # If styles are not available, use default prompt (no style modifications)
        if not english_style and not chinese_style:
            logging.info("No style settings found or failed to fetch. Using default prompt.")
            prompt = POEM_GENERATION_PROMPT
        else:
            # Build prompt with style
            logging.info(f"Applying styles to prompt: English={english_style}, Chinese={chinese_style}")
            prompt = build_prompt_with_style(POEM_GENERATION_PROMPT, english_style, chinese_style)
    except Exception as e:
        # If style fetching fails for any reason, use default prompt
        # This ensures poem generation continues even without network connectivity
        logging.warning(f"Error fetching styles (non-critical, using default): {str(e)}")
        prompt = POEM_GENERATION_PROMPT
    
    # Log the complete prompt for debugging style application
    logging.info("=" * 80)
    logging.info("COMPLETE PROMPT TO GEMINI:")
    logging.info("-" * 80)
    logging.info(prompt)
    logging.info("-" * 80)
    logging.info("=" * 80)
    
    try:
        logging.info(f"Reading image and encoding for Gemini...")
        with open(image_path, "rb") as image_file:
            encoded_image = base64.b64encode(image_file.read()).decode('utf-8') # Encode image to base64 string.

        # Construct the JSON payload required by the Gemini API for image and text input.
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}, # The text prompt for the poem generation (with style).
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

# --- Function to Upload Poem to Web App ---
def upload_poem_to_webapp(image_path, poem_text):
    """
    上传照片和诗歌到 Web 应用（可选功能，失败不影响打印）
    
    注意：此函数是可选功能，即使上传失败也不会影响核心功能（拍照和打印）。
    如果相机无法连接到服务器，此函数会静默失败，不影响诗歌生成和打印。
    
    Args:
        image_path: 照片文件路径
        poem_text: 生成的诗歌文本
    
    Returns:
        bool: 上传成功返回 True，失败返回 False（但不抛出异常）
    """
    if not WEB_APP_API_KEY:
        logging.info("Web app API key not configured. Skipping upload (non-critical).")
        return False
    
    if not os.path.exists(image_path):
        logging.warning(f"Image file not found at {image_path}. Skipping upload (non-critical).")
        return False
    
    try:
        logging.info("Attempting to upload poem to web app (optional backup)...")
        
        # 读取图片并转换为 base64
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
        
        # 准备请求数据
        payload = {
            "poem": poem_text,
            "image": image_data
        }
        
        # 发送 POST 请求
        headers = {
            "X-API-Key": WEB_APP_API_KEY,
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            f"{WEB_APP_URL}/api/upload",
            json=payload,
            headers=headers,
            timeout=10  # Reduced timeout to fail faster if server is unreachable
        )
        
        if response.status_code == 201:
            logging.info("Poem uploaded successfully to web app!")
            return True
        else:
            logging.warning(f"Failed to upload poem to web app (non-critical): {response.status_code} - {response.text}")
            return False
    
    except requests.exceptions.Timeout:
        logging.warning("Timeout while uploading to web app (non-critical). Server may be slow or unreachable. Poem was already printed successfully.")
        return False
    except requests.exceptions.ConnectionError:
        logging.warning("Connection error while uploading to web app (non-critical). Check internet connection. Poem was already printed successfully.")
        return False
    except Exception as e:
        logging.warning(f"Unexpected error uploading to web app (non-critical): {str(e)}. Poem was already printed successfully.")
        return False

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
            rtscts=RTSCTS,  # Now False
            # --- IMPORTANT CHANGE: Add encoding for Chinese support ---
            encoding='CP936' # 'CP936' covers GBK/GB2312 for Simplified Chinese.
                             # This encoding also handles standard ASCII English characters.
        )
        logging.info(f"Attempting to connect to printer on port {SERIAL_PORT} with baud rate {BAUD_RATE} for printing poem...")

        # Set printer alignment and font - left aligned for poem text
        p.set(align='left', font='a', height=1, width=1)

        # Poem title might be here, if returned by Gemini with a title.
        # Ensure the entire poem_text is handled for both English and Chinese.
        # The 'encoding' parameter in the Serial constructor handles this for all subsequent text() calls.
        for line in poem_text.split('\n'):
            p.text(line + '\n')

        # Add a footer text.
        p.text("\n----------------------\n")
        # p.set(align='center')
        # p.text("（老赵的脚印）\n") # Example Chinese line in footer for testing
        p.cut() # Send command to cut the paper.
        logging.info("Poem printed successfully!")
    except Exception as e:
        # Log printer-specific errors and provide common troubleshooting tips.
        logging.error(f"Error printing poem: {e}")
        logging.error("Please ensure the printer is connected, powered on, and you have the correct serial port and baud rate.")
        logging.error("On Linux (Raspberry Pi), you might need to add your user to the 'dialout' group or run the script with sudo for serial port access.")
        logging.error("If Chinese characters are not printing correctly, double-check your printer's manual for supported code pages and ensure it has Chinese font ROM.")
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
        # 1. Check actual pin state: Filter out false triggers (e.g., on button release or noise)
        #    If the button is currently HIGH (not pressed, assuming PUD_UP), ignore this trigger.
        if GPIO.input(channel) == GPIO.HIGH:
            logging.debug(f"Callback triggered for GPIO {channel} but pin is currently HIGH. Ignoring false trigger.")
            return

        # 2. Cooldown check: Prevent rapid *intentional* presses within the cooldown period.
        #    This also catches any bounces that might slip past the bouncetime if they are
        #    still within the cooldown.
        if (current_time - last_poetry_action_time) < COOLDOWN_TIME_SECONDS:
            logging.debug(f"Button press ignored due to cooldown. Time elapsed: {current_time - last_poetry_action_time:.2f}s (Min {COOLDOWN_TIME_SECONDS}s needed)")
            return

        # If we reach here, the press is considered valid, so update the last action time.
        last_poetry_action_time = current_time
        # --- END REVISED SOFTWARE DEBOUNCE LOGIC ---

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
                # 3. Log the generated poem
                logging.info("=" * 80)
                logging.info("GENERATED POEM:")
                logging.info("-" * 80)
                logging.info(poem)
                logging.info("-" * 80)
                logging.info("=" * 80)
                
                # TEMPORARILY SKIP PHYSICAL PRINTING - for debugging style application
                # print_poem_on_thermal_printer(poem)
                logging.info("Physical printing temporarily disabled for debugging")
                
                # 4. Upload to web app (if configured) - this is optional and should not block printing
                # Even if upload fails, the poem has already been printed successfully
                if WEB_APP_API_KEY:
                    try:
                        upload_poem_to_webapp(captured_filepath, poem)
                    except Exception as e:
                        # Log error but don't fail - printing was already successful
                        logging.warning(f"Failed to upload to web app (non-critical): {str(e)}")
                else:
                    logging.info("Web app upload skipped (API key not configured)")
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
        
        # Log configuration status
        logging.info(f"Gemini API key: {'Configured' if API_KEY else 'Not configured'}")
        if WEB_APP_API_KEY:
            logging.info(f"Web app upload enabled. URL: {WEB_APP_URL}")
        else:
            logging.info("Web app upload disabled (WEB_APP_API_KEY not configured in .env)")

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

