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

units = ["", "אחד", "שתיים", "שלוש", "ארבע", "חמש", "שש", "שבע", "שמונה", "תשע"]
tens = ["", "עשר", "עשרים", "שלושים", "ארבעים", "חמישים", "שישים", "שבעים", "שמונים", "תשעים"]


def number_to_words(n):
    if n >= 1000:
        return str(int(n))
    int_part = int(n)
    frac_part = round(n - int_part, 2)
    words = []
    if int_part >= 100:
        words.append(str(int_part))
    elif int_part >= 20:
        t = int_part // 10
        u = int_part % 10
        words.append(tens[t])
        if u:
            words.append(units[u])
    elif int_part >= 10:
        words.append(str(int_part))
    elif int_part > 0:
        words.append(units[int_part])
    else:
        words.append("אפס")

    if frac_part > 0:
        decimal = int(round(frac_part * 100))
        words.append("נקודה")
        words.append(str(decimal))

    return " ".join(words)


def spell_price(p):
    return number_to_words(p) + " שקלים חדשים"


def spell_percent(p):
    return number_to_words(abs(p)) + " אחוז"


def describe_change(title, p):
    if p == 0:
        return f"{title} נרשם שינוי אפסי."
    direction = "עלייה" if p > 0 else "ירידה"
    return f"{title} נרשמה {direction} של {spell_percent(p)}."


def ensure_ffmpeg():
    if not shutil.which("ffmpeg"):
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
        return None, None

    data = response.json()
    files = data.get("files", [])
    valid_files = [(int(re.match(r"(\\d+)\\.wav$", f["name"]).group(1)), f["name"]) for f in files if f.get("exists", False) and f["name"].endswith(".wav") and re.match(r"(\\d+)\\.wav$", f["name"])]
    if not valid_files:
        return None, None

    max_number, max_name = max(valid_files)
    download_url = "https://www.call2all.co.il/ym/api/DownloadFile"
    download_params = {"token": TOKEN, "path": f"ivr2:/9/{max_name}"}
    r = requests.get(download_url, params=download_params)
    if r.status_code == 200 and r.content:
        with open("input.wav", "wb") as f:
            f.write(r.content)
        return "input.wav", max_name
    return None, None


def delete_yemot_file(file_name):
    url = "https://www.call2all.co.il/ym/api/DeleteFile"
    params = {"token": TOKEN, "path": f"ivr2:/9/{file_name}"}
    requests.get(url, params=params)


def transcribe_audio(filename):
    r = sr.Recognizer()
    with sr.AudioFile(filename) as source:
        audio = r.record(source)
    try:
        return r.recognize_google(audio, language="he-IL")
    except:
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
        current = hist['Close'].iloc[-1]
        day = hist['Close'].iloc[-2]
        week = hist['Close'].iloc[-6] if len(hist) > 6 else day
        mo3 = hist['Close'].iloc[-66] if len(hist) > 66 else day
        year = hist['Close'].iloc[0]
        high = hist['Close'].max()
        return {
            'current': current,
            'day': ((current - day) / day) * 100,
            'week': ((current - week) / week) * 100,
            '3mo': ((current - mo3) / mo3) * 100,
            'year': ((current - year) / year) * 100,
            'from_high': ((current - high) / high) * 100
        }
    except:
        return None


def format_text(name, ticker, data):
    return (
        f"נמצאה מניית {name}. "
        f"המנייה נסחרת כעת בשווי של {spell_price(data['current'])}. "
        f"{describe_change('מתחילת היום', data['day'])} "
        f"{describe_change('מתחילת השבוע', data['week'])} "
        f"{describe_change('בשלושת החודשים האחרונים', data['3mo'])} "
        f"{describe_change('מתחילת השנה', data['year'])} "
        f"המחיר הנוכחי רחוק מהשיא ב־{spell_percent(data['from_high'])}."
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


async def main_loop():
    stock_dict = load_stock_list("hebrew_stocks.csv")
    ensure_ffmpeg()
    last_processed_file = None

    while True:
        filename, file_name_only = download_yemot_file()
        if filename and file_name_only != last_processed_file:
            last_processed_file = file_name_only
            recognized = transcribe_audio(filename)
            if recognized:
                best_match = get_best_match(recognized, stock_dict)
                if best_match:
                    ticker = stock_dict[best_match]
                    data = get_stock_data(ticker)
                    text = format_text(best_match, ticker, data) if data else "לא נמצאו נתונים מתאימים לזיהוי המניה"
                else:
                    text = "לא נמצאו נתונים מתאימים לזיהוי המניה"
                await create_audio(text, "output.mp3")
                convert_mp3_to_wav("output.mp3", "output.wav")
                upload_to_yemot("output.wav")
                delete_yemot_file(file_name_only)
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main_loop())
