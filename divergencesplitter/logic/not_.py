"""Not: logical negation of a boolean input."""


class Not:
    """True when the single input is ``False``.

    ``value`` must be a strict ``bool``; any other type raises
    :class:`TypeError`.
    """

    def apply(self, value: bool) -> bool:
        if type(value) is not bool:
            raise TypeError(f"value must be a strict bool, got {value!r}")
        return not value
