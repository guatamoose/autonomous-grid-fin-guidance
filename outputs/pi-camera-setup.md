# Raspberry Pi camera bench setup

Hardware: Raspberry Pi Zero 2 W and Raspberry Pi AI Camera (IMX500).

- The Pi joins the Windows `DroneSetup` hotspot and accepts SSH as `pi`. Its observed address was `192.168.137.104`; the hotspot may assign a different address later.
- The Pi account uses SSH key authentication and password-protected `sudo`. Credential files are held in the Windows user's `.ssh` directory, outside this workspace.
- `/boot/firmware/config.txt` sets `camera_auto_detect=0` and, under `[all]`, `dtoverlay=imx500`. The previous file is backed up on the Pi as `/boot/firmware/config.txt.before-imx500`.
- `imx500-firmware` version `0.FF23+3` is installed. The larger `imx500-all` bundle was not installed after the Pi stopped responding during its first attempt.
- `rpicam-hello --list-cameras` identified the IMX500 at 2028 × 1520 and 4056 × 3040 modes after the explicit overlay was set.
- `rpicam-still -n -t 1000 --width 640 --height 480 -o /tmp/camera-test.jpg` saved a valid JPEG. A copy is at `outputs/camera-test.jpg`.
- `vcgencmd get_throttled` returned `0x0` after capture.

The orange landing pad has not yet been tested in the camera image. No camera-based commands have been sent to the flight controller.
