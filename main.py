# main.py — Entry point for the Galactic Unicorn text scroller.
#
# Boot sequence:
#   1. Initialise the display hardware.
#   2. Show "Connecting..." while joining WiFi.
#   3. Show the assigned IP address (green) for 2 s, or "WiFi FAIL" (red).
#   4. Hand off to asyncio.gather() which runs the display and HTTP server
#      coroutines concurrently for the lifetime of the device.

try:
    import asyncio
except ImportError:
    # Older MicroPython firmware exposes the module as uasyncio
    import uasyncio as asyncio

from galactic import GalacticUnicorn
from picographics import PicoGraphics, DISPLAY_GALACTIC_UNICORN
import wifi
from state import state
from display import run_display
from server import run_server
from config import DEFAULT_BRIGHTNESS, DEFAULT_COLOR


def show_boot_message(gu, graphics, text, color=DEFAULT_COLOR):
    """Render a static message on the display during the boot sequence.

    Clears the framebuffer, draws text starting at the left edge (x=0),
    then pushes the frame to the LED matrix immediately.  Used before the
    asyncio event loop starts, so direct (synchronous) calls are fine here.

    Args:
        gu:       GalacticUnicorn hardware instance.
        graphics: PicoGraphics framebuffer.
        text:     The string to display.
        color:    (R, G, B) tuple; defaults to DEFAULT_COLOR (white).
    """
    graphics.set_pen(graphics.create_pen(0, 0, 0))  # black background
    graphics.clear()
    graphics.set_pen(graphics.create_pen(*color))
    graphics.text(text, 0, 2, -1, scale=1)
    gu.update(graphics)  # push framebuffer to the physical LEDs


async def main():
    # Initialise hardware — must happen before any display calls
    gu       = GalacticUnicorn()
    graphics = PicoGraphics(display=DISPLAY_GALACTIC_UNICORN)
    gu.set_brightness(DEFAULT_BRIGHTNESS)

    # --- WiFi connection ---
    show_boot_message(gu, graphics, "Connecting...")
    try:
        ip = wifi.connect()           # blocks until connected or timeout
        state.ip_address = ip         # store so /status can report it
        show_boot_message(gu, graphics, ip, color=(0, 255, 0))  # green = success
        await asyncio.sleep(2)        # leave IP visible for 2 seconds
    except RuntimeError:
        # WiFi failed — show error briefly then continue into the main loop
        # (the display will still work; the HTTP server will be unreachable)
        show_boot_message(gu, graphics, "WiFi FAIL", color=(255, 0, 0))
        await asyncio.sleep(3)

    # --- Run display and HTTP server concurrently ---
    # gather() suspends here and drives both coroutines cooperatively.
    # Neither coroutine is expected to return; the device runs until powered off.
    await asyncio.gather(
        run_display(state, gu, graphics),
        run_server(state),
    )


# Start the asyncio event loop — this call never returns
asyncio.run(main())
