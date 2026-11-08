"""Tests for the Bluetooth transport."""

import asyncio
from unittest.mock import Mock

from bleak.exc import BleakError
from homeassistant.core import HomeAssistant
import pytest

from custom_components.ipixel_color_se import connection as connection_module
from custom_components.ipixel_color_se.connection import (
    IPixelCommandError,
    IPixelConnection,
    IPixelConnectionError,
)
from custom_components.ipixel_color_se.protocol import SendPlan, Window

from .common import ADDRESS, INFO_FRAME, FakePanel, ack

BRIGHTNESS = bytes.fromhex("05 00 04 80 46")
POWER_ON = bytes.fromhex("05 00 07 01 01")
SET_TIME = bytes.fromhex("08 00 01 80 13 11 02 00")


def plan(*windows: bytes, **kwargs: object) -> SendPlan:
    """Return a plan that waits for an ACK after each window."""
    return SendPlan(
        name="test", windows=tuple(Window(data=w, ack=True) for w in windows), **kwargs
    )


@pytest.fixture
def callbacks() -> Mock:
    """Record the connection callbacks."""
    return Mock()


@pytest.fixture
async def connection(
    hass: HomeAssistant, mock_panel: FakePanel, callbacks: Mock
) -> IPixelConnection:
    """Return a connected IPixelConnection."""
    conn = IPixelConnection(
        hass,
        ADDRESS,
        "Kitchen Pixel",
        on_connected=callbacks.connected,
        on_disconnected=callbacks.disconnected,
    )
    await conn.async_connect()
    return conn


async def test_connect_enables_notifications_once(
    connection: IPixelConnection, mock_panel: FakePanel, callbacks: Mock
) -> None:
    """Connecting twice keeps the first connection."""
    await connection.async_connect()

    assert connection.connected
    assert len(mock_panel.clients) == 1
    assert mock_panel.client.notifying
    callbacks.connected.assert_called_once_with()


async def test_connect_needs_the_panel_in_range(
    hass: HomeAssistant, mock_panel: FakePanel
) -> None:
    """A panel no scanner sees can't be connected."""
    mock_panel.present = False
    conn = IPixelConnection(hass, ADDRESS, "Kitchen Pixel")

    with pytest.raises(IPixelConnectionError, match="isn't in range"):
        await conn.async_connect()
    assert not mock_panel.clients


@pytest.mark.parametrize("attribute", ["connect_error", "notify_error"])
async def test_connect_errors(
    hass: HomeAssistant, mock_panel: FakePanel, attribute: str
) -> None:
    """Bleak errors while connecting become IPixelConnectionError."""
    setattr(mock_panel, attribute, BleakError("boom"))
    conn = IPixelConnection(hass, ADDRESS, "Kitchen Pixel")

    with pytest.raises(IPixelConnectionError, match="boom"):
        await conn.async_connect()
    assert not conn.connected
    assert not mock_panel.connected


async def test_send_waits_for_the_ack(
    connection: IPixelConnection, mock_panel: FakePanel
) -> None:
    """A simple command is acknowledged, even before its write returns."""
    await connection.async_send(plan(BRIGHTNESS))

    assert mock_panel.writes == [BRIGHTNESS]


async def test_send_without_ack_fails(
    connection: IPixelConnection,
    mock_panel: FakePanel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing ACK is an error, not a silent success."""
    monkeypatch.setattr(connection_module, "ACK_TIMEOUT", 0.01)
    mock_panel.responder = lambda _data: []

    with pytest.raises(IPixelCommandError, match="didn't acknowledge"):
        await connection.async_send(plan(BRIGHTNESS))


async def test_send_write_error(
    connection: IPixelConnection, mock_panel: FakePanel
) -> None:
    """A failed write is a command error."""
    mock_panel.write_error = BleakError("write failed")

    with pytest.raises(IPixelCommandError, match="write failed"):
        await connection.async_send(plan(BRIGHTNESS))


async def test_windows_are_written_in_chunks(
    connection: IPixelConnection, mock_panel: FakePanel
) -> None:
    """Each window goes out in chunk_size writes, then waits for its ACK."""
    # 600 bytes, starting with their length
    window = (
        (600).to_bytes(2, "little") + b"\x03\x00" + bytes(range(256)) * 2 + bytes(84)
    )
    mock_panel.responder = lambda data: [ack(data)]

    await connection.async_send(plan(window, window))

    assert [len(data) for data in mock_panel.chunks] == [244, 244, 112] * 2
    assert mock_panel.writes == [window, window]


async def test_final_ack(connection: IPixelConnection, mock_panel: FakePanel) -> None:
    """With final_ack, the transfer ends only at status 3."""
    statuses = iter([[1], [0, 3]])
    mock_panel.responder = lambda data: [ack(data, s) for s in next(statuses)]

    await connection.async_send(plan(POWER_ON, POWER_ON, final_ack=True))

    assert len(mock_panel.writes) == 2


async def test_final_ack_after_the_last_window(
    connection: IPixelConnection, mock_panel: FakePanel
) -> None:
    """The end-of-transfer ACK may follow the last window's own ACK."""
    loop = asyncio.get_running_loop()

    def late_end(data: bytes) -> list[bytes]:
        loop.call_later(0.01, mock_panel.client.notify, ack(data, 3))
        return [ack(data, 1)]

    mock_panel.responder = late_end

    await connection.async_send(plan(POWER_ON, final_ack=True))

    assert len(mock_panel.writes) == 1


async def test_ack_of_another_command_is_ignored(
    connection: IPixelConnection,
    mock_panel: FakePanel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only an ACK that echoes the command's bytes 2 and 3 counts (check V9).

    A late ACK of another command can't let the next window go too early.
    """
    monkeypatch.setattr(connection_module, "ACK_TIMEOUT", 0.05)
    mock_panel.responder = lambda _data: [ack(POWER_ON)]

    with pytest.raises(IPixelCommandError, match="didn't acknowledge"):
        await connection.async_send(plan(BRIGHTNESS))

    mock_panel.responder = lambda data: [ack(POWER_ON), ack(data)]
    await connection.async_send(plan(BRIGHTNESS))


async def test_request_returns_the_response(
    connection: IPixelConnection, mock_panel: FakePanel
) -> None:
    """A request skips ACKs and returns the first other frame."""
    mock_panel.responder = lambda data: [ack(data), INFO_FRAME]
    request = SendPlan(
        name="info", windows=(Window(data=SET_TIME, ack=False),), response=True
    )

    assert await connection.async_request(request) == INFO_FRAME


async def test_request_needs_a_response_plan(connection: IPixelConnection) -> None:
    """async_request refuses a plan without a response."""
    with pytest.raises(ValueError, match="doesn't expect a response"):
        await connection.async_request(plan(BRIGHTNESS))


async def test_commands_run_in_order(
    connection: IPixelConnection, mock_panel: FakePanel
) -> None:
    """A second command waits until the first one is acknowledged."""
    loop = asyncio.get_running_loop()

    def slow_ack(data: bytes) -> list[bytes]:
        if data == BRIGHTNESS:
            loop.call_later(0.05, mock_panel.client.notify, ack(data))
            return []
        return [ack(data)]

    mock_panel.responder = slow_ack
    first = asyncio.create_task(connection.async_send(plan(BRIGHTNESS)))
    second = asyncio.create_task(connection.async_send(plan(POWER_ON)))
    await asyncio.sleep(0.01)

    assert mock_panel.writes == [BRIGHTNESS]
    await asyncio.gather(first, second)
    assert mock_panel.writes == [BRIGHTNESS, POWER_ON]


async def test_dropped_connection_while_waiting(
    connection: IPixelConnection, mock_panel: FakePanel, callbacks: Mock
) -> None:
    """A drop wakes the command in progress and reports an unexpected disconnect."""

    def drop(_data: bytes) -> list[bytes]:
        asyncio.get_running_loop().call_soon(mock_panel.client.drop)
        return []

    mock_panel.responder = drop

    with pytest.raises(IPixelConnectionError, match="Lost the connection"):
        await connection.async_send(plan(BRIGHTNESS))
    assert not connection.connected
    callbacks.disconnected.assert_called_once_with(False)


async def test_dropped_client_is_closed(
    hass: HomeAssistant, connection: IPixelConnection, mock_panel: FakePanel
) -> None:
    """A dropped client is disconnected too, to free what it holds in BlueZ.

    Otherwise BlueZ restores its notification sessions on the next
    connection, and every frame arrives once more per dropped connection.
    """
    dropped = mock_panel.client

    dropped.drop()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert dropped.closed


async def test_disconnect(
    connection: IPixelConnection, mock_panel: FakePanel, callbacks: Mock
) -> None:
    """Disconnecting on purpose frees the panel and is reported as expected."""
    await connection.async_disconnect()

    assert not connection.connected
    assert not mock_panel.connected
    callbacks.disconnected.assert_called_once_with(True)
    with pytest.raises(IPixelConnectionError, match="Not connected"):
        await connection.async_send(plan(BRIGHTNESS))

    await connection.async_disconnect()
    callbacks.disconnected.assert_called_once_with(True)
