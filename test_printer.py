import sys
import time
from escpos.printer import Serial

# --- Configuration for Thermal Printer ---
# These should match the settings in your main script
SERIAL_PORT = '/dev/serial0'
BAUD_RATE = 9600

# Optional: Serial port settings (usually default is fine)
BYTESIZE = 8
PARITY = 'N' # No parity
STOPBITS = 1
TIMEOUT = 1.00 # Read timeout in seconds
DSRDTR = True # Data Set Ready/Data Terminal Ready flow control (often needed for these printers)

def test_serial_printer_connection():
    """
    Attempts to connect to the serial thermal printer and prints a test message.
    """
    p = None # Initialize printer object to None
    try:
        print(f"Attempting to connect to printer on port {SERIAL_PORT} with baud rate {BAUD_RATE}...")
        p = Serial(
            devfile=SERIAL_PORT,
            baudrate=BAUD_RATE,
            bytesize=BYTESIZE,
            parity=PARITY,
            stopbits=STOPBITS,
            timeout=TIMEOUT,
            dsrdtr=DSRDTR
        )

        print("Connection successful! Sending test print...")

        # Print some test text with different formatting
        p.set(align='center', font='b', height=2, width=2) # Large, bold, centered
        p.text("--- Test Print ---\n")
        p.set(align='left', font='a', height=1, width=1) # Normal font, left aligned
        p.text("This is a test print from your Raspberry Pi.\n")
        p.text(f"Port: {SERIAL_PORT}\n")
        p.text(f"Baud Rate: {BAUD_RATE}\n")
        p.text("\n") # Blank line
        p.text("If you see this, the serial connection is working!\n")
        p.text("Date: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
        p.text("\n") # Blank line

        # Try some special characters (might vary by printer/encoding)
        # p.text("Special chars: Hello áéíóúñüçøß你好世界\n") # Uncomment if you need to test this

        p.cut() # Cut the paper
        print("Test print sent successfully!")

    except Exception as e:
        print(f"Error connecting or printing: {e}", file=sys.stderr)
        print("\nTroubleshooting tips:", file=sys.stderr)
        print(f"1. Is the printer powered on and connected to {SERIAL_PORT}?", file=sys.stderr)
        print(f"2. Does the baud rate ({BAUD_RATE}) match your printer's setting?", file=sys.stderr)
        print(f"3. Have you run 'sudo raspi-config' to enable the serial port for general use (not console)?", file=sys.stderr)
        print(f"4. Is your user ('{os.getenv('USER')}') in the 'dialout' group? (Check with 'groups {os.getenv('USER')}' and reboot if you added it recently).", file=sys.stderr)
        print(f"5. Try running this script with 'sudo python test_printer.py' as a last resort for permission issues.", file=sys.stderr)
    finally:
        if p:
            try:
                p.close()
                print("Printer connection closed.")
            except Exception as e:
                print(f"Error closing printer connection: {e}", file=sys.stderr)

if __name__ == "__main__":
    test_serial_printer_connection()
