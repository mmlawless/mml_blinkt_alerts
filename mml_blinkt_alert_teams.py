#!/usr/bin/env python3
"""
mmlteams.py - Teams status → Blinkt via MQTT
with startup LED patterns for network/MQTT states
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

# Status strings as sent by Node-RED
STATUS_COLORS = {
    "Available":     (0, 255, 0),      # Green
    "Busy":          (255, 0, 0),      # Red
    "DND":  (128, 0, 128),    # Purple
    "BeRightBack":   (255, 255, 0),    # Yellow

    "OnThePhone":    (255, 0, 0),      # Red
    "Presenting":    (255, 0, 0),      # Red

    "InAMeeting":    (0, 0, 255),      # Blue
    "Away":          (0, 0, 0),        # Off / Black
    "Offline":       (255, 255, 255),  # White

    "In A Meeting":  (0, 0, 255),
    "AppearAway":    (0, 0, 0),
    "AppearOffline": (255, 255, 255),
    "Unknown":       (0, 128, 255),    # Light Blue
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

    rgb = STATUS_COLORS.get(message_text)
    if rgb is not None:
        set_blinkt_color(*rgb, brightness=0.1)
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

    # 4) Connected → all green for 2 seconds
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
