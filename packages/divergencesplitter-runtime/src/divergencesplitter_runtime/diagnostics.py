"""Concrete operational diagnostics for the runtime and its command line."""

from __future__ import annotations

import json
import logging
import re
import threading
import traceback
import uuid
from collections.abc import Mapping, MutableMapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit, urlunsplit

from divergencesplitter import (
    Action,
    ColorRangeConfig,
    DetectionResult,
    DifferenceHashSimilarityConfig,
    ErrorAction,
    Frame,
    FrameContext,
    FrameNormalizationError,
    FrameSource,
    FrameSourceError,
    FrameSourceState,
    ImageDetector,
    LiveSplitConnection,
    MeanAbsoluteSimilarityConfig,
    MonotonicTime,
    OpenCvCameraSource,
    PhaseCorrelationConfig,
    Scenario,
    TemplateMatchConfig,
    TimeProvider,
    VideoFileSource,
)

from divergencesplitter_runtime.capture import PublishResult
from divergencesplitter_runtime.livesplit.models import (
    LiveSplitResyncReason,
    LiveSplitSnapshot,
)
from divergencesplitter_runtime.livesplit.worker import (
    ActionSubmission,
    BridgeActionRequest,
)
from divergencesplitter_runtime.metrics import RuntimeMetricsSnapshot
from divergencesplitter_runtime.observability import (
    DetectorScore,
    DetectorTreeSnapshot,
    build_detector_tree,
)

_METRICS_WINDOW_NANOSECONDS = 1_000_000_000
_METRICS_BUCKET_NANOSECONDS = 50_000_000
_METRICS_BUCKET_COUNT = _METRICS_WINDOW_NANOSECONDS // _METRICS_BUCKET_NANOSECONDS + 1

_BUILTIN_LOG_RECORD_FIELDS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "event_name"}


class _OneLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = (
            datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        event_name = getattr(record, "event_name", record.getMessage())
        fields = [
            f"{key}={_format_value(value)}"
            for key, value in record.__dict__.items()
            if key not in _BUILTIN_LOG_RECORD_FIELDS
        ]
        if record.exc_info is not None and record.exc_info[1] is not None:
            fields.extend(_exception_pairs(record.exc_info[1]))
        suffix = "" if not fields else f" {' '.join(fields)}"
        return (
            f"{timestamp} {record.levelname} [{record.threadName}] {event_name}{suffix}"
        )


class _SafeStreamHandler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            stream = self.stream
            stream.write(message + self.terminator)
            self.flush()
        except Exception:  # noqa: BLE001
            return


class _ScenarioLoggerAdapter(logging.LoggerAdapter):
    def process(
        self,
        msg: object,
        kwargs: MutableMapping[str, Any],
    ) -> tuple[object, MutableMapping[str, Any]]:
        processed = dict(kwargs)
        extra = dict(self.extra or {})
        supplied = processed.get("extra")
        if isinstance(supplied, Mapping):
            extra.update(supplied)
        processed["extra"] = extra
        return msg, processed


class OperationalDiagnostics:
    """Write typed runtime facts as safe, human-readable one-line logs."""

    def __init__(
        self,
        stream: TextIO,
        *,
        level: int = logging.INFO,
        time_provider: TimeProvider | None = None,
    ) -> None:
        self._logger = logging.getLogger(
            f"divergencesplitter.operational.{uuid.uuid4().hex}"
        )
        self._logger.setLevel(level)
        handler = _SafeStreamHandler(stream)
        handler.setFormatter(_OneLineFormatter())
        self._logger.addHandler(handler)
        self._logger.propagate = False
        self._connections: dict[LiveSplitConnection, int] = {}
        self._source_fields: dict[str, object] = {}
        self._context_lock = threading.Lock()
        self._time_provider = time_provider or TimeProvider()
        self._metrics_lock = threading.Lock()
        self._input_rate = _TimeBucketRate()
        self._processing_rate = _TimeBucketRate()
        self._input_frames_total = 0
        self._processed_frames_total = 0
        self._observable_lock = threading.Lock()
        self._latest_input_frame: Frame | None = None
        self._detector_scores: dict[ImageDetector, float] = {}
        self._detector_tree: DetectorTreeSnapshot | None = None

    def set_level(self, level: int) -> None:
        self._logger.setLevel(level)

    def bind_runtime(
        self,
        scenarios: tuple[Scenario, ...],
        frame_source: FrameSource,
    ) -> None:
        with self._context_lock:
            try:
                self._connections = {
                    scenario.connection: index
                    for index, scenario in enumerate(scenarios)
                }
            except Exception:  # noqa: BLE001
                self._connections = {}
            try:
                self._source_fields = _describe_source(frame_source)
            except Exception:  # noqa: BLE001
                self._source_fields = {"source_type": type(frame_source).__name__}
        with self._observable_lock:
            try:
                self._detector_tree = build_detector_tree(scenarios)
            except Exception:  # noqa: BLE001
                self._detector_tree = None

    def scenario_logger(
        self,
        scenario_index: int,
    ) -> logging.LoggerAdapter:
        connection = next(
            (
                item
                for item, index in self._connections.items()
                if index == scenario_index
            ),
            None,
        )
        fields: dict[str, object] = {"scenario_index": scenario_index}
        if connection is not None:
            fields.update(_connection_fields(connection))
        return _ScenarioLoggerAdapter(self._logger, fields)

    def usage_failed(self, message: str) -> None:
        self._emit(logging.ERROR, "cli.usage_failed", usage_detail=message)

    def configuration_failed(self, error: BaseException) -> None:
        self._emit_error(logging.ERROR, "cli.configuration_failed", error)

    def scenario_module_failed(self, error: BaseException) -> None:
        self._emit_error(logging.ERROR, "cli.scenario_module_failed", error)

    def startup_validation_failed(self, error: BaseException) -> None:
        self._emit_error(logging.ERROR, "cli.startup_validation_failed", error)

    def runtime_failed(self, error: BaseException) -> None:
        self._emit_error(logging.ERROR, "cli.runtime_failed", error)

    def interrupted(self) -> None:
        self._emit(logging.INFO, "cli.interrupted")

    def completed(self) -> None:
        self._emit(logging.INFO, "cli.completed")

    def preparing(self) -> None:
        self._emit(logging.INFO, "capture.preparing", **self._source_context())

    def prepared(self) -> None:
        self._emit(logging.INFO, "capture.prepared", **self._source_context())

    def frame_received(self, frame: Frame, publish_result: PublishResult) -> None:
        with self._metrics_lock:
            self._input_rate.record(frame.captured_at)
            self._input_frames_total += 1
        with self._observable_lock:
            self._latest_input_frame = frame
        self._emit(
            logging.DEBUG,
            "capture.frame_received",
            **self._source_context(),
            **_frame_fields(frame),
            publish_result=publish_result.name,
        )
        if publish_result is PublishResult.OVERWROTE:
            self._emit(
                logging.WARNING,
                "capture.frame_overwritten",
                **self._source_context(),
                **_frame_fields(frame),
            )

    def source_error(self, error: FrameSourceError) -> None:
        self._emit(
            logging.WARNING,
            "capture.source_error",
            **self._source_context(),
            error_type=type(error).__name__,
        )

    def error_handled(self, action: ErrorAction, state: FrameSourceState) -> None:
        self._emit(
            logging.WARNING,
            "capture.error_handled",
            **self._source_context(),
            action=action.name,
            source_state=state.name,
        )

    def source_state_changed(
        self,
        previous: FrameSourceState | None,
        current: FrameSourceState,
    ) -> None:
        self._emit(
            logging.INFO,
            "capture.source_state_changed",
            **self._source_context(),
            previous_state=None if previous is None else previous.name,
            current_state=current.name,
        )

    def source_state_unavailable(self, error: Exception) -> None:
        self._emit_error(
            logging.ERROR,
            "capture.source_state_unavailable",
            error,
            **self._source_context(),
        )

    def source_closed(self) -> None:
        self._emit(logging.INFO, "capture.source_closed", **self._source_context())

    def stopped(self) -> None:
        self._emit(logging.INFO, "capture.stopped", **self._source_context())

    def frame_processing_started(
        self,
        frame: Frame,
        processing_started_at: MonotonicTime,
    ) -> None:
        self._emit(
            logging.DEBUG,
            "processing.frame_started",
            **_frame_fields(frame),
            processing_started_at_ns=processing_started_at.nanoseconds,
            capture_to_processing_ns=(
                processing_started_at.nanoseconds - frame.captured_at.nanoseconds
            ),
        )

    def frame_processing_completed(self, context: FrameContext) -> None:
        completed_at = self._time_provider.now()
        with self._metrics_lock:
            self._processing_rate.record(completed_at)
            self._processed_frames_total += 1
        with self._observable_lock:
            self._record_detector_scores(context.detection_cache)
        fields: dict[str, object] = {
            **_frame_fields(context.frame),
            "processing_started_at_ns": context.now.nanoseconds,
            "processing_completed_at_ns": completed_at.nanoseconds,
            "processing_duration_ns": (
                completed_at.nanoseconds - context.now.nanoseconds
            ),
            "detector_count": len(context.detection_cache),
            "preprocessing_cache_entries": len(context.preprocessing_cache),
        }
        for index, (detector, result) in enumerate(context.detection_cache.items()):
            for name, value in _detector_fields(detector, result).items():
                fields[f"detector.{index}.{name}"] = value
        self._emit(logging.DEBUG, "processing.frame_completed", **fields)

    def take_latest_input_frame(self) -> Frame | None:
        """Return the newest captured input Frame and clear the slot.

        The slot only ever holds the latest reference; reading it consumes the
        value and has no effect on capture, processing, or metrics.
        """
        with self._observable_lock:
            frame = self._latest_input_frame
            self._latest_input_frame = None
            return frame

    def take_detector_scores(self) -> tuple[DetectorScore, ...]:
        """Return each detector's latest score and clear the pending values.

        A detector re-evaluated before a read keeps only its newest score.
        """
        with self._observable_lock:
            scores = tuple(
                DetectorScore(detector=detector, score=score)
                for detector, score in self._detector_scores.items()
            )
            self._detector_scores.clear()
            return scores

    def detector_tree(self) -> DetectorTreeSnapshot | None:
        """Return the immutable display tree built at runtime bind time."""
        with self._observable_lock:
            return self._detector_tree

    def runtime_started(self) -> None:
        self._emit(logging.INFO, "runtime.started")

    def _record_detector_scores(
        self,
        cache: Mapping[ImageDetector, DetectionResult],
    ) -> None:
        for detector, result in cache.items():
            self._detector_scores[detector] = result.score

    def metrics_snapshot(self) -> RuntimeMetricsSnapshot:
        """Copy current throughput metrics without consuming aggregation state."""

        with self._metrics_lock:
            sampled_at = self._time_provider.now()
            return RuntimeMetricsSnapshot(
                sampled_at=sampled_at,
                window_seconds=(_METRICS_WINDOW_NANOSECONDS / 1_000_000_000),
                input_fps=self._input_rate.rate(sampled_at),
                processing_fps=self._processing_rate.rate(sampled_at),
                input_frames_total=self._input_frames_total,
                processed_frames_total=self._processed_frames_total,
            )

    def runtime_fps(self, snapshot: RuntimeMetricsSnapshot) -> None:
        self._emit(
            logging.INFO,
            "runtime.fps",
            sampled_at_ns=snapshot.sampled_at.nanoseconds,
            window_seconds=snapshot.window_seconds,
            input_fps=snapshot.input_fps,
            processing_fps=snapshot.processing_fps,
            input_frames_total=snapshot.input_frames_total,
            processed_frames_total=snapshot.processed_frames_total,
        )

    def frame_normalization_failed(self, error: FrameNormalizationError) -> None:
        self._emit(
            logging.ERROR,
            "processing.frame_normalization_failed",
            error_type=type(error).__name__,
            error_message=error.message,
        )

    def scenario_evaluation_failed(
        self,
        scenario_index: int,
        error: Exception,
    ) -> None:
        self._emit_error(
            logging.ERROR,
            "processing.scenario_evaluation_failed",
            error,
            scenario_index=scenario_index,
        )

    def worker_started(self, connection: LiveSplitConnection) -> None:
        self._emit_connection(logging.INFO, "bridge.worker_started", connection)

    def initial_sync_failed(
        self,
        connection: LiveSplitConnection,
        error: Exception,
    ) -> None:
        self._emit_connection_error(
            logging.ERROR, "bridge.initial_sync_failed", connection, error
        )

    def connection_lost(
        self,
        connection: LiveSplitConnection,
        error: Exception,
    ) -> None:
        self._emit_connection(
            logging.WARNING,
            "bridge.connection_lost",
            connection,
            error_type=type(error).__name__,
        )

    def reconnect_failed(
        self,
        connection: LiveSplitConnection,
        error: Exception,
    ) -> None:
        self._emit_connection(
            logging.WARNING,
            "bridge.reconnect_failed",
            connection,
            error_type=type(error).__name__,
        )

    def update_queue_overflowed(self, connection: LiveSplitConnection) -> None:
        self._emit_connection(
            logging.WARNING, "bridge.update_queue_overflowed", connection
        )

    def action_submitted(
        self,
        connection: LiveSplitConnection,
        request: BridgeActionRequest,
        result: ActionSubmission,
    ) -> None:
        self._emit_connection(
            logging.DEBUG if result is ActionSubmission.ACCEPTED else logging.WARNING,
            "bridge.action_submitted",
            connection,
            action=request.action.operation,
            submission=result.name,
            **_snapshot_fields("expected", request.expected_snapshot),
        )

    def worker_stopped(self, connection: LiveSplitConnection) -> None:
        self._emit_connection(logging.INFO, "bridge.worker_stopped", connection)

    def snapshot_failed(
        self,
        connection: LiveSplitConnection,
        action: Action,
        error: Exception,
    ) -> None:
        self._emit_connection(
            logging.WARNING,
            "bridge.snapshot_failed",
            connection,
            action=action.operation,
            error_type=type(error).__name__,
        )

    def snapshot_mismatched(
        self,
        connection: LiveSplitConnection,
        action: Action,
        expected: LiveSplitSnapshot,
        actual: LiveSplitSnapshot,
    ) -> None:
        self._emit_connection(
            logging.WARNING,
            "bridge.snapshot_mismatched",
            connection,
            action=action.operation,
            mismatched_fields=_snapshot_mismatches(expected, actual),
            **_snapshot_fields("expected", expected),
            **_snapshot_fields("actual", actual),
        )

    def action_precondition_failed(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None:
        self._emit_connection(
            logging.WARNING,
            "bridge.action_precondition_failed",
            connection,
            action=action.operation,
            required_state=_action_precondition(action),
            **_snapshot_fields("snapshot", snapshot),
        )

    def action_succeeded(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None:
        self._emit_connection(
            logging.INFO,
            "bridge.action_succeeded",
            connection,
            action=action.operation,
            **_snapshot_fields("snapshot", snapshot),
        )

    def action_rejected(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
        code: int | None,
        message: str,
    ) -> None:
        self._emit_connection(
            logging.WARNING,
            "bridge.action_rejected",
            connection,
            action=action.operation,
            rejection_code=code,
            rejection_message=_sanitize_text(message),
            **_snapshot_fields("snapshot", snapshot),
        )

    def action_result_unknown(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
        error: Exception,
    ) -> None:
        self._emit_connection_error(
            logging.ERROR,
            "bridge.action_result_unknown",
            connection,
            error,
            action=action.operation,
            **_snapshot_fields("snapshot", snapshot),
        )

    def gap_detected(
        self,
        connection: LiveSplitConnection,
        baseline: LiveSplitSnapshot,
        received_session_id: int,
        received_event_sequence: int,
    ) -> None:
        self._emit_connection(
            logging.WARNING,
            "bridge.gap_detected",
            connection,
            **_snapshot_fields("baseline", baseline),
            received_session_id=received_session_id,
            received_event_sequence=received_event_sequence,
        )

    def heartbeat_received(
        self,
        connection: LiveSplitConnection,
        session_id: int,
        event_sequence: int,
    ) -> None:
        self._emit_connection(
            logging.DEBUG,
            "bridge.heartbeat_received",
            connection,
            session_id=session_id,
            event_sequence=event_sequence,
        )

    def resync_started(
        self,
        connection: LiveSplitConnection,
        reason: LiveSplitResyncReason,
    ) -> None:
        self._emit_connection(
            logging.INFO,
            "bridge.resync_started",
            connection,
            reason=reason.name,
        )

    def resync_completed(
        self,
        connection: LiveSplitConnection,
        reason: LiveSplitResyncReason,
        previous: LiveSplitSnapshot,
        current: LiveSplitSnapshot,
    ) -> None:
        self._emit_connection(
            logging.INFO,
            "bridge.resync_completed",
            connection,
            reason=reason.name,
            **_snapshot_fields("previous", previous),
            **_snapshot_fields("current", current),
        )

    def _source_context(self) -> dict[str, object]:
        with self._context_lock:
            return dict(self._source_fields)

    def _connection_context(
        self,
        connection: LiveSplitConnection,
    ) -> dict[str, object]:
        with self._context_lock:
            scenario_index = self._connections.get(connection)
        return {
            "scenario_index": scenario_index,
            **_connection_fields(connection),
        }

    def _emit_connection(
        self,
        level: int,
        event_name: str,
        connection: LiveSplitConnection,
        **fields: object,
    ) -> None:
        self._emit(
            level,
            event_name,
            **self._connection_context(connection),
            **fields,
        )

    def _emit_connection_error(
        self,
        level: int,
        event_name: str,
        connection: LiveSplitConnection,
        error: BaseException,
        **fields: object,
    ) -> None:
        self._emit_error(
            level,
            event_name,
            error,
            **self._connection_context(connection),
            **fields,
        )

    def _emit_error(
        self,
        level: int,
        event_name: str,
        error: BaseException,
        **fields: object,
    ) -> None:
        fields.update(_exception_fields(error))
        self._emit(level, event_name, **fields)

    def _emit(self, level: int, event_name: str, **fields: object) -> None:
        try:
            self._logger.log(
                level,
                event_name,
                extra={"event_name": event_name, **fields},
            )
        except Exception:  # noqa: BLE001
            return


class _TimeBucketRate:
    """Count events in a fixed-memory approximation of the latest time window."""

    def __init__(self) -> None:
        self._bucket_ids = [-1] * _METRICS_BUCKET_COUNT
        self._counts = [0] * _METRICS_BUCKET_COUNT

    def record(self, occurred_at: MonotonicTime) -> None:
        bucket_id = occurred_at.nanoseconds // _METRICS_BUCKET_NANOSECONDS
        index = bucket_id % _METRICS_BUCKET_COUNT
        if self._bucket_ids[index] != bucket_id:
            self._bucket_ids[index] = bucket_id
            self._counts[index] = 0
        self._counts[index] += 1

    def rate(self, sampled_at: MonotonicTime) -> float:
        cutoff = sampled_at.nanoseconds - _METRICS_WINDOW_NANOSECONDS
        oldest_bucket_id = cutoff // _METRICS_BUCKET_NANOSECONDS
        newest_bucket_id = sampled_at.nanoseconds // _METRICS_BUCKET_NANOSECONDS
        oldest_overlap = (
            (oldest_bucket_id + 1) * _METRICS_BUCKET_NANOSECONDS - cutoff
        ) / _METRICS_BUCKET_NANOSECONDS
        count = 0.0
        for bucket_id, bucket_count in zip(
            self._bucket_ids,
            self._counts,
            strict=True,
        ):
            if not oldest_bucket_id <= bucket_id <= newest_bucket_id:
                continue
            weight = oldest_overlap if bucket_id == oldest_bucket_id else 1.0
            count += bucket_count * weight
        return count / (_METRICS_WINDOW_NANOSECONDS / 1_000_000_000)


def _frame_fields(frame: Frame) -> dict[str, object]:
    return {
        "captured_at_ns": frame.captured_at.nanoseconds,
        "frame_shape": tuple(int(value) for value in frame.image.shape),
        "frame_dtype": str(frame.image.dtype),
    }


def _snapshot_fields(prefix: str, snapshot: LiveSplitSnapshot) -> dict[str, object]:
    return {
        f"{prefix}.session_id": snapshot.session_id,
        f"{prefix}.state_revision": snapshot.state_revision,
        f"{prefix}.event_sequence": snapshot.event_sequence,
        f"{prefix}.phase": snapshot.phase.name,
        f"{prefix}.split_index": snapshot.split_index,
        f"{prefix}.split_count": snapshot.split_count,
    }


def _connection_fields(connection: LiveSplitConnection) -> dict[str, object]:
    return {
        "rpc_endpoint": _sanitize_endpoint(connection.rpc_endpoint),
        "event_endpoint": _sanitize_endpoint(connection.event_endpoint),
    }


def _sanitize_endpoint(endpoint: str) -> str:
    try:
        parsed = urlsplit(endpoint)
        if parsed.hostname is None or parsed.username is None:
            return endpoint
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        return urlunsplit(
            (parsed.scheme, host, parsed.path, parsed.query, parsed.fragment)
        )
    except Exception:  # noqa: BLE001
        return re.sub(r"(?<=://)[^/@\s]+@", "", endpoint)


def _sanitize_text(value: str) -> str:
    return re.sub(
        r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@", r"\g<scheme>", value
    )


def _describe_source(source: FrameSource) -> dict[str, object]:
    fields: dict[str, object] = {"source_type": type(source).__name__}
    if isinstance(source, VideoFileSource):
        fields["source_path"] = str(Path(source.path))
    elif isinstance(source, OpenCvCameraSource):
        fields.update(
            source_device_index=source.device_index,
            source_backend=source.backend,
            source_width=source.width,
            source_height=source.height,
            source_requested_fps=source.fps,
        )
    normalizer = source.normalizer
    clip = normalizer.clip_region
    output = normalizer.output_size
    if clip is not None:
        fields.update(
            clip_x=clip.x,
            clip_y=clip.y,
            clip_width=clip.width,
            clip_height=clip.height,
        )
    if output is not None:
        fields.update(output_width=output.width, output_height=output.height)
    return fields


def _safe_config(config: object) -> dict[str, object]:
    try:
        if isinstance(config, ColorRangeConfig):
            return {
                "type": type(config).__name__,
                "lower": config.lower,
                "upper": config.upper,
            }
        if isinstance(config, DifferenceHashSimilarityConfig):
            return {
                "type": type(config).__name__,
                "reference_shape": _nested_shape(config.reference),
                "hash_size": config.hash_size,
            }
        if isinstance(
            config,
            (
                MeanAbsoluteSimilarityConfig,
                PhaseCorrelationConfig,
                TemplateMatchConfig,
            ),
        ):
            return {
                "type": type(config).__name__,
                "reference_shape": _nested_shape(config.reference),
            }
        return {"type": type(config).__name__}
    except Exception:  # noqa: BLE001
        return {"type": type(config).__name__}


def _detector_fields(detector: object, result: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "type": type(detector).__name__,
        "score": result.score if isinstance(result, DetectionResult) else None,
    }
    try:
        config = getattr(detector, "config", None)
    except Exception:  # noqa: BLE001
        config = None
    if isinstance(
        config,
        (
            ColorRangeConfig,
            DifferenceHashSimilarityConfig,
            MeanAbsoluteSimilarityConfig,
            PhaseCorrelationConfig,
            TemplateMatchConfig,
        ),
    ):
        fields["config"] = _safe_config(config)
    elif config is not None:
        fields["config_type"] = type(config).__name__
    return fields


def _snapshot_mismatches(
    expected: LiveSplitSnapshot,
    actual: LiveSplitSnapshot,
) -> tuple[str, ...]:
    names = ("session_id", "state_revision", "phase", "split_index", "split_count")
    return tuple(
        name for name in names if getattr(expected, name) != getattr(actual, name)
    )


def _action_precondition(action: Action) -> str:
    return {
        "split": "phase=RUNNING",
        "skip": "phase=RUNNING and split_index<split_count-1",
        "undo": "phase=ENDED or completed_split_exists",
        "reset": "phase in RUNNING,PAUSED,ENDED",
        "pause": "phase=RUNNING",
        "resume": "phase=PAUSED",
    }.get(action.operation, "known_action_operation")


def _nested_shape(value: object) -> tuple[int, ...]:
    dimensions: list[int] = []
    current = value
    while isinstance(current, (tuple, list)):
        dimensions.append(len(current))
        if not current:
            break
        current = current[0]
    return tuple(dimensions)


def _exception_fields(error: BaseException) -> dict[str, object]:
    leaves = _leaf_exceptions(error)
    if len(leaves) == 1 and leaves[0] is error:
        return {
            "exception_type": type(error).__name__,
            "exception_message": _safe_string(error),
            "exception_traceback": _safe_traceback(error),
        }
    fields: dict[str, object] = {
        "exception_type": type(error).__name__,
        "exception_message": _safe_string(error),
        "exception_count": len(leaves),
    }
    for index, leaf in enumerate(leaves):
        fields[f"exception.{index}.type"] = type(leaf).__name__
        fields[f"exception.{index}.message"] = _safe_string(leaf)
        fields[f"exception.{index}.traceback"] = _safe_traceback(leaf)
    return fields


def _exception_pairs(error: BaseException) -> list[str]:
    return [
        f"{key}={_format_value(value)}"
        for key, value in _exception_fields(error).items()
    ]


def _leaf_exceptions(error: BaseException) -> list[BaseException]:
    if not isinstance(error, BaseExceptionGroup):
        return [error]
    leaves: list[BaseException] = []
    for nested in error.exceptions:
        leaves.extend(_leaf_exceptions(nested))
    return leaves


def _safe_string(value: object) -> str:
    try:
        return _sanitize_text(str(value))
    except Exception:  # noqa: BLE001
        return f"<{type(value).__name__} could not be formatted>"


def _safe_traceback(error: BaseException) -> str:
    try:
        return _sanitize_text("".join(traceback.format_exception(error)))
    except Exception:  # noqa: BLE001
        return f"<{type(error).__name__} traceback could not be formatted>"


def _format_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, tuple):
        return "[" + ",".join(_format_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(f"{key}:{_format_value(item)}" for key, item in value.items())
            + "}"
        )
    return json.dumps(type(value).__name__)
