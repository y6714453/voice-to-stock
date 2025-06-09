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

async def main_loop():
    stock_dict = load_stock_list("hebrew_stocks.csv")
    print("\U0001F501 בלולאת בדיקה מתחילה...")
    ensure_ffmpeg()
    last_processed_file = None

    while True:
        file_name, phone = get_last_file_with_phone()

        if not file_name or not phone:
            await asyncio.sleep(1)
            continue

        if file_name == last_processed_file:
            await asyncio.sleep(1)
            continue

        last_processed_file = file_name
        short_phone = phone[-5:]
        print(f"\U0001F4E5 קובץ חדש: {file_name}. מופק על ידי: {short_phone}")

        download_url = "https://www.call2all.co.il/ym/api/DownloadFile"
        r = requests.get(download_url, params={"token": TOKEN, "path": f"ivr2:/9/{file_name}.wav"})
        if r.status_code == 200 and r.content:
            with open("input.wav", "wb") as f:
                f.write(r.content)
        else:
            print("\u274C שגיאה בהורדת קובץ")
            continue

        recognized = transcribe_audio("input.wav")
        if recognized:
            best_match = get_best_match(recognized, stock_dict)
            if best_match:
                ticker, stock_type = stock_dict[best_match]
                data = get_stock_data(ticker)
                if data:
                    text = format_text(best_match, ticker, data, stock_type)
                else:
                    text = f"לא נמצאו נתונים עבור {best_match}"
            else:
                text = "לא זוהה נייר ערך תואם"
        else:
            text = "לא זוהה דיבור ברור"

        await create_audio(text, f"{short_phone}.mp3")
        convert_mp3_to_wav(f"{short_phone}.mp3", f"{short_phone}.wav")
        upload_to_yemot(f"{short_phone}.wav", short_phone)
        delete_yemot_file(f"{file_name}.wav")
        print("\u2705 הושלמה פעולה מחזורית\n")

        await asyncio.sleep(1)

def get_last_file_with_phone():
    url = "https://www.call2all.co.il/ym/api/GetIVR2Dir"
    params = {"token": TOKEN, "path": "9", "full_info": "true"}
    response = requests.get(url, params=params)
    if response.status_code != 200:
        return None, None

    files = response.json().get("files", [])
    valid = [f for f in files if f["name"].endswith(".wav") and f.get("exists")]
    if not valid:
        return None, None

    valid.sort(key=lambda f: f.get("modifyDate", ""), reverse=True)
    last = valid[0]
    file_name = last["name"].replace(".wav", "")
    phone = last.get("caller", "")

    return file_name, phone

def ensure_ffmpeg():
    if not shutil.which("ffmpeg"):
        print("\U0001F527 מוריד ffmpeg...")
        os.makedirs("ffmpeg_bin", exist_ok=True)
        zip_path = "ffmpeg.zip"
        r = requests.get("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip")
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
    return dict(zip(df['hebrew_name'], zip(df['ticker'], df['type'])))

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

def format_text(name, ticker, data, stock_type):
    currency = "שקלים" if ticker.endswith(".TA") else "דולר"
    if stock_type == "מניה":
        return (
            f"נמצאה מניה בשם {name}. המניה נסחרת בשווי של {data['current']} {currency}. "
            f"מתחילת היום נרשמה {'עלייה' if data['day'] > 0 else 'ירידה'} של {abs(data['day'])} אחוז. "
            f"בשלושת החודשים האחרונים נרשמה {'עלייה' if data['3mo'] > 0 else 'ירידה'} של {abs(data['3mo'])} אחוז. "
            f"המחיר הנוכחי רחוק מהשיא ב־{abs(data['from_high'])} אחוז."
        )
    elif stock_type == "מדד":
        return (
            f"נמצא מדד בשם {name}. המדד עומד כעת על {data['current']} נקודות. "
            f"מתחילת היום נרשמה {'עלייה' if data['day'] > 0 else 'ירידה'} של {abs(data['day'])} אחוז. "
            f"בשלושת החודשים האחרונים {'עלייה' if data['3mo'] > 0 else 'ירידה'} של {abs(data['3mo'])} אחוז. "
            f"המדד עומד כעת במרחק של {abs(data['from_high'])} אחוז מהשיא."
        )
    elif stock_type == "מטבע":
        return (
            f"נמצא מטבע בשם {name}. המטבע נסחר כעת בשווי של {data['current']} דולר. "
            f"מתחילת היום {'עלייה' if data['day'] > 0 else 'ירידה'} של {abs(data['day'])} אחוז. "
            f"בשלושת החודשים האחרונים {'עלייה' if data['3mo'] > 0 else 'ירידה'} של {abs(data['3mo'])} אחוז. "
            f"המחיר הנוכחי רחוק מהשיא ב־{abs(data['from_high'])} אחוז."
        )
    else:
        return f"נמצא נייר ערך בשם {name}. המחיר הנוכחי הוא {data['current']} {currency}."

async def create_audio(text, filename="output.mp3"):
    communicate = edge_tts.Communicate(text, voice="he-IL-AvriNeural")
    await communicate.save(filename)

def convert_mp3_to_wav(mp3_file, wav_file):
    subprocess.run(["ffmpeg", "-y", "-i", mp3_file, "-ar", "8000", "-ac", "1", "-acodec", "pcm_s16le", wav_file])

def upload_to_yemot(wav_file, short_name):
    url = "https://www.call2all.co.il/ym/api/UploadFile"
    m = MultipartEncoder(
        fields={"token": TOKEN, "path": f"ivr2:/99/{short_name}.wav", "upload": (wav_file, open(wav_file, 'rb'), 'audio/wav')}
    )
    response = requests.post(url, data=m, headers={'Content-Type': m.content_type})
    print("\u2B06️ קובץ עלה לשלוחה 99")

def delete_yemot_file(file_name):
    url = "https://www.call2all.co.il/ym/api/DeleteFile"
    params = {"token": TOKEN, "path": f"ivr2:/9/{file_name}"}
    requests.get(url, params=params)
    print(f"\U0001F5D1️ הקובץ {file_name} נמחק מהשלוחה")

if __name__ == "__main__":
    asyncio.run(main_loop())
