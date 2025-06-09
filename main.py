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
import re
import shutil

USERNAME = "0733181201"
PASSWORD = "6714453"
TOKEN = f"{USERNAME}:{PASSWORD}"
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

async def main_loop():
    stock_dict = load_stock_list("hebrew_stocks.csv")
    print("🔁 בלולאת בדיקה מתחילה...")

    ensure_ffmpeg()
    last_processed_file = None

    while True:
        filename, file_name_only = download_yemot_file()

        if not file_name_only:
            await asyncio.sleep(1)
            continue

        if file_name_only == last_processed_file:
            print(f"🔍 נמצא הקובץ: {file_name_only}")
            await asyncio.sleep(1)
            continue

        last_processed_file = file_name_only
        print(f"📥 קובץ חדש לזיהוי: {file_name_only}")

        if filename:
            recognized = transcribe_audio(filename)
            if recognized:
                best_match = get_best_match(recognized, stock_dict)
                if best_match:
                    ticker = stock_dict[best_match]
                    data = get_stock_data(ticker)
                    if data:
                        text = format_text(best_match, ticker, data)
                    else:
                        text = f"לא נמצאו נתונים עבור {best_match}"
                else:
                    text = "לא זוהה נייר ערך תואם"
            else:
                text = "לא זוהה דיבור ברור"

            await create_audio(text, "output.mp3")
            convert_mp3_to_wav("output.mp3", "output.wav")
            upload_to_yemot("output.wav")
            delete_yemot_file(file_name_only)
            print("✅ הושלמה פעולה מחזורית\n")

        await asyncio.sleep(1)

def ensure_ffmpeg():
    if not shutil.which("ffmpeg"):
        print("🔧 מוריד ffmpeg...")
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
    url = "https://www.call2all.co.il/ym/api/GetIVR2Dir"
    params = {"token": TOKEN, "path": "9"}
    response = requests.get(url, params=params)

    if response.status_code != 200:
        print("❌ שגיאה בשליפת הקבצים")
        return None, None

    data = response.json()
    files = data.get("files", [])
    if not files:
        print("📭 אין קבצים בשלוחה")
        return None, None

    numbered_wav_files = []
    for f in files:
        name = f.get("name", "")
        if not f.get("exists", False):
            continue
        if not name.endswith(".wav"):
            continue
        if name.startswith("M"):
            continue
        match = re.match(r"(\d+)\.wav$", name)
        if match:
            number = int(match.group(1))
            numbered_wav_files.append((number, name))

    if not numbered_wav_files:
        print("📭 אין קובצי WAV תקינים")
        return None, None

    max_number, max_name = max(numbered_wav_files, key=lambda x: x[0])
    print(f"🔍 נמצא הקובץ: {max_name}")

    download_url = "https://www.call2all.co.il/ym/api/DownloadFile"
    download_params = {"token": TOKEN, "path": f"ivr2:/9/{max_name}"}
    r = requests.get(download_url, params=download_params)

    if r.status_code == 200 and r.content:
        with open("input.wav", "wb") as f:
            f.write(r.content)
        return "input.wav", max_name
    else:
        print("❌ שגיאה בהורדת הקובץ")
        return None, None

def delete_yemot_file(file_name):
    url = "https://www.call2all.co.il/ym/api/DeleteFile"
    params = {"token": TOKEN, "path": f"ivr2:/9/{file_name}"}
    requests.get(url, params=params)
    print(f"🗑️ הקובץ {file_name} נמחק מהשלוחה")

def transcribe_audio(filename):
    r = sr.Recognizer()
    with sr.AudioFile(filename) as source:
        audio = r.record(source)
    try:
        text = r.recognize_google(audio, language="he-IL")
        print(f"🗣️ זיהוי: {text}")
        return text
    except:
        print("❌ לא הצליח לזהות דיבור")
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
        f"נמצאה מניה בשם {name}. המניה נסחרת כעת בשווי של {data['current']} דולר. "
        f"מתחילת היום נרשמה {'עלייה' if data['day'] > 0 else 'ירידה'} של {abs(data['day'])} אחוז. "
        f"מתחילת השבוע נרשמה {'עלייה' if data['week'] > 0 else 'ירידה'} של {abs(data['week'])} אחוז. "
        f"בשלושת החודשים האחרונים נרשמה {'עלייה' if data['3mo'] > 0 else 'ירידה'} של {abs(data['3mo'])} אחוז. "
        f"מתחילת השנה נרשמה {'עלייה' if data['year'] > 0 else 'ירידה'} של {abs(data['year'])} אחוז. "
        f"המחיר הנוכחי רחוק מהשיא ב־{abs(data['from_high'])} אחוז."
    )

async def create_audio(text, filename="output.mp3"):
    communicate = edge_tts.Communicate(text, voice="he-IL-AvriNeural")
    await communicate.save(filename)

def convert_mp3_to_wav(mp3_file, wav_file):
    subprocess.run(["ffmpeg", "-y", "-i", mp3_file, "-ar", "8000", "-ac", "1", "-acodec", "pcm_s16le", wav_file])

def upload_to_yemot(wav_file):
    url = "https://www.call2all.co.il/ym/api/UploadFile"
    m = MultipartEncoder(
        fields={"token": TOKEN, "path": "ivr2:/99/001.wav", "upload": (wav_file, open(wav_file, 'rb'), 'audio/wav')}
    )
    response = requests.post(url, data=m, headers={'Content-Type': m.content_type})
    print("⬆️ קובץ עלה לשלוחה 99")

if __name__ == "__main__":
    asyncio.run(main_loop())
