import sys
import os
import time
import base64
import json
import picamera
from PIL import Image
from escpos.printer import Serial
import RPi.GPIO as GPIO
import logging
import requests
from datetime import datetime
import pytz
import io
from google import genai
from google.genai import types


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

# Create a custom formatter that uses EST timezone
class ESTFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt, datefmt)
        self.est_tz = pytz.timezone('US/Eastern')
    
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=self.est_tz)
        if datefmt:
            s = dt.strftime(datefmt)
        else:
            s = dt.strftime('%Y-%m-%d %H:%M:%S %Z')
        return s

formatter = ESTFormatter('%(asctime)s - %(levelname)s - %(message)s')

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

# Gemini API Model IDs
POEM_MODEL_ID = "gemini-3-pro-preview"  # Model for text/poem generation
LINE_ART_MODEL_ID = "gemini-3-pro-image-preview"  # Model for image generation

# Line art generation prompt
LINE_ART_PROMPT = """
Turn the provided image into a purely monochromatic line art illustration based on geometric minimalism.

Requirements:
1. STRICTLY Black lines on a White background only.
2. NO shading, NO greyscale, NO gradients.
3. Use clean, continuous contour lines to define the subjects and background.
4. Maintain the recognizable features of the people and objects but simplify them into a graphic style.
5. The style should resemble a clean coloring book page.
"""
# Prompt string for instructing Gemini to generate a poem based on an image.
# Note: Style information will be added separately via build_prompt_with_style()
# PRIMARY GOAL: Generate high-quality, artistic poetry that deeply captures the essence of the image.
# Order: Chinese first, then English
POEM_GENERATION_PROMPT = (
    "Your primary task is to create a high-quality, artistic poem in Chinese based on the image. "
    "First, carefully analyze the image's composition, atmosphere, mood, and emotional resonance. "
    "Then, craft a poem that demonstrates poetic artistry with rich imagery, elegant language, and cultural depth. "
    "The poem should capture not just what is seen, but the deeper meaning, emotion, and atmosphere of the scene. "
    "Use vivid imagery, precise language, and poetic devices natural to Chinese poetic expression. "
    "Ensure the poem's style and imagery deeply resonate with the specific mood of the scene. "
    "Start the poem with a title, adorned with three tildes (~~~ ) on each side. "
    "Add a single empty line after the title. "
    "IMPORTANT: Output ONLY the poem. Do not include any introductory explanations, analysis, or descriptions before the poem."
)
# Comment this line out if you don't want English translation.
POEM_GENERATION_PROMPT += (
    "\n\nNext, compose an ORIGINAL, high-quality poem in English about the same scene. "
    "IMPORTANT: Do not translate the Chinese poem. Instead, create a distinct, independent piece that captures "
    "the image's spirit using imagery and phrasing natural to English poetic expression. "
    "The English poem should be: descriptive, elegant, and subtly humorous. "
    "Use vivid imagery, precise language, and poetic devices (metaphor, alliteration, rhythm) to create depth. "
    "It should also closely reflect the photo's unique atmosphere while standing as a complete work of art on its own. "
    "Place this directly following the Chinese version after a single empty line, "
    "and also adorn the English title with three tildes (~~~ ) on each side, "
    "followed by a single empty line before the English poem body."
    "\n\nOUTPUT FORMAT: Output ONLY the two poems (Chinese first, then English) with their titles. "
    "Do not include any introductory text, explanations, or analysis before the poems."
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

# --- Global Config Variables ---
SKIP_PRINTING = False # Flag to skip actual printing for debugging


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
    logging.info(f"  Chinese style to apply: {chinese_style if chinese_style else '(None - will use default)'}")
    logging.info(f"  English style to apply: {english_style if english_style else '(None - will use default)'}")
    
    # Add Chinese style instruction first (since Chinese poem comes first)
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
        
        # Insert style instruction after "Then, craft a poem that demonstrates poetic artistry"
        insertion_point = "Then, craft a poem that demonstrates poetic artistry with rich imagery, elegant language, and cultural depth."
        if insertion_point in prompt:
            # Insert style instruction right after this line
            prompt = prompt.replace(
                insertion_point,
                insertion_point + style_instruction
            )
            logging.info("  ✓ Chinese style instruction successfully inserted into prompt")
        else:
            # Fallback: insert at the beginning of Chinese poem section
            prompt = prompt.replace(
                "Your primary task is to create a high-quality, artistic poem in Chinese",
                f"Your primary task is to create a high-quality, artistic poem in Chinese{style_instruction}"
            )
            logging.info("  ✓ Chinese style instruction inserted at beginning of Chinese section")
    else:
        logging.info("  No Chinese style specified - using default")
    
    # Add English style instruction if provided (English comes after Chinese)
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
        
        # Insert style instruction after "The English poem should be:"
        insertion_point = "The English poem should be: descriptive, elegant, and subtly humorous."
        if insertion_point in prompt:
            # Insert style instruction right after this line
            prompt = prompt.replace(
                insertion_point,
                insertion_point + style_instruction
            )
            logging.info("  ✓ English style instruction successfully inserted into prompt")
        else:
            # Fallback: insert at the beginning of English poem section
            prompt = prompt.replace(
                "Next, compose an ORIGINAL, high-quality poem in English",
                f"Next, compose an ORIGINAL, high-quality poem in English{style_instruction}"
            )
            logging.info("  ✓ English style instruction inserted at beginning of English section")
    else:
        logging.info("  No English style specified - using default")
    
    logging.info(f"  Final prompt length: {len(prompt)} characters")
    return prompt


# --- Function to Generate Poem with Gemini using genai library ---
def generate_poem_from_image(image_path, api_key):
    """
    Sends an image to the Google Gemini API using genai library to generate a poem.
    
    Returns:
        tuple: (poem_text, log_info_dict) or (None, None) if failed
        log_info_dict contains: english_style, chinese_style, prompt
    """
    if not os.path.exists(image_path):
        logging.error(f"Error: Image file not found at {image_path}")
        return None, None
    if not api_key:
        logging.error("Error: Gemini API Key is not set or loaded. Check .api_key file.")
        return None, None
    
    # Initialize log info dictionary to collect information for server sync
    log_info = {
        'english_style': None,
        'chinese_style': None,
        'prompt': None
    }
    
    # Get style settings from web app (optional - if this fails, we use default prompt)
    # This should not block poem generation even if network is unavailable
    try:
        styles = get_poem_styles_from_webapp()
        english_style = styles.get('english') if styles else None
        chinese_style = styles.get('chinese') if styles else None
        
        # Store in log info
        log_info['english_style'] = english_style
        log_info['chinese_style'] = chinese_style
        
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
    
    # Store prompt in log info
    log_info['prompt'] = prompt
    
    # Log the complete prompt for debugging style application
    logging.info("=" * 80)
    logging.info("COMPLETE PROMPT TO GEMINI:")
    logging.info("-" * 80)
    logging.info(prompt)
    logging.info("-" * 80)
    logging.info("=" * 80)
    
    try:
        logging.info(f"Loading image for Gemini...")
        # Load image using PIL
        image = Image.open(image_path)
        
        logging.info(f"Sending request to Gemini API using genai library...")
        
        # Create Gemini client
        client = genai.Client(api_key=api_key)
        
        # Call Gemini API for poem generation
        response = client.models.generate_content(
            model=POEM_MODEL_ID,
            contents=[prompt, image]
        )
        
        # Extract the generated poem from the API response
        if response.candidates and len(response.candidates) > 0:
            first_candidate = response.candidates[0]
            if first_candidate.content and first_candidate.content.parts:
                for part in first_candidate.content.parts:
                    if hasattr(part, 'text') and part.text:
                        poem = part.text
                        
                        # Remove introductory explanation text if present
                        # Find the first occurrence of poem title marker (~~~)
                        first_poem_marker = poem.find('~~~')
                        if first_poem_marker > 0:
                            # Remove everything before the first poem title
                            poem = poem[first_poem_marker:].strip()
                        elif first_poem_marker == -1:
                            # No poem marker found, try to remove common intro patterns
                            lines = poem.split('\n')
                            cleaned_lines = []
                            found_poem_start = False
                            for line in lines:
                                line_stripped = line.strip()
                                # Skip obvious intro lines
                                if not found_poem_start and (
                                    line_stripped.lower().startswith('based on') or
                                    line_stripped.lower().startswith('here are') or
                                    line_stripped.lower().startswith('here is') or
                                    (line_stripped and len(line_stripped) > 100 and 'analysis' in line_stripped.lower())
                                ):
                                    continue
                                else:
                                    found_poem_start = True
                                    cleaned_lines.append(line)
                            poem = '\n'.join(cleaned_lines).strip()
                        
                        # Add style information at the end if styles were applied
                        if log_info.get('english_style') or log_info.get('chinese_style'):
                            # Style name mappings: code -> (Chinese name, English code)
                            english_style_names = {
                                'classic': ('经典', 'classic'),
                                'romantic': ('浪漫', 'romantic'),
                                'modern': ('现代', 'modern'),
                                'haiku': ('俳句', 'haiku'),
                                'sonnet': ('十四行诗', 'sonnet'),
                                'humorous': ('幽默', 'humorous'),
                                'absurd': ('荒诞', 'absurd'),
                                'cyberpunk': ('赛博朋克', 'cyberpunk'),
                                'gothic': ('哥特', 'gothic'),
                                'zen': ('禅意', 'zen')
                            }
                            
                            chinese_style_names = {
                                'classic': ('古典', 'classic'),
                                'tang': ('唐诗', 'tang'),
                                'song': ('宋词', 'song'),
                                'modern': ('现代', 'modern'),
                                'free': ('自由体', 'free'),
                                'humorous': ('幽默', 'humorous'),
                                'absurd': ('荒诞', 'absurd'),
                                'cyberpunk': ('赛博朋克', 'cyberpunk'),
                                'zen': ('禅意', 'zen'),
                                'minimalist': ('极简', 'minimalist')
                            }
                            
                            style_parts = []
                            # Add Chinese style first (since Chinese poem comes first)
                            chn_style = log_info.get('chinese_style')
                            if chn_style:
                                # Check if it's a predefined style or custom
                                if chn_style in chinese_style_names:
                                    chn_name, eng_code = chinese_style_names[chn_style]
                                    style_parts.append(f"中文：{chn_name}（{eng_code}）")
                                else:
                                    # Custom style: show as is
                                    style_parts.append(f"中文：{chn_style}")
                            
                            # Add English style second (since English poem comes after Chinese)
                            eng_style = log_info.get('english_style')
                            if eng_style:
                                # Check if it's a predefined style or custom
                                if eng_style in english_style_names:
                                    chn_name, eng_code = english_style_names[eng_style]
                                    style_parts.append(f"英文：{chn_name}（{eng_code}）")
                                else:
                                    # Custom style: show as is
                                    style_parts.append(f"英文：{eng_style}")
                            
                            if style_parts:
                                style_info = '【' + ' | '.join(style_parts) + '】'
                                # Ensure poem ends with newline before adding style info
                                poem = poem.rstrip() + '\n\n' + style_info
                                logging.info(f"Added style info to poem: {style_info}")
                        
                        # Log the final poem (only once, after all processing)
                        logging.info("\n--- Generated Poem (Final) ---")
                        logging.info(poem)
                        logging.info("----------------------")
                        
                        log_info['poem'] = poem  # Update log_info with processed poem (including style info)
                        return poem, log_info
            
            # Check for safety ratings
            if hasattr(first_candidate, 'safety_ratings') and first_candidate.safety_ratings:
                logging.warning("Warning: Response blocked by safety settings.")
                for rating in first_candidate.safety_ratings:
                    logging.warning(f"  {rating.category}: {rating.probability}")
                return None, None
        
        # Log if the expected poem content was not found in the response or if the format was unexpected.
        logging.error("Error: Could not find poem in Gemini response or unexpected response format.")
        logging.error(f"Full response: {response}")
        return None, None
        
    except Exception as e:
        # Catch any unexpected errors that might occur during the Gemini API call process.
        logging.error(f"An unexpected error occurred during Gemini API call: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return None, None

# --- Function to Generate Line Art from Image ---
def generate_line_art_from_image(image_path, api_key):
    """
    Uses Gemini API to generate geometric line art from a photo.
    This is an optional feature - if it fails, the system continues without it.
    
    Args:
        image_path: Path to the original photo
        api_key: Gemini API key
    
    Returns:
        str: Path to the saved line art image, or None if generation failed
    """
    if not os.path.exists(image_path):
        logging.error(f"Error: Image file not found at {image_path}")
        return None
    if not api_key:
        logging.error("Error: Gemini API Key is not set or loaded")
        return None
    
    try:
        logging.info("=" * 80)
        logging.info("GENERATING LINE ART:")
        logging.info(f"  Input image: {image_path}")
        logging.info(f"  Model: {LINE_ART_MODEL_ID}")
        logging.info("-" * 80)
        
        # Load original image
        image = Image.open(image_path)
        logging.info(f"  Image loaded: {image.size} pixels")
        
        # Create Gemini client
        client = genai.Client(api_key=api_key)
        
        # Call Gemini API for image generation (line art)
        logging.info("  Sending request to Gemini for line art generation...")
        response = client.models.generate_content(
            model=LINE_ART_MODEL_ID,
            contents=[LINE_ART_PROMPT, image],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"]
            )
        )
        
        # Extract image data from response
        if response.candidates and len(response.candidates) > 0:
            first_candidate = response.candidates[0]
            if first_candidate.content and first_candidate.content.parts:
                for part in first_candidate.content.parts:
                    if hasattr(part, 'inline_data') and part.inline_data:
                        # Decode image data
                        image_bytes = part.inline_data.data
                        generated_image = Image.open(io.BytesIO(image_bytes))
                        
                        # Generate output path (same directory as original, with _lineart suffix)
                        base_name = os.path.splitext(os.path.basename(image_path))[0]
                        output_dir = os.path.dirname(image_path)
                        output_path = os.path.join(output_dir, f"{base_name}_lineart.png")
                        
                        # Save line art
                        generated_image.save(output_path)
                        logging.info(f"  ✓ Line art generated successfully!")
                        logging.info(f"  Saved to: {output_path}")
                        logging.info(f"  Size: {generated_image.size} pixels")
                        logging.info("=" * 80)
                        return output_path
        
        logging.warning("  ✗ No image data found in API response")
        logging.warning("  Continuing without line art (non-critical feature)")
        logging.info("=" * 80)
        return None
        
    except Exception as e:
        logging.warning(f"  ✗ Line art generation failed (non-critical): {str(e)}")
        logging.warning("  Continuing without line art")
        logging.info("=" * 80)
        return None

# --- Function to Upload Poem to Web App ---
def upload_poem_to_webapp(image_path, poem_text, camera_logs=None, line_art_path=None):
    """
    上传照片和诗歌到 Web 应用（可选功能，失败不影响打印）
    
    注意：此函数是可选功能，即使上传失败也不会影响核心功能（拍照和打印）。
    如果相机无法连接到服务器，此函数会静默失败，不影响诗歌生成和打印。
    
    Args:
        image_path: 照片文件路径
        poem_text: 生成的诗歌文本
        camera_logs: 相机端的日志信息（可选），用于同步到服务器端日志
        line_art_path: 线条画文件路径（可选）
    
    Returns:
        tuple: (success: bool, qr_code_bytes: bytes or None)
    """
    if not WEB_APP_API_KEY:
        logging.info("Web app API key not configured. Skipping upload (non-critical).")
        return False, None
    
    if not os.path.exists(image_path):
        logging.warning(f"Image file not found at {image_path}. Skipping upload (non-critical).")
        return False, None
    
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
        
        # 如果有线条画，一起上传
        if line_art_path and os.path.exists(line_art_path):
            logging.info(f"  Including line art in upload: {line_art_path}")
            with open(line_art_path, 'rb') as f:
                line_art_data = base64.b64encode(f.read()).decode('utf-8')
                payload["line_art"] = line_art_data
        else:
            if line_art_path:
                logging.warning(f"  Line art path provided but file not found: {line_art_path}")
            else:
                logging.info("  No line art to upload")
        
        # 如果提供了相机端日志，一起上传
        if camera_logs:
            payload["camera_logs"] = camera_logs
        
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
            
            # Extract QR code if available
            response_data = response.json()
            qr_code_bytes = None
            if 'qr_code' in response_data and response_data['qr_code']:
                try:
                    qr_code_bytes = base64.b64decode(response_data['qr_code'])
                    logging.info("QR code received and decoded successfully")
                except Exception as e:
                    logging.warning(f"Failed to decode QR code: {e}")
            
            # Send heartbeat after successful upload to update camera online status
            send_camera_heartbeat()
            return True, qr_code_bytes
        else:
            logging.warning(f"Failed to upload poem to web app (non-critical): {response.status_code} - {response.text}")
            return False, None
    
    except requests.exceptions.Timeout:
        logging.warning("Timeout while uploading to web app (non-critical). Server may be slow or unreachable. Poem will be printed without QR code.")
        return False, None
    except requests.exceptions.ConnectionError:
        logging.warning("Connection error while uploading to web app (non-critical). Check internet connection. Poem will be printed without QR code.")
        return False, None
    except Exception as e:
        logging.warning(f"Unexpected error uploading to web app (non-critical): {str(e)}. Poem will be printed without QR code.")
        return False, None


def send_camera_heartbeat():
    """
    发送心跳信号到 Web 应用，更新相机在线状态（可选功能，失败不影响相机启动）
    
    注意：此函数是可选功能，即使心跳失败也不会影响相机启动。
    如果相机无法连接到服务器，此函数会静默失败，不影响相机正常运行。
    
    Returns:
        bool: 心跳成功返回 True，失败返回 False（但不抛出异常）
    """
    if not WEB_APP_API_KEY:
        logging.info("Web app API key not configured. Skipping heartbeat (non-critical).")
        return False
    
    heartbeat_url = f"{WEB_APP_URL}/api/camera/heartbeat"
    
    try:
        logging.info("=" * 80)
        logging.info("CAMERA HEARTBEAT:")
        logging.info(f"  URL: {heartbeat_url}")
        logging.info(f"  Purpose: Update camera online status on web app")
        logging.info("-" * 80)
        
        # 发送 POST 请求
        headers = {
            "X-API-Key": WEB_APP_API_KEY,
            "Content-Type": "application/json"
        }
        
        logging.info("  Sending POST request to web app...")
        
        response = requests.post(
            heartbeat_url,
            json={},  # Empty payload, just a heartbeat signal
            headers=headers,
            timeout=5  # Short timeout to fail fast
        )
        
        logging.info(f"  Response status code: {response.status_code}")
        
        if response.status_code == 200:
            try:
                response_data = response.json()
                logging.info(f"  Response data: {response_data}")
                logging.info("  ✓ Camera heartbeat sent successfully to web app!")
                logging.info("=" * 80)
                return True
            except json.JSONDecodeError:
                logging.warning(f"  ⚠ Response is not valid JSON: {response.text}")
                logging.info("  ✓ Camera heartbeat sent (status 200, but response format unexpected)")
                logging.info("=" * 80)
                return True
        else:
            logging.warning(f"  ✗ Failed to send camera heartbeat (non-critical):")
            logging.warning(f"    Status code: {response.status_code}")
            logging.warning(f"    Response: {response.text}")
            logging.info("=" * 80)
            return False
    
    except requests.exceptions.Timeout:
        logging.warning("  ✗ Timeout while sending camera heartbeat (non-critical):")
        logging.warning(f"    URL: {heartbeat_url}")
        logging.warning("    Server may be slow or unreachable.")
        logging.info("=" * 80)
        return False
    except requests.exceptions.ConnectionError as e:
        logging.warning("  ✗ Connection error while sending camera heartbeat (non-critical):")
        logging.warning(f"    URL: {heartbeat_url}")
        logging.warning(f"    Error: {str(e)}")
        logging.warning("    Check internet connection.")
        logging.info("=" * 80)
        return False
    except Exception as e:
        logging.warning(f"  ✗ Unexpected error sending camera heartbeat (non-critical):")
        logging.warning(f"    URL: {heartbeat_url}")
        logging.warning(f"    Error type: {type(e).__name__}")
        logging.warning(f"    Error message: {str(e)}")
        logging.info("=" * 80)
        return False


# --- Function to Print Poem on Thermal Printer ---
def print_poem_on_thermal_printer(poem_text, qr_code_bytes=None, line_art_path=None):
    """
    Prints the given poem text on the thermal printer connected via serial port.
    Handles potential printer connection and printing errors.
    
    Args:
        poem_text: The poem text to print
        qr_code_bytes: Optional QR code image bytes to print after the poem
        line_art_path: Optional path to line art image to print before the poem
    """
    if not poem_text:
        logging.warning("No poem text to print.")
        return

    if SKIP_PRINTING:
        logging.info("SKIP_PRINTING flag is set. Skipping actual thermal printing.")
        logging.info("Poem would have been printed similarly to:")
        logging.info(poem_text)
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

        # Print line art if available
        if line_art_path and os.path.exists(line_art_path):
            try:
                logging.info(f"Printing line art: {line_art_path}...")
                p.set(align='center')
                line_art_image = Image.open(line_art_path)
                p.image(line_art_image)
                p.text("\n")  # Add spacing after line art
                logging.info("Line art printed successfully.")
            except Exception as e:
                logging.error(f"Failed to print line art: {e}")
                logging.info("Continuing with poem printing...")

        # Set printer alignment and font - left aligned for poem text
        p.set(align='left', font='a', height=1, width=1)

        # Poem title might be here, if returned by Gemini with a title.
        # Ensure the entire poem_text is handled for both English and Chinese.
        # The 'encoding' parameter in the Serial constructor handles this for all subsequent text() calls.
        for line in poem_text.split('\n'):
            p.text(line + '\n')

        # Add a footer text.
        # Add a footer text.
        p.text("\n----------------------\n")
        # p.set(align='center')
        # p.text("（老赵的脚印）\n") # Example Chinese line in footer for testing
        
        # Print QR Code if available
        if qr_code_bytes:
            try:
                logging.info("Printing QR code...")
                p.set(align='center')
                # Load image from bytes
                qr_image = Image.open(io.BytesIO(qr_code_bytes))
                # Print image
                p.image(qr_image)
                p.text("\nScan to view photo\n")
                logging.info("QR code printed.")
            except Exception as e:
                logging.error(f"Failed to print QR code: {e}")
        
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
            # 2. Generate line art from the captured photo (optional feature)
            line_art_filepath = None
            try:
                logging.info("Generating line art from captured photo...")
                line_art_filepath = generate_line_art_from_image(captured_filepath, API_KEY)
                if line_art_filepath:
                    logging.info(f"Line art generation successful: {line_art_filepath}")
                else:
                    logging.info("Line art generation skipped or failed (continuing without it)")
            except Exception as e:
                logging.warning(f"Line art generation error (non-critical): {str(e)}")
                logging.info("Continuing without line art")
            
            # 3. Generate poem using Gemini
            poem, log_info = generate_poem_from_image(captured_filepath, API_KEY)

            if poem:
                # 4. Upload to web app (if configured) first to get QR code
                qr_code_bytes = None
                if WEB_APP_API_KEY:
                    try:
                        # Prepare camera logs for server sync
                        camera_logs = {
                            'english_style': log_info.get('english_style') if log_info else None,
                            'chinese_style': log_info.get('chinese_style') if log_info else None,
                            'prompt': log_info.get('prompt') if log_info else None,
                            'generated_poem': poem
                        }
                        # Now upload returns success flag AND qr_code_bytes
                        # Also pass line_art_filepath if available
                        success, qr_code_bytes = upload_poem_to_webapp(
                            captured_filepath, 
                            poem, 
                            camera_logs=camera_logs,
                            line_art_path=line_art_filepath
                        )
                    except Exception as e:
                        # Log error but don't fail - we will still print
                        logging.warning(f"Failed to upload to web app (non-critical): {str(e)}")
                else:
                    logging.info("Web app upload skipped (API key not configured)")

                # 5. Print the poem (with line art if available, and QR code if available)
                print_poem_on_thermal_printer(poem, qr_code_bytes, line_art_filepath)
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

        # Send heartbeat to web app to indicate camera is online
        # This allows the web app to show camera status before first photo is taken
        if WEB_APP_API_KEY:
            send_camera_heartbeat()
        else:
            logging.info("Skipping camera heartbeat (WEB_APP_API_KEY not configured)")

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

