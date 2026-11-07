"""A simulated iPixel panel and other helpers for the tests."""

from collections.abc import Callable

from bleak.backends.device import BLEDevice
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS

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


def ack(command: bytes, status: int = 1) -> bytes:
    """Return the ACK the panel sends for a command: 05 00 <id> <type> <status>."""
    return bytes([0x05, 0x00, command[2], command[3], status])


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
        self.panel.writes.append(bytes(data))
        for frame in self.panel.responder(bytes(data)):
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

    set_time gets the info frame, every other command an ACK. Tests change
    responder, info_frame or the error attributes to simulate failures.
    """

    def __init__(self) -> None:
        """Start powered on and in range."""
        self.present = True
        self.info_frame = INFO_FRAME
        self.connect_error: Exception | None = None
        self.notify_error: Exception | None = None
        self.write_error: Exception | None = None
        self.writes: list[bytes] = []
        self.clients: list[FakeBleakClient] = []
        self.responder: Callable[[bytes], list[bytes]] = self.answer

    def answer(self, data: bytes) -> list[bytes]:
        """Answer a command the way the panel does."""
        if data[2:4] == b"\x01\x80":
            return [self.info_frame]
        return [ack(data)]

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
        if self.connect_error:
            raise self.connect_error
        client = FakeBleakClient(self, disconnected_callback)
        self.clients.append(client)
        return client


def service_info(
    address: str = ADDRESS,
    name: str = BLE_NAME,
    service_uuids: list[str] | None = None,
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
        connectable=True,
        time=0,
        tx_power=None,
    )
