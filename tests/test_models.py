import unittest
from datetime import datetime

import numpy as np

from divergencesplitter.models import Frame, FrameContext


class FrameContextTest(unittest.TestCase):
    def test_naive_datetime_rejected(self):
        naive = datetime(2024, 1, 1)  # noqa: DTZ001
        with self.assertRaises(ValueError):
            FrameContext(frame=Frame(image=np.zeros((2, 2))), now=naive)


if __name__ == "__main__":
    unittest.main()
