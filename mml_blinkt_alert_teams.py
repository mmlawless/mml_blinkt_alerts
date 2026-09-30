#!/usr/bin/env python3
"""
mml_blinkt_alert_teams.py - Teams status -> Pimoroni Blinkt (8 RGB LEDs) via MQTT

DESCRIPTION OF OPERATION
------------------------
1. STARTUP / NETWORK CHECK
   The script waits until it can open a TCP connection to the MQTT broker.
   While waiting, the LEDs alternate BLUE / RED / BLUE / RED ...

2. MQTT CONNECTION
   Once the network is up, the script connects to the broker.
   While waiting for the MQTT CONNACK, the LEDs alternate BLUE / WHITE ...

3. CONNECTED
   When connected and subscribed, all LEDs show GREEN for 2 seconds,
   then all LEDs go WHITE until the first status message arrives.

4. STATUS DISPLAY
   Node-RED publishes the Teams status as a plain text string to MQTT_TOPIC.
   Each status is shown using a PRIMARY and a SECONDARY colour:

     - PRIMARY colour   = the "family" colour (e.g. red for busy-type
                          statuses, yellow for away-type statuses).
     - SECONDARY colour = a status-specific accent, so you can tell apart
                          statuses that share the same primary colour
                          (e.g. Busy vs DND vs Presenting).

   WHICH LEDs GET WHICH COLOUR is controlled by a "pixel map" string of
   8 characters, one per LED (left to right):
        "P" = use the PRIMARY colour
        "S" = use the SECONDARY colour
   The default map (DEFAULT_PIXEL_MAP) is "SPPPPPPS": the two end LEDs use
   the secondary colour and the central six use the primary colour.
   Individual statuses can use a different map via PIXEL_MAP_OVERRIDES.

   Statuses with no accent (Available, Offline, Unknown, etc.) have the
   same primary and secondary colour, so the whole strip is one colour.

5. UNKNOWN PAYLOAD
   If a message arrives that is not in STATUS_COLORS, the whole strip is
   shown bright white.

6. EXIT
   Ctrl+C clears the LEDs and disconnects cleanly.
"""

import time
import socket
import os
import logging

import paho.mqtt.client as paho
import blinkt

# ----- Configuration -----
MQTT_BROKER_HOST = "192.168.1.15"
MQTT_BROKER_PORT = 1883
MQTT_TOPIC       = "MMLNR/TeamsStatusOUT"

# Make client id unique (prevents the broker kicking you off if a 2nd copy runs)
MQTT_CLIENT_ID = f"mmlteams-blinkt-{socket.gethostname()}-{os.getpid()}"

# Overall LED brightness for status display (0.0 - 1.0)
STATUS_BRIGHTNESS = 0.1

# ----- Colour definitions (R, G, B) -----
OFF     = (0, 0, 0)
RED     = (255, 0, 0)
GREEN   = (0, 255, 0)
BLUE    = (0, 0, 255)
YELLOW  = (255, 255, 0)
WHITE   = (255, 255, 255)
PURPLE  = (128, 0, 128)
CYAN    = (0, 255, 255)
ORANGE  = (255, 100, 0)
LIGHT_BLUE = (0, 128, 255)

# ----- Pixel map -----
# One character per LED, left to right (8 LEDs on the Blinkt):
#   "P" = primary colour, "S" = secondary colour
# Default: end LEDs = secondary, central six = primary.
# Examples:
#   "SPPPPPPS"  ends secondary, middle primary   (default)
#   "PPPPPPPP"  all primary (secondary not shown)
#   "PPPSSPPP"  centre two secondary
#   "SSPPPPSS"  outer two each side secondary
DEFAULT_PIXEL_MAP = "SPPPPPPS"

# Optional per-status pixel map overrides (status name -> 8 char map).
# Any status not listed here uses DEFAULT_PIXEL_MAP.
PIXEL_MAP_OVERRIDES = {
    # "Presenting": "SSPPPPSS",
}

# ----- Status colours -----
# Format:  "Status": (PRIMARY colour, SECONDARY colour),
#
# Status strings are as sent by Node-RED.
# Where primary and secondary are the same, the whole strip is one colour.
STATUS_COLORS = {
    # --- Green family ---
    # Available:     primary GREEN,  secondary GREEN   (all green)
    "Available":     (GREEN, GREEN),

    # --- Red family (busy-type statuses) ---
    # Busy:          primary RED,    secondary WHITE
    "Busy":          (RED, WHITE),
    # DND:           primary RED,    secondary PURPLE
    "DND":           (RED, PURPLE),
    # OnThePhone:    primary RED,    secondary CYAN
    "OnThePhone":    (RED, CYAN),
    # Presenting:    primary RED,    secondary ORANGE
    "Presenting":    (RED, ORANGE),
    # InAMeeting:    primary RED,    secondary BLUE
    "InAMeeting":    (RED, BLUE),
    # In A Meeting:  primary RED,    secondary BLUE  (alternate spelling)
    "In A Meeting":  (RED, BLUE),

    # --- Yellow family (away-type statuses) ---
    # BeRightBack:   primary YELLOW, secondary WHITE
    "BeRightBack":   (YELLOW, WHITE),

    # --- Off ---
    # Away:          primary OFF,    secondary OFF     (LEDs off)
    "Away":          (OFF, OFF),
    # AppearAway:    primary OFF,    secondary OFF     (LEDs off)
    "AppearAway":    (OFF, OFF),

    # --- White ---
    # Offline:       primary WHITE,  secondary WHITE   (all white)
    "Offline":       (WHITE, WHITE),
    # AppearOffline: primary WHITE,  secondary WHITE   (all white)
    "AppearOffline": (WHITE, WHITE),

    # --- Fallback for a status Teams/Node-RED reports as "Unknown" ---
    # Unknown:       primary LIGHT_BLUE, secondary LIGHT_BLUE (all light blue)
    "Unknown":       (LIGHT_BLUE, LIGHT_BLUE),
}

connected_to_broker = False
first_message_received = False


# ----- Blinkt helpers -----
def show_blue_red_pattern(brightness=0.1):
    """Show blue/red/blue/red/... across the 8 pixels."""
    for i in range(8):
        if i % 2 == 0:
            blinkt.set_pixel(i, 0, 0, 255, brightness)      # blue
        else:
            blinkt.set_pixel(i, 255, 0, 0, brightness)      # red
    blinkt.show()


def show_blue_white_pattern(brightness=0.1):
    """Show blue/white/blue/white/... across the 8 pixels."""
    for i in range(8):
        if i % 2 == 0:
            blinkt.set_pixel(i, 0, 0, 255, brightness)      # blue
        else:
            blinkt.set_pixel(i, 255, 255, 255, brightness)  # white
    blinkt.show()


def set_blinkt_color(r, g, b, brightness=0.1):
    """Set all Blinkt pixels to one color and show."""
    blinkt.set_all(r, g, b, brightness)
    blinkt.show()


def show_status(status, brightness=STATUS_BRIGHTNESS):
    """
    Show a status using its primary/secondary colours and pixel map.
    Each pixel is set to the primary or secondary colour according to the
    "P"/"S" character in the pixel map for that status.
    """
    primary, secondary = STATUS_COLORS[status]
    pixel_map = PIXEL_MAP_OVERRIDES.get(status, DEFAULT_PIXEL_MAP).upper()

    for i in range(8):
        # If the map is shorter than 8 characters, default to primary
        role = pixel_map[i] if i < len(pixel_map) else "P"
        r, g, b = secondary if role == "S" else primary
        blinkt.set_pixel(i, r, g, b, brightness)
    blinkt.show()


# ----- MQTT callbacks -----
def on_connect(client, userdata, flags, rc):
    """
    MQTT v3.1.1 callback API v1:
      on_connect(client, userdata, flags, rc)
    """
    global connected_to_broker

    if rc == 0:
        print("CONNACK received (connected OK)")
        connected_to_broker = True

        # Subscribe here so it also re-subscribes after any reconnect
        print(f"Subscribing to topic {MQTT_TOPIC}")
        client.subscribe(MQTT_TOPIC)
    else:
        print(f"ERROR: Connection failed with code {rc}")
        raise SystemExit(1)


def on_disconnect(client, userdata, rc):
    # rc=0 means clean disconnect; nonzero means unexpected drop
    print(f"DISCONNECTED rc={rc} (0=clean, nonzero=unexpected)")


def on_message(client, userdata, message):
    global first_message_received

    message_text = message.payload.decode("utf-8")
    print("Message Received:", message_text)

    first_message_received = True

    if message_text in STATUS_COLORS:
        show_status(message_text)
    else:
        print("Unknown status payload, using bright white")
        set_blinkt_color(255, 255, 255, brightness=0.5)


# ----- Network helper -----
def wait_for_network():
    """
    Wait until we can open a TCP connection to the broker host/port.
    While waiting, show blue/red/blue/red/... pattern.
    """
    print(f"Checking network connectivity to {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}")

    while True:
        try:
            with socket.create_connection((MQTT_BROKER_HOST, MQTT_BROKER_PORT), timeout=2):
                print("Network connection OK (TCP to broker succeeded)")
                return
        except OSError:
            show_blue_red_pattern(brightness=0.1)
            time.sleep(1)


# ----- Main program -----
def main():
    global connected_to_broker, first_message_received

    logging.basicConfig(level=logging.INFO)

    print(f"Selected topic {MQTT_TOPIC}")

    # 1) Wait for network connectivity (TCP to broker host)
    wait_for_network()

    # 2) Show blue/white pattern while waiting for MQTT CONNACK
    show_blue_white_pattern(brightness=0.1)

    # Create MQTT client
    client = paho.Client(
        client_id=MQTT_CLIENT_ID,
        protocol=paho.MQTTv311,
        transport="tcp",
    )

    # Enable Paho internal logging (very useful for diagnosing reconnects)
    client.enable_logger()

    # Register callbacks
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    print(f"Connecting to broker (MQTT) as client_id={MQTT_CLIENT_ID}")
    client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=60)
    print("MQTT connection initiated")

    client.loop_start()

    # 3) Wait until MQTT broker connection is fully established (CONNACK)
    while not connected_to_broker:
        show_blue_white_pattern(brightness=0.1)
        time.sleep(0.5)

    # 4) Connected -> all green for 2 seconds
    set_blinkt_color(0, 255, 0, brightness=0.1)
    time.sleep(2)

    # 5) Then all white until first MQTT message is received
    set_blinkt_color(255, 255, 255, brightness=0.1)

    print("Connected to broker (and subscribed). Waiting for messages...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting program")
        blinkt.clear()
        blinkt.show()
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
