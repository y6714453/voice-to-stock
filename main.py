import requests
import asyncio
import edge_tts
import os
import subprocess
import speech_recognition as sr
import pandas as pd
import yfinance as yf
from difflib import get_close_matches
from requests_toolbelt.multipart.encoder import MultipartEncoder

USERNAME = "0733181201"
PASSWORD = "6714453"
TOKEN = f"{USERNAME}:{PASSWORD}"

FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

async def main_loop():
    stock_dict = load_stock_list("hebrew_stocks.csv")
    print("\U0001F501 בלולאת בדיקה מתחילה 9...")

    ensure_ffmpeg()

    while True:
        filename = download_yemot_file()
        if filename:
            recognized = transcribe_audio(filename)
            if recognized:
                best_match = get_best_match(recognized, stock_dict)
                if best_match:
                    ticker = stock_dict[best_match]
                    data = get_stock_data(ticker)
                    if data:
                        text = format_text(best_match, ticker, data)
                        await create_audio(text, "output.mp3")
                        convert_mp3_to_wav("output.mp3", "output.wav")
                        upload_to_yemot("output.wav")
                        delete_yemot_file()
                        print("\u2705 הושלמה פעולה מחזורית\n")
        await asyncio.sleep(2)

def ensure_ffmpeg():
    if not shutil.which("ffmpeg"):
        print("\U0001F527 מוריד ffmpeg...")
        os.makedirs("ffmpeg_bin", exist_ok=True)
        zip_path = "ffmpeg.zip"
        r = requests.get(FFMPEG_URL)
        with open(zip_path, 'wb') as f:
            f.write(r.content)
        import zipfile
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall("ffmpeg_bin")
        os.remove(zip_path)
        bin_path = next((os.path.join(root, file)
                         for root, _, files in os.walk("ffmpeg_bin")
                         for file in files if file == "ffmpeg.exe" or file == "ffmpeg"), None)
        if bin_path:
            os.environ["PATH"] += os.pathsep + os.path.dirname(bin_path)


def download_yemot_file():
    # 🧾 בקשה לרשימת הקבצים בשלוחה
    url_list = "https://www.call2all.co.il/ym/api/GetFolder"
    params = {"token": TOKEN, "path": "ivr2:/9"}
    response = requests.get(url_list, params=params)
    
    if response.status_code != 200:
        print("❌ שגיאה בשליפת רשימת קבצים")
        return None

    files = response.json().get("files", [])
    
    # 📂 סינון קבצי WAV עם שם מספרי בלבד
    wav_files = [f for f in files if f.get("name", "").endswith(".wav") and f["name"][:-4].isdigit()]
    if not wav_files:
        print("📭 אין קבצי WAV לשליפה")
        return None

    # 🔢 בחירת הקובץ עם המספר הגבוה ביותר
    max_file = max(wav_files, key=lambda f: int(f["name"][:-4]))
    filename = max_file["name"]
    
    # 📥 הורדת הקובץ שנבחר
    url_download = "https://www.call2all.co.il/ym/api/DownloadFile"
    params = {"token": TOKEN, "path": f"ivr2:/9/{filename}"}
    response = requests.get(url_download, params=params)
    
    if response.status_code == 200 and response.content:
        with open("input.wav", "wb") as f:
            f.write(response.content)
        print(f"\U0001F4E5 הקובץ {filename} ירד בהצלחה")
        return "input.wav"
    else:
        print("❌ לא הצליח להוריד את הקובץ")
        return None


def transcribe_audio(filename):
    r = sr.Recognizer()
    with sr.AudioFile(filename) as source:
        audio = r.record(source)
    try:
        text = r.recognize_google(audio, language="he-IL")
        print(f"\U0001F5E3️ זיהוי: {text}")
        return text
    except:
        print("\u274C לא הצליח לזהות דיבור")
        return ""

def load_stock_list(csv_path):
    df = pd.read_csv(csv_path)
    return dict(zip(df['hebrew_name'], df['ticker']))

def get_best_match(query, stock_dict):
    matches = get_close_matches(query, stock_dict.keys(), n=1, cutoff=0.6)
    return matches[0] if matches else None

def get_stock_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")
        if hist.empty or len(hist) < 2:
            return None
        current_price = hist['Close'].iloc[-1]
        price_day = hist['Close'].iloc[-2]
        price_week = hist['Close'].iloc[-6] if len(hist) > 6 else price_day
        price_3mo = hist['Close'].iloc[-66] if len(hist) > 66 else price_day
        price_year = hist['Close'].iloc[0]
        max_price = hist['Close'].max()
        return {
            'current': round(current_price, 2),
            'day': round((current_price - price_day) / price_day * 100, 2),
            'week': round((current_price - price_week) / price_week * 100, 2),
            '3mo': round((current_price - price_3mo) / price_3mo * 100, 2),
            'year': round((current_price - price_year) / price_year * 100, 2),
            'from_high': round((current_price - max_price) / max_price * 100, 2)
        }
    except:
        return None

def format_text(name, ticker, data):
    return (
        f"נמצאה מניה בשם {name}, סימול {ticker}. "
        f"המחיר הנוכחי הוא {data['current']} שקלים. "
        f"שינוי יומי: {data['day']} אחוז. "
        f"שינוי שבועי: {data['week']} אחוז. "
        f"שינוי בשלושה חודשים: {data['3mo']} אחוז. "
        f"שינוי מתחילת השנה: {data['year']} אחוז. "
        f"המניה רחוקה מהשיא ב־{abs(data['from_high'])} אחוז."
    )

async def create_audio(text, filename="output.mp3"):
    communicate = edge_tts.Communicate(text, voice="he-IL-AvriNeural")
    await communicate.save(filename)

def convert_mp3_to_wav(mp3_file, wav_file):
    subprocess.run(["ffmpeg", "-y", "-i", mp3_file, "-ar", "8000", "-ac", "1", "-acodec", "pcm_s16le", wav_file])

def upload_to_yemot(wav_file):
    url = "https://www.call2all.co.il/ym/api/UploadFile"
    m = MultipartEncoder(
        fields={"token": TOKEN, "path": "ivr2:/8/001.wav", "upload": (wav_file, open(wav_file, 'rb'), 'audio/wav')}
    )
    response = requests.post(url, data=m, headers={'Content-Type': m.content_type})
    print("\u2B06️ קובץ עלה לשלוחה 8")

def delete_yemot_file():
    url = "https://www.call2all.co.il/ym/api/DeleteFile"
    params = {"token": TOKEN, "path": "ivr2:/9/000.wav"}
    requests.get(url, params=params)
    print("\U0001F5D1️ הקובץ נמחק מהשלוחה")

if __name__ == "__main__":
    import shutil
    asyncio.run(main_loop())
