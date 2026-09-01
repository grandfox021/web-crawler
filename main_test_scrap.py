
from playwright.sync_api import sync_playwright

def open_bale():

    with sync_playwright() as p:

        context = p.chromium.launch_persistent_context(user_data_dir="./profile" ,
                                                        headless=False ,)
        
        page = (
            context.pages[0]
            if context.pages
            else context.new_page()
        )

        page.goto("https://web.bale.ai/")

        page.pause()

open_bale()    