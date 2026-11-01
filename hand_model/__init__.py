# 3D model of the hiwonder uHand UNO (right hand) for the HANDMOVE gui


# gives "" if the opengl view can be used, if not it gives the reason
def opengl_available():
    try:
        import numpy  # noqa: F401
        from OpenGL import GL  # noqa: F401
        import pyopengltk  # noqa: F401
    except Exception as exc:
        # ImportError or opengl cant load a driver
        return f"{type(exc).__name__}: {exc}"
    return ""
