import os

from PIL import Image
import pytesseract

#IMSTORE_ROOT = 'C:/Doclink/IMSTORE'
IMSTORE_ROOT = '/Users/cgthomas/Dev/docroot'

# Need to determine if str or int, need return type from tesseract
def capture_document(doclink_sql, docid: str | int):
    filename = '000000003-3.tif' # doclink_sql.get_file_by_docid(docid)
    
    full_docid = str(docid).zfill(9)
    level1 = full_docid[0:3]
    level2 = full_docid[3:6]

    full_path = os.path.join(IMSTORE_ROOT, level1, level2, filename)
    if not os.path.exists(full_path):
        print("ERROR: file " + full_path + " does not exist")
        quit()

    file_ext = filename.split('.')[-1].lower()
    
    if file_ext not in ['tiff', 'tif', 'pdf', 'txt']:
        print("ERROR: unsupported extension '" + file_ext + "'")
        quit()

    text_info = None
    if file_ext in ['tiff', 'tif']:
        text_info = extract_from_tiff(full_path)
    else:
        text_info = extract_from_pdf(full_path)

    
    return text_info

def extract_from_pdf(full_path: str) -> list:
    return []
    # images = pdf2image.convert_from_path(full_path)
# 
    # text_data = [pytesseract.image_to_boxes(page) for page in images]
    #text_data = [pytesseract.image_to_data(page, output_type=pytesseract.Output.DICT) for page in images]

    # return text_data

def extract_from_tiff(full_path: str) -> list:
    image = Image.open(full_path)

    text_data = []

    for i in range(image.n_frames):
        image.seek(i)
        # text_data.append(pytesseract.image_to_data(image, output_type = pytesseract.Output.DICT)) #image_to_boxes(image))
        text_data.append(pytesseract.image_to_boxes(image))

    return text_data

def get_text_in_box(text_data, left: int, top: int, right: int, bottom: int) -> str:
    # so theres gotta be a beter way of doing this and we'll likely just have to
    # refactor
    text = ''
    row = 0
    for char in text_data[0].split('\n'):
        if char == '':
            continue
        char_data = char.strip().split(' ')
        if row < 10:
            print(char_data)
            row += 1
        if (int(char_data[1]) > left and
            int(char_data[2]) > top and
            int(char_data[3]) < right and
            int(char_data[4]) < bottom):

            text += char_data[0]

    return text
            


"""def connect(serverName: str, databaseName: str, username: str, password: str):
    doclink = DocLinkSQL()
    credentials = DocLinkSQLCredentials(
            serverName,
            databaseName,
            username,
            password
        )
    doclink.connect(credentials)"""

if __name__ == "__main__":

    serverName = '172.16.205.129'
    dbName = 'doclink2'
    username = 'sa'
    pword = 'Sa2014'

    # doclink_sql = connect(serverName, dbName, username, pword)
    doclink_sql = None

    captext = capture_document(doclink_sql, 3)

    print(get_text_in_box(captext, 390, 2890, 650, 2930))
