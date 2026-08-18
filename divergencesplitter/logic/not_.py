"""Not: logical negation of a boolean input."""


class Not:
    """True when the single input is ``False``."""

    def apply(self, value: bool) -> bool:
        return not value
