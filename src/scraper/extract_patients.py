"""
Navega pela lista de pacientes (Datebox) e extrai perfil, histórico, prontuários e mensagens.

Ajuste os seletores CSS/XPath à estrutura real do CRM antes de produção.
"""

from __future__ import annotations

import random
import time

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from scraper.anti_detection import random_delay, random_mouse_move


def extract_all_patients(driver, base_patients_url=None):
    """
    Navega pela lista de pacientes, extrai dados de cada um.
    Retorna lista de dicionários com dados do perfil, histórico, prontuários e mensagens.
    """
    if base_patients_url is not None:
        driver.get(base_patients_url)

    all_patients = []
    page = 1

    while True:
        print(f"🔍 Processando página {page} de pacientes...")
        wait = WebDriverWait(driver, 15)

        try:
            patient_rows = wait.until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, ".patient-row, .patient-card, tbody tr")
                )
            )
        except TimeoutException:
            print("⚠️ Nenhum paciente encontrado ou lista vazia.")
            break

        if not patient_rows:
            break

        for idx in range(len(patient_rows)):
            rows = driver.find_elements(
                By.CSS_SELECTOR, ".patient-row, .patient-card, tbody tr"
            )
            if idx >= len(rows):
                break

            row = rows[idx]
            try:
                profile_link = row.find_element(
                    By.CSS_SELECTOR, "a[href*='/paciente/'], a.patient-name"
                )
                patient_name = profile_link.text.strip()
                profile_url = profile_link.get_attribute("href")
            except NoSuchElementException:
                profile_link = row
                patient_name = row.text.split("\n")[0] if row.text else f"paciente_{idx}"
                profile_url = None

            print(f"👉 Extraindo dados de: {patient_name}")

            original_window = driver.current_window_handle
            handles_before = list(driver.window_handles)

            if profile_url:
                driver.execute_script("window.open(arguments[0], '_blank');", profile_url)
            else:
                profile_link.click()
                time.sleep(2)

            handles_after = list(driver.window_handles)
            new_handles = [h for h in handles_after if h not in handles_before]

            if new_handles:
                driver.switch_to.window(new_handles[-1])
                same_tab = False
            else:
                same_tab = True

            patient_data = extract_patient_profile(driver)
            patient_data["nome"] = patient_name
            patient_data["url_perfil"] = driver.current_url

            patient_data["historico"] = extract_tab_content(driver, "Histórico")
            patient_data["prontuarios"] = extract_tab_content(
                driver, "Prontuários", multi=True
            )
            patient_data["mensagens"] = extract_tab_content(
                driver, "Mensagens", multi=False
            )

            all_patients.append(patient_data)

            if not same_tab:
                driver.close()
                driver.switch_to.window(original_window)
            else:
                driver.back()
                try:
                    wait.until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, ".patient-row, .patient-card, tbody tr")
                        )
                    )
                except TimeoutException:
                    pass

            random_delay()

        try:
            next_btn = driver.find_element(
                By.CSS_SELECTOR, "a.next, button.next, li.next:not(.disabled) a"
            )
            cls = next_btn.get_attribute("class") or ""
            if "disabled" in cls or not next_btn.is_enabled():
                break
            next_btn.click()
            time.sleep(random.uniform(2, 4))
            page += 1
        except NoSuchElementException:
            break

    return all_patients


def extract_patient_profile(driver):
    """Extrai dados do perfil do paciente: idade, objetivos, informações de contato."""
    profile_data = {}

    try:
        nome_elem = driver.find_element(By.CSS_SELECTOR, ".patient-name, h1")
        profile_data["nome"] = nome_elem.text.strip()
    except Exception:
        profile_data["nome"] = "desconhecido"

    try:
        idade_elem = driver.find_element(By.CSS_SELECTOR, ".age, .birth-date")
        profile_data["idade"] = idade_elem.text.strip()
    except Exception:
        profile_data["idade"] = None

    try:
        objetivos = driver.find_elements(By.CSS_SELECTOR, ".goals li, .objectives p")
        profile_data["objetivos"] = [obj.text.strip() for obj in objetivos]
    except Exception:
        profile_data["objetivos"] = []

    try:
        contato = driver.find_element(By.CSS_SELECTOR, ".contact-info, .email, .phone")
        profile_data["contato"] = contato.text.strip()
    except Exception:
        profile_data["contato"] = None

    return profile_data


def extract_tab_content(driver, tab_name, multi=False):
    """
    Clica na aba com nome `tab_name` (ex: 'Histórico') e extrai o conteúdo textual.
    Se multi=True, retorna lista de itens (múltiplos prontuários), senão retorna string.
    """
    wait = WebDriverWait(driver, 10)
    try:
        tab = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, f"//*[contains(text(), '{tab_name}')]")
            )
        )
        random_mouse_move(driver)
        tab.click()
        time.sleep(random.uniform(0.8, 1.8))

        if multi:
            items = driver.find_elements(
                By.CSS_SELECTOR, ".prontuario-item, .document-item, .note-item"
            )
            return [item.text.strip() for item in items if item.text.strip()]
        content_elem = driver.find_element(
            By.CSS_SELECTOR, ".content-area, .history-text, .message-thread"
        )
        return content_elem.text.strip()
    except (TimeoutException, NoSuchElementException):
        print(f"⚠️ Aba '{tab_name}' não encontrada ou sem conteúdo.")
        return [] if multi else ""


if __name__ == "__main__":
    from selenium import webdriver

    drv = webdriver.Chrome()
    drv.get("https://datebox.exemplo.com/pacientes")
    # login deve ser feito antes de chamar extract_all_patients
    lista = extract_all_patients(drv)
    print(f"Total extraído: {len(lista)}")
    drv.quit()
