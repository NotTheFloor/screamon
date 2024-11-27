import time
import json
import os
from PIL import ImageGrab, Image, ImageEnhance
import mouse
import pytesseract
import cv2
import numpy as np
import playsound



REFRESH_RATE = 3
SAVE_FILE = 'settings.conf'


def get_coords(location):
    storage = []

    print(f'Please click the top left then bottom right corners of {location}')

    # Define the click handler within the function
    def store_click():
        storage.append(mouse.get_position())

    # Register the click listener
    mouse.on_pressed(store_click)

    # Wait for two mouse releases (two clicks)
    mouse.wait(target_types=mouse.UP)
    mouse.wait(target_types=mouse.UP)

    # I don't want to do this, but mouse won't unhook the handler..
    mouse._listener.handlers = []

    return storage

def capture_text(coords):
    # Capture a screenshot of the specified region
    img = ImageGrab.grab(bbox=(int(coords[0][0]), int(coords[0][1]), int(coords[1][0]), int(coords[1][1])))

    # Uncomment to save the raw screenshot
    # screenshot.save('saved_screen_grab.png')

    screenshot = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)

    screenshot = ImageEnhance.Contrast(screenshot)
    screenshot = screenshot.enhance(2)  # Increase contrast by a factor of 2

    # Step 2: Convert the Pillow image to a NumPy array
    screenshot_np = np.array(screenshot)

    # Step 3: Convert RGB (Pillow) to BGR (OpenCV)
    img = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)

    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Apply thresholding
    _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)

    # Remove noise
    denoised = thresh # cv2.medianBlur(thresh, 2)

    # Uncomment to debug and save intermediate images
    # cv2.imwrite('gray.png', gray)
    # cv2.imwrite('thresh.png', thresh)
    # cv2.imwrite('denoised.png', denoised)
     
    # Convert back to Pillow format directly
    img_pillow = Image.fromarray(denoised)

    # Uncomment to save the processed image for debugging
    # img_pillow.save('post_proc.png')

    # Perform OCR with Tesseract
    text = pytesseract.image_to_string(img_pillow)

    return text

def extract_local_count(local_text):
    local_index = local_text.find('l')
    corp_index = local_text.find('C')

    if local_index == -1 or local_index > corp_index or corp_index == -1:
        return -1

    pop_count_string = local_corp_text[local_index + 1:corp_index]
    open_index = pop_count_string.find('[') # ]

    if open_index == -1:
        return -1

    close_index = pop_count_string.find(']')
    if close_index == -1 or close_index > corp_index:
        return -1

    result = -1
    try:
       result = int(pop_count_string[open_index + 1:close_index])
    except ValueError:
        return -1

    return result

def get_user_col_count(user_col_text):
    return len([line.strip() for line in user_col_text.splitlines() if line.strip()])

local_corp_coords = []
chat_col_coords = []

if os.path.exists(SAVE_FILE):
    ans = input('Settings found. Use last settings? Y/n: ')
    if ans == '' or ans.upper()[0] != 'N':
        with open(SAVE_FILE, 'r') as f:
            coords = json.load(f)
            
        local_corp_coords = coords[0]
        chat_col_coords = coords[1]

if not local_corp_coords:
    local_corp_coords = get_coords('Local [x] Corp [x] line')
    chat_col_coords = get_coords('chat user column')

    with open(SAVE_FILE, 'w') as f:
        coords = [local_corp_coords, chat_col_coords]
        json.dump(coords, f)

t0 = time.time()
last_count = 0

print(f"Entering loop - current refresh rate {REFRESH_RATE}")
while True:
    t1 = time.time()
    if t1 < (t0 + REFRESH_RATE):
        time.sleep((t0+REFRESH_RATE) - t1)
    t0 = time.time()

    local_corp_text = capture_text(local_corp_coords)
    #chat_col_text = capture_text(chat_col_coords)

    local_count = extract_local_count(local_corp_text)
    #user_col_count = get_user_col_count(chat_col_text)

    if local_count == -1:
        print('Misread')
        playsound.playsound('sounds/woop.flac')
        continue

    if local_count > last_count: 
        print(f'Local count increased to {local_count} from {last_count}')
        last_count = local_count
        playsound.playsound('sounds/bad.wav')
    elif local_count < last_count:
        print(f'Local count decreased to {local_count} from {last_count}')
        last_count = local_count
        playsound.playsound('sounds/ok.wav')
        
        

