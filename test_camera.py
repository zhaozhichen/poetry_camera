import picamera
import time
import os
import sys

# --- Function to Take a Picture (Copied from main.py) ---
def take_picture(filename="test_image.jpg"):
    """
    Captures a picture using the Raspberry Pi Camera and saves it to a file.
    """
    try:
        with picamera.PiCamera() as camera:
            print("Camera warming up...")
            time.sleep(1) # Give camera time to warm up
            # Using a slightly lower resolution for quicker tests,
            # but you can change it back to (2592, 1944) if needed.
            camera.resolution = (1920, 1080) # A common resolution for testing
            
            # Create a 'pictures' directory in the same location as the script
            current_dir = os.path.dirname(os.path.abspath(__file__))
            save_dir = os.path.join(current_dir, "pictures")
            os.makedirs(save_dir, exist_ok=True) # Ensure directory exists
            
            filepath = os.path.join(save_dir, filename)
            print(f"Taking picture and saving to: {filepath}")
            camera.capture(filepath)
            print("Picture taken successfully!")
            return filepath
    except picamera.PiCameraError as e:
        print(f"Error: Could not access the camera. Make sure it's connected and enabled in raspi-config.", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"An unexpected error occurred during camera operation: {e}", file=sys.stderr)
        return None

# --- Main Execution Flow for Camera Test ---
if __name__ == "__main__":
    print("--- Starting Camera Test ---")
    
    # Generate a unique filename with a timestamp
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    picture_name = f"test_picture_{timestamp}.jpg"
    
    captured_filepath = take_picture(picture_name)
    
    if captured_filepath:
        print(f"Camera test successful! Image saved to: {captured_filepath}")
    else:
        print("Camera test failed. Please check the error messages above.", file=sys.stderr)
    
    print("--- Camera Test Complete ---")
