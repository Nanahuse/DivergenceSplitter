class Not:
    def apply(self, value: bool) -> bool:
        if type(value) is not bool:
            raise TypeError(f"value must be a strict bool, got {value!r}")
        return not value
