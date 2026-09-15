"""Shared frame evaluation and single-flight cache contracts."""

import threading
import unittest

import numpy as np
from divergencesplitter.clock import MonotonicTime
from divergencesplitter.detector.common import evaluate, preprocessed
from divergencesplitter.detector.models import DetectionResult, ReferenceImage
from divergencesplitter.frame.cache import RecursiveFrameComputationError
from divergencesplitter.frame.models import (
    Frame,
    FrameContext,
    SharedFrameEvaluation,
)

EPOCH = MonotonicTime(0)


def make_shared(now: MonotonicTime = EPOCH) -> SharedFrameEvaluation:
    image = np.zeros((2, 2), dtype=np.uint8)
    return SharedFrameEvaluation(frame=Frame(image=image, captured_at=now), now=now)


class CountingDetector:
    """All instances are equivalent but count their own detections."""

    def __init__(self, calls: list[int]) -> None:
        self._calls = calls

    @property
    def reference_images(self) -> tuple[ReferenceImage, ...]:
        return ()

    def detect(self, context: FrameContext) -> DetectionResult:
        self._calls.append(1)
        return DetectionResult(score=0.5)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CountingDetector)

    def __hash__(self) -> int:
        return hash("CountingDetector")


class BlockingDetector:
    """Equivalent detectors whose first evaluation blocks until released."""

    def __init__(
        self,
        calls: list[int],
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        self._calls = calls
        self._entered = entered
        self._release = release

    @property
    def reference_images(self) -> tuple[ReferenceImage, ...]:
        return ()

    def detect(self, context: FrameContext) -> DetectionResult:
        self._calls.append(1)
        self._entered.set()
        if not self._release.wait(5):
            raise TimeoutError("test did not release blocking detector")
        return DetectionResult(score=0.75)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, BlockingDetector)

    def __hash__(self) -> int:
        return hash("BlockingDetector")


class FlakyDetector:
    def __init__(self) -> None:
        self.attempts = 0

    @property
    def reference_images(self) -> tuple[ReferenceImage, ...]:
        return ()

    def detect(self, context: FrameContext) -> DetectionResult:
        self.attempts += 1
        if self.attempts == 1:
            raise ValueError("boom")
        return DetectionResult(score=0.25)


class SharedFrameEvaluationTest(unittest.TestCase):
    def test_contexts_from_same_shared_evaluation_share_frame_and_now(self) -> None:
        shared = make_shared()
        first = FrameContext(shared=shared)
        second = FrameContext(shared=shared)

        self.assertIs(first.shared, shared)
        self.assertIs(second.shared, shared)
        self.assertIs(first.frame, second.frame)
        self.assertEqual(first.now, second.now)

    def test_contexts_have_independent_evaluated_condition_ids(self) -> None:
        shared = make_shared()
        first = FrameContext(shared=shared)
        second = FrameContext(shared=shared)

        first.evaluated_condition_ids.add(1)

        self.assertEqual(first.evaluated_condition_ids, {1})
        self.assertEqual(second.evaluated_condition_ids, set())

    def test_standalone_context_builds_its_own_shared_evaluation(self) -> None:
        frame = Frame(image=np.zeros((2, 2), dtype=np.uint8), captured_at=EPOCH)
        first = FrameContext(frame=frame, now=EPOCH)
        second = FrameContext(frame=frame, now=EPOCH)

        self.assertIs(first.frame, frame)
        self.assertEqual(first.now, EPOCH)
        self.assertIsNot(first.shared, second.shared)
        self.assertIsNot(first.shared.cache, second.shared.cache)

    def test_positional_arguments_remain_supported(self) -> None:
        frame = Frame(image=np.zeros((2, 2), dtype=np.uint8), captured_at=EPOCH)

        context = FrameContext(frame, EPOCH)

        self.assertIs(context.frame, frame)
        self.assertEqual(context.now, EPOCH)

    def test_context_requires_frame_and_now_or_shared(self) -> None:
        with self.assertRaises(TypeError):
            FrameContext()
        with self.assertRaises(TypeError):
            FrameContext(frame=Frame(np.zeros((1, 1), dtype=np.uint8), EPOCH))

    def test_explicit_evaluated_condition_ids_are_preserved(self) -> None:
        shared = make_shared()
        context = FrameContext(shared=shared, evaluated_condition_ids={2, 3})

        self.assertEqual(context.evaluated_condition_ids, {2, 3})


class PreprocessingCacheTest(unittest.TestCase):
    def test_preprocessing_is_shared_across_contexts(self) -> None:
        shared = make_shared()
        first = FrameContext(shared=shared)
        second = FrameContext(shared=shared)
        calls: list[int] = []

        def compute() -> int:
            calls.append(1)
            return 42

        self.assertEqual(preprocessed(first, "key", compute), 42)
        self.assertEqual(preprocessed(second, "key", compute), 42)
        self.assertEqual(len(calls), 1)

    def test_preprocessing_is_not_shared_across_frames(self) -> None:
        first = FrameContext(shared=make_shared())
        second = FrameContext(shared=make_shared())
        calls: list[int] = []

        def compute() -> int:
            calls.append(1)
            return 42

        preprocessed(first, "key", compute)
        preprocessed(second, "key", compute)
        self.assertEqual(len(calls), 2)

    def test_none_is_a_cached_preprocessing_value(self) -> None:
        context = FrameContext(shared=make_shared())
        calls: list[int] = []

        def compute() -> None:
            calls.append(1)

        self.assertIsNone(preprocessed(context, "key", compute))
        self.assertIsNone(preprocessed(context, "key", compute))
        self.assertEqual(len(calls), 1)

    def test_seeded_preprocessing_is_reused_without_computing(self) -> None:
        context = FrameContext(shared=make_shared())
        context.cache.store_preprocessing("key", None)
        calls: list[int] = []

        def compute() -> str:
            calls.append(1)
            return "value"

        self.assertIsNone(preprocessed(context, "key", compute))
        self.assertEqual(calls, [])


class DetectionCacheTest(unittest.TestCase):
    def test_equivalent_detectors_share_across_contexts(self) -> None:
        shared = make_shared()
        first = FrameContext(shared=shared)
        second = FrameContext(shared=shared)
        first_calls: list[int] = []
        second_calls: list[int] = []

        first_result = evaluate(first, CountingDetector(first_calls))
        second_result = evaluate(second, CountingDetector(second_calls))

        self.assertEqual(first_result, second_result)
        self.assertEqual(len(first_calls), 1)
        self.assertEqual(second_calls, [])

    def test_detection_is_not_shared_across_frames(self) -> None:
        first = FrameContext(shared=make_shared())
        second = FrameContext(shared=make_shared())
        first_calls: list[int] = []
        second_calls: list[int] = []

        evaluate(first, CountingDetector(first_calls))
        evaluate(second, CountingDetector(second_calls))

        self.assertEqual(len(first_calls), 1)
        self.assertEqual(len(second_calls), 1)


class SingleFlightConcurrencyTest(unittest.TestCase):
    def test_same_preprocessing_key_is_computed_once(self) -> None:
        context = FrameContext(shared=make_shared())
        barrier = threading.Barrier(2)
        release = threading.Event()
        entered = threading.Event()
        calls: list[int] = []
        results: list[int] = []

        def compute() -> int:
            calls.append(1)
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test did not release preprocessing")
            return 42

        def worker() -> None:
            barrier.wait()
            results.append(preprocessed(context, "key", compute))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        self.assertTrue(entered.wait(5))
        release.set()
        for thread in threads:
            thread.join(5)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(calls, [1])
        self.assertEqual(sorted(results), [42, 42])

    def test_same_detector_is_evaluated_once(self) -> None:
        context = FrameContext(shared=make_shared())
        barrier = threading.Barrier(2)
        release = threading.Event()
        entered = threading.Event()
        calls: list[int] = []
        results: list[DetectionResult] = []

        def worker() -> None:
            detector = BlockingDetector(calls, entered, release)
            barrier.wait()
            results.append(evaluate(context, detector))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        self.assertTrue(entered.wait(5))
        release.set()
        for thread in threads:
            thread.join(5)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(calls, [1])
        self.assertEqual([result.score for result in results], [0.75, 0.75])

    def test_different_keys_are_not_serialized(self) -> None:
        context = FrameContext(shared=make_shared())
        release = threading.Event()
        entered = threading.Event()
        slow_results: list[str] = []

        def slow_compute() -> str:
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test did not release slow preprocessing")
            return "slow"

        def slow_worker() -> None:
            slow_results.append(preprocessed(context, "slow", slow_compute))

        slow = threading.Thread(target=slow_worker)
        slow.start()
        self.assertTrue(entered.wait(5))

        # A different key must complete while "slow" is still in flight.
        self.assertEqual(preprocessed(context, "fast", lambda: "fast"), "fast")

        release.set()
        slow.join(5)
        self.assertFalse(slow.is_alive())
        self.assertEqual(slow_results, ["slow"])


class NestedPreprocessingTest(unittest.TestCase):
    def test_nested_different_key_does_not_deadlock(self) -> None:
        context = FrameContext(shared=make_shared())

        def outer() -> str:
            inner = preprocessed(context, "inner", lambda: "inner-value")
            return f"outer:{inner}"

        self.assertEqual(preprocessed(context, "outer", outer), "outer:inner-value")
        self.assertEqual(
            preprocessed(context, "inner", lambda: "unused"), "inner-value"
        )

    def test_same_key_self_recursion_is_rejected(self) -> None:
        context = FrameContext(shared=make_shared())

        def recursive() -> object:
            return preprocessed(context, "key", recursive)

        with self.assertRaises(RecursiveFrameComputationError):
            preprocessed(context, "key", recursive)

        # The failed entry is released, so a later request succeeds.
        self.assertEqual(preprocessed(context, "key", lambda: "recovered"), "recovered")


class FailureHandlingTest(unittest.TestCase):
    def test_preprocessing_failure_releases_waiters_and_is_not_cached(self) -> None:
        context = FrameContext(shared=make_shared())
        barrier = threading.Barrier(2)
        release = threading.Event()
        entered = threading.Event()
        calls: list[int] = []
        errors: list[ValueError] = []

        def compute() -> int:
            calls.append(1)
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test did not release failing compute")
            raise ValueError("boom")

        def worker() -> None:
            barrier.wait()
            try:
                preprocessed(context, "key", compute)
            except ValueError as error:
                errors.append(error)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        self.assertTrue(entered.wait(5))
        release.set()
        for thread in threads:
            thread.join(5)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(errors), 2)
        self.assertGreaterEqual(len(calls), 1)

        recovery_calls: list[int] = []

        def recover() -> int:
            recovery_calls.append(1)
            return 7

        self.assertEqual(preprocessed(context, "key", recover), 7)
        self.assertEqual(len(recovery_calls), 1)

    def test_detector_failure_is_not_cached_and_can_be_retried(self) -> None:
        context = FrameContext(shared=make_shared())
        detector = FlakyDetector()

        with self.assertRaises(ValueError):
            evaluate(context, detector)

        self.assertEqual(evaluate(context, detector).score, 0.25)
        self.assertEqual(evaluate(context, detector).score, 0.25)
        self.assertEqual(detector.attempts, 2)


if __name__ == "__main__":
    unittest.main()
