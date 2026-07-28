"""Side-effect-free fixture handler used only by driver unit tests."""


def _test_echo(**inputs):
    return inputs
