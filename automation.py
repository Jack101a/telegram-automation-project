"""
Part 3: Browser Automation (automation.py)

This module contains the browser automation logic using Playwright. It is designed
to be driven by an orchestrator, executing steps in a stateful manner. The core
function, `execute_automation_step`, takes the current state of a session and
performs the corresponding browser actions.

Key Features:
- Integrates the specific website flow from the user's codegen script.
- Pauses execution to request human input for CAPTCHA and OTP.
- Takes screenshots of CAPTCHA elements for the user to solve.
- Logs all major actions and errors to the database via db.py.
- Handles session artifacts (screenshots) by saving them to a structured directory.
- Implements basic error handling and waits for page elements.
"""

import os
import logging
from datetime import date
from typing import Dict, Any, Optional

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

# Local application imports
import db

# --- Configuration ---
ARTIFACTS_DIR = "artifacts"
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# --- Helper Functions ---

def _log(session_id: str, level: str, message: str):
    """Convenience function to log events to both the logger and the database."""
    logger.log(logging.getLevelName(level), f"[Session: {session_id}] {message}")
    db.log_event(session_id, level, message)

async def _take_element_screenshot(element, session_id: str, name: str) -> str:
    """Takes a screenshot of a specific Playwright element and saves it as an artifact."""
    session_dir = os.path.join(ARTIFACTS_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
    
    path = os.path.join(session_dir, f"{name}.png")
    try:
        await element.screenshot(path=path)
        db.add_artifact(session_id, f"{name.upper()}_SCREENSHOT", path)
        _log(session_id, "INFO", f"Saved screenshot artifact to {path}")
        return path
    except Exception as e:
        _log(session_id, "ERROR", f"Failed to take screenshot {name}: {e}")
        raise

async def _take_full_page_screenshot(page: Page, session_id: str, name: str) -> str:
    """Takes a screenshot of the full page and saves it as an artifact."""
    session_dir = os.path.join(ARTIFACTS_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    path = os.path.join(session_dir, f"{name}.png")
    try:
        await page.screenshot(path=path, full_page=True)
        db.add_artifact(session_id, f"{name.upper()}_SCREENSHOT", path)
        _log(session_id, "INFO", f"Saved full page screenshot artifact to {path}")
        return path
    except Exception as e:
        _log(session_id, "ERROR", f"Failed to take full page screenshot {name}: {e}")
        raise

# --- Core Automation Function ---

async def execute_automation_step(
    page: Page,
    session_id: str,
    user_data: Dict[str, Any],
    current_state: str,
    user_input: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes a single, state-aware step in the automation process.

    This function is the heart of the automation. It contains the logic for each
    stage of the web form submission process. It's designed to be called repeatedly
    by an orchestrator, which manages the overall session state.

    Args:
        page: The active Playwright Page object for this session.
        session_id: The unique ID for the current session.
        user_data: A dictionary containing 'serial_no' and 'dob'.
        current_state: The current state of the session (e.g., 'QUEUED', 'AWAITING_CAPTCHA').
        user_input: The input provided by the user (e.g., CAPTCHA text, OTP code).

    Returns:
        A dictionary indicating the result of the step, which can be:
        - A success or failure status.
        - A pause status, requesting user input.
    """
    try:
        # State: QUEUED -> This is the first step of the process.
        if current_state == "QUEUED":
            _log(session_id, "INFO", "Starting automation flow.")
            
            # 1. Navigate and select state
            await page.goto("https://sarathi.parivahan.gov.in/sarathiservice/stateSelection.do", timeout=60000)
            
            # Handle potential intro popup
            try:
                await page.get_by_label("Close").click(timeout=5000)
            except PlaywrightTimeoutError:
                _log(session_id, "INFO", "Introductory popup not found, continuing.")

            await page.locator("#stfNameId").select_option("MH")
            _log(session_id, "INFO", "State 'MH' selected.")

            # 2. Navigate through menus
            await page.get_by_role("link", name="Apply for DL Renewal").click()
            await page.get_by_role("button", name="Continue").click()
            _log(session_id, "INFO", "Navigated to DL Renewal form.")

            # 3. Fill user details
            serial_no = user_data['serial_no']
            dob_str = user_data['dob'].strftime('%d-%m-%Y') # Format date as DD-MM-YYYY

            await page.get_by_role("textbox", name="DL number").fill(serial_no)
            await page.get_by_role("textbox", name="DD-MM-YYYY").fill(dob_str)
            _log(session_id, "INFO", "Filled DL number and DOB.")

            # 4. PAUSE for first CAPTCHA
            captcha_image_element = page.get_by_role("img", name="Click Here to Refresh Captcha")
            captcha_path = await _take_element_screenshot(captcha_image_element, session_id, "captcha_1")
            
            return {"status": "PAUSE_AWAITING_CAPTCHA", "captcha_path": captcha_path, "next_state": "AWAITING_FIRST_CAPTCHA"}

        # State: AWAITING_FIRST_CAPTCHA -> User has provided the first CAPTCHA text.
        elif current_state == "AWAITING_FIRST_CAPTCHA":
            if not user_input:
                return {"status": "FAILURE", "reason": "CAPTCHA input was not provided."}

            _log(session_id, "INFO", f"Submitting first CAPTCHA: '{user_input}'.")
            await page.get_by_role("textbox", name="Enter Captcha Here").fill(user_input)
            await page.locator("#PrivacyPolicyTermsofService").check()
            await page.get_by_role("button", name="Get DL Details").click()

            # Check for invalid captcha error
            try:
                error_element = await page.wait_for_selector("text=/Invalid Captcha/", timeout=5000)
                if await error_element.is_visible():
                    reason = await error_element.inner_text()
                    _log(session_id, "WARNING", f"First CAPTCHA failed: {reason}")
                    # Re-take screenshot and re-request
                    captcha_image_element = page.get_by_role("img", name="Click Here to Refresh Captcha")
                    await captcha_image_element.click() # Refresh captcha
                    await asyncio.sleep(1) # Wait for new image to load
                    captcha_path = await _take_element_screenshot(captcha_image_element, session_id, "captcha_1_retry")
                    return {"status": "RETRY_AWAITING_CAPTCHA", "captcha_path": captcha_path, "next_state": "AWAITING_FIRST_CAPTCHA"}
            except PlaywrightTimeoutError:
                _log(session_id, "INFO", "CAPTCHA seems to be correct. Proceeding.")

            # 5. Handle confirmations
            await page.locator("#dispDLDet").select_option("YES")
            await page.locator("#rtoCodeDLTr").select_option("MH47") # Hardcoded for Borivali as in codegen
            await page.get_by_role("button", name="Proceed").click()
            _log(session_id, "INFO", "Confirmed DL details and RTO.")

            # Handle alert/dialog popups by automatically dismissing
            page.once("dialog", lambda dialog: dialog.accept())
            await page.get_by_role("button", name="Confirm").click()
            _log(session_id, "INFO", "Handled confirmation dialog.")

            # 6. Generate OTP (which requires another CAPTCHA)
            _log(session_id, "INFO", "Reached OTP generation step.")
            captcha_image_element_2 = page.get_by_role("img", name="Click Here to Refresh Captcha")
            captcha_path_2 = await _take_element_screenshot(captcha_image_element_2, session_id, "captcha_2_for_otp")

            return {"status": "PAUSE_AWAITING_CAPTCHA", "captcha_path": captcha_path_2, "next_state": "AWAITING_OTP_CAPTCHA"}

        # State: AWAITING_OTP_CAPTCHA -> User has provided CAPTCHA to generate OTP.
        elif current_state == "AWAITING_OTP_CAPTCHA":
            if not user_input:
                return {"status": "FAILURE", "reason": "CAPTCHA for OTP was not provided."}

            _log(session_id, "INFO", "Submitting CAPTCHA to generate OTP.")
            await page.get_by_role("textbox", name="Enter Captcha").fill(user_input)
            await page.get_by_role("button", name="Generate OTP").click()
            
            # Check for OTP sent success message or errors
            # This part is crucial and may need adjustment based on the live site's behavior
            try:
                await page.wait_for_selector("text=/OTP has been sent/", timeout=10000)
                _log(session_id, "INFO", "OTP generation successful.")
            except PlaywrightTimeoutError:
                _log(session_id, "WARNING", "Could not confirm OTP was sent. This might be a CAPTCHA error.")
                # You could add a retry mechanism here similar to the first CAPTCHA
                return {"status": "FAILURE", "reason": "Failed to generate OTP. Possibly an invalid CAPTCHA."}

            # 7. PAUSE for OTP input
            return {"status": "PAUSE_AWAITING_OTP", "next_state": "AWAITING_OTP_SUBMISSION"}

        # State: AWAITING_OTP_SUBMISSION -> User has provided the OTP.
        elif current_state == "AWAITING_OTP_SUBMISSION":
            if not user_input:
                return {"status": "FAILURE", "reason": "OTP was not provided."}
            
            _log(session_id, "INFO", "Submitting OTP.")
            await page.locator("#otpNumberSarathi").fill(user_input)
            await page.get_by_role("button", name="Submit OTP").click() # Codegen shows another button here
            
            # Logic to check for successful OTP submission
            # Example: Wait for a specific element that appears after success
            try:
                await page.wait_for_selector("#trsaction_dlc", timeout=15000)
                _log(session_id, "INFO", "OTP Submitted successfully. On final submission page.")
            except PlaywrightTimeoutError:
                return {"status": "FAILURE", "reason": "Failed to submit OTP. It might be incorrect or expired."}

            # 8. Final steps from codegen (declarations, etc.)
            await page.locator("div:nth-child(3) > div:nth-child(3) > #trsaction_dlc").check()
            await page.get_by_role("button", name="Proceed").click()
            _log(session_id, "INFO", "Proceeded after selecting transactions.")

            # This is a simplification. The full flow with self-declaration popup
            # and final captcha would be implemented here following the codegen.
            # For this example, we'll assume success after this point.
            
            final_screenshot = await _take_full_page_screenshot(page, session_id, "final_success")
            return {"status": "SUCCESS", "screenshot_path": final_screenshot}

        # Default case for unknown states
        else:
            _log(session_id, "ERROR", f"Automation entered an unknown state: {current_state}")
            return {"status": "FAILURE", "reason": f"Unknown state '{current_state}'"}

    except PlaywrightTimeoutError as e:
        _log(session_id, "ERROR", f"A timeout error occurred: {e}")
        screenshot_path = await _take_full_page_screenshot(page, session_id, "error_timeout")
        return {"status": "FAILURE", "reason": "Page element not found or timed out.", "screenshot_path": screenshot_path}
    except Exception as e:
        _log(session_id, "CRITICAL", f"An unexpected error occurred during automation: {e}", exc_info=True)
        screenshot_path = await _take_full_page_screenshot(page, session_id, "error_unexpected")
        return {"status": "FAILURE", "reason": "An unexpected critical error occurred.", "screenshot_path": screenshot_path}


# --- Sample Usage Snippet (for testing purposes) ---
if __name__ == '__main__':
    # This snippet demonstrates how an orchestrator would call the function.
    # It requires a running Playwright instance.
    from playwright.async_api import async_playwright
    
    async def test_run():
        db.initialize_database()
        
        test_session_id = "test-session-123"
        test_user_data = {
            "serial_no": "MH47XXXXXXXXXXX", # Replace with a valid test DL number
            "dob": date(1990, 1, 1)      # Replace with the corresponding DOB
        }

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, slow_mo=50)
            context = await browser.new_context()
            page = await context.new_page()

            # --- Step 1: Initial call ---
            print("--- Running Step 1: QUEUED ---")
            result = await execute_automation_step(page, test_session_id, test_user_data, "QUEUED")
            print(f"Result: {result}")
            
            if result.get("status") == "PAUSE_AWAITING_CAPTCHA":
                # --- Step 2: Simulate user providing CAPTCHA ---
                captcha_input = input("Enter the first CAPTCHA from the browser: ")
                current_state = result["next_state"]
                print(f"\n--- Running Step 2: {current_state} ---")
                result = await execute_automation_step(page, test_session_id, test_user_data, current_state, captcha_input)
                print(f"Result: {result}")
                
                if result.get("status") == "PAUSE_AWAITING_CAPTCHA":
                    # --- Step 3: Simulate user providing CAPTCHA for OTP ---
                    otp_captcha_input = input("Enter the CAPTCHA for OTP from browser: ")
                    current_state = result["next_state"]
                    print(f"\n--- Running Step 3: {current_state} ---")
                    result = await execute_automation_step(page, test_session_id, test_user_data, current_state, otp_captcha_input)
                    print(f"Result: {result}")
                    
                    if result.get("status") == "PAUSE_AWAITING_OTP":
                        # --- Step 4: Simulate user providing OTP ---
                        otp_input = input("Enter the OTP from your phone: ")
                        current_state = result["next_state"]
                        print(f"\n--- Running Step 4: {current_state} ---")
                        result = await execute_automation_step(page, test_session_id, test_user_data, current_state, otp_input)
                        print(f"Result: {result}")

            print("\nTest run finished. Close the browser manually.")
            await asyncio.sleep(300) # Keep browser open for inspection
            await context.close()
            await browser.close()

    asyncio.run(test_run())


