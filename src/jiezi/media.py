"""核心、TTS、ASR 輪流使用 GPU（add-tts、add-asr）。 / GPU turn-taking between the core, TTS and ASR.

規則：
- `sup.media_lock`：TTS 與 ASR 共用一把鎖，同一時間只有一個語音工作在跑（兩把鎖互相等待會卡死）。
- `sup.gpu_owner`：None（核心或閒置）、"tts"、"asr"。`sup.gpu_stoppers[名稱]` 是讓該方停止並釋放 GPU 的函式。
- 語音工作（持有 media_lock 時）呼叫 `take_gpu`：先停掉另一個語音行程，再等核心沒有進行中的請求、卸載核心。
- 聊天：Supervisor.acquire 在拿自己的鎖之前，先取得 media_lock 停掉目前的語音行程。
Media jobs share one lock; the core waits for it and evicts the media worker before loading."""

from __future__ import annotations

import time

import anyio

WAIT_CORE_S = 120


class GpuBusy(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


async def take_gpu(sup, name: str, log=print, wait_s: float | None = None) -> None:
    """呼叫者必須持有 sup.media_lock。 / The caller must hold sup.media_lock."""
    other = sup.gpu_owner
    if other and other != name and other in sup.gpu_stoppers:
        log(f"{name}: stopping {other} to take the GPU")
        await anyio.to_thread.run_sync(sup.gpu_stoppers[other])
        sup.gpu_owner = None
    if sup.gpu_owner == name:
        return
    deadline = time.monotonic() + (WAIT_CORE_S if wait_s is None else wait_s)
    while True:
        if sup.status == "held":
            raise GpuBusy("gpu_held", "the GPU is reserved for a night evaluation; try again later")
        async with sup._lock:
            if sup.in_flight == 0:
                if sup.status == "loaded":
                    log(f"{name}: unloading the core to take the GPU")
                    sup._stop("unloaded")
                    sup.write_state()
                sup.gpu_owner = name
                return
        if time.monotonic() > deadline:
            raise GpuBusy("gpu_busy", "the local model is busy answering; try again shortly")
        await anyio.sleep(0.5)


async def release_for_core(sup) -> None:
    """核心要載入：停掉目前占用 GPU 的語音行程（等它手上的工作做完）。 / Evict the media worker for the core."""
    while sup.gpu_owner and sup.gpu_owner in sup.gpu_stoppers:
        async with sup.media_lock:
            owner = sup.gpu_owner
            if owner and owner in sup.gpu_stoppers:
                await anyio.to_thread.run_sync(sup.gpu_stoppers[owner])
            sup.gpu_owner = None
