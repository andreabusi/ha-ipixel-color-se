"""A simulated iPixel panel and other helpers for the tests."""

from collections.abc import Callable, Sequence
from io import BytesIO
import random

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS
from PIL import Image

from custom_components.ipixel_color_se.const import (
    CONF_DEVICE_TYPE,
    CONF_HEIGHT,
    CONF_WIDTH,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"
BLE_NAME = "LED_BLE_CCDDEEFF"
NAME = "Kitchen Pixel"

# The real reply of a 32×32 panel to set_time (check V9)
INFO_FRAME = bytes.fromhex("0c 00 01 80 81 11 02 00 00 01 00 01")

ENTRY_DATA = {
    CONF_ADDRESS: ADDRESS,
    CONF_DEVICE_TYPE: 0x81,
    CONF_WIDTH: 32,
    CONF_HEIGHT: 32,
}


# Commands by their id and type bytes, as describe() names them
_COMMANDS = {
    b"\x01\x80": "set_time",
    b"\x04\x80": "brightness",
    b"\x06\x80": "orientation",
    b"\x06\x01": "clock",
    b"\x07\x01": "power",
    b"\x02\x00": "png",
    b"\x03\x00": "gif",
}

# An image window: 15 header bytes, then the image's bytes
_WINDOW_HEADER = 15
_CONTINUED = 0x02


def ack(command: bytes, status: int = 1) -> bytes:
    """Return the ACK the panel sends for a command: 05 00 <id> <type> <status>."""
    return bytes([0x05, 0x00, command[2], command[3], status])


def describe(command: bytes) -> str:
    """Name a command written to the panel, like "power off" or "brightness 40".

    The clock shows its style and options, like "clock 1 24h date" or
    "clock 3 12h"; panel_date() reads its date. An image transfer is "gif"
    or "png" for its first window, then "gif, continued" for each other.
    """
    match _COMMANDS.get(command[2:4]):
        case "power":
            return "power on" if command[4] else "power off"
        case "brightness" | "orientation" as name:
            return f"{name} {command[4]}"
        case "set_time":
            return "set_time"
        case "gif" | "png" as name:
            return f"{name}, continued" if command[4] == _CONTINUED else name
        case "clock":
            style, format_24h, show_date = command[4:7]
            return f"clock {style} {'24h' if format_24h else '12h'}" + (
                " date" if show_date else ""
            )
        case _:
            return command.hex(" ")


def panel_time(command: bytes) -> str:
    """Return the time a set_time command carries, like "19:17:02"."""
    assert describe(command) == "set_time"
    hour, minute, second = command[4:7]
    return f"{hour:02}:{minute:02}:{second:02}"


def panel_date(command: bytes) -> str:
    """Return the date a clock command carries, like "08/11/26 7".

    The last number is the weekday, 1 for Monday to 7 for Sunday.
    """
    assert describe(command).startswith("clock")
    year, month, day, weekday = command[7:11]
    return f"{day:02}/{month:02}/{year:02} {weekday}"


class FakeBleakClient:
    """A connected BleakClient whose writes reach a FakePanel."""

    def __init__(
        self,
        panel: FakePanel,
        disconnected_callback: Callable[[FakeBleakClient], None] | None,
    ) -> None:
        """Connect to the panel."""
        self.panel = panel
        self.is_connected = True
        self.closed = False
        self.notifying = False
        self._disconnected_callback = disconnected_callback
        self._notify: Callable[[object, bytearray], None] | None = None

    async def start_notify(
        self, _uuid: str, callback: Callable[[object, bytearray], None]
    ) -> None:
        """Enable notifications."""
        if self.panel.notify_error:
            raise self.panel.notify_error
        self.notifying = True
        self._notify = callback

    async def write_gatt_char(
        self, _uuid: str, data: bytes, response: bool = False
    ) -> None:
        """Write to the panel, which may answer before the write returns."""
        if self.panel.write_error:
            raise self.panel.write_error
        for frame in self.panel.receive(bytes(data)):
            self.notify(frame)

    def notify(self, frame: bytes) -> None:
        """Send a frame from the panel."""
        assert self._notify is not None
        self._notify(None, bytearray(frame))

    async def disconnect(self) -> None:
        """Disconnect, calling the callback as bleak does, and free the client."""
        self.closed = True
        self.drop()

    def drop(self) -> None:
        """Lose the connection."""
        if not self.is_connected:
            return
        self.is_connected = False
        if self._disconnected_callback:
            self._disconnected_callback(self)


class FakePanel:
    """A panel that answers like the real one (check V9).

    set_time gets the info frame, every other command an ACK. An image
    window gets an ACK with status 1, or 3 for the last one, and the panel
    then shows the image. Tests change responder, info_frame or the error
    attributes to simulate failures.

    chunks are the BLE writes, writes the commands and windows they make up.

    It also stands in for HA's Bluetooth manager: present is whether the
    manager has the panel in its history, and advertise(), vanish(),
    lose_power() and power_on() drive the controller's callbacks.
    """

    def __init__(self) -> None:
        """Start powered on, with the screen on, and in range."""
        self.present = True
        self.powered = True
        self.screen_on = True
        self.info_frame = INFO_FRAME
        self.connect_error: Exception | None = None
        self.notify_error: Exception | None = None
        self.write_error: Exception | None = None
        self.chunks: list[bytes] = []
        self.writes: list[bytes] = []
        self.image: bytes | None = None
        """The image shown: the GIF or PNG the last transfer carried."""
        self._pending = bytearray()
        self._transfer = bytearray()
        self.connect_attempts = 0
        self.clients: list[FakeBleakClient] = []
        self.responder: Callable[[bytes], list[bytes]] = self.answer
        self.advertisement_callbacks: list[
            Callable[[BluetoothServiceInfoBleak], None]
        ] = []
        self.unavailable_callbacks: list[
            Callable[[BluetoothServiceInfoBleak], None]
        ] = []

    @property
    def commands(self) -> list[str]:
        """Return the commands written so far, named by describe()."""
        return [describe(data) for data in self.writes]

    @property
    def shown(self) -> Image.Image:
        """Return the image shown, decoded."""
        assert self.image is not None
        return Image.open(BytesIO(self.image))

    def receive(self, chunk: bytes) -> list[bytes]:
        """Take a BLE write, answering each command or window it completes.

        A frame starts with its length, header included, as two bytes.
        """
        self.chunks.append(chunk)
        self._pending += chunk
        length = int.from_bytes(self._pending[:2], "little")
        assert length >= 4, f"Bad frame {bytes(self._pending).hex(' ')}"
        if len(self._pending) < length:
            return []
        frame = bytes(self._pending[:length])
        del self._pending[:length]
        self.writes.append(frame)
        return self.responder(frame)

    def answer(self, data: bytes) -> list[bytes]:
        """Answer a command the way the panel does.

        Brightness, orientation and set_time turn the screen back on (checks
        V1 and V7), like any content, the clock and images included.
        """
        match describe(data).split()[0].removesuffix(","):
            case "set_time":
                self.screen_on = True
                return [self.info_frame]
            case "power":
                self.screen_on = bool(data[4])
            case "brightness" | "orientation" | "clock":
                self.screen_on = True
            case "gif" | "png":
                return [ack(data, self.receive_window(data))]
        return [ack(data)]

    def receive_window(self, window: bytes) -> int:
        """Collect a window of an image transfer, and return its ACK status.

        The header carries the size of the whole image: the window that
        completes it gets status 3, and the panel shows the image.
        """
        if window[4] != _CONTINUED:
            self._transfer = bytearray()
        self._transfer += window[_WINDOW_HEADER:]
        if len(self._transfer) < int.from_bytes(window[5:9], "little"):
            return 1
        self.image = bytes(self._transfer)
        self.screen_on = True
        return 3

    def advertise(self, *, connectable: bool = True) -> None:
        """Advertise, as the panel does while powered and not connected (check V4).

        Like HA's Bluetooth manager, call the callbacks before recording the
        advertisement: until then the panel can't be looked up.
        """
        info = service_info(connectable=connectable)
        for callback in list(self.advertisement_callbacks):
            callback(info)
        if connectable:
            self.present = True

    def vanish(self) -> None:
        """Be forgotten by HA's Bluetooth manager, after a while without advertising."""
        self.present = False
        for callback in list(self.unavailable_callbacks):
            callback(service_info())

    def lose_power(self) -> None:
        """Lose power: the connection drops and connecting fails.

        HA's Bluetooth still has the panel in its history until vanish().
        """
        self.powered = False
        for client in self.clients:
            client.drop()

    def power_on(self) -> None:
        """Get power back: the screen boots on, and the panel advertises."""
        self.powered = True
        self.screen_on = True
        self.advertise()

    def register_advertisement_callback(
        self,
        _hass: object,
        callback: Callable[[BluetoothServiceInfoBleak], None],
        _address: str,
    ) -> Callable[[], None]:
        """Stand in for bluetooth.async_register_advertisement_callback."""
        self.advertisement_callbacks.append(callback)
        return lambda: self.advertisement_callbacks.remove(callback)

    def track_unavailable(
        self,
        _hass: object,
        callback: Callable[[BluetoothServiceInfoBleak], None],
        _address: str,
        connectable: bool = True,
    ) -> Callable[[], None]:
        """Stand in for bluetooth.async_track_unavailable."""
        assert connectable
        self.unavailable_callbacks.append(callback)
        return lambda: self.unavailable_callbacks.remove(callback)

    @property
    def client(self) -> FakeBleakClient:
        """Return the latest client."""
        return self.clients[-1]

    @property
    def connected(self) -> bool:
        """Return whether a client is connected."""
        return any(client.is_connected for client in self.clients)

    def ble_device(self, *_args: object, **_kwargs: object) -> BLEDevice | None:
        """Stand in for async_ble_device_from_address."""
        return BLEDevice(ADDRESS, BLE_NAME, {}) if self.present else None

    async def establish_connection(
        self,
        _client_class: type,
        _device: BLEDevice,
        _name: str,
        disconnected_callback: Callable[[FakeBleakClient], None] | None = None,
        **_kwargs: object,
    ) -> FakeBleakClient:
        """Stand in for bleak_retry_connector.establish_connection."""
        self.connect_attempts += 1
        if self.connect_error:
            raise self.connect_error
        if not self.powered:
            raise BleakError(f"{ADDRESS} not found")
        client = FakeBleakClient(self, disconnected_callback)
        self.clients.append(client)
        return client


def service_info(
    address: str = ADDRESS,
    name: str = BLE_NAME,
    service_uuids: list[str] | None = None,
    *,
    connectable: bool = True,
) -> BluetoothServiceInfoBleak:
    """Return an advertisement like the panel's."""
    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=-62,
        manufacturer_data={21076: bytes.fromhex("00 72 00 07 02 00 81")},
        service_data={},
        service_uuids=service_uuids or [],
        source="00:00:00:00:00:01",
        device=BLEDevice(address, name, {}),
        advertisement=None,
        connectable=connectable,
        time=0,
        tx_power=None,
    )


def gif(
    frames: int = 3,
    size: tuple[int, int] = (64, 64),
    durations: Sequence[int] = (100, 200, 300),
) -> bytes:
    """Return an animated GIF, a different red in each frame."""
    images = [Image.new("RGB", size, (60 + 60 * i, 0, 0)) for i in range(frames)]
    output = BytesIO()
    images[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=list(durations[:frames]),
        loop=0,
    )
    return output.getvalue()


def noise_gif(frames: int, size: tuple[int, int] = (32, 32)) -> bytes:
    """Return a GIF that doesn't compress, to fill several windows."""
    rng = random.Random(frames)  # noqa: S311  # repeatable, not secret
    images = [
        Image.frombytes("RGB", size, rng.randbytes(size[0] * size[1] * 3))
        for _ in range(frames)
    ]
    output = BytesIO()
    images[0].save(output, format="GIF", save_all=True, append_images=images[1:])
    return output.getvalue()


def still(
    image_format: str = "JPEG",
    size: tuple[int, int] = (64, 32),
    color: tuple[int, ...] = (0, 255, 0),
    mode: str = "RGB",
) -> bytes:
    """Return a still image of one color."""
    output = BytesIO()
    Image.new(mode, size, color).save(output, format=image_format)
    return output.getvalue()
