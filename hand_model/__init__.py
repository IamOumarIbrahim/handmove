"""3D model of the Hiwonder uHand UNO (right hand) for the HANDMOVE GUI."""

def opengl_available() -> str:
    """Return "" if the OpenGL viewport can be used, else the reason it can't."""
    try:
        import numpy  # noqa: F401
        from OpenGL import GL  # noqa: F401
        import pyopengltk  # noqa: F401
    except Exception as exc:  # ImportError, or OpenGL failing to load a driver
        return f"{type(exc).__name__}: {exc}"
    return ""
