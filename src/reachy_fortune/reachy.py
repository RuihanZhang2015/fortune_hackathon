from __future__ import annotations

import math
import subprocess
import sys
import threading
import time
from dataclasses import dataclass


@dataclass
class ReachyController:
    """Small adapter around Reachy Mini SDK with a dry-run fallback."""

    mode: str = "dry-run"

    def __post_init__(self) -> None:
        self._mini = None
        try:
            from reachy_mini import ReachyMini

            self._ReachyMini = ReachyMini
            self.mode = "reachy-mini"
        except Exception:
            self._ReachyMini = None

    def say(self, text: str, emotion: str = "calm") -> None:
        self.express(emotion)
        if self.mode == "reachy-mini":
            # The Realtime browser audio should be routed to Reachy's speaker.
            # Keep SDK control focused on expressive motion.
            print(f"[Reachy speech route] {text}")
            return
        self.say_local(text)

    def say_local(self, text: str) -> None:
        if sys.platform == "darwin":
            threading.Thread(
                target=lambda: subprocess.run(["say", "-v", "Tingting", text], check=False),
                daemon=True,
            ).start()
        else:
            print(f"[Reachy dry-run say] {text}")

    def express(self, emotion: str) -> None:
        if self.mode != "reachy-mini":
            print(f"[Reachy dry-run express] {emotion}")
            return
        threading.Thread(target=self._express_with_sdk, args=(emotion,), daemon=True).start()

    def _express_with_sdk(self, emotion: str) -> None:
        try:
            from reachy_mini.utils import create_head_pose
            import numpy as np

            with self._ReachyMini() as mini:
                if emotion in {"mystical", "thinking"}:
                    mini.goto_target(
                        head=create_head_pose(z=8, roll=-8, degrees=True, mm=True),
                        antennas=np.deg2rad([28, -28]),
                        body_yaw=np.deg2rad(-12),
                        duration=0.55,
                    )
                    time.sleep(0.25)
                    mini.goto_target(
                        head=create_head_pose(z=4, roll=8, degrees=True, mm=True),
                        antennas=np.deg2rad([-18, 18]),
                        body_yaw=np.deg2rad(10),
                        duration=0.65,
                    )
                elif emotion in {"happy", "excited"}:
                    mini.goto_target(
                        head=create_head_pose(z=12, roll=0, degrees=True, mm=True),
                        antennas=np.deg2rad([45, 45]),
                        body_yaw=np.deg2rad(20),
                        duration=0.45,
                    )
                else:
                    mini.goto_target(
                        head=create_head_pose(z=2, roll=0, degrees=True, mm=True),
                        antennas=np.deg2rad([8, -8]),
                        body_yaw=0.0,
                        duration=0.5,
                    )
        except Exception as exc:
            print(f"[Reachy SDK expression failed] {exc}")
            self.mode = "dry-run"
