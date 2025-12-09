# blt_biquad.py
import re
import numpy as np


FILTER_TYPES = [
    'lowpass', 'highpass',
    'bandpass_csg', 'bandpass_czpg',
    'notch', 'allpass',
    'peaking', 'lowshelf', 'highshelf'
]


def _constrain(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else (hi if x > hi else x)


def rbj_biquad(filter_type: str, fs: float, f0: float, Q: float = 1.0, gain_db: float = 0.0):
    """
    Biquad coefficients matching the provided C implementation.
    Returns normalized (b, a) with a[0] == 1.
    """
    f0 = max(0.1, float(f0))
    fs = float(fs)
    Q = float(Q)

    w0 = 2.0 * np.pi * f0 / fs
    cosw0 = np.cos(w0)
    sinw0 = np.sin(w0)

    A = 10.0 ** (gain_db / 40.0)

    # s_max = 1/(1-2/(A+1/A)) - 0.001
    denom = (1.0 - 2.0 / (A + 1.0 / A))
    if abs(denom) < 1e-12:
        s_max = 1e6
    else:
        s_max = 1.0 / denom - 0.001

    # alpha
    if filter_type in ('lowshelf', 'highshelf'):
        Q = _constrain(Q, 0.001, s_max)
        inside = (A + 1.0 / A) * (1.0 / Q - 1.0) + 2.0
        inside = max(0.0, inside)
        alpha = (sinw0 / 2.0) * np.sqrt(inside)
    else:
        alpha = sinw0 / (2.0 * max(Q, 1e-6))

    if filter_type == 'lowpass':
        b0 = (1.0 - cosw0) / 2.0
        b1 = 1.0 - cosw0
        b2 = (1.0 - cosw0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cosw0
        a2 = 1.0 - alpha

    elif filter_type == 'highpass':
        b0 = (1.0 + cosw0) / 2.0
        b1 = -(1.0 + cosw0)
        b2 = (1.0 + cosw0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cosw0
        a2 = 1.0 - alpha

    elif filter_type == 'bandpass_csg':  # constant skirt gain
        b0 = sinw0 / 2.0
        b1 = 0.0
        b2 = -sinw0 / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cosw0
        a2 = 1.0 - alpha

    elif filter_type == 'bandpass_czpg':  # constant 0 dB peak gain
        b0 = alpha
        b1 = 0.0
        b2 = -alpha
        a0 = 1.0 + alpha
        a1 = -2.0 * cosw0
        a2 = 1.0 - alpha

    elif filter_type == 'notch':
        b0 = 1.0
        b1 = -2.0 * cosw0
        b2 = 1.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cosw0
        a2 = 1.0 - alpha

    elif filter_type == 'allpass':
        b0 = 1.0 - alpha
        b1 = -2.0 * cosw0
        b2 = 1.0 + alpha
        a0 = 1.0 + alpha
        a1 = -2.0 * cosw0
        a2 = 1.0 - alpha

    elif filter_type == 'peaking':
        b0 = 1.0 + alpha * A
        b1 = -2.0 * cosw0
        b2 = 1.0 - alpha * A
        a0 = 1.0 + alpha / A
        a1 = -2.0 * cosw0
        a2 = 1.0 - alpha / A

    elif filter_type == 'lowshelf':
        sqrtA = np.sqrt(A)
        b0 = A * ((A + 1.0) - (A - 1.0) * cosw0 + 2.0 * sqrtA * alpha)
        b1 = 2.0 * A * ((A - 1.0) - (A + 1.0) * cosw0)
        b2 = A * ((A + 1.0) - (A - 1.0) * cosw0 - 2.0 * sqrtA * alpha)
        a0 = (A + 1.0) + (A - 1.0) * cosw0 + 2.0 * sqrtA * alpha
        a1 = -2.0 * ((A - 1.0) + (A + 1.0) * cosw0)
        a2 = (A + 1.0) + (A - 1.0) * cosw0 - 2.0 * sqrtA * alpha

    elif filter_type == 'highshelf':
        sqrtA = np.sqrt(A)
        b0 = A * ((A + 1.0) + (A - 1.0) * cosw0 + 2.0 * sqrtA * alpha)
        b1 = -2.0 * A * ((A - 1.0) + (A + 1.0) * cosw0)
        b2 = A * ((A + 1.0) + (A - 1.0) * cosw0 - 2.0 * sqrtA * alpha)
        a0 = (A + 1.0) - (A - 1.0) * cosw0 + 2.0 * sqrtA * alpha
        a1 = 2.0 * ((A - 1.0) - (A + 1.0) * cosw0)
        a2 = (A + 1.0) - (A - 1.0) * cosw0 - 2.0 * sqrtA * alpha

    else:
        raise ValueError(f"Unknown filter type: {filter_type}")

    inv_a0 = 1.0 / a0
    b = np.array([b0, b1, b2], dtype=float) * inv_a0
    a = np.array([1.0, a1 * inv_a0, a2 * inv_a0], dtype=float)
    return b, a


def apply_biquad_df2t(x: np.ndarray, b: np.ndarray, a: np.ndarray) -> np.ndarray:
    """Direct Form II Transposed biquad. a[0] must be 1."""
    x = np.asarray(x, dtype=float)
    y = np.empty_like(x)

    b0, b1, b2 = float(b[0]), float(b[1]), float(b[2])
    a1, a2 = float(a[1]), float(a[2])

    z1 = 0.0
    z2 = 0.0
    for i in range(x.size):
        xn = float(x[i])
        yn = b0 * xn + z1
        z1 = b1 * xn - a1 * yn + z2
        z2 = b2 * xn - a2 * yn
        y[i] = yn
    return y


def parse_numbers(text: str) -> np.ndarray:
    """Extract floats from C/CSV/space/newline formatted text (supports scientific notation)."""
    text = text.replace('{', ' ').replace('}', ' ').replace(';', ' ')
    pattern = r'[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?'
    nums = re.findall(pattern, text)
    if not nums:
        return np.array([], dtype=float)
    return np.array([float(s) for s in nums], dtype=float)


def format_c_array(arr: np.ndarray, per_line: int = 8) -> str:
    """C style array, N floats per line, comma-separated."""
    if arr.size == 0:
        return "{\n};"
    nums = [f"{float(v):.8g}" for v in arr]
    lines = []
    for i in range(0, len(nums), per_line):
        chunk = nums[i:i + per_line]
        trailing = "," if (i + per_line) < len(nums) else ""
        lines.append("  " + ", ".join(chunk) + trailing)
    return "{\n" + "\n".join(lines) + "\n};"
