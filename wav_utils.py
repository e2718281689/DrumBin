import re
from typing import Iterable

import numpy as np
import soundfile as sf


def parse_float_array(text: str) -> np.ndarray:
    """从任意文本中提取浮点数字，返回 numpy float32 一维数组。

    支持 Python 列表、C 风格数组、以及纯数值序列（使用逗号或空白分隔）。
    """
    # 匹配浮点或整数，包括科学计数法
    nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)
    if not nums:
        return np.array([], dtype=np.float32)
    arr = np.array([float(n) for n in nums], dtype=np.float32)
    return arr


def float_array_to_wav(
    samples: Iterable[float],
    sr: int,
    out_path: str,
    bit_depth: int = 16,
):
    """将一维浮点数组保存为 PCM WAV 文件。

    - `samples` 可以是可迭代的浮点数（或 numpy 数组），值范围不限，函数会在写入前进行裁剪。
    - `sr` 采样率。
    - `out_path` 输出文件路径（应以 .wav 结尾）。
    - `bit_depth` 支持 16, 24, 32（以 PCM 编码写入）。
    """
    arr = np.asarray(list(samples), dtype=np.float32)
    if arr.ndim != 1:
        raise ValueError("Only 1-D arrays are supported")

    # 裁剪到 [-1.0, 1.0]
    arr = np.clip(arr, -1.0, 1.0)

    subtype = {
        16: "PCM_16",
        24: "PCM_24",
        32: "PCM_32",
    }.get(bit_depth)
    if subtype is None:
        raise ValueError("Unsupported bit depth: choose 16, 24 or 32")

    sf.write(out_path, arr, sr, subtype=subtype)
