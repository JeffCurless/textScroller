# wifi.py — Blocking WiFi connection helper for the Galactic Unicorn.
#
# Called once during boot, before the asyncio event loop starts.
# Blocks until the Pico W joins the network or the timeout expires.

import network
import time
from config import WIFI_SSID, WIFI_PASSWORD, WIFI_TIMEOUT


def connect():
    """Connect to the configured WiFi network and return the assigned IP string.

    Activates the wireless interface, initiates the connection, then polls
    wlan.isconnected() every 500 ms until the link is up or WIFI_TIMEOUT
    seconds have elapsed.

    Returns:
        str: The IPv4 address assigned by DHCP (e.g. "192.168.1.82").

    Raises:
        RuntimeError: If the connection is not established within WIFI_TIMEOUT
                      seconds.  main.py catches this and shows "WiFi FAIL".
    """
    wlan = network.WLAN(network.STA_IF)  # station (client) mode
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    # Poll until connected or deadline reached
    deadline = time.time() + WIFI_TIMEOUT
    while not wlan.isconnected():
        if time.time() > deadline:
            raise RuntimeError("WiFi connect timeout")
        time.sleep(0.5)

    # ifconfig() returns (ip, subnet, gateway, dns); we only need the IP
    return wlan.ifconfig()[0]
