"""Small demo: create a sine wave array and write WAV using wav_utils."""
from math import sin, pi

import numpy as np

from wav_utils import float_array_to_wav


def make_sine(freq=440.0, sr=44100, dur=1.0):
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    return 0.5 * np.sin(2 * pi * freq * t)


if __name__ == "__main__":
    s = make_sine(440.0, sr=44100, dur=2.0)
    float_array_to_wav(s, 44100, "example_sine.wav", bit_depth=16)
    print("Wrote example_sine.wav")
