import asyncio
from playwright.async_api import async_playwright

EMAIL = "nutrideboraoliver@gmail.com"
PASSWORD = "De251079v"
URL_LOGIN = "https://dietbox.me/pt-BR"

async def extrair_primeiro_paciente():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-zygote",
                "--disable-ipv6",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        print("Acessando o site...")
        await page.goto(URL_LOGIN, timeout=60000, wait_until="domcontentloaded")
        print(f"Pagina carregada: {page.url}")

        await page.wait_for_selector('input[type="email"]', timeout=15000)
        print("Fazendo login...")
        await page.fill('input[type="email"]', EMAIL)
        await page.fill('input[type="password"]', PASSWORD)
        await page.click('button[type="submit"]')

        await page.wait_for_timeout(6000)
        print(f"URL apos login: {page.url}")

        await page.screenshot(path="/opt/automa-aoNutriDeby/screenshot_pos_login.png")
        print("Screenshot salvo em screenshot_pos_login.png")

        await browser.close()

asyncio.run(extrair_primeiro_paciente())
