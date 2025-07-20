import sys
import time
from escpos.printer import Serial

# --- Configuration for Thermal Printer ---
SERIAL_PORT = '/dev/serial0'
BAUD_RATE = 9600

# Common Serial Port Settings (adjust if your printer's manual says otherwise)
BYTESIZE = 8
PARITY = 'N' # 'N' (None), 'E' (Even), or 'O' (Odd)
STOPBITS = 1
TIMEOUT = 1.00 # Read timeout in seconds

# Flow Control: Often a culprit for garbage or no prints.
# Set both to False if your printer does not use hardware flow control.
DSRDTR = False # Data Set Ready/Data Terminal Ready flow control
RTSCTS = False # Request To Send/Clear To Send flow control


def test_serial_printer_connection():
    """
    Attempts to connect to the serial thermal printer and prints a simple test message.
    """
    p = None # Initialize printer object to None. Important for the finally block.
    try:
        print(f"Attempting to connect to printer on port {SERIAL_PORT} with baud rate {BAUD_RATE}...")
        p = Serial(
            devfile=SERIAL_PORT,
            baudrate=BAUD_RATE,
            bytesize=BYTESIZE,
            parity=PARITY,
            stopbits=STOPBITS,
            timeout=TIMEOUT,
            dsrdtr=DSRDTR,
            rtscts=RTSCTS # Explicitly set RTS/CTS
        )

        print("Connection successful! Sending test print...")

        # Simple test text
        p.set(align='center', font='b') # Centered, bold
        p.text("--- Test Print ---\n")
        p.set(align='left', font='a') # Left-aligned, normal font
        p.text("Hello from Raspberry Pi!\n")
        p.text(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        p.text("--------------------\n")
        p.cut()

        print("Test print sent successfully!")

    except Exception as e:
        print(f"Error connecting or printing: {e}", file=sys.stderr)
        print("\nTroubleshooting reminder:", file=sys.stderr)
        print(f"- Ensure printer is on and connected to {SERIAL_PORT}.", file=sys.stderr)
        print(f"- Verify ALL printer settings (baud rate, data bits, parity, stop bits, flow control).", file=sys.stderr)
        print(f"- Check serial port permissions (e.g., add user to 'dialout' group or run with sudo).", file=sys.stderr)
        print(f"- Check wiring (TX/RX lines).", file=sys.stderr)

    finally:
        if p:
            try:
                p.close()
                print("Printer connection closed.")
            except Exception as e:
                print(f"Error closing printer connection: {e}", file=sys.stderr)

if __name__ == "__main__":
    test_serial_printer_connection()
