"""EEG -> HANDMOVE bridge: device-agnostic sources, decoding, and hand mapping."""
from .sources import (BrainFlowSource, Chunk, EEGSource, FINGER_LABELS, LSLSource, ReplaySource,
                      SourceInfo, SyntheticSource, load_kaya_mat, load_recording, save_recording)
from .decoder import FingerDecoder, Preprocessor, train_from_recording
from .mapper import DEFAULT_POSES, IntentMapper
from .bridge import EEGBridge, UDPCommandListener
