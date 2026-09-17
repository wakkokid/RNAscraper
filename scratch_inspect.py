import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto('https://www.rna.gov.it/trasparenza/aiuti', wait_until="domcontentloaded")
        
        try:
            await page.wait_for_selector('button#truste-consent-button', timeout=5000)
            await page.click('button#truste-consent-button')
            await asyncio.sleep(2)
            await page.goto('https://www.rna.gov.it/trasparenza/aiuti', wait_until="domcontentloaded")
        except:
            pass
            
        selects = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll("select")).map(s => {
                return {
                    id: s.id,
                    name: s.name,
                    options: Array.from(s.options).map(o => ({text: o.text.trim(), value: o.value}))
                }
            });
        }''')
        import json
        print(json.dumps(selects, indent=2))
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

