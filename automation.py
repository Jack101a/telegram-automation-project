import asyncio
import logging
import os
from datetime import datetime
from playwright.async_api import Page, TimeoutError, Error as PlaywrightException
import db

# --- Logging Setup ---
logger = logging.getLogger(__name__)

# --- Helper Functions ---
async def take_screenshot(page: Page, session_id: str, name: str):
    try:
        path = os.path.join("artifacts", session_id)
        os.makedirs(path, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = os.path.join(path, f"{name}_{timestamp}.png")
        await page.screenshot(path=screenshot_path, full_page=True)
        db.add_artifact(session_id, "screenshot", screenshot_path)
        logger.info(f"[{session_id}] Saved screenshot to {screenshot_path}")
    except Exception as e:
        logger.error(f"[{session_id}] Failed to take screenshot {name}: {e}")

# --- Main State Machine ---
async def execute_automation_step(page: Page, session_id: str, current_state: str, user_data) -> dict:
    logger.info(f"[{session_id}] Executing state: {current_state}")
    serial_no = user_data.serial_no
    dob_str = user_data.dob.strftime("%d-%m-%Y")

    try:
        if current_state in ["COMPLETED", "FAILED"]:
            return {"status": "END", "next_state": current_state}

        if current_state == "QUEUED":
            ## 1. PATIENCE: Wait for the page to fully load, not just navigate.
            await page.goto("https://sarathi.parivahan.gov.in/sarathiservice/stateSelection.do", wait_until="networkidle", timeout=60000)
            return {"status": "CONTINUE", "next_state": "NAVIGATED_TO_SELECTION"}

        elif current_state == "NAVIGATED_TO_SELECTION":
            state_dropdown = page.locator("#stfNameId")
            ## 1. PATIENCE: Wait for the element to be visible before interacting.
            await state_dropdown.wait_for(state="visible", timeout=30000)
            await state_dropdown.select_option("MH")
            return {"status": "CONTINUE", "next_state": "STATE_SELECTED"}
        
        elif current_state == "STATE_SELECTED":
            renewal_link = page.get_by_role("link", name="Apply for DL Renewal")
            await renewal_link.wait_for(state="visible", timeout=30000)
            await renewal_link.click()
            return {"status": "CONTINUE", "next_state": "CLICKED_RENEWAL"}

        elif current_state == "CLICKED_RENEWAL":
            continue_button = page.get_by_role("button", name="Continue")
            await continue_button.wait_for(state="visible", timeout=30000)
            await continue_button.click()
            return {"status": "CONTINUE", "next_state": "SUBMIT_FIRST_FORM"}

        elif current_state == "SUBMIT_FIRST_FORM":
            ## 2. RESILIENCE: This is a critical step, so we will retry it up to 3 times.
            for attempt in range(3):
                try:
                    logger.info(f"[{session_id}] Filling DL details, attempt {attempt + 1}")
                    await page.get_by_role("textbox", name="DL number").wait_for(state="visible", timeout=30000)
                    await page.get_by_role("textbox", name="DL number").fill(serial_no)
                    await page.get_by_role("textbox", name="DD-MM-YYYY").fill(dob_str)
                    
                    captcha_element = page.locator("#captcha_img_span > img")
                    await captcha_element.wait_for(state="visible", timeout=15000)
                    captcha_path = os.path.join("artifacts", session_id, "captcha1.png")
                    os.makedirs(os.path.dirname(captcha_path), exist_ok=True)
                    await captcha_element.screenshot(path=captcha_path)
                    
                    # If all steps succeed, we exit the retry loop.
                    return {
                        "status": "PAUSE_FOR_CAPTCHA",
                        "next_state": "AWAITING_FIRST_CAPTCHA",
                        "captcha_path": captcha_path,
                        "target_selector": "#captchatext"
                    }
                except TimeoutError as e:
                    logger.warning(f"[{session_id}] Timeout on attempt {attempt + 1}: {e}. Reloading and retrying...")
                    await page.reload(wait_until="networkidle") # Reload page on failure
                    await asyncio.sleep(3) # Wait a moment before retrying
            # If all attempts fail, raise an error to fail the session.
            raise TimeoutError("Failed to fill DL details after 3 attempts.")

        elif current_state == "AWAITING_FIRST_CAPTCHA":
            await page.locator("#submit").click()
            # Wait for the confirmation element that appears after successful submission
            await page.locator("#dispDLDet").wait_for(state="visible", timeout=30000)
            
            # This is where you would continue with the rest of your codegen logic...
            # For example:
            # await page.locator("#dispDLDet").select_option("YES")
            # await page.locator("#rtoCodeDLTr").select_option("REGIONAL TRANSPORT OFFICE BORIVALI -- MH47 ")
            # await page.get_by_role("button", name="Proceed").click()
            
            # For now, we'll mark it as complete.
            return {"status": "CONTINUE", "next_state": "COMPLETED", "details": "Successfully submitted initial form."}
        
        # Add other states from your codegen (AWAITING_OTP, etc.) here as needed...
        
        logger.error(f"[{session_id}] Reached an unhandled state: {current_state}")
        await take_screenshot(page, session_id, "unhandled_state")
        return {"status": "ERROR", "next_state": "FAILED", "details": f"Unhandled state: {current_state}"}

    except (TimeoutError, PlaywrightException) as e:
        error_message = f"A Playwright error occurred in state '{current_state}': {e}"
        logger.error(f"[{session_id}] {error_message}")
        await take_screenshot(page, session_id, "playwright_error")
        return {"status": "ERROR", "next_state": "FAILED", "details": error_message}
    except Exception as e:
        error_message = f"An unexpected error occurred in state '{current_state}': {e}"
        logger.error(f"[{session_id}] {error_message}", exc_info=True)
        await take_screenshot(page, session_id, "unexpected_error")
        return {"status": "ERROR", "next_state": "FAILED", "details": error_message}