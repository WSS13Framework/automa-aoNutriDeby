import asyncio
from playwright.async_api import async_playwright

EMAIL = "nutrideboraoliver@gmail.com"
PASSWORD = "De251079v"
URL_LOGIN = "https://dietbox.me/pt-BR"

async def conectar_ao_crm():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("🔐 Acessando o site...")
        await page.goto(URL_LOGIN, timeout=60000, wait_until='domcontentloaded')

        print("🔐 Fazendo login...")
        await page.fill('input[type="email"]', EMAIL)
        await page.fill('input[type="password"]', PASSWORD)
        
        print("🔐 Submetendo formulário...")
        await page.click('button[type="submit"]')

        try:
            # Aguarda um elemento que só aparece após o login.
            # Você precisará ajustar o seletor (ex: um texto 'Dashboard' ou um ícone de menu).
            await page.wait_for_selector('text=Dashboard', timeout=60000)
            print("✅ Login realizado com sucesso!")
            print(f"📄 URL atual: {page.url}")

            # Aqui você começa a extração dos dados!

        except Exception as e:
            print("❌ Falha no login:", e)
            # Salva um print da tela em caso de erro para depuração
            await page.screenshot(path="erro_login.png")
            print("📸 Screenshot da tela de erro salvo como 'erro_login.png'")

        finally:
            await browser.close()

asyncio.run(conectar_ao_crm())
