"""Delays e gestos leves para reduzir padrões totalmente robóticos (uso moderado, respeitando ToS)."""

from __future__ import annotations

import random
import time

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By


def random_delay(low: float = 0.8, high: float = 2.5) -> None:
    time.sleep(random.uniform(low, high))


def random_mouse_move(driver) -> None:
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        ac = ActionChains(driver)
        x = random.randint(8, 80)
        y = random.randint(8, 80)
        ac.move_to_element_with_offset(body, x, y).pause(random.uniform(0.05, 0.2)).perform()
    except Exception:
        pass
