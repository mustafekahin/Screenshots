from datetime import datetime
from pathlib import Path
import time
import os

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, JavascriptException

# Use webdriver-manager so you don't have to download/point to chromedriver manually.
from webdriver_manager.chrome import ChromeDriverManager
service = ChromeService(ChromeDriverManager().install())

URL = os.getenv("STREAM_URL")  # Link from environment variable or default
OUT_DIR = Path("screenshots") # Folder where images will be stored
SHOT_COUNT = 3
ANGLE_INTERVAL_SEC = 30
WAIT_BEFORE_FIRST_SHOT = 5
#VIEWPORT = (1920, 1080)
VIEWPORT = (1280, 720)
# Function that returns timestamp for files
def ts():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

#Create and return a configured Chrome WebDriver.
def make_driver(headless=True):
    options = webdriver.ChromeOptions()
    options.add_argument(f"--window-size={VIEWPORT[0]},{VIEWPORT[1]}")
    if headless:
        # Use new headless if available
        options.add_argument("--headless=new")
    options.add_argument("--mute-audio")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    return webdriver.Chrome(service=service, options=options)

""" Try to click an element if it becomes clickable within 'timeout' seconds. Returns True if clicked, False otherwise (swallows errors quietly)."""

def click_if_present(driver, locator, timeout=4):
    try:
        btn = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable(locator))
        btn.click()
        return True
    except Exception:
        return False

def accept_cookies_robust(driver):
    """Attempt to accept cookie banners using several strategies:
    Try common CMPs first, then a generic text-based click on any 'accept all' button (EN/DK)."""
    
    # 1) Known vendors/selectors (OneTrust / Cookiebot / Cookie Information / Didomi-like)
    known_locators = [
        # OneTrust
        (By.ID, "onetrust-accept-btn-handler"),
        (By.CSS_SELECTOR, "button#onetrust-accept-btn-handler"),
        (By.CSS_SELECTOR, "button[aria-label='Accept all']"),
        (By.CSS_SELECTOR, "button[aria-label='Accept All']"),
        # Cookiebot
        (By.ID, "CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"),
        (By.CSS_SELECTOR, "#CybotCookiebotDialogBodyButtonAccept, #CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"),
        # Cookie Information (common in DK)
        (By.CSS_SELECTOR, ".coi-banner__accept, button[data-action='accept'], button.coi-consent-accept"),
        # Didomi-ish
        (By.CSS_SELECTOR, "button.didomi-continue, button[data-didomi-action='accept']"),
    ]
    for loc in known_locators:
        if click_if_present(driver, loc, timeout=3):
            return True

    # 2) If banner inside iframe (OneTrust sometimes uses iframes)
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.frame(frame)
                for loc in known_locators:
                    if click_if_present(driver, loc, timeout=2):
                        driver.switch_to.default_content()
                        return True
                driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()
    except Exception:
        pass

    # 3) Generic text-based approach: find any visible button with accept text (English/Danish)
    #    Works across many CMPs, even with different classnames.
    js = r"""
    (function() {
      const texts = [
        'accept', 'accept all', 'allow all',
        'accepter', 'accepter alle', 'acceptér', 'acceptér alle',
        'tillad alle', 'tillad alle cookies',
      ];
      function norm(s){ return (s||'').toLowerCase().trim(); }
      function visible(el){
        const r = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return r.width>1 && r.height>1 && style.visibility!=='hidden' && style.display!=='none';
      }
      const candidates = Array.from(document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"]'));
      for (const el of candidates) {
        const t = norm(el.innerText || el.value || el.getAttribute('aria-label'));
        if (!t) continue;
        for (const needle of texts) {
          if (t.includes(needle) && visible(el)) {
            el.click();
            return true;
          }
        }
      }
      return false;
    })();
    """
    try:
        if driver.execute_script(js):
            return True
    except JavascriptException:
        pass

    # 4) Generic inside iframes
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.frame(frame)
                try:
                    if driver.execute_script(js):
                        driver.switch_to.default_content()
                        return True
                except JavascriptException:
                    pass
                driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()
    except Exception:
        pass

    return False

def find_player_element(driver):
    """Return <video> or visible <iframe>—whichever likely contains the live stream."""
    wait = WebDriverWait(driver, 12)
    # Try native <video> first
    try:
        video = wait.until(EC.presence_of_element_located((By.TAG_NAME, "video")))
        if video.is_displayed():
            return video
    except TimeoutException:
        pass
    # Visible iframe(s)
    frames = driver.find_elements(By.TAG_NAME, "iframe")
    for f in frames:
        if f.is_displayed():
            return f
    return None

def scroll_into_view(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({behavior:'instant', block:'center'});", el)
    time.sleep(1)

def run():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    driver = make_driver(headless=True)
    try:
        driver.get(URL)

        # Try to accept cookies; ignore if none
        accept_cookies_robust(driver)

        # Locate player and bring it into view (helps ensure it’s in the screenshots)
        player = find_player_element(driver)
        if not player:
            # small nudge to trigger lazy content
            driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(2)
            player = find_player_element(driver)

        if player:
            scroll_into_view(driver, player)
        else:
            print("⚠️ Could not find a <video> or visible <iframe>. Will still capture full page.")

        # Small settle time
        time.sleep(WAIT_BEFORE_FIRST_SHOT)

        # Take 3 screenshots, 30s apart
        for i in range(SHOT_COUNT):
            fname = OUT_DIR / f"camera_angle_{i+1}_{ts()}.png"
            driver.save_screenshot(str(fname))
            print(f"Saved: {fname}")
            if i < SHOT_COUNT - 1:
                time.sleep(ANGLE_INTERVAL_SEC)

    finally:
        driver.quit()

if __name__ == "__main__":
    run()
