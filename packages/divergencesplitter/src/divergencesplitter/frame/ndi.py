"""NDI video frame source.

NDI is an optional capability. The NDI runtime and its Python binding are
imported lazily, only when a source is actually prepared or discovery runs, so
importing this module never imports NDI and systems without NDI keep working.

The NDI global state is owned once for the whole process by ``_NdiGlobal`` and
reference counted, so a capability probe, a discovery call, and a running
receiver never initialize or destroy it out of order.

Received video is copied out of the NDI buffer before that buffer is freed, so
``Frame.image`` never aliases NDI-managed memory.
"""

from __future__ import annotations

import contextlib
import importlib
import threading
from dataclasses import dataclass
from types import ModuleType, TracebackType
from typing import Protocol, Self

import numpy as np

from divergencesplitter.clock import TimeProvider
from divergencesplitter.frame.models import Frame, ImageArray
from divergencesplitter.frame.normalizer import (
    ClipRegion,
    CropMargins,
    FrameNormalizer,
    OutputSize,
    ResizeInterpolation,
)
from divergencesplitter.frame.source import (
    ErrorAction,
    FrameSourceError,
    FrameSourceState,
)

NDI_MODULE_NAME = "NDIlib"
DEFAULT_RECEIVE_TIMEOUT_MS = 100
DEFAULT_FINDER_TIMEOUT_MS = 1000


@dataclass(frozen=True)
class NdiSupport:
    """Whether NDI can be used in this process.

    This reports capability only. It never reports whether a configured source
    currently exists or whether a sender is currently transmitting.
    """

    available: bool
    reason: str | None = None


@dataclass(frozen=True)
class NdiError(FrameSourceError, Exception):
    """Base type for all ``NdiSource``-specific errors.

    NDI errors are both the values a ``FrameSource`` returns and the signals the
    NDI boundary raises, so the same hierarchy covers both roles.
    """

    message: str


class NdiUnavailableError(NdiError):
    """The NDI runtime or its Python binding is not installed."""


class NdiInitializationError(NdiError):
    """The NDI runtime exists but failed to initialize."""


class NdiSourceNotFoundError(NdiError):
    """The configured source is not currently advertised on the network."""


class NdiReceiverCreationError(NdiError):
    """A receiver could not be created for the configured source."""


class NdiReceiveError(NdiError):
    """A video frame could not be received from an existing receiver."""


class NdiNoFrameError(NdiError):
    """No video frame arrived before the receive timeout elapsed."""


class NdiReadBeforeReadyError(NdiError):
    """``read`` was attempted while the source is not READY."""


@dataclass(frozen=True)
class NdiVideoFrame:
    """One received video frame as an owned BGR uint8 array."""

    image: ImageArray


class _NdiGlobal:
    """Own the process-wide NDI global state with reference counting."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._module: ModuleType | None = None
        self._initialized = False
        self._users = 0

    def acquire(self) -> ModuleType:
        with self._lock:
            if self._module is None:
                try:
                    self._module = importlib.import_module(NDI_MODULE_NAME)
                except (ImportError, ModuleNotFoundError, OSError) as error:
                    raise NdiUnavailableError(
                        "the NDI runtime or its Python binding is not installed"
                    ) from error
            if not self._initialized:
                try:
                    initialized = bool(self._module.initialize())
                except Exception as error:
                    raise NdiInitializationError(
                        "the NDI runtime failed to initialize"
                    ) from error
                if not initialized:
                    raise NdiInitializationError("the NDI runtime failed to initialize")
                self._initialized = True
            self._users += 1
            return self._module

    def release(self) -> None:
        with self._lock:
            if self._users == 0:
                return
            self._users -= 1
            if self._users == 0 and self._initialized and self._module is not None:
                with contextlib.suppress(Exception):
                    self._module.destroy()
                self._initialized = False


_runtime = _NdiGlobal()


def detect_ndi_support() -> NdiSupport:
    """Return whether NDI can be initialized in this process.

    Capability is decided by importing the binding and initializing the NDI
    runtime, not by module presence alone. The reference-counted global state is
    released again, so probing never tears down a running receiver.
    """

    try:
        _runtime.acquire()
    except NdiUnavailableError as error:
        return NdiSupport(False, error.message)
    except NdiInitializationError as error:
        return NdiSupport(False, error.message)
    except Exception as error:  # noqa: BLE001
        return NdiSupport(False, f"the NDI runtime is unavailable: {error}")
    else:
        _runtime.release()
        return NdiSupport(True)


def discover_ndi_sources(
    timeout_ms: int = DEFAULT_FINDER_TIMEOUT_MS,
) -> tuple[str, ...]:
    """Return the names of the NDI sources currently advertised.

    Raises an ``NdiError`` when NDI itself is not usable. An empty result simply
    means no source is currently advertised.
    """

    if type(timeout_ms) is not int or timeout_ms < 0:
        raise ValueError("timeout_ms must be a non-negative integer")
    module = _runtime.acquire()
    try:
        finder = module.find_create_v2()
        if finder is None:
            raise NdiInitializationError("cannot create an NDI source finder")
        try:
            module.find_wait_for_sources(finder, timeout_ms)
            sources = module.find_get_current_sources(finder)
        finally:
            module.find_destroy(finder)
        return tuple(str(source.ndi_name) for source in sources)
    finally:
        _runtime.release()


class NdiApi(Protocol):
    """The NDI operations ``NdiSource`` depends on, injectable for tests."""

    def open_receiver(self, source_name: str) -> object: ...

    def receive_video(
        self, receiver: object, timeout_ms: int
    ) -> NdiVideoFrame | None: ...

    def destroy_receiver(self, receiver: object) -> None: ...

    def close(self) -> None: ...


class NdiModuleApi:
    """``NdiApi`` backed by the lazily loaded ``NDIlib`` binding."""

    def __init__(self, *, finder_timeout_ms: int = DEFAULT_FINDER_TIMEOUT_MS) -> None:
        self._finder_timeout_ms = finder_timeout_ms
        self._module: ModuleType | None = None
        self._finder: object | None = None
        self._closed = False

    def _ensure_module(self) -> ModuleType:
        if self._closed:
            raise NdiUnavailableError("the NDI api has already been closed")
        if self._module is None:
            self._module = _runtime.acquire()
        return self._module

    def _ensure_finder(self, module: ModuleType) -> object:
        if self._finder is None:
            finder = module.find_create_v2()
            if finder is None:
                raise NdiInitializationError("cannot create an NDI source finder")
            self._finder = finder
        return self._finder

    def open_receiver(self, source_name: str) -> object:
        module = self._ensure_module()
        finder = self._ensure_finder(module)
        module.find_wait_for_sources(finder, self._finder_timeout_ms)
        sources = module.find_get_current_sources(finder)
        source = next(
            (value for value in sources if str(value.ndi_name) == source_name), None
        )
        if source is None:
            raise NdiSourceNotFoundError(
                f"NDI source is not currently available: {source_name!r}"
            )
        create = module.RecvCreateV3()
        create.color_format = module.RECV_COLOR_FORMAT_BGRX_BGRA
        receiver = module.recv_create_v3(create)
        if receiver is None:
            raise NdiReceiverCreationError(
                f"cannot create an NDI receiver for source: {source_name!r}"
            )
        module.recv_connect(receiver, source)
        return receiver

    def receive_video(self, receiver: object, timeout_ms: int) -> NdiVideoFrame | None:
        module = self._ensure_module()
        frame_type, video, _audio, _metadata = module.recv_capture_v2(
            receiver,
            timeout_ms,
            want_audio=False,
            want_metadata=False,
        )
        if video is None:
            if frame_type == getattr(module, "FRAME_TYPE_ERROR", None):
                raise NdiReceiveError("the NDI receiver reported an error")
            return None
        try:
            if video.data is None or int(video.xres) <= 0 or int(video.yres) <= 0:
                return None
            raw = np.array(video.data, copy=True)
            image = np.ascontiguousarray(raw[:, :, :3])
        finally:
            module.recv_free_video_v2(receiver, video)
        return NdiVideoFrame(image)

    def destroy_receiver(self, receiver: object) -> None:
        if self._module is not None:
            self._module.recv_destroy(receiver)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._module is None:
            return
        finder, self._finder = self._finder, None
        if finder is not None:
            with contextlib.suppress(Exception):
                self._module.find_destroy(finder)
        _runtime.release()
        self._module = None


class NdiSource:
    """Reads raw frames from an NDI source by name."""

    def __init__(
        self,
        source_name: str,
        *,
        clip_region: ClipRegion | None = None,
        crop_margins: CropMargins | None = None,
        output_size: OutputSize | None = None,
        resize_interpolation: ResizeInterpolation = ResizeInterpolation.AREA,
        time_provider: TimeProvider | None = None,
        api: NdiApi | None = None,
        receive_timeout_ms: int = DEFAULT_RECEIVE_TIMEOUT_MS,
    ) -> None:
        if not source_name:
            raise ValueError("NDI source name must not be empty")
        if type(receive_timeout_ms) is not int or receive_timeout_ms <= 0:
            raise ValueError("receive_timeout_ms must be a positive integer")
        self._normalizer = FrameNormalizer(
            clip_region=clip_region,
            crop_margins=crop_margins,
            output_size=output_size,
            resize_interpolation=resize_interpolation,
        )
        self._source_name = source_name
        self._time_provider = (
            time_provider if time_provider is not None else TimeProvider()
        )
        self._api: NdiApi = api if api is not None else NdiModuleApi()
        self._receive_timeout_ms = receive_timeout_ms
        self._receiver: object | None = None
        self._resolution: tuple[int, int] | None = None
        self._state = FrameSourceState.NOT_READY

    @property
    def state(self) -> FrameSourceState:
        return self._state

    @property
    def normalizer(self) -> FrameNormalizer:
        return self._normalizer

    @property
    def source_name(self) -> str:
        return self._source_name

    @property
    def resolution(self) -> tuple[int, int] | None:
        """The most recently received frame size, in ``(width, height)``."""

        return self._resolution

    def prepare(self) -> FrameSourceError | None:
        if self._state is FrameSourceState.READY:
            return None
        try:
            receiver = self._api.open_receiver(self._source_name)
        except (
            NdiUnavailableError,
            NdiInitializationError,
            NdiSourceNotFoundError,
            NdiReceiverCreationError,
        ) as error:
            self._state = FrameSourceState.NOT_READY
            return error
        self._receiver = receiver
        self._state = FrameSourceState.READY
        return None

    def read(self) -> Frame | FrameSourceError:
        if self._state is not FrameSourceState.READY or self._receiver is None:
            return NdiReadBeforeReadyError("source is not READY")
        try:
            received = self._api.receive_video(self._receiver, self._receive_timeout_ms)
        except NdiReceiveError as error:
            self._discard_receiver()
            self._state = FrameSourceState.NOT_READY
            return error
        except (NdiUnavailableError, NdiInitializationError) as error:
            self._discard_receiver()
            self._state = FrameSourceState.NOT_READY
            return error
        if received is None:
            return NdiNoFrameError("no NDI video frame arrived before the timeout")
        self._resolution = (received.image.shape[1], received.image.shape[0])
        return Frame(image=received.image, captured_at=self._time_provider.now())

    def handle_error(self, error: FrameSourceError) -> ErrorAction:
        if isinstance(
            error,
            (NdiUnavailableError, NdiInitializationError, NdiReadBeforeReadyError),
        ):
            return ErrorAction.STOP
        return ErrorAction.RETRY

    def close(self) -> None:
        self._discard_receiver()
        self._state = FrameSourceState.NOT_READY
        self._api.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _discard_receiver(self) -> None:
        receiver, self._receiver = self._receiver, None
        if receiver is not None:
            with contextlib.suppress(Exception):
                self._api.destroy_receiver(receiver)
