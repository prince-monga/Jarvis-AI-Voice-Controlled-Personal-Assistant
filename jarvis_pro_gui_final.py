"""
Jarvis AI - Pro (GUI + Voice control + App open/close + Inside-app tasks)
Final file with:
 - Multilingual (English, Hindi, Punjabi) listening
 - Auto-language reply (Jarvis replies in the language you spoke)
 - Translation features (using googletrans when available)
 - GUI language selector (Auto / en / hi / pa) and small Translate panel
 - Graceful fallbacks when optional deps missing

Author: (Your Name) - adapted for Prince
Save as jarvis_pro_gui_final.py and run: python jarvis_pro_gui_final.py
"""

import threading
import queue
import time
import os
import sys
import webbrowser
import subprocess
import datetime
from pathlib import Path
from typing import Optional

# optional imports with graceful fallbacks
try:
    import speech_recognition as sr
except Exception:
    sr = None

try:
    import pyttsx3
except Exception:
    pyttsx3 = None

try:
    import requests
except Exception:
    requests = None

try:
    import pywhatkit
except Exception:
    pywhatkit = None

try:
    import pyautogui
except Exception:
    pyautogui = None

try:
    from rapidfuzz import fuzz, process
    _HAS_RAPIDFUZZ = True
except Exception:
    import difflib
    _HAS_RAPIDFUZZ = False

# translation library (optional)
try:
    from googletrans import Translator as GoogleTranslator
    _HAS_GOOGLETRANS = True
except Exception:
    GoogleTranslator = None
    _HAS_GOOGLETRANS = False

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext
except Exception:
    tk = None

# ---------------- CONFIG ----------------
config = {
    "OPENWEATHER_API_KEY": "PUT_YOUR_OPENWEATHER_API_KEY_HERE",
    "USER_NAME": "Prince",
    "NOTES_FILE": "jarvis_notes_gui.txt",
    "WAKE_WORDS": ["jarvis", "hey jarvis", "ok jarvis", "prince", "please","Riya","hey Riya","ok Riya","please Riya"],
    # Map friendly app names to file paths (Windows) or command names (mac/linux)
    "APPS": {
       # Browsers
    "chrome": r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "brave": r"C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
    "edge": r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",

    # Code & Editors
    "vscode": r"C:\\Users\\princ\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe",
    "notepad": "notepad.exe",

    # System Apps
    "file explorer": r"C:\\Windows\\explorer.exe",
    "explorer": r"C:\\Windows\\explorer.exe",
    "cmd": r"C:\\Windows\\System32\\cmd.exe",
    "command prompt": r"C:\\Windows\\System32\\cmd.exe",
    "powershell": r"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
    "terminal": r"C:\\Users\\princ\\AppData\\Local\\Microsoft\\WindowsApps\\wt.exe",

    # Basic Windows Tools
    "calculator": "calc",
    "paint": r"C:\\Windows\\System32\\mspaint.exe",
    "camera": r"microsoft.windows.camera:",
    "snipping tool": r"C:\\Windows\\System32\\SnippingTool.exe",

    # Settings & Controls
    "settings": "ms-settings:",
    "wifi": "ms-settings:network-wifi",
    "bluetooth": "ms-settings:bluetooth",
    "update": "ms-settings:windowsupdate",
    "display": "ms-settings:display",
    "sound": "ms-settings:sound",
    "power": "ms-settings:powersleep",
    "battery": "ms-settings:batterysaver",
    "apps settings": "ms-settings:appsfeatures",

    # Control Panels
    "control panel": r"C:\\Windows\\System32\\control.exe",
    "system info": r"C:\\Windows\\System32\\msinfo32.exe",

    # Admin / Task Tools
    "task manager": r"C:\\Windows\\System32\\Taskmgr.exe",
    "run": r"C:\\Windows\\System32\\run.exe"  # Opens Run dialog
    },
    # languages to attempt for recognition (order)
    "LANGUAGES": ["en-IN", "hi-IN", "pa-IN"],
    # "RESPONSE_LANGUAGE": "auto" (auto means follow speaker if auto_reply enabled)
    "RESPONSE_LANGUAGE": "en",  # default speaking language (en / hi / pa / auto)
    "AUTO_LANGUAGE_REPLY": True,  # if True, Jarvis replies in the same language the user spoke
}
# ----------------------------------------

def resolve_path(path: str) -> str:
    if not path:
        return path
    return os.path.expanduser(os.path.expandvars(path))


class TTS:
    def __init__(self, config_ref):
        self.engine = None
        self.config = config_ref
        if pyttsx3:
            try:
                self.engine = pyttsx3.init()
                rate = self.engine.getProperty("rate")
                # slightly slower
                self.engine.setProperty("rate", int(rate * 0.95))
            except Exception:
                self.engine = None


        # optional googletrans fallback TTS could be added, but to keep simple we use pyttsx3 only
        # note: pyttsx3 voices vary by system. We'll try to pick a voice matching language codes.

    def _find_voice_for_lang(self, target_lang_code: str):
        """Try to find a voice id that matches the short language code (en, hi, pa)."""
        if not self.engine or not target_lang_code:
            return None
        try:
            voices = self.engine.getProperty("voices")
            for v in voices:
                # try multiple heuristics: v.languages, v.id, v.name
                try:
                    langs = []
                    if hasattr(v, 'languages') and v.languages:
                        # languages can be like [b'\x05en_GB'] or ['en_US']
                        for L in v.languages:
                            if isinstance(L, bytes):
                                try:
                                    langs.append(L.decode('utf-8', errors='ignore'))
                                except Exception:
                                    pass
                            else:
                                langs.append(str(L))
                    # combine properties
                    searchable = " ".join([str(v.id or ""), str(v.name or "")] + langs).lower()
                    if target_lang_code in searchable or f"{target_lang_code}-" in searchable or f"{target_lang_code}_" in searchable:
                        return v.id
                except Exception:
                    continue
            # fallback heuristics: 'hindi' or 'punjabi' in name
            for v in voices:
                try:
                    name_search = (v.name or "").lower()
                    if target_lang_code == "hi" and ("hindi" in name_search or "hind" in name_search):
                        return v.id
                    if target_lang_code == "pa" and ("punjabi" in name_search or "punjabi" in name_search):
                        return v.id
                except Exception:
                    continue
        except Exception:
            return None
        return None

    def speak(self, text: str, lang: Optional[str] = None):
        """Speak text. lang is short code: 'en', 'hi', 'pa', or None to use config."""
        if not text:
            return
        # decide language
        if lang is None:
            resp_lang = self.config.get("RESPONSE_LANGUAGE", "en")
            if resp_lang == "auto":
                resp_lang = "en"
        else:
            resp_lang = lang

        print("Jarvis:", text)
        if self.engine:
            try:
                # try to set voice if we can find appropriate one
                voice_id = None
                short = None
                if resp_lang and len(resp_lang) >= 2:
                    # given values in config may be 'en' or 'hi' or 'pa' or full like 'en-IN'
                    short = resp_lang.split("-")[0]
                if short:
                    voice_id = self._find_voice_for_lang(short)
                if voice_id:
                    try:
                        self.engine.setProperty("voice", voice_id)
                    except Exception:
                        pass
                # speak in background thread
                threading.Thread(target=self._say, args=(text,), daemon=True).start()
            except Exception:
                pass

    def _say(self, text: str):
        try:
            self.engine.say(text)
            self.engine.runAndWait()
        except Exception:
            pass


class JarvisCore:
    def __init__(self, config: dict, out_queue: queue.Queue):
        self.config = config
        self.out_queue = out_queue
        self.username = config.get("USER_NAME", "User")
        self.notes_file = Path(config.get("NOTES_FILE", "jarvis_notes_gui.txt"))
        self.notes_file.parent.mkdir(parents=True, exist_ok=True)
        self.notes_file.touch(exist_ok=True)
        self.wake_words = config.get("WAKE_WORDS", [])
        self.recognizer = sr.Recognizer() if sr else None
        self.tts = TTS(config)
        self.listening = False
        self._stop_listening_flag = threading.Event()
        self.translator = GoogleTranslator() if _HAS_GOOGLETRANS else None
        self.last_detected_lang = "en"  # short code like 'en', 'hi', 'pa'

    def _put(self, typ: str, payload):
        try:
            self.out_queue.put((typ, payload))
        except Exception:
            pass

    def speak(self, text: str, lang: Optional[str] = None):
        # if auto-reply enabled, prefer last_detected_lang
        if self.config.get("AUTO_LANGUAGE_REPLY", False):
            lang_to_use = self.last_detected_lang or lang or self.config.get("RESPONSE_LANGUAGE", "en")
        else:
            # use explicit RESPONSE_LANGUAGE unless set to 'auto'
            resp = self.config.get("RESPONSE_LANGUAGE", "en")
            if resp == "auto":
                lang_to_use = self.last_detected_lang or lang or "en"
            else:
                lang_to_use = lang or resp
        # normalize to short codes
        if isinstance(lang_to_use, str) and "-" in lang_to_use:
            lang_to_use = lang_to_use.split("-")[0]
        # finally speak
        self.tts.speak(text, lang=lang_to_use)
        self._put("status", f"Spoke: {text}")

    def listen_once(self, timeout: Optional[int] = None, phrase_time_limit: Optional[int] = None) -> Optional[str]:
        """
        Listen once and try to recognize speech. We attempt multiple languages (config LANGUAGES).
        After recognition, detect language (if translator available) and set last_detected_lang.
        """
        if not self.recognizer:
            self._put("status", "SpeechRecognition not available")
            return None
        try:
            with sr.Microphone() as source:
                self._put("status", "Listening...")
                try:
                    self.recognizer.adjust_for_ambient_noise(source, duration=0.4)
                except Exception:
                    pass
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
                self._put("status", "Recognizing...")
                # try multiple languages
                detected_text = None
                for lang in self.config.get("LANGUAGES", ["en-IN"]):
                    try:
                        text = self.recognizer.recognize_google(audio, language=lang)
                        if text:
                            detected_text = text
                            break
                    except sr.UnknownValueError:
                        continue
                    except Exception:
                        continue

                if not detected_text:
                    self._put("status", "Could not understand audio")
                    return None

                # detected_text now holds string. detect language using translator if possible
                text_low = detected_text.lower()
                detected_lang_short = "en"
                if self.translator:
                    try:
                        det = self.translator.detect(detected_text)
                        if det and hasattr(det, 'lang'):
                            # map to short code (googletrans returns 'en', 'hi', 'pa')
                            detected_lang_short = det.lang.split('-')[0]
                    except Exception:
                        # fallback heuristic: check presence of Hindi/Punjabi words
                        detected_lang_short = self._heuristic_lang_detect(text_low)
                else:
                    detected_lang_short = self._heuristic_lang_detect(text_low)

                # update last detected
                self.last_detected_lang = detected_lang_short
                self._put("last_command", detected_text)
                return detected_text.lower()
        except sr.WaitTimeoutError:
            self._put("status", "Listen timeout")
            return None
        except sr.UnknownValueError:
            self._put("status", "Could not understand audio")
            return None
        except sr.RequestError as e:
            self._put("status", f"Speech service error: {e}")
            return None
        except Exception as e:
            self._put("status", f"Unexpected listening error: {e}")
            return None

    def _heuristic_lang_detect(self, text: str) -> str:
        """Very small heuristic if googletrans not available: look for Devanagari or Punjabi words."""
        # Devanagari unicode range roughly \u0900-\u097F
        if any('\u0900' <= ch <= '\u097F' for ch in text):
            return 'hi'
        # presence of common Hindi words (in latin) - weak heuristic
        hi_tokens = ['kya', 'hai', 'hamesha', 'kar', 'kaun', 'ka']
        pa_tokens = ['ki', 'ki', 'hun', 'haan', 'kiven', 'kidaan', 'sadda']
        words = text.split()
        for t in words:
            if t in hi_tokens:
                return 'hi'
            if t in pa_tokens:
                return 'pa'
        # default
        return 'en'

    def is_wake_word(self, text: str) -> bool:
        if not text:
            return False
        for w in self.wake_words:
            if w in text:
                return True
        return False

    # fuzzy app name matcher
    def fuzzy_match(self, command: str, choices: dict):
        if not choices:
            return None
        if _HAS_RAPIDFUZZ:
            best = process.extractOne(command, choices.keys(), scorer=fuzz.ratio)
            if best and best[1] >= 60:
                return best[0]
            return None
        else:
            keys = list(choices.keys())
            matches = difflib.get_close_matches(command, keys, n=1, cutoff=0.5)
            return matches[0] if matches else None

    # Open application by config name or command
    def handle_open_app(self, command: str):
        for name, path in self.config.get("APPS", {}).items():
            if name in command:
                resolved = resolve_path(path)
                try:
                    if sys.platform.startswith("win"):
                        os.startfile(resolved)
                    elif sys.platform == "darwin":
                        subprocess.Popen(["open", resolved])
                    else:
                        if os.path.exists(resolved):
                            subprocess.Popen([resolved])
                        else:
                            subprocess.Popen(resolved.split())
                    self.speak(f"Opening {name}")
                    return
                except Exception as e:
                    print("open app error", e)
                    self.speak(f"Couldn't open {name}")
                    return
        # fallback: youtube or web
        if "youtube" in command:
            webbrowser.open("https://www.youtube.com")
            self.speak("Opening YouTube")
            return
        best = self.fuzzy_match(command, self.config.get("APPS", {}))
        if best:
            try:
                resolved = resolve_path(self.config['APPS'][best])
                if sys.platform.startswith('win'):
                    os.startfile(resolved)
                elif sys.platform == 'darwin':
                    subprocess.Popen(['open', resolved])
                else:
                    if os.path.exists(resolved):
                        subprocess.Popen([resolved])
                    else:
                        subprocess.Popen(resolved.split())
                self.speak(f"Opening {best}")
                return
            except Exception as e:
                print("fuzzy open error", e)
        self.speak("I could not find that application. Please add it to APPS in config.")

    # Close application by name (best-effort) - cross-platform
    def handle_close_app(self, command: str):
        target = command
        for w in ["close", "kill", "stop", "exit"]:
            target = target.replace(w, "")
        target = target.strip()
        if not target:
            self.speak("Which application should I close?")
            resp = self.listen_once(timeout=5, phrase_time_limit=4)
            if not resp:
                return
            target = resp
        # try config mapping
        for name, path in self.config.get("APPS", {}).items():
            if name in target:
                proc_name = os.path.basename(path)
                try:
                    if sys.platform.startswith('win'):
                        subprocess.run(["taskkill", "/f", "/im", proc_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        subprocess.run(["pkill", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.speak(f"Attempted to close {name}")
                    return
                except Exception as e:
                    print("close error", e)
                    self.speak("Failed to close application")
                    return
        # generic close attempts
        try:
            if sys.platform.startswith('win'):
                subprocess.run(["taskkill", "/f", "/im", f"{target}.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.run(["pkill", "-f", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.speak(f"Attempted to close {target}")
        except Exception as e:
            print("close generic error", e)
            self.speak("Failed to close app")

    # Inside-app tasks using pyautogui
    def handle_inside_task(self, command: str):
        if not pyautogui:
            self.speak("pyautogui not installed. Install it to use inside-app tasks.")
            return
        # simple parsing
        if "type" in command:
            text = command.split("type", 1)[1].strip()
            pyautogui.typewrite(text, interval=0.05)
            self.speak("Typed the text")
        elif "press enter" in command or "press return" in command:
            pyautogui.press('enter')
            self.speak("Pressed enter")
        elif "press escape" in command or "press esc" in command:
            pyautogui.press('esc')
            self.speak("Pressed escape")
        elif "new tab" in command:
            pyautogui.hotkey('ctrl', 't')
            self.speak('Opened new tab')
        elif "close tab" in command:
            pyautogui.hotkey('ctrl', 'w')
            self.speak('Closed tab')
        elif "copy" in command:
            pyautogui.hotkey('ctrl', 'c')
            self.speak('Copied')
        elif "paste" in command:
            pyautogui.hotkey('ctrl', 'v')
            self.speak('Pasted')
        else:
            self.speak("Task not recognized for inside-app automation.")

    def handle_search(self, command: str):
        query = command
        for trigger in ["search for", "search", "google"]:
            if trigger in command:
                query = command.split(trigger, 1)[-1].strip()
                break
        if not query:
            self.speak("What should I search for?")
            q = self.listen_once(timeout=5, phrase_time_limit=8)
            if not q:
                self.speak("No query received.")
                return
            query = q
        url = f"https://www.google.com/search?q={requests.utils.requote_uri(query) if requests else query}"
        webbrowser.open(url)
        self.speak(f"Here are the results for {query}")

    def handle_play_youtube(self, command: str):
        query = command
        for trigger in ["play on youtube", "play youtube", "play"]:
            if trigger in command:
                query = command.split(trigger, 1)[-1].strip()
                break
        if not query:
            self.speak("What should I play on YouTube?")
            q = self.listen_once(timeout=6, phrase_time_limit=8)
            if not q:
                self.speak("No query provided.")
                return
            query = q
        self.speak(f"Playing {query} on YouTube")
        if pywhatkit:
            try:
                pywhatkit.playonyt(query)
            except Exception:
                webbrowser.open(f"https://www.youtube.com/results?search_query={query}")
        else:
            webbrowser.open(f"https://www.youtube.com/results?search_query={query}")

    def handle_weather(self, command: str):
        if not requests:
            self.speak("Requests not available. Can't fetch weather.")
            return
        city = None
        if " in " in command:
            city = command.split(" in ", 1)[1].strip()
        else:
            words = command.split()
            if words:
                city = words[-1]
        if not city:
            self.speak("Which city?")
            city = self.listen_once(timeout=5, phrase_time_limit=5)
            if not city:
                self.speak("No city specified.")
                return
        api_key = '0af251d9cd7937c07fa0bc56d4d9bff0'
        if not api_key or api_key.startswith('PUT_YOUR'):
            self.speak('Weather API key not configured. Please update config.')
            return
        try:
            resp = requests.get(f"https://api.openweathermap.org/data/2.5/weather?units=metric&q={requests.utils.requote_uri(city)}&appid={api_key}&units=metric", timeout=8)
            data = resp.json()
            if resp.status_code != 200:
                self.speak(f"Couldn't fetch weather: {data.get('message', 'unknown')}")
                return
            desc = data['weather'][0]['description']
            temp = data['main']['temp']
            self.speak(f"Weather in {city}: {desc}, {temp} degree Celsius")
        except Exception as e:
            print('weather error', e)
            self.speak('Failed to fetch weather right now.')

    def handle_notes(self, command: str):
        fn = self.notes_file
        action = None
        if any(k in command for k in ["write", "take note", "add note"]):
            action = 'write'
        elif any(k in command for k in ["read", "show notes", "list notes"]):
            action = 'read'
        elif any(k in command for k in ["delete", "clear notes", "remove notes"]):
            action = 'delete'
        else:
            self.speak('Write, read, or delete notes?')
            resp = self.listen_once(timeout=5, phrase_time_limit=4)
            if not resp:
                self.speak('No response. Cancelling notes.')
                return
            if 'write' in resp or 'add' in resp:
                action = 'write'
            elif 'read' in resp or 'show' in resp:
                action = 'read'
            elif 'delete' in resp or 'clear' in resp:
                action = 'delete'
        if action == 'write':
            self.speak('What should I write?')
            note = self.listen_once(timeout=8, phrase_time_limit=15)
            if not note:
                self.speak('No note content detected.')
                return
            ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with fn.open('a', encoding='utf-8') as f:
                f.write(f'[{ts}] {note}\n')
            self.speak('Note saved.')
            self._put('notes_updated', None)
        elif action == 'read':
            if not fn.exists() or fn.stat().st_size == 0:
                self.speak('No notes found.')
                return
            with fn.open('r', encoding='utf-8') as f:
                lines = f.readlines()[-10:]
                for line in lines:
                    self.speak(line.strip())
        elif action == 'delete':
            self.speak('Are you sure you want to clear all notes? Say yes to confirm.')
            conf = self.listen_once(timeout=5, phrase_time_limit=4)
            if conf and 'yes' in conf:
                fn.write_text('')
                self.speak('All notes cleared.')
                self._put('notes_updated', None)
            else:
                self.speak('Delete cancelled.')

    def handle_time_date(self, _=None):
        now = datetime.datetime.now()
        self.speak(f"It is {now.strftime('%I:%M %p on %A, %B %d, %Y')}")

    # Translation helpers
    def translate_text(self, text: str, dest: str = "en") -> str:
        if not text:
            return ""
        dest_short = dest.split("-")[0] if "-" in dest else dest
        if self.translator:
            try:
                res = self.translator.translate(text, dest=dest_short)
                return res.text
            except Exception:
                # fallback: return original
                return text
        else:
            # no translator available
            return text

    def process_command(self, command: str):
        if not command:
            return
        command = command.lower()
        # strip wake words
        for w in self.config.get('WAKE_WORDS', []):
            if w in command:
                command = command.replace(w, '').strip()

        # special language commands
        if "speak hindi" in command or "bol hindi" in command:
            self.config["RESPONSE_LANGUAGE"] = "hi"
            self.config["AUTO_LANGUAGE_REPLY"] = False
            self.speak("अब मैं हिंदी में बात करूँगा।", lang="hi")
            return
        if "speak punjabi" in command or "bol punjabi" in command or "bol panjabi" in command:
            self.config["RESPONSE_LANGUAGE"] = "pa"
            self.config["AUTO_LANGUAGE_REPLY"] = False
            # Punjabi phrase - written in Gurmukhi
            self.speak("ਹੁਣ ਮੈਂ ਪੰਜਾਬੀ ਵਿੱਚ ਗੱਲ ਕਰਾਂਗਾ।", lang="pa")
            return
        if "speak english" in command or "bol english" in command:
            self.config["RESPONSE_LANGUAGE"] = "en"
            self.config["AUTO_LANGUAGE_REPLY"] = False
            self.speak("I will now speak in English.", lang="en")
            return
        if "auto language reply" in command or "auto reply" in command or "auto language" in command:
            self.config["AUTO_LANGUAGE_REPLY"] = not self.config.get("AUTO_LANGUAGE_REPLY", False)
            state = "enabled" if self.config["AUTO_LANGUAGE_REPLY"] else "disabled"
            self.speak(f"Auto language reply {state}.")
            return

        # translate command: "translate to hi <text>" or "translate <text> to pa"
        if command.startswith("translate ") or command.startswith("translate to ") or " translate to " in command:
            # naive parser
            dest = "en"
            text = ""
            if " to " in command:
                # eg "translate hello to hi" or "translate to hi hello"
                parts = command.split(" to ")
                if parts[0].strip() == "translate":
                    # form: translate to hi something OR translate to hi
                    after = parts[1].strip()
                    toks = after.split()
                    if len(toks) >= 2:
                        dest = toks[0]
                        text = " ".join(toks[1:])
                    else:
                        dest = toks[0]
                        text = ""
                else:
                    # form: translate some text to hi
                    dest = parts[-1].strip().split()[0]
                    text = " to ".join(parts[:-1]).replace("translate", "").strip()
            else:
                text = command.replace("translate", "").strip()
            if not text:
                self.speak("What text should I translate?")
                q = self.listen_once(timeout=6, phrase_time_limit=10)
                if not q:
                    self.speak("No text provided for translation.")
                    return
                text = q
            # normalize language codes
            code_map = {"hindi": "hi", "hi": "hi", "english": "en", "en": "en", "punjabi": "pa", "pa": "pa", "panjabi": "pa"}
            if dest.lower() in code_map:
                dest_short = code_map[dest.lower()]
            else:
                dest_short = dest.split("-")[0] if "-" in dest else dest[:2]
            translated = self.translate_text(text, dest_short)
            self.speak(f"Translation: {translated}", lang=dest_short)
            return

        # routing
        if any(k in command for k in ['open', 'launch', 'start']):
            self.handle_open_app(command)
        elif any(k in command for k in ['close', 'kill', 'stop']) and not command.startswith("screenshot"):
            self.handle_close_app(command)
        elif any(k in command for k in ['search', 'google']):
            self.handle_search(command)
        elif any(k in command for k in ['weather', 'temperature', 'forecast']):
            self.handle_weather(command)
        elif any(k in command for k in ['note', 'notes', 'write note', 'take note']):
            self.handle_notes(command)
        elif any(k in command for k in ['play', 'youtube']):
            self.handle_play_youtube(command)
        elif any(k in command for k in ['time', 'date']):
            self.handle_time_date(command)
        elif any(k in command for k in ['type', 'press', 'copy', 'paste', 'new tab', 'close tab']):
            self.handle_inside_task(command)
        elif any(k in command for k in ['exit', 'quit']):
            self.speak('Goodbye.')
            self._put('exit', None)
        else:
            # fallback quick search
            self.speak("I didn't catch that. Should I search the web for it?")
            resp = self.listen_once(timeout=5, phrase_time_limit=6)
            if resp and ('yes' in resp or 'search' in resp):
                self.handle_search(command)
            else:
                self.speak('Okay. Waiting for commands.')

    # Wake-word loop
    def run_wake_word_loop(self):
        if not self.recognizer:
            self._put('status', 'SpeechRecognition not installed; wake-word disabled')
            return
        self.listening = True
        self._stop_listening_flag.clear()
        self._put('status', 'Wake-word mode active')
        while not self._stop_listening_flag.is_set():
            text = self.listen_once(timeout=None, phrase_time_limit=6)
            if not text:
                continue
            if self.is_wake_word(text):
                remainder = text
                for w in self.wake_words:
                    remainder = remainder.replace(w, '')
                remainder = remainder.strip()
                if remainder:
                    self.process_command(remainder)
                else:
                    # ask and process
                    self.speak('Yes? What can I do for you?')
                    cmd = self.listen_once(timeout=6, phrase_time_limit=12)
                    if cmd:
                        self.process_command(cmd)
        self._put('status', 'Wake-word mode stopped')
        self.listening = False

    def start_wake_word(self):
        if self.listening:
            return
        self._stop_listening_flag.clear()
        threading.Thread(target=self.run_wake_word_loop, daemon=True).start()

    def stop_wake_word(self):
        if not self.listening:
            return
        self._stop_listening_flag.set()

    def listen_and_process_once(self):
        text = self.listen_once(timeout=None, phrase_time_limit=12)
        if text:
            for w in self.config.get('WAKE_WORDS', []):
                text = text.replace(w, '')
            text = text.strip()
            self.process_command(text)


class JarvisGUI(tk.Tk):
    def __init__(self, jarvis: JarvisCore):
        super().__init__()
        self.title('Jarvis AI - Pro (Final)')
        self.geometry('860x600')
        self.jarvis = jarvis
        self.out_queue = jarvis.out_queue
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.create_widgets()
        self.after(200, self.check_queue)

    def create_widgets(self):
        pad = 8
        frm_top = ttk.Frame(self)
        frm_top.pack(fill=tk.X, padx=pad, pady=(pad, 0))

        self.status_var = tk.StringVar(value='Idle')
        ttk.Label(frm_top, text='Status:').pack(side=tk.LEFT)
        ttk.Label(frm_top, textvariable=self.status_var, foreground='blue').pack(side=tk.LEFT, padx=(6, 20))

        ttk.Label(frm_top, text='Last Command:').pack(side=tk.LEFT)
        self.last_cmd_var = tk.StringVar(value='None')
        ttk.Label(frm_top, textvariable=self.last_cmd_var, foreground='green').pack(side=tk.LEFT, padx=(6, 20))

        # Language selector and auto checkbox
        ttk.Label(frm_top, text='Response Language:').pack(side=tk.LEFT)
        self.lang_var = tk.StringVar(value=self.jarvis.config.get("RESPONSE_LANGUAGE", "en"))
        lang_choices = ["auto", "en", "hi", "pa"]
        self.lang_combo = ttk.Combobox(frm_top, values=lang_choices, textvariable=self.lang_var, width=6, state="readonly")
        self.lang_combo.pack(side=tk.LEFT, padx=(6, 10))
        self.lang_combo.bind("<<ComboboxSelected>>", self.on_lang_change)

        self.auto_reply_var = tk.BooleanVar(value=self.jarvis.config.get("AUTO_LANGUAGE_REPLY", True))
        self.auto_chk = ttk.Checkbutton(frm_top, text='Auto-reply', variable=self.auto_reply_var, command=self.on_auto_toggle)
        self.auto_chk.pack(side=tk.LEFT, padx=(6, 10))

        ttk.Button(frm_top, text='Start Wake-word', command=self.toggle_wake).pack(side=tk.RIGHT)
        self.wake_btn = ttk.Button(frm_top, text='Push-to-Talk', command=self.push_to_talk)
        self.wake_btn.pack(side=tk.RIGHT, padx=(0,10))

        # Middle: notes, translate and log
        frm_mid = ttk.Frame(self)
        frm_mid.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)

        left_col = ttk.Frame(frm_mid)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        notes_frame = ttk.LabelFrame(left_col, text='Notes')
        notes_frame.pack(fill=tk.BOTH, expand=True, padx=(0,6))
        self.notes_box = scrolledtext.ScrolledText(notes_frame, wrap=tk.WORD, width=40, height=10)
        self.notes_box.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        notes_btns = ttk.Frame(notes_frame)
        notes_btns.pack(fill=tk.X, padx=6, pady=(0,6))
        ttk.Button(notes_btns, text='Refresh Notes', command=self.load_notes).pack(side=tk.LEFT)
        ttk.Button(notes_btns, text='Add Note (text)', command=self.add_note_via_gui).pack(side=tk.LEFT, padx=6)
        ttk.Button(notes_btns, text='Clear Notes', command=self.clear_notes_gui).pack(side=tk.LEFT)

        # Translate panel
        translate_frame = ttk.LabelFrame(left_col, text='Translate (manual)')
        translate_frame.pack(fill=tk.BOTH, expand=False, pady=(8,0))
        ttk.Label(translate_frame, text='Dest (en/hi/pa):').pack(side=tk.LEFT, padx=6)
        self.trans_dest_var = tk.StringVar(value='hi')
        self.trans_entry = ttk.Entry(translate_frame, width=6, textvariable=self.trans_dest_var)
        self.trans_entry.pack(side=tk.LEFT, padx=(0,8))
        self.trans_text_var = tk.StringVar()
        ttk.Entry(translate_frame, textvariable=self.trans_text_var, width=40).pack(side=tk.LEFT, padx=(0,6))
        ttk.Button(translate_frame, text='Translate', command=self.gui_translate).pack(side=tk.LEFT)

        right_col = ttk.Frame(frm_mid)
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        log_frame = ttk.LabelFrame(right_col, text='Activity Log')
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_box = scrolledtext.ScrolledText(log_frame, height=20)
        self.log_box.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Bottom: quick commands
        frm_bottom = ttk.Frame(self)
        frm_bottom.pack(fill=tk.X, padx=pad, pady=(0,pad))
        ttk.Label(frm_bottom, text='Quick Commands:').pack(side=tk.LEFT)
        ttk.Button(frm_bottom, text='Open Chrome', command=lambda: self.run_quick('open chrome')).pack(side=tk.LEFT, padx=6)
        ttk.Button(frm_bottom, text='Search Google', command=self.quick_search_prompt).pack(side=tk.LEFT, padx=6)
        ttk.Button(frm_bottom, text='Play YouTube', command=self.quick_play_prompt).pack(side=tk.LEFT, padx=6)
        ttk.Button(frm_bottom, text='Weather', command=self.quick_weather_prompt).pack(side=tk.LEFT, padx=6)
        ttk.Button(frm_bottom, text='Translate sample', command=lambda: self.run_quick('translate hello to hi')).pack(side=tk.LEFT, padx=6)

        self.load_notes()

    def on_lang_change(self, _evt=None):
        sel = self.lang_var.get()
        self.jarvis.config["RESPONSE_LANGUAGE"] = sel
        self.log(f"Response language set to: {sel}")

    def on_auto_toggle(self):
        val = self.auto_reply_var.get()
        self.jarvis.config["AUTO_LANGUAGE_REPLY"] = val
        self.log(f"Auto language reply: {'ON' if val else 'OFF'}")

    def toggle_wake(self):
        if self.jarvis.listening:
            self.jarvis.stop_wake_word()
            self.status_var.set('Wake-word stopped')
            self.log('Wake-word listening stopped')
        else:
            self.jarvis.start_wake_word()
            self.status_var.set('Wake-word active')
            self.log('Wake-word listening started')

    def push_to_talk(self):
        self.status_var.set('Push-to-Talk: Listening')
        self.log('Push-to-Talk activated')
        threading.Thread(target=self._push_thread, daemon=True).start()

    def _push_thread(self):
        self.jarvis.listen_and_process_once()
        time.sleep(0.5)
        self.status_var.set('Idle')

    def run_quick(self, command: str):
        self.log(f'Quick command: {command}')
        threading.Thread(target=self.jarvis.process_command, args=(command,), daemon=True).start()

    def quick_search_prompt(self):
        q = self.simple_input_dialog('Search Google', 'Enter search query:')
        if q:
            self.run_quick(f'search {q}')

    def quick_play_prompt(self):
        q = self.simple_input_dialog('Play YouTube', 'Enter song or video name:')
        if q:
            self.run_quick(f'play {q}')

    def quick_weather_prompt(self):
        city = self.simple_input_dialog('Weather', 'Enter city name:')
        if city:
            self.run_quick(f'weather in {city}')

    def simple_input_dialog(self, title: str, prompt: str) -> Optional[str]:
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry('420x120')
        ttk.Label(dialog, text=prompt).pack(padx=8, pady=8)
        entry = ttk.Entry(dialog, width=60)
        entry.pack(padx=8)
        entry.focus()
        result = {'value': None}

        def on_ok():
            result['value'] = entry.get().strip()
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        btns = ttk.Frame(dialog)
        btns.pack(pady=8)
        ttk.Button(btns, text='OK', command=on_ok).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text='Cancel', command=on_cancel).pack(side=tk.LEFT)
        self.wait_window(dialog)
        return result['value']

    def add_note_via_gui(self):
        text = self.simple_input_dialog('Add Note', 'Enter note text:')
        if text:
            with self.jarvis.notes_file.open('a', encoding='utf-8') as f:
                ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f'[{ts}] {text}\n')
            self.log('Note added via GUI')
            self.load_notes()

    def load_notes(self):
        try:
            with self.jarvis.notes_file.open('r', encoding='utf-8') as f:
                content = f.read()
            self.notes_box.delete('1.0', tk.END)
            self.notes_box.insert(tk.END, content)
            self.log('Notes refreshed')
        except Exception as e:
            self.log(f'Failed to load notes: {e}')

    def clear_notes_gui(self):
        if messagebox.askyesno('Confirm', 'Clear all notes?'):
            try:
                self.jarvis.notes_file.write_text('')
                self.load_notes()
                self.log('Notes cleared')
            except Exception as e:
                self.log(f'Failed to clear notes: {e}')

    def gui_translate(self):
        dest = self.trans_dest_var.get().strip()
        text = self.trans_text_var.get().strip()
        if not text:
            messagebox.showinfo("Translate", "Enter text to translate.")
            return
        # run in thread
        threading.Thread(target=self._do_translate, args=(text, dest), daemon=True).start()

    def _do_translate(self, text, dest):
        self.log(f"Translating to {dest}: {text}")
        result = self.jarvis.translate_text(text, dest)
        # show result in popup and speak result (in dest language if possible)
        messagebox.showinfo("Translation", f"{result}")
        try:
            short = dest.split("-")[0] if "-" in dest else dest
            self.jarvis.speak(result, lang=short)
        except Exception:
            self.jarvis.speak(result)

    def log(self, text: str):
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        self.log_box.insert(tk.END, f'[{ts}] {text}\n')
        self.log_box.see(tk.END)

    def check_queue(self):
        try:
            while True:
                item = self.out_queue.get_nowait()
                typ, payload = item
                if typ == 'status':
                    self.status_var.set(payload)
                    self.log(payload)
                elif typ == 'last_command':
                    self.last_cmd_var.set(payload)
                    self.log(f'Recognized: {payload}')
                elif typ == 'notes_updated':
                    self.load_notes()
                elif typ == 'exit':
                    self.on_close()
                else:
                    self.log(f'{typ}: {payload}')
        except queue.Empty:
            pass
        self.after(200, self.check_queue)

    def on_close(self):
        if messagebox.askokcancel('Quit', 'Do you want to quit Jarvis?'):
            try:
                self.jarvis.stop_wake_word()
            except Exception:
                pass
            self.destroy()


def main():
    out_q = queue.Queue()
    jarvis = JarvisCore(config, out_q)
    if tk is None:
        print('Tkinter not available. Exiting.')
        return
    app = JarvisGUI(jarvis)
    # start mainloop; wake-word runs on background threads
    app.mainloop()


if __name__ == '__main__':
    main()

