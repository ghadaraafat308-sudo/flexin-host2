import os
import sys


if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import json
import re
import time
import time as _time_module  # alias للتوافق مع الكود
import datetime
import asyncio
import threading
import concurrent.futures

# Rate Limiter — يمنع فلود /start

_start_rate: dict = {}   # user_id -> last_start_time
_START_COOLDOWN = 5      # ثواني بين كل /start وتاني لنفس المستخدم


_pending_orders: dict = {}  # user_id -> {type, amount, url, price, extra}


pending_market_data: dict = {}  # user_id -> {"step": str, "phone": str, "price": int, "desc": str}


guess_games: dict = {}  # user_id -> {"secret": int, "attempts": int, "hint": str}


pending_admin_action: dict = {}  # user_id -> {"action": str, "step": str, ...}

def _check_rate_limit(user_id: int) -> bool:
    """يرجع True لو المستخدم عنده إذن يبعت /start، False لو في فترة cooldown"""
    now = _time_module.time()
    last = _start_rate.get(user_id, 0)
    if now - last < _START_COOLDOWN:
        return False
    _start_rate[user_id] = now
    return True

import random

if not os.path.isdir('dbs'):
    os.makedirs('dbs', exist_ok=True)

def _pip(*pkgs):
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", *pkgs],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _ensure_packages():
    missing = []
    checks = {
        "schedule": "schedule",
        "telebot": "pyTelegramBotAPI>=4.21.0",
        "requests": "requests",
        "pyromod": "pyromod==1.4",
    }
    # google-auth اختياري — بيشتغل بدونه
    try:
        import google.oauth2
    except ImportError:
        try:
            _pip("google-auth")
        except Exception:
            pass
    # فحص pyrogram بشكل منفصل بدون import عشان يتجنب مشكلة event loop
    try:
        import importlib.util
        spec = importlib.util.find_spec("pyrogram")
        if spec is None:
            missing.append("pyrogram")
    except Exception:
        missing.append("pyrogram")
    for mod, pkg in checks.items():
        try:
            __import__(mod.split(".")[0])
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[startup] تثبيت المكتبات الناقصة: {missing}")
        _pip(*missing)


import asyncio as _asyncio_fix
try:
    _asyncio_fix.get_event_loop()
except RuntimeError:
    _loop = _asyncio_fix.new_event_loop()
    _asyncio_fix.set_event_loop(_loop)

_ensure_packages()

import schedule
import telebot
from telebot import TeleBot
from telebot.types import InlineKeyboardButton as TelebotButton, InlineKeyboardMarkup as TelebotMarkup, MessageEntity
import requests as _requests_mod
try:
    from google.oauth2 import service_account as _sa_mod
    import google.auth.transport.requests as _gtr_mod
    _GOOGLE_AVAILABLE = True
except ImportError:
    _sa_mod = None
    _gtr_mod = None
    _GOOGLE_AVAILABLE = False

# Firebase Realtime Database — بديل kvsqlite

FIREBASE_URL = "https://bostgram-default-rtdb.firebaseio.com"

FIREBASE_SA_INFO = {
    "type": "service_account",
    "project_id": "bostgram",
    "private_key_id": "2039a9d57714806f864913c2dda8a3ee137e37aa",
    "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCmGcrc4wMd8n4q\nLmLozJdaoqa3VA9zI/S1xqHf3oVr17JsQ/qNroz0o+ko8swO+I1OXSy640tIn//y\nNr4IyNV8D5HdZ7K5pu2u3ePxg53c1xE4s2HKNsIJOdcyeKTOssAdgXkxSzPx5IoI\nWIIN/RbcS8fwW6ODP/E59l8UC5UagO49u15P6hRGaxTO5BykYljtBBI8sbJUBEDw\n8wuNo0HCSKIZsbNzIXL9qg0UZeERVuXTTJAk9WdPBu4YK04n0VCoPUAZD5+Lpuqo\nUhkmIvw8fFtGnrjCo+fgvnqVOsdFVY/n72forXqEOmM3NdYWvxHawv+pIlVF7Nxg\nW3frcTiTAgMBAAECggEAIMgtZAv/1PzDjsKp7cVXR+GbIsqZ5AEgLnIeB6eM0Jx5\nD+oYvLbLBguFnHnS8U934BP+nIH4nURKyPyp4+TzUXFnOfnZ6c860MzlTIjL8saV\nlQm+TqEhCZ4bTVBHQq4/wXMIvsRXY7HV1lDVljoxtVfVhagobOKFUwm/eR7SFjEz\nleJcyr24rjqTrq5BBEKTdqyqNTFJVEUwJ0JS5fqw8ROPmo5bA1OLTxO1OSvTQr0J\nwT+J0fF+xKtMJMUN8FJbaE4eKmyeXpCeGcJP2nPBjKgFSbIAnrPo4L9W3h4guaYt\nOKq61BtmcVAlZQ8fHbKSxmHlMDM6mh055EMhMPSGfQKBgQDYfB1EPWdv2vWGWLJz\nLoO4CQHC0UXgX/6KxyATDtl7pk18usSeQIfh9E4/qtjuO2fEfzQ1GiwV0PJo1ZZw\nQ80Znyy9mk0TTB9wVBrybHPzLwR3zE72ee2EHPteagNC1C5p6SP7nYh2VKGZOeLU\nJSGnV05l5m9LNgpOPvsmHsZntwKBgQDEa1XT6FLG299yEyfrnXEk+krUn29LDzxr\nEs5x8Wv9q41nz3HREeR0+BRvsIYaFP7YXpG4EKYD2uI5CiaILwrNGvIy5pLLM/YF\n4Acu3VEueJ74E7a9kci3LNLm3B48c/IPEb8XubVPJN4n7aiVuX2pCZKiNbjubPNU\nLfarrGReBQKBgAsMoq3F+I6T/W4i/tC0MhLlmspnxgpCvAo3SaLPYjhWb6QLIFf3\ncTgOMSQ8wx+9tnkoCPEg6dkfNhA1vpzySPii0DTJOF/gxcYE9O8kq/JglvjKW8lm\nxcG1fPr/rDTwAYJ0XNrN2pY3kZvxgWtUjdgts5mt3kZXdsUxn739WiEXAoGARJpg\nrdTVJJOjJYq/RLIG1K1++Wh+TK8ToSo+ZNm3qDAFAZ8Y17byHlCPgrsa+30dzaCq\nMKnP8kS/AsEi2CnmEeE5esHBv6t0YHTwzVOLiTmj/G2WQ/vpKOFFAFEdVmwAvXar\nUbQROYVc+oEtgq34z9OCHZm577yp+FrdbvSVUakCgYEAoCLiloAOiP+wCiyFv8B/\nHRIMI7mYquB5R29yUPWToFzGfS+KVAFjCmfXVpMfGYBTILG/yYdMpJvD8YwJLUfe\nI/Pl4gwKItS1FP4hzbWx82cM+DQN1QV+A5gRtsTp5LQzVoyrWqhvWpCoHzf6gSs0\nLeQduKG8FNxKJfd4rS/L6Mw=\n-----END PRIVATE KEY-----\n",
    "client_email": "firebase-adminsdk-fbsvc@bostgram.iam.gserviceaccount.com",
    "client_id": "109165842728854310464",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40bostgram.iam.gserviceaccount.com",
    "universe_domain": "googleapis.com"
}

class FirebaseDB:
    _SCOPES = [
        "https://www.googleapis.com/auth/firebase.database",
        "https://www.googleapis.com/auth/userinfo.email",
    ]
    _SYNC_INTERVAL = 7 * 3600  # 7 ساعات

    def __init__(self, db_url, sa_info):
        self._base        = db_url.rstrip("/")
        self._sa_info     = sa_info
        self._token       = None
        self._token_exp   = 0
        self._cache       = {}
        self._cache_loaded = False
        self._lock        = threading.RLock()
        self._wq          = []
        self._wq_lock     = threading.Lock()
        self._creds       = None
        self._init_creds()

        wt = threading.Thread(target=self._write_worker, daemon=True)
        wt.start()

        lt = threading.Thread(target=self._initial_load, daemon=True)
        lt.start()

        st = threading.Thread(target=self._periodic_sync, daemon=True)
        st.start()
        print("[Firebase] ✅ تم الاتصال بقاعدة البيانات السحابية")

    def _init_creds(self):
        if not _GOOGLE_AVAILABLE or _sa_mod is None:
            print("[Firebase] ⚠️ google-auth غير متاح — سيتم استخدام REST بدون توثيق")
            return
        try:
            self._creds = _sa_mod.Credentials.from_service_account_info(
                self._sa_info, scopes=self._SCOPES
            )
        except Exception as e:
            print(f"[Firebase] ❌ خطأ في بيانات الاعتماد: {e}")

    def _get_token(self):
        if not _GOOGLE_AVAILABLE or self._creds is None:
            return None
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        try:
            req = _gtr_mod.Request()
            self._creds.refresh(req)
            self._token = self._creds.token
            self._token_exp = time.time() + 3600
        except Exception as e:
            print(f"[Firebase] ❌ خطأ في التوكن: {e}")
        return self._token

    @staticmethod
    def _safe_key(key):
        return (str(key)
                .replace(".", "__dot__")
                .replace("#", "__hash__")
                .replace("$", "__dlr__")
                .replace("[", "__lb__")
                .replace("]", "__rb__"))

    def _node_url(self, key):
        return f"{self._base}/{self._safe_key(key)}.json"

    def _http_get(self, key):
        token = self._get_token()
        if not token:
            return None
        try:
            r = _requests_mod.get(
                self._node_url(key),
                headers={"Authorization": f"Bearer {token}"},
                timeout=10
            )
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f"[Firebase] GET {key}: {e}")
        return None

    def _http_put(self, key, value):
        token = self._get_token()
        if not token:
            return False
        try:
            r = _requests_mod.put(
                self._node_url(key),
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                data=json.dumps(value, ensure_ascii=False),
                timeout=5
            )
            return r.status_code == 200
        except Exception as e:
            print(f"[Firebase] PUT {key}: {e}")
        return False

    def _http_delete(self, key):
        token = self._get_token()
        if not token:
            return False
        try:
            r = _requests_mod.delete(
                self._node_url(key),
                headers={"Authorization": f"Bearer {token}"},
                timeout=5
            )
            return r.status_code == 200
        except Exception as e:
            print(f"[Firebase] DELETE {key}: {e}")
        return False

    def _write_worker(self):
        while True:
            try:
                time.sleep(0.02)  # batch interval — أسرع استجابة للكتابة
                with self._wq_lock:
                    if not self._wq:
                        continue
                    batch = list(self._wq)
                    self._wq.clear()
                # كتابة متوازية لتسريع الـ batch
                def _do_write(item):
                    op, key, val = item
                    try:
                        if op == "set":
                            self._http_put(key, val)
                        elif op == "delete":
                            self._http_delete(key)
                    except Exception as e:
                        print(f"[Firebase] worker error ({op} {key}): {e}")
                if len(batch) == 1:
                    _do_write(batch[0])
                else:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(batch))) as ex:
                        list(ex.map(_do_write, batch))
            except Exception as e:
                print(f"[Firebase] worker crash: {e}")
                time.sleep(1)

    def _fetch_all(self) -> dict:
        """يجيب كل البيانات من Firebase دفعة واحدة — request واحد فقط"""
        token = self._get_token()
        if not token:
            return {}
        try:
            r = _requests_mod.get(
                f"{self._base}/.json",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30
            )
            if r.status_code != 200:
                print(f"[Firebase] ❌ fetch_all فشل — status: {r.status_code}")
                return {}
            data = r.json()
            if data is None:
                print("[Firebase] ⚠️ fetch_all — Firebase أرجع null (قاعدة فارغة تماماً)")
                return {}
            if not isinstance(data, dict):
                print(f"[Firebase] ⚠️ fetch_all — نوع بيانات غير متوقع: {type(data)}")
                return {}
            print(f"[Firebase] ✅ تم جلب {len(data)} عنصر بـ request واحد")
            return data
        except Exception as e:
            print(f"[Firebase] ❌ خطأ في fetch_all: {e}")
            return {}

    def _initial_load(self):
        """يُحمَّل عند الـ startup — يملأ الـ cache بكل البيانات"""
        print("[Firebase] ⏳ جارٍ تحميل البيانات من Firebase...")
        # حاول 3 مرات لو فشل
        for attempt in range(3):
            data = self._fetch_all()
            if data:
                with self._lock:
                    self._cache.update(data)
                    self._cache_loaded = True
                print(f"[Firebase] ✅ تم تحميل {len(data)} عنصر في الذاكرة")
                return
            print(f"[Firebase] ⚠️ محاولة {attempt+1}/3 فشلت، إعادة المحاولة...")
            time.sleep(2)
        # بعد 3 محاولات — شغّل البوت بدون preload
        with self._lock:
            self._cache_loaded = True
        print("[Firebase] ⚠️ تعذر تحميل البيانات — البوت سيعمل بدون cache أولي")

    def refresh_user(self, user_id):
        """يحدّث بيانات مستخدم معين من Firebase مباشرة في الـ cache"""
        key = f'user_{user_id}'
        val = self._http_get(key)
        with self._lock:
            self._cache[key] = val
        return val

    def _periodic_sync(self):
        """Sync كل 7 ساعات — Firebase → cache"""
        while True:
            time.sleep(self._SYNC_INTERVAL)
            print("[Firebase] 🔄 جارٍ مزامنة البيانات (كل 7 ساعات)...")
            data = self._fetch_all()
            if data:
                with self._lock:
                    # نحدث الـ cache بالقيم الجديدة بدون حذف اللي اتعدّل محلياً
                    for k, v in data.items():
                        if k not in self._cache or self._cache[k] != v:
                            self._cache[k] = v
                print(f"[Firebase] ✅ تمت المزامنة — {len(data)} عنصر")

    def wait_until_loaded(self, timeout=30):
        """ينتظر لحد ما الـ preload يخلص"""
        deadline = time.time() + timeout
        while not self._cache_loaded and time.time() < deadline:
            time.sleep(0.2)

    def _enqueue(self, op, key, val=None):
        with self._wq_lock:
            self._wq = [(o, k, v) for o, k, v in self._wq if k != key]
            self._wq.append((op, key, val))

    def get(self, key):
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        # لو الـ cache لسه بيتحمل — اجيب من Firebase
        if not self._cache_loaded:
            val = self._http_get(key)
            if val is not None:
                with self._lock:
                    self._cache[key] = val
            return val
        # الـ cache اتحمل — الـ key مش موجود بيرجع None
        # (سريع — مش بيروح Firebase في كل مرة)
        return None

    def set(self, key, value):
        with self._lock:
            self._cache[key] = value
        self._enqueue("set", key, value)

    def delete(self, key):
        with self._lock:
            self._cache[key] = None
        self._enqueue("delete", key)

    def exists(self, key):
        val = self.get(key)
        return val is not None

    def keys(self, pattern=""):
        prefix = pattern.rstrip("%").rstrip("*") if pattern else ""
        # لو الـ cache محمّل — استخدمه بدل HTTP request
        if self._cache_loaded:
            with self._lock:
                all_keys = [k for k, v in self._cache.items() if v is not None]
            if prefix:
                filtered = [k for k in all_keys if k.startswith(prefix)]
            else:
                filtered = all_keys
            return [(k,) for k in filtered]
        # fallback: HTTP
        token = self._get_token()
        if not token:
            return []
        try:
            r = _requests_mod.get(
                f"{self._base}/.json?shallow=true",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15
            )
            if r.status_code == 200:
                data = r.json()
                if not data or not isinstance(data, dict):
                    return []
                all_keys = list(data.keys())
                if prefix:
                    filtered = [k for k in all_keys if k.startswith(prefix)]
                else:
                    filtered = all_keys
                return [(k,) for k in filtered]
        except Exception as e:
            print(f"[Firebase] keys({pattern}): {e}")
        return []

from pyrogram import Client, filters, enums
from pyrogram.raw import functions
from pyrogram.types import Message
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.types import InlineKeyboardButton as pbtn, InlineKeyboardMarkup as pmk
from pyrogram.errors import (
    ApiIdInvalid,
    PhoneNumberInvalid,
    PhoneCodeInvalid,
    PhoneCodeExpired,
    SessionPasswordNeeded,
    PasswordHashInvalid
)
from pyromod import listen

try:
    from asyncio.exceptions import TimeoutError
except ImportError:
    from asyncio import TimeoutError

# نظام الأزرار الملونة (Bot API 9.4)
# green=أخضر | red=أحمر | blue=أزرق

_STYLE_MAP = {
    "green": "success",
    "red":   "danger",
    "blue":  "primary",
}

# أسماء الأزرار الرئيسية القابلة للتعديل من لوحة الأدمن
BTN_KEYS = {
    "ps": "الخدمات",
    "collect": "تجميع النقاط",
    "charge_points": "شحن النقاط",
    "charge_stars": "شحن تلقائي بالنجوم",
    "charge_vf": "شحن بفودافون كاش",
    "charge_usdt": "شحن بيوستد",
    "account": "معلومات حسابك",
    "send": "تحويل نقاط",
    "normal": "الخدمات العادية",
    "free": "الخدمات المجانية",
    "vips": "الخدمات الـ ViP",
    "dailygift": "الهدية اليومية",
    "share_link": "رابط الدعوة",
    "wheel": "عجلة الحظ",
    "votes": "تصويت مسابقات",
    "votes_fsub": "تصويت مسابقات اشتراك إجباري",
    "react": "تفاعلات اختياري",
    "reacts": "تفاعلات عشوائي",
    "react_special": "رشق ايموجي ( مميز )",
    "forward": "توجيهات منشور",
    "view": "مشاهدات",
    "poll": "استفتاء",
    "linkbot": "روابط دعوة مجانية",
    "members": "اعضاء قناة عامة",
    "membersp": "اعضاء قناة خاصة",
    "userbot": "مستخدمين البوت",
    "comments": "تعليقات",
    "linkbot2": "روابط دعوة VIP",
    "free_member": "رشق أعضاء قناة مجانية",
    "spams": "سبام رسائل",
    "top_level": "TOP LEVEL",
    "support": "الدعم الفني",
    "sell_numbers": "بيع الأرقام",
    "register_accounts": "تسجيل حساباتك للتحكم فيها",
    "channels": "قنوات البوت",
    "leaderboard": "Leaderboard",
    "user_store": "متجر البوت",
    "none": "رصيدك",
    "11": "عدد الطلبات",
    "bot_channel_btn": "قناة البوت",
    "tasks": "قائمة المهام (ربح نقاط)",
    "guess": "لعبة التخمين",
    "adm_export_db": "تصدير قاعدة البيانات",
    "adm_export_users": "تصدير المستخدمين",
    "adm_export_accounts": "تصدير الحسابات",
    "adm_export_settings": "تصدير الإعدادات",
    "adm_export_all": "تصدير الكل",
    "adm_import_db": "استيراد قاعدة البيانات",
    "adm_import_type_users": "استيراد المستخدمين",
    "adm_import_type_accounts": "استيراد الحسابات",
    "adm_import_type_settings": "استيراد الإعدادات",
    "adm_import_type_all": "استيراد الكل",
    "back": "رجوع",
    "back_cancel": "إلغاء و رجوع",
    "setforce": "تعيين قنوات الاشتراك",
    "force_add": "إضافة قناة اشتراك",
    "force_del": "حذف قناة اشتراك",
    "force_list": "قنوات الاشتراك الإجباري",
    "free_reactions": "الخدمات المجانية",
    "free_react_go": "تفاعلات مجانية على منشور",
    "free_react_plus": "⚡ تفاعلات + مشاهدات مستقبلية",
}

def _get_btn_color(callback_data, default="blue"):
    """يقرأ لون الزر من قاعدة البيانات، إن لم يوجد يرجع الافتراضي"""
    try:
        saved = db.get(f"btn_color_{callback_data}")
        if saved in _STYLE_MAP:
            return saved
    except:
        pass
    return default

def _get_btn_label(callback_data, default=None):
    """يقرأ اسم الزر من قاعدة البيانات، إن لم يوجد يرجع الافتراضي"""
    try:
        saved = db.get(f"btn_label_{callback_data}")
        if saved:
            return saved
    except:
        pass
    return default or BTN_KEYS.get(callback_data, "")

# ====== AR/EN language + Captcha system ======
def _user_lang_raw(uid):
    try:
        l = db.get('lang_' + str(uid))
        if l in ('ar', 'en'):
            return l
    except Exception:
        pass
    return None

def _user_lang(uid):
    l = _user_lang_raw(uid)
    return l if l else 'ar'

def _L(uid, ar, en):
    return en if _user_lang(uid) == 'en' else ar

def _send_lang_picker(chat_id, uid, mid=None):
    try:
        keys = mk(row_width=2)
        keys.add(btn('🇸🇦 العربية', callback_data='setlang_ar', color='green'),
                 btn('🇬🇧 English', callback_data='setlang_en', color='blue'))
        txt = '🌐 اختر لغتك المفضلة | Please choose your language:'
        if mid:
            try:
                bot.edit_message_text(text=txt, chat_id=chat_id, message_id=mid, reply_markup=keys)
                return
            except Exception:
                pass
        bot.send_message(chat_id, txt, reply_markup=keys)
    except Exception as _e:
        print('[lang picker] ' + str(_e))

def _send_captcha(chat_id, uid, mid=None):
    try:
        a = random.randint(1, 9)
        b = random.randint(1, 9)
        ans = a + b
        db.set('captcha_ans_' + str(uid), ans)
        opts = {ans}
        while len(opts) < 4:
            opts.add(random.randint(2, 18))
        opts = list(opts)
        random.shuffle(opts)
        keys = mk(row_width=2)
        keys.add(*[btn(str(o), callback_data='capans_' + str(o), color='blue') for o in opts])
        _nl = chr(10)
        if _user_lang(uid) == 'en':
            txt = ('🤖 Verification' + _nl + _nl +
                   'To make sure you are human, solve this:' + _nl + _nl +
                   '      ' + str(a) + ' + ' + str(b) + ' = ?')
        else:
            txt = ('🤖 تأكيد بشري' + _nl + _nl +
                   'علشان نتأكد إنك مش بوت، حل المسألة دي:' + _nl + _nl +
                   '      ' + str(a) + ' + ' + str(b) + ' = ؟')
        if mid:
            try:
                bot.edit_message_text(text=txt, chat_id=chat_id, message_id=mid, reply_markup=keys)
                return
            except Exception:
                pass
        bot.send_message(chat_id, txt, reply_markup=keys)
    except Exception as _e:
        print('[captcha] ' + str(_e))

def _onboarding_gate(uid, chat_id):
    try:
        if _user_lang_raw(uid) is None:
            _send_lang_picker(chat_id, uid)
            return True
        _is_adm = (uid == sudo) or (uid in _get_admins_cached())
        if (not _is_adm) and (not db.get('captcha_ok_' + str(uid))):
            _send_captcha(chat_id, uid)
            return True
    except Exception as _e:
        print('[gate] ' + str(_e))
    return False

def _finish_start(uid, chat_id):
    try:
        _is_adm = (uid == sudo) or (uid in _get_admins_cached())
        if not _is_adm:
            _ok, _ns = _check_user_subs(uid)
            if not _ok:
                _send_force_sub_msg(bot, chat_id, _ns)
                return
            try:
                _settle_pending_referral(uid)
            except Exception:
                pass
        keys = _build_main_keys(uid)
        bot.send_message(chat_id, get_welcome_msg(uid), reply_markup=keys, parse_mode="HTML")
    except Exception as _e:
        print('[finish_start] ' + str(_e))

def _is_btn_visible(callback_data):
    """يتحقق إذا كان الزر مرئي (غير مخفي)"""
    try:
        hidden = db.get("hidden_buttons") or []
        return callback_data not in hidden
    except:
        return True

def _toggle_btn_visibility(callback_data):
    """يخفي/يظهر زر - يرجع الحالة الجديدة (True=visible)"""
    try:
        hidden = list(db.get("hidden_buttons") or [])
    except:
        hidden = []
    if callback_data in hidden:
        hidden.remove(callback_data)
        db.set("hidden_buttons", hidden)
        return True
    else:
        hidden.append(callback_data)
        db.set("hidden_buttons", hidden)
        return False

# نظام الإيموجي المميز (Custom Emoji ID) — النظام الجديد


def _db_get_btn_emoji(cb):
    """جلب custom_emoji_id لزر معين"""
    try:
        v = db.get(f"btn_emoji:{cb}")
        return str(v) if v else ""
    except:
        return ""

def _db_set_btn_emoji(cb, emoji_id):
    """ضبط custom_emoji_id لزر معين — لو فارغ يُحذف"""
    try:
        if emoji_id:
            db.set(f"btn_emoji:{cb}", str(emoji_id))
        else:
            db.delete(f"btn_emoji:{cb}")
    except:
        pass

def _db_list_btn_emojis():
    """إرجاع dict {cb: emoji_id} لكل الأزرار المضبوطة"""
    # kvsqlite لا يدعم LIKE مباشرة، نعتمد على الكاش
    return dict(_BTN_EMOJI_CACHE) if _BTN_EMOJI_CACHE else {}

def _db_clear_all_btn_emojis():
    """مسح كل رموز الأزرار المميزة"""
    try:
        cache = dict(_BTN_EMOJI_CACHE) if _BTN_EMOJI_CACHE else {}
        for cb in list(cache.keys()):
            db.delete(f"btn_emoji:{cb}")
    except:
        pass


_BTN_EMOJI_CACHE = None

def _load_btn_emoji_cache():
    global _BTN_EMOJI_CACHE
    try:
        result = {}
        for cb in BTN_KEYS:
            v = db.get(f"btn_emoji:{cb}")
            if v:
                result[cb] = str(v)
        _BTN_EMOJI_CACHE = result
    except:
        _BTN_EMOJI_CACHE = {}

def _invalidate_btn_emoji_cache():
    global _BTN_EMOJI_CACHE
    _BTN_EMOJI_CACHE = None

def _resolve_btn_emoji(cb):
    """يرجع emoji_id للزر من الكاش"""
    if not cb:
        return ""
    global _BTN_EMOJI_CACHE
    if _BTN_EMOJI_CACHE is None:
        _load_btn_emoji_cache()
    return _BTN_EMOJI_CACHE.get(cb, "") if _BTN_EMOJI_CACHE else ""


def pe(emoji_char: str, custom_emoji_id: str = "") -> str:
    """\n    يُرجع HTML يدعم Premium Emoji في تليجرام.\n    لو فيه custom_emoji_id يستخدم <tg-emoji>، وإلا يرجع الإيموجي العادي.\n    استخدمها مع parse_mode='HTML' فقط.\n    """
    if custom_emoji_id:
        return f'<tg-emoji emoji-id="{custom_emoji_id}">{emoji_char}</tg-emoji>'
    return emoji_char


STATIC_BUTTON_REGISTRY = [
    ("الأزرار الرئيسية", [
        ("ps",            "🛒 الخدمات"),
        ("collect",       "💠 تجميع النقاط"),
        ("charge_points", "💳 شحن النقاط"),
        ("charge_stars",  "⭐ شحن تلقائي بالنجوم"),
        ("charge_vf",     "📱 شحن بفودافون كاش"),
        ("charge_usdt",   "💎 شحن بيوستد"),
        ("account",       "🪪 معلومات حسابك"),
        ("send",          "🔄 تحويل نقاط"),
        ("normal",        "🛍️ الخدمات العادية"),
        ("vips",          "👑 الخدمات الـ ViP"),
        ("dailygift",     "🎁 الهدية اليومية"),
        ("share_link",    "🔮 رابط الدعوة"),
        ("wheel",         "🎰 عجلة الحظ"),
        ("votes",         "🗳️ تصويت مسابقات"),
        ("react",         "⚡ تفاعلات اختياري"),
        ("reacts",        "🎲 تفاعلات عشوائي"),
        ("react_special", "✨ رشق ايموجي ( مميز )"),
        ("forward",       "📤 توجيهات منشور"),
        ("view",          "🎯 مشاهدات"),
        ("poll",          "📊 استفتاء"),
        ("linkbot",       "🔑 روابط دعوة مجانية"),
        ("members",       "👥 اعضاء قناة عامة"),
        ("membersp",      "🔐 اعضاء قناة خاصة"),
        ("userbot",       "🤖 مستخدمين البوت"),
        ("comments",      "💬 تعليقات"),
        ("linkbot2",      "💎 روابط دعوة VIP"),
        ("free_member",   "👥 رشق أعضاء قناة مجانية"),
        ("spams",         "💣 سبام رسائل"),
        ("top_level",     "🏅 TOP LEVEL"),
        ("support",       "الدعم الفني"),
        ("sell_numbers",  "💸 بيع الأرقام"),
        ("register_accounts", "📲 تسجيل حساباتك للتحكم فيها"),
        ("channels",      "قنوات البوت"),
        ("leaderboard",   "Leaderboard"),
        ("none",          "💰 رصيدك"),
        ("11",            "عدد الطلبات"),
        ("bot_channel_btn", "📢 قناة البوت"),
    ]),
]

def _label_for_cb(cb):
    """يرجع اسم الزر من السجل"""
    for _grp, items in STATIC_BUTTON_REGISTRY:
        for k, lbl in items:
            if k == cb:
                return lbl
    return BTN_KEYS.get(cb, cb)


def btn(text, callback_data=None, url=None, color="blue", **kwargs):
    """إنشاء زر ملوّن مع دعم Custom Emoji ID — اللون والاسم والإيموجي يُقرآن من DB"""
    emoji_id = None
    if callback_data and callback_data in BTN_KEYS:
        color    = _get_btn_color(callback_data, default=color)
        text     = _get_btn_label(callback_data, default=text)
        emoji_id = _resolve_btn_emoji(callback_data)

    style = _STYLE_MAP.get(color, "primary")
    b = TelebotButton(text=text, callback_data=callback_data, url=url, **kwargs)
    original_to_dict = b.to_dict
    _style  = style
    _eid    = str(emoji_id) if emoji_id else None

    def colored_to_dict():
        d = original_to_dict()
        d["style"] = _style
        if _eid:
            d["icon_custom_emoji_id"] = _eid
        return d

    b.to_dict = colored_to_dict
    return b

def mk(row_width=2):
    return TelebotMarkup(row_width=row_width)

# الإعدادات - يمكنك تعديلها هنا مباشرة

CONFIG = {
    "sudo": 6472365461,
    "start_msg": "︎مرحبا بكم في اقوي بوت رشق علي الساحه",
    "prices": {
        "member": 1000,
        "link": 1,
        "vote": 100,
        "react": 100,
        "forward": 100,
        "view": 100,
        "poll": 100,
        "userbot": 100,
        "linkbot": 100,
        "linkbot2": 100,
        "votes_fsub": 150,
        "comments": 100,
        "spam": 100
    },
    "bot_token": "8608887988:AAE0TWNFwFKhTBoyJbGzDXhPi2P4Q1c-A4Y",
    "give_bot_token": "8961757018:AAEMW-tTREk2wmozthM6DIPEHsglr0Csk1M",
    "sell_gmail":     "bbbabdullah9@gmail.com",
    "rent_reward":    100
}

BOT_TOKEN      = CONFIG["bot_token"]
GIVE_BOT_TOKEN = CONFIG["give_bot_token"]


_GIVE_BOT_USERNAME = "nnnlllq1_bot"  # قيمة افتراضية فورية

def _load_bot_usernames():
    """يجيب username بوت التسجيل في الخلفية"""
    global _GIVE_BOT_USERNAME
    try:
        _t = telebot.TeleBot(GIVE_BOT_TOKEN)
        _GIVE_BOT_USERNAME = _t.get_me().username or "nnnlllq1_bot"
        print(f"[startup] give_bot: @{_GIVE_BOT_USERNAME}")
    except:
        pass

threading.Thread(target=_load_bot_usernames, daemon=True).start()

API_ID = 30666915
API_HASH = "19420db67ff7203ba1b4619cd9a9af7c"

sudo = CONFIG["sudo"]
mm = CONFIG["start_msg"]

def get_welcome_msg(user_id):
    """يبني رسالة الترحيب الديناميكية بناءً على بيانات المستخدم"""
    try:
        info = db.get(f'user_{user_id}')
        coins = int(info['coins']) if info else 0
    except:
        coins = 0
    # تقييم الحساب بناءً على عدد الطلبات
    buys = int(db.get(f"user_{user_id}_buys")) if db.exists(f"user_{user_id}_buys") else 0
    if buys == 0:
        rating = "جديد 🆕"
    elif buys < 5:
        rating = "حقيقي ✅"
    elif buys < 20:
        rating = "موثوق 🔰"
    else:
        rating = "VIP ⭐"
    # مستوى المستخدم
    try:
        _lv_num = int(db.get(f'user_{user_id}_top_level') or 1)
    except:
        _lv_num = 1
    lang = _user_lang(user_id)
    if lang == 'en':
        if buys == 0:
            rating = "New 🆕"
        elif buys < 5:
            rating = "Trusted ✅"
        elif buys < 20:
            rating = "Verified 🔰"
        else:
            rating = "VIP ⭐"
        _wnl = chr(10)
        return (
            "🎉 Welcome! This is the most powerful bot for all Telegram services 🫡" + _wnl + _wnl +
            "- 🛰 The only bot that opens the world of Telegram services for you ❤️‍🔥⚡️" + _wnl + _wnl +
            "- 🏆 Browse the available sections using the buttons below" + _wnl + _wnl +
            f"- 💸 Your points: {coins:,}" + _wnl +
            f"- 🆔 Your account ID: {user_id}" + _wnl +
            f"- 📮 Account rating: {rating}" + _wnl +
            f"- 🧧 Your level: {_lv_num}"
        )
    return (
        "🎉 السلام عليكم؛ أهلاً بِكَ في أقوى بوت عربي يقدم لك جميع خدمات تيلجرام  🫡\n\n"
        "- 🛰 البوت العربي الوحيد الذي يجعلك تدخل في عالم خدمات تيليجرام ❤️‍🔥⚡️\n\n"
        "- 🏆 يمكنك إستعراض الأقسام المتاحة عبر الأزرار أدناهُ\n\n"
        f"- 💸 نقاطك : {coins:,}\n"
        f"- 🆔 آيدي حسابك : {user_id}\n"
        f"- 📮 تقييم حسابك : {rating}\n"
        f"- 🧧 مستواك : {_lv_num}"
    )
# الأسعار تُقرأ ديناميكياً عبر svc_price() من DB
# هذه القيم الافتراضية فقط للتوافق مع الكود القديم
member_price   = CONFIG["prices"]["member"]
vote_price     = CONFIG["prices"]["vote"]
link_price     = CONFIG["prices"]["link"]
spam_price     = CONFIG["prices"]["spam"]
react_price    = CONFIG["prices"]["react"]
forward_price  = CONFIG["prices"]["forward"]
view_price     = CONFIG["prices"]["view"]
poll_price     = CONFIG["prices"]["poll"]
userbot_price  = CONFIG["prices"]["userbot"]
linkbot_price  = CONFIG["prices"]["linkbot"]
comment_price  = CONFIG["prices"]["comments"]
linkbot2_price = CONFIG["prices"]["linkbot2"]
votes_fsub_price = CONFIG["prices"]["votes_fsub"]

# قاعدة البيانات — Firebase Realtime Database

print("[⏳] جارٍ الاتصال بقاعدة البيانات...")
db = FirebaseDB(FIREBASE_URL, FIREBASE_SA_INFO)
# البوت يبدأ فوراً — البيانات تتحمل في الخلفية (cache يعمل من أول request)
print("[���] Firebase متصل — البوت جاهز فوراً، البيانات تتحمل في الخلفية...")

# إخفاء افتراضي لليدربورد + تصفير المهام القديمة (مرّة واحدة)
try:
    if not db.get("_migrated_hide_lb_v2"):
        _hidden_init = list(db.get("hidden_buttons") or [])
        if "tasks" in _hidden_init:
            _hidden_init.remove("tasks")
        if "leaderboard" not in _hidden_init:
            _hidden_init.append("leaderboard")
        db.set("hidden_buttons", _hidden_init)
        db.set("tasks_list", [])
        db.set("_migrated_hide_lb_v2", True)
        print("[ℹ️] رجّعت زر المهام، أخفيت الليدربورد، وصفّرت المهام القديمة.")
except Exception as _mig_e:
    print(f"[⚠️] تحذير migration: {_mig_e}")

# إعدادات الخدمات (السعر والحد الأدنى والأقصى) — تُقرأ من DB

SERVICES = {
    "member":      {"label": "أعضاء قناة عامة (مدفوع)",   "price_key": "member_price",      "min_key": "member_min",      "max_key": "member_max",      "default_price": 1000, "default_min": 10, "default_max": 500, "enabled_key": "svc_enabled_member"},
    "free_member": {"label": "أعضاء قناة عامة",           "price_key": "free_member_price",  "min_key": "free_member_min",  "max_key": "free_member_max",  "default_price": 100,  "default_min": 1,  "default_max": 50,  "enabled_key": "svc_enabled_member"},
    "membersp": {"label": "أعضاء قناة خاصة",          "price_key": "membersp_price", "min_key": "membersp_min", "max_key": "membersp_max", "default_price": 1000, "default_min": 10,  "default_max": 500, "enabled_key": "svc_enabled_membersp"},
    "react":    {"label": "تفاعلات اختياري",           "price_key": "react_price",    "min_key": "react_min",    "max_key": "react_max",    "default_price": 100,  "default_min": 1,   "default_max": 500, "enabled_key": "svc_enabled_react"},
    "reacts":   {"label": "تفاعلات عشوائي",            "price_key": "reacts_price",   "min_key": "reacts_min",   "max_key": "reacts_max",   "default_price": 100,  "default_min": 1,   "default_max": 500, "enabled_key": "svc_enabled_reacts"},
    "react_special": {"label": "رشق ايموجي ( مميز )", "price_key": "react_special_price", "min_key": "react_special_min", "max_key": "react_special_max", "default_price": 150, "default_min": 1, "default_max": 500, "enabled_key": "svc_enabled_react_special"},
    "forward":  {"label": "توجيهات منشور",             "price_key": "forward_price",  "min_key": "forward_min",  "max_key": "forward_max",  "default_price": 100,  "default_min": 1,   "default_max": 500, "enabled_key": "svc_enabled_forward"},
    "view":     {"label": "مشاهدات",                   "price_key": "view_price",     "min_key": "view_min",     "max_key": "view_max",     "default_price": 100,  "default_min": 1,   "default_max": 500, "enabled_key": "svc_enabled_view"},
    "poll":     {"label": "استفتاء",                   "price_key": "poll_price",     "min_key": "poll_min",     "max_key": "poll_max",     "default_price": 100,  "default_min": 1,   "default_max": 500, "enabled_key": "svc_enabled_poll"},
    "votes":     {"label": "تصويت مسابقات",             "price_key": "votes_price",    "min_key": "votes_min",    "max_key": "votes_max",    "default_price": 100,  "default_min": 1,   "default_max": 500, "enabled_key": "svc_enabled_votes"},
    "votes_fsub":{"label": "تصويت مسابقات اشتراك إجباري", "price_key": "votes_fsub_price","min_key": "votes_fsub_min","max_key": "votes_fsub_max","default_price": 150,  "default_min": 1,   "default_max": 500, "enabled_key": "svc_enabled_votes_fsub"},
    "userbot":  {"label": "مستخدمين البوت",            "price_key": "userbot_price",  "min_key": "userbot_min",  "max_key": "userbot_max",  "default_price": 100,  "default_min": 1,   "default_max": 500, "enabled_key": "svc_enabled_userbot"},
    "linkbot":  {"label": "روابط دعوة مجانية",         "price_key": "linkbot_price",  "min_key": "linkbot_min",  "max_key": "linkbot_max",  "default_price": 100,  "default_min": 1,   "default_max": 500, "enabled_key": "svc_enabled_linkbot"},
    "linkbot2": {"label": "روابط دعوة VIP",            "price_key": "linkbot2_price", "min_key": "linkbot2_min", "max_key": "linkbot2_max", "default_price": 100,  "default_min": 1,   "default_max": 500, "enabled_key": "svc_enabled_linkbot2"},
    "comments": {"label": "تعليقات",                   "price_key": "comments_price", "min_key": "comments_min", "max_key": "comments_max", "default_price": 100,  "default_min": 1,   "default_max": 500, "enabled_key": "svc_enabled_comments"},
    "spam":     {"label": "سبام رسائل",                "price_key": "spam_price",     "min_key": "spam_min",     "max_key": "spam_max",     "default_price": 100,  "default_min": 1,   "default_max": 500, "enabled_key": "svc_enabled_spam"},
}

def svc_price(key):
    s = SERVICES.get(key, {})
    try:
        v = db.get(s.get("price_key", ""))
        if v is not None: return int(v)
    except: pass
    return s.get("default_price", 100)

def svc_min(key):
    s = SERVICES.get(key, {})
    try:
        v = db.get(s.get("min_key", ""))
        if v is not None: return int(v)
    except: pass
    return s.get("default_min", 1)

def svc_max(key):
    s = SERVICES.get(key, {})
    try:
        v = db.get(s.get("max_key", ""))
        if v is not None: return int(v)
    except: pass
    return s.get("default_max", 500)

def svc_enabled(key):
    """هل الخدمة مفعّلة؟ يرجع True بالقيمة الافتراضية"""
    s = SERVICES.get(key, {})
    ekey = s.get("enabled_key", "")
    if not ekey:
        return True
    try:
        v = db.get(ekey)
        if v is not None:
            return bool(v)
    except:
        pass
    return True  # مفعّلة افتراضياً

stypes = ['member', 'administrator', 'creator']

# دوال الاشتراك الإجباري الاحترافي

# helpers لقنوات الاشتراك الإجباري

def _get_force_channels():
    """يرجع قائمة القنوات — يدعم الهيكل القديم والجديد"""
    raw = db.get('force') or []
    result = []
    for ch in raw:
        if isinstance(ch, dict):
            result.append(ch)
        else:
            # هيكل قديم: string → نحوّله للجديد
            clean = str(ch).lstrip('@').strip()
            result.append({
                'id':    '@' + clean,
                'name':  clean,
                'url':   f'https://t.me/{clean}',
                'limit': 0
            })
    return result

def _ch_id(ch: dict) -> str:
    """يرجع معرف القناة بدون @"""
    return ch.get('id', '').lstrip('@').strip()

def _ch_name(ch: dict) -> str:
    """يرجع اسم القناة للعرض"""
    return ch.get('name') or _ch_id(ch)

def _ch_url(ch: dict) -> str:
    return ch.get('url') or f"https://t.me/{_ch_id(ch)}"

def _build_force_sub_keyboard(not_subscribed_ids: list, all_channels: list = None):
    """يبني لوحة أزرار اشتراك إجبارية — يعرض اسم القناة + رابط الجوين"""
    if all_channels is None:
        all_channels = _get_force_channels()
    keys = mk(row_width=1)
    ns_ids = [_ch_id(c) if isinstance(c, dict) else c.lstrip('@') for c in not_subscribed_ids]

    _sub_emoji  = (db.get('fsub_sub_emoji')   or '📢').strip()
    _sub_text   = (db.get('fsub_sub_text')    or 'اشترك').strip()
    _check_emoji = (db.get('fsub_check_emoji') or '✅').strip()
    _check_text  = (db.get('fsub_check_text')  or 'تحققت من الاشتراك').strip()
    for i, ch in enumerate(all_channels, 1):
        cid_  = _ch_id(ch)
        name_ = _ch_name(ch)
        url_  = _ch_url(ch)
        is_done = cid_ not in ns_ids
        label   = f'✅ {name_}' if is_done else f'{_sub_emoji} {_sub_text} • {name_}'
        color   = 'blue' if is_done else 'green'
        keys.add(btn(label, url=url_, color=color))
    keys.add(btn(f'{_check_emoji} {_check_text}', callback_data='check_force_sub', color='blue'))
    return keys

def _force_sub_text(not_subscribed: list, all_channels: list = None) -> str:
    if all_channels is None:
        all_channels = _get_force_channels()
    ns_ids = [_ch_id(c) if isinstance(c, dict) else c.lstrip('@') for c in not_subscribed]
    ch_lines = []
    for ch in all_channels:
        cid__  = _ch_id(ch)
        name__ = _ch_name(ch)
        done   = cid__ not in ns_ids
        ch_lines.append('   ' + (chr(0x2705) if done else chr(0x274C)) + ' ' + name__)
    remaining = len(not_subscribed)
    sep = chr(0x2550) * 22
    header = chr(0x2554) + sep + chr(0x2557) + '\n'
    header += chr(0x2551) + '  🔒  اشتراك إجباري   ' + chr(0x2551) + '\n'
    header += chr(0x255a) + sep + chr(0x255d) + '\n\n'
    body  = f'⚠️ عذراً، تبقى عليك الاشتراك في <b>{remaining}</b> قناة:\n\n'
    body += '\n'.join(ch_lines)
    body += '\n\n📌 اشترك في القنوات ثم اضغط زر التحقق أدناه'
    return header + body

def _send_force_sub_msg(bot_obj, chat_id, not_subscribed, reply_to=None):
    """يرسل رسالة الاشتراك الإجباري"""
    all_ch = _get_force_channels()
    txt    = _force_sub_text(not_subscribed, all_ch)
    keys   = _build_force_sub_keyboard(not_subscribed, all_ch)
    try:
        if reply_to:
            bot_obj.send_message(chat_id=chat_id, text=txt, reply_markup=keys,
                                  reply_to_message_id=reply_to, parse_mode="HTML")
        else:
            bot_obj.send_message(chat_id=chat_id, text=txt, reply_markup=keys, parse_mode="HTML")
    except Exception:
        bot_obj.send_message(chat_id=chat_id, text=txt, reply_markup=keys, parse_mode="HTML")

def _edit_force_sub_msg(bot_obj, chat_id, message_id, not_subscribed):
    """يعدّل رسالة الاشتراك الإجباري"""
    all_ch = _get_force_channels()
    txt    = _force_sub_text(not_subscribed, all_ch)
    keys   = _build_force_sub_keyboard(not_subscribed, all_ch)
    try:
        bot_obj.edit_message_text(text=txt, chat_id=chat_id, message_id=message_id,
                                   reply_markup=keys, parse_mode="HTML")
    except Exception:
        bot_obj.send_message(chat_id=chat_id, text=txt, reply_markup=keys, parse_mode="HTML")

# cache نتائج الاشتراك — مفتاح: user_id، قيمة: (ok, not_sub, timestamp)
_subs_cache: dict = {}
_SUBS_CACHE_TTL = 600  # 10 دقائق — يقلل API calls بشكل كبير

# ✅ Cache للأدمن — يُحدَّث كل 60 ثانية بدل Firebase ����ي كل ضغطة زر
_admins_cache: list = []
_admins_cache_ts: float = 0
_ADMINS_CACHE_TTL = 300  # 5 دقائق

def _get_admins_cached() -> list:
    global _admins_cache, _admins_cache_ts
    if time.time() - _admins_cache_ts < _ADMINS_CACHE_TTL and _admins_cache:
        return _admins_cache
    _admins_cache = db.get('admins') or []
    _admins_cache_ts = time.time()
    return _admins_cache

# ✅ Cache لقنوات الاشتراك الإجباري — يُحدَّث كل 120 ثانية
_force_cache: list = []
_force_cache_ts: float = 0
_FORCE_CACHE_TTL = 600

def _get_force_channels_cached() -> list:
    global _force_cache, _force_cache_ts
    if time.time() - _force_cache_ts < _FORCE_CACHE_TTL:
        return _force_cache
    _force_cache = _get_force_channels()
    _force_cache_ts = time.time()
    return _force_cache

def _check_user_subs(user_id: int, force: bool = False):
    """يتحقق من اشتراك المستخدم — يرجع (ok, not_subscribed_list)"""
    channels = _get_force_channels_cached()
    if not channels:
        return True, []

    # فحص الـ cache أولاً
    if not force and user_id in _subs_cache:
        ok, not_sub, ts = _subs_cache[user_id]
        if time.time() - ts < _SUBS_CACHE_TTL:
            return ok, not_sub

    def _check_one(ch):
        cid_ = _ch_id(ch)
        attempts = []
        try:
            attempts.append(int(cid_))
        except (ValueError, TypeError):
            pass
        attempts.append('@' + cid_.lstrip('@'))
        for attempt in attempts:
            try:
                x = bot.get_chat_member(chat_id=attempt, user_id=user_id)
                status = str(x.status).lower()
                if status in [s.lower() for s in stypes]:
                    return None  # مشترك
                return ch  # غير مشترك
            except Exception:
                continue
        return None  # خطأ = اعتبره مشترك

    # فحص كل القنوات بالتوازي بدل متسلسل
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(channels))) as ex:
        results = list(ex.map(_check_one, channels))
    not_sub = [r for r in results if r is not None]

    result = (len(not_sub) == 0, not_sub)
    # خزّن في الـ cache
    _subs_cache[user_id] = (result[0], result[1], time.time())
    return result

bk = TelebotMarkup(row_width=1)
bk.add(btn(_get_btn_label('back', 'رجوع'), callback_data='back', color='blue'))

# زر إلغاء ورجوع — يظهر في كل خطوات الخدمات
bk_cancel = TelebotMarkup(row_width=1)
bk_cancel.add(btn(_get_btn_label('back_cancel', 'إلغاء و رجوع'), callback_data='back', color='red'))

def _bk_cancel_svc(back_data: str, label: str = '❌ إلغاء و رجوع'):
    """زر إلغاء ورجوع مخصص يرجع لصفحة معينة بدل الرئيسية"""
    k = TelebotMarkup(row_width=1)
    k.add(btn(label, callback_data=back_data, color='red'))
    return k

bk_cancel_adm = TelebotMarkup(row_width=1)
bk_cancel_adm.add(btn('🔙 رجوع للوحة الأدمن', callback_data='adm_back_main', color='red'))

print("[⏳] جارٍ إنشاء البوت...")
bot = TeleBot(token=BOT_TOKEN, num_threads=16)
print("[✅] البوت جاهز — BOT_TOKEN صحيح")

# ── cache لـ _get_bot_me() عشان منعملش API call في كل رسالة ──
_bot_me_cache = None
def _get_bot_me():
    global _bot_me_cache
    if _bot_me_cache is None:
        try:
            _bot_me_cache = bot.get_me()
        except:
            pass
    return _bot_me_cache

# ✅ انتظر تحميل Firebase قبل أي checks — يمنع مسح البيانات عند إعادة التشغيل
print("[⏳] انتظار تحميل بيانات Firebase...")
db.wait_until_loaded(timeout=60)
print("[✅] Firebase جاهز — جارٍ التهي��ة...")

# ✅ حماية: لا نمسح الأرقام إلا لو Firebase فعلاً فاضي (مش فشل في التحميل)
_existing_accounts = db.get('accounts')
if _existing_accounts is None:
    # حاول مرة ثانية مباشرة من Firebase قبل ما تعتبره فاضياً
    import time as _t2
    _t2.sleep(2)
    _existing_accounts = db._http_get('accounts')
    if _existing_accounts is None:
        print("[⚠️] accounts غير موجود في Firebase — إنشاء قائمة فارغة جديدة")
        db.set('accounts', [])
    else:
        # كان موجود لكن الـ cache لم يحمّله — نحدث الـ cache
        with db._lock:
            db._cache['accounts'] = _existing_accounts
        print(f"[��] تم استرداد {len(_existing_accounts)} حساب من Firebase مباشرة")

# db.delete("force")  # تم التعطيل — كان يمسح القنوات الإجبارية عند كل تشغيل

admin = sudo

_default_admins = [6472365461, 6635130346, 8202070583]
if not db.get('admins'):
    db.set('admins', list(set([admin] + _default_admins)))
else:
    # نضيف الأدمن الافتراضيين لو مش موجودين
    _cur = db.get('admins')
    _updated = list(set(_cur + [admin] + _default_admins))
    if _updated != _cur:
        db.set('admins', _updated)
if not db.get('badguys'):
    db.set('badguys', [])
if not db.get('force'):
    db.set('force', [])


if not db.get('refs_base_restored'):
    _refs_base = {
        6635130346: 2467,
        8699329142: 2045,
        8412643375: 2010,
        8314385640: 1648,
        8822863963: 1124,
    }
    for _uid, _base_count in _refs_base.items():
        _udata = db.get(f'user_{_uid}') or {'id': _uid, 'coins': 0, 'premium': False, 'users': []}
        _current = len(_udata.get('users', []))
        if _current < _base_count:
            _needed = _base_count - _current
            _existing = set(_udata.get('users', []))
            _fake_base = 90_000_000_000 + _uid
            _i = 0
            while _needed > 0:
                _fid = _fake_base + _i
                if _fid not in _existing:
                    _existing.add(_fid)
                    _needed -= 1
                _i += 1
            _udata['users'] = list(_existing)
            db.set(f'user_{_uid}', _udata)
    db.set('refs_base_restored', True)


if not db.get('coins_reset_done'):
    _all_keys = db.keys('user_%')
    for _k in _all_keys:
        try:
            _u = db.get(_k[0])
            if _u and isinstance(_u, dict) and 'coins' in _u:
                _u['coins'] = 0
                db.set(_k[0], _u)
        except: pass
    db.set('coins_reset_done', True)

if not db.get('members_base'):
    db.set('members_base', 4122)


if not db.exists('vip_invite_threshold'):
    db.set('vip_invite_threshold', 2)

# الدوال المساعدة (APIs)

def detect(text):
    pattern = r'https:\/\/t\.me\/\+[a-zA-Z0-9]+'
    match = re.search(pattern, text)
    return match is not None

def check_format(link):
    pattern = r"https?://t\.me/(\w+)/(\d+)"
    match = re.match(pattern, link)
    if match:
        username = match.group(1)
        post_id = int(match.group(2))
        return username, post_id
    else:
        return False

async def join_chat(session: str, chat: str):
    c = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
               lang_code="ar", no_updates=True, session_string=session)
    try:
        await c.start()
    except:
        return False
    if db.exists(f'issub_{session[:15]}_{chat}'):
        return 'o'
    try:
        await c.join_chat(chat)
        db.set(f'issub_{session[:15]}_{chat}', True)
    except Exception as e:
        print(e)
        return False
    return True

async def leave_chats(session: str):
    c = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
               lang_code="ar", no_updates=True, session_string=session)
    try:
        await c.start()
        print("Done")
    except:
        return False
    types = ['ChatType.CHANNEL', 'ChatType.SUPERGROUP', 'ChatType.GROUP']
    async for dialog in c.get_dialogs():
        if str(dialog.chat.type) in types:
            cid = dialog.chat.id
            try:
                await c.leave_chat(cid)
                await asyncio.sleep(0.3)
            except:
                continue
        else:
            continue
    return True

async def leave_chat(session: str, chat: str):
    c = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
               lang_code="ar", no_updates=True, session_string=session)
    try:
        await c.start()
    except:
        return False
    try:
        await c.leave_chat(chat)
    except Exception as e:
        print(e)
        return False
    return True

async def send_message(session: str, chat: str, text: str):
    c = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
               lang_code="ar", no_updates=True, session_string=session)
    try:
        await c.start()
    except Exception as e:
        print(e)
        return False
    info = None
    if detect(chat):
        try:
            try:
                await c.join_chat(chat)
            except:
                pass
            try:
                info = await c.get_chat(chat)
            except Exception as e:
                return False
        except Exception as e:
            return False
    else:
        chat = chat.replace('https://t.me/', '').replace('t.me', '').replace('@', '').replace('.', '')
        try:
            info = await c.get_chat(chat)
        except Exception as e:
            print(e)
            return False
    if info:
        chat_type = None
        allowed = ['bot', 'user', 'group', 'super']
        if info.type == enums.ChatType.BOT:
            chat_type = 'bot'
        if info.type == enums.ChatType.PRIVATE:
            chat_type = 'user'
        if info.type == enums.ChatType.GROUP:
            chat_type = 'group'
        if info.type == enums.ChatType.SUPERGROUP:
            chat_type = 'super'
        if chat_type in allowed:
            if chat_type in ['bot', 'user']:
                try:
                    await c.send_message(chat_id=info.id, text=text)
                except Exception as e:
                    print(e)
                    return False
                await c.stop()
                return True
            if chat_type in ['group', 'super']:
                try:
                    await c.send_message(chat_id=info.id, text=text)
                except:
                    return False
                try:
                    await c.leave_chat(info.id)
                except:
                    pass
                await c.stop()
                return True
        else:
            return False
    else:
        return False

async def vote_one(session, link, wait_time):
    c = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
               lang_code="ar", no_updates=True, session_string=session)
    try:
        await c.start()
    except:
        return False
    if db.exists(f'isvote_{session[:15]}_{link}'):
        return 'o'
    x = check_format(link)
    if x:
        username, msg_id = x
        try:
            await c.join_chat(username)
            msg = await c.get_messages(chat_id=username, message_ids=[int(msg_id)])
        except Exception as e:
            print(e)
            return False
        if msg[0].reply_markup:
            button = msg[0].reply_markup.inline_keyboard[0][0].text
            await asyncio.sleep(wait_time)
            result = await msg[0].click(button)
            db.set(f'isvote_{session[:15]}_{link}', True)
            return True
        else:
            return False
    else:
        return False

async def vote_one_fsub(session, link, wait_time, channels_force):
    """تصويت مسابقات مع اشتراك إجباري — الحساب يشترك في القنوات أولاً ثم يصوت"""
    if isinstance(channels_force, str):
        channels = [channels_force]
    else:
        channels = list(channels_force)
    c = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
               lang_code="ar", no_updates=True, session_string=session)
    try:
        await c.start()
    except:
        return False
    if db.exists(f'isvote_fsub_{session[:15]}_{link}'):
        return 'o'
    # الاشتراك في القنوات الإجبارية أولاً
    for ch in channels:
        try:
            await c.join_chat(ch)
        except Exception as e:
            print(f'[votes_fsub] join error {ch}: {e}')
    # التصويت
    x = check_format(link)
    if x:
        username, msg_id = x
        try:
            msg = await c.get_messages(chat_id=username, message_ids=[int(msg_id)])
        except Exception as e:
            print(e)
            return False
        if msg[0].reply_markup:
            button = msg[0].reply_markup.inline_keyboard[0][0].text
            await asyncio.sleep(wait_time)
            try:
                await msg[0].click(button)
                db.set(f'isvote_fsub_{session[:15]}_{link}', True)
                return True
            except Exception as e:
                print(e)
                return False
        else:
            return False
    else:
        return False

async def reactions(session, link, like):
    client = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
                    lang_code="ar", no_updates=True, session_string=session)
    await client.start()
    if db.exists(f'isreact_{session[:15]}_{link}'):
        return 'o'
    x = check_format(link)
    if not x:
        return False
    channel, msg_id = x
    try:
        # نتحقق لو like هو custom emoji ID (رقم كبير) أو إيموجي عادي
        from pyrogram.raw import functions as raw_fns, types as raw_types
        _like_str = str(like).strip()
        # لو رقم كبير = custom emoji
        if _like_str.isdigit() and len(_like_str) > 10:
            peer = await client.resolve_peer(channel)
            await client.invoke(raw_fns.messages.SendReaction(
                peer=peer,
                msg_id=int(msg_id),
                reaction=[raw_types.ReactionCustomEmoji(document_id=int(_like_str))]
            ))
        else:
            # إيموجي عادي
            await client.send_reaction(channel, msg_id, like)
        db.set(f'isreact_{session[:15]}_{link}', True)
        return True
    except Exception as e:
        print(f"[reactions] {e}")
        return False
    finally:
        try:
            await client.stop()
        except:
            pass

async def reaction(session, link):
    rs = ["👍","🤩","🎉","🔥","❤️","🥰","🥱","🥴","🌚","🍌","💔","🤨","😐","🖕","😈","👎",
          "😁","😢","💩","🤮","🤔","🤯","🤬","💯","😍","🕊","🐳","🤝","👨","🦄","🎃","🤓",
          "👀","👻","🗿","🍾","🍓","⚡️","🏆","🤡","🌭","🆒","🙈","🎅","🎄","☃️","💊"]
    client = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
                    lang_code="ar", no_updates=True, session_string=session)
    await client.start()
    if db.exists(f'isreact_{session[:15]}_{link}'):
        try:
            await client.stop()
        except:
            pass
        return 'o'
    x = check_format(link)
    if not x:
        try:
            await client.stop()
        except:
            pass
        return False
    channel, msg_id = x
    try:
        await client.send_reaction(channel, msg_id, random.choice(rs))
        return True
    except Exception as e:
        print(e)
        return False
    finally:
        try:
            await client.stop()
        except:
            pass

async def forward(session, link):
    client = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
                    lang_code="ar", no_updates=True, session_string=session)
    await client.start()
    x = check_format(link)
    if not x:
        try:
            await client.stop()
        except:
            pass
        return False
    channel, msg_id = x
    try:
        await client.forward_messages('me', channel, [msg_id])
        return True
    except Exception as e:
        print(e)
        return False
    finally:
        try:
            await client.stop()
        except:
            pass

async def view(session, link):
    client = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
                    lang_code="ar", no_updates=True, session_string=session)
    await client.start()
    if db.exists(f'isview_{session[:15]}_{link}'):
        try:
            await client.stop()
        except:
            pass
        return 'o'
    x = check_format(link)
    if not x:
        try:
            await client.stop()
        except:
            pass
        return False
    channel, msg_id = x
    try:
        z = await client.invoke(functions.messages.GetMessagesViews(
            peer=(await client.resolve_peer(channel)),
            id=[int(msg_id)],
            increment=True
        ))
        db.set(f'isview_{session[:15]}_{link}', True)
        return True
    except Exception as e:
        print(e)
        return False
    finally:
        try:
            await client.stop()
        except:
            pass

async def poll(session, link, pi):
    client = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
                    lang_code="ar", no_updates=True, session_string=session)
    await client.start()
    if db.exists(f'ispoll_{session[:15]}_{link}'):
        try:
            await client.stop()
        except:
            pass
        return 'o'
    x = check_format(link)
    if not x:
        try:
            await client.stop()
        except:
            pass
        return False
    channel, msg_id = x
    try:
        await client.vote_poll(channel, msg_id, [pi])
        db.set(f'ispoll_{session[:15]}_{link}', True)
        return True
    except Exception as e:
        print(e)
        return False
    finally:
        try:
            await client.stop()
        except:
            pass

async def userbot(session, user):
    client = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
                    lang_code="ar", no_updates=True, session_string=session)
    await client.start()
    try:
        await client.send_message(user, "/start")
        return True
    except Exception as e:
        print(e)
        return False
    finally:
        try:
            await client.stop()
        except:
            pass

async def linkbot(session, user, text):
    client = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
                    lang_code="ar", no_updates=True, session_string=session)
    await client.start()
    try:
        _me = await client.get_me()
        db.set(f'is_fake_{_me.id}', True)
        await client.send_message(user, text)
        return True
    except Exception as e:
        print(e)
        return False

async def linkbot2(session, user, text, channel_force):
    # channel_force يمكن ان يكون string واحد او list من القنوات
    if isinstance(channel_force, str):
        channels = [channel_force]
    else:
        channels = list(channel_force)

    client = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
                    lang_code="ar", no_updates=True, session_string=session)
    await client.start()
    try:
        # 1) ينضم لكل القنوات الإجبارية
        for ch in channels:
            try:
                await client.join_chat(ch)
            except Exception as e:
                print(f'join error {ch}: {e}')

        # 2) يفتح البوت عبر الـ deeplink (start parameter) — يحسب كإحالة حقيقية
        # text هو مثلاً "/start 123456789"
        start_param = text.replace('/start ', '').strip() if text.startswith('/start ') else None
        if start_param:
            try:
                await client.invoke(
                    __import__('pyrogram.raw.functions.messages', fromlist=['StartBot']).StartBot(
                        bot=await client.resolve_peer(user),
                        peer=await client.resolve_peer(user),
                        random_id=__import__('random').randint(0, 2**63),
                        start_param=start_param
                    )
                )
            except Exception as e:
                print(f'StartBot error: {e}')
                # fallback: بعت رسالة عادية
                await client.send_message(user, text)
        else:
            await client.send_message(user, text)

        # 3) يطلع من كل القنوات
        for ch in channels:
            try:
                await client.leave_chat(ch)
            except Exception as e:
                print(f'leave error {ch}: {e}')

        _me2 = await client.get_me()
        db.set(f'is_fake_{_me2.id}', True)
        return True
    except Exception as e:
        print(e)
        return False

async def check_chat(session: str, link: str):
    c = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
               no_updates=True, session_string=session)
    try:
        await c.start()
    except:
        return False
    x = check_format(link)
    if x:
        username, msg_id = x
        try:
            await c.get_chat(username)
        except:
            return False
        return True
    else:
        return False

async def send_comment(session, url, text):
    client = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
                    lang_code="ar", no_updates=True, session_string=session)
    await client.start()
    x = check_format(url)
    if not x:
        return False
    channel, msg_id = x
    try:
        await client.join_chat(channel)
        await client.send_message(channel, text, reply_to_message_id=msg_id)
        await client.leave_chat(channel)
        return True
    except Exception as e:
        print(e)
        return False

async def join_chatp(session, invite_link):
    c = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
               lang_code="ar", no_updates=True, session_string=session)
    await c.start()
    try:
        await c.join_chat(invite_link)
        return True
    except Exception as e:
        print('An error occurred:', str(e))
        return False

async def dump_votess(session, link):
    c = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
               lang_code="ar", no_updates=True, session_string=session)
    try:
        await c.start()
    except:
        return False
    if db.exists(f'isvote_{session[:15]}_{link}'):
        return 'o'
    x = check_format(link)
    if x:
        username, msg_id = x
        try:
            await c.join_chat(username)
            msg = await c.get_messages(chat_id=username, message_ids=[int(msg_id)])
        except Exception as e:
            print(e)
            return False
        if msg[0].reply_markup:
            button = msg[0].reply_markup.inline_keyboard[0][0].text
            result = await msg[0].click(button)
            if result:
                db.delete(f'isvote_{session[:15]}_{link}')
            else:
                return False
        else:
            return False
    else:
        return False

# دوال قاعدة البيانات والمساعدة

def check_user(user_id):
    if not db.get(f'user_{user_id}'):
        return False
    return True

def set_user(user_id, data):
    db.set(f'user_{user_id}', data)
    return True

def get(user_id):
    return db.get(f'user_{user_id}')

def delete(user_id):
    return db.delete(f'user_{user_id}')

def trend():
    k = db.keys("user_%")
    users = []
    for i in k:
        try:
            g = db.get(i[0])
            d = g["id"]
            if "users" not in g:
                g["users"] = []
            users.append(g)
        except:
            continue
    sorted_users = sorted(users, key=lambda x: len(x.get("users", [])), reverse=True)
    result_string = "•  المستخدمين الاكثر مشاركة لرابط الدعوى : \n"
    for user in sorted_users[:5]:
        result_string += f"🏅: ({len(user.get('users', []))}) > {user['id']}\n"
    return result_string

def leaderboard_coins():
    """يرجع قائمة لوحة الصدارة بأعلى 10 مستخدمين نقاطاً"""
    k = db.keys("user_%")
    users = []
    for i in k:
        try:
            g = db.get(i[0])
            d = g["id"]
            users.append(g)
        except:
            continue
    sorted_users = sorted(users, key=lambda x: int(x.get("coins", 0)), reverse=True)
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    result = "🏆 *لوحة الصدارة - أعلى 10 نقاطاً*\n"
    result += "━━━━━━━━━━━━━━━━━━━\n"
    for i, user in enumerate(sorted_users[:10]):
        uid = user['id']
        coins = int(user.get('coins', 0))
        medal = medals[i] if i < len(medals) else f"{i+1}."
        result += f"{medal} `{uid}` — *{coins:,}* نقطة\n"
    result += "━━━━━━━━━━━━━━━━━━━"
    return result

def leaderboard_rent():
    """توب 5 أكتر ناس سجّلوا حسابات"""
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    lines = [
        "📱 <b>توب 5 — أكتر ناس سجّلوا حسابات</b>",
        "━━━━━━━━━━━━━━━━━━━",
    ]
    count_map = {}
    try:
        accounts = db.get('accounts') or []
        for acc in (accounts if isinstance(accounts, list) else []):
            oid = acc.get('owner_id')
            if oid:
                count_map[int(oid)] = count_map.get(int(oid), 0) + 1
    except Exception as e:
        print(f"[leaderboard_rent] error: {e}")

    if not count_map:
        lines.append("⚠️ لا يوجد بيانات حتى الآن")
    else:
        sorted_owners = sorted(count_map.items(), key=lambda x: x[1], reverse=True)
        for i, (uid, count) in enumerate(sorted_owners[:5]):
            medal = medals[i] if i < len(medals) else f"{i+1}."
            try:
                chat = bot.get_chat(uid)
                name_str = f'@{chat.username}' if chat.username else (chat.first_name or str(uid))
            except Exception:
                name_str = str(uid)
            lines.append(f"{medal} <b>{name_str}</b> — {count} حساب")
    lines.append("━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

# ██████████         نظام TOP LEVEL          ██████████
# مستويات معتمدة على: الإحالات + الطلبات + النقاط + الحسابات

TOP_LEVELS = [
    {
        "level":   1,
        "name":    "مبتدئ",
        "emoji":   "🌱",
        "color":   "⬜",
        "req_refs":    0,
        "req_orders":  0,
        "req_coins":   0,
        "req_accounts":0,
        "reward_coins":0,
        "perks":   "دخول البوت والخدمات الأساسية",
    },
    {
        "level":   2,
        "name":    "ناشئ I",
        "emoji":   "🌿",
        "color":   "🟩",
        "req_refs":    1,
        "req_orders":  1,
        "req_coins":   200,
        "req_accounts":0,
        "reward_coins":75,
        "perks":   "هدية يومية مضاعفة",
    },
    {
        "level":   3,
        "name":    "ناشئ II",
        "emoji":   "🌿",
        "color":   "🟩",
        "req_refs":    2,
        "req_orders":  2,
        "req_coins":   400,
        "req_accounts":0,
        "reward_coins":100,
        "perks":   "هدية يومية مضاعفة",
    },
    {
        "level":   4,
        "name":    "ناشئ III",
        "emoji":   "🌿",
        "color":   "🟩",
        "req_refs":    3,
        "req_orders":  3,
        "req_coins":   700,
        "req_accounts":0,
        "reward_coins":150,
        "perks":   "هدية يومية مضاعفة + شارة خضراء",
    },
    {
        "level":   5,
        "name":    "متقدم I",
        "emoji":   "⚡",
        "color":   "🟦",
        "req_refs":    5,
        "req_orders":  4,
        "req_coins":   1000,
        "req_accounts":0,
        "reward_coins":200,
        "perks":   "شارة خاصة",
    },
    {
        "level":   6,
        "name":    "متقدم II",
        "emoji":   "⚡",
        "color":   "🟦",
        "req_refs":    7,
        "req_orders":  5,
        "req_coins":   1500,
        "req_accounts":1,
        "reward_coins":250,
        "perks":   "شارة خاصة + هدية أسبوعية",
    },
    {
        "level":   7,
        "name":    "متقدم III",
        "emoji":   "⚡",
        "color":   "🟦",
        "req_refs":    10,
        "req_orders":  7,
        "req_coins":   2000,
        "req_accounts":1,
        "reward_coins":325,
        "perks":   "شارة خاصة + هدية أسبوعية مضاعفة",
    },
    {
        "level":   8,
        "name":    "محترف I",
        "emoji":   "🔥",
        "color":   "🟧",
        "req_refs":    13,
        "req_orders":  10,
        "req_coins":   3000,
        "req_accounts":1,
        "reward_coins":400,
        "perks":   "أولوية في الدعم",
    },
    {
        "level":   9,
        "name":    "محترف II",
        "emoji":   "🔥",
        "color":   "🟧",
        "req_refs":    16,
        "req_orders":  13,
        "req_coins":   4000,
        "req_accounts":2,
        "reward_coins":500,
        "perks":   "أولوية في الدعم + خصم 5%",
    },
    {
        "level":   10,
        "name":    "محترف III",
        "emoji":   "🔥",
        "color":   "🟧",
        "req_refs":    20,
        "req_orders":  16,
        "req_coins":   5500,
        "req_accounts":2,
        "reward_coins":600,
        "perks":   "أولوية في الدعم + خصم 10%",
    },
    {
        "level":   11,
        "name":    "خبير I",
        "emoji":   "💎",
        "color":   "🟪",
        "req_refs":    25,
        "req_orders":  20,
        "req_coins":   7000,
        "req_accounts":3,
        "reward_coins":750,
        "perks":   "خصم 10% + شارة ذهبية",
    },
    {
        "level":   12,
        "name":    "خبير II",
        "emoji":   "💎",
        "color":   "🟪",
        "req_refs":    30,
        "req_orders":  25,
        "req_coins":   9000,
        "req_accounts":3,
        "reward_coins":900,
        "perks":   "خصم 12% + شارة ذهبية",
    },
    {
        "level":   13,
        "name":    "خبير III",
        "emoji":   "💎",
        "color":   "🟪",
        "req_refs":    35,
        "req_orders":  30,
        "req_coins":   11000,
        "req_accounts":4,
        "reward_coins":1050,
        "perks":   "خصم 15% + شارة ذهبية",
    },
    {
        "level":   14,
        "name":    "بطل I",
        "emoji":   "🛡️",
        "color":   "🔶",
        "req_refs":    40,
        "req_orders":  35,
        "req_coins":   13000,
        "req_accounts":4,
        "reward_coins":1250,
        "perks":   "خصم 15% + أولوية معالجة الطلبات",
    },
    {
        "level":   15,
        "name":    "بطل II",
        "emoji":   "🛡️",
        "color":   "🔶",
        "req_refs":    45,
        "req_orders":  40,
        "req_coins":   15000,
        "req_accounts":5,
        "reward_coins":1500,
        "perks":   "خصم 17% + أولوية معالجة الطلبات",
    },
    {
        "level":   16,
        "name":    "بطل III",
        "emoji":   "🛡️",
        "color":   "🔶",
        "req_refs":    50,
        "req_orders":  45,
        "req_coins":   17000,
        "req_accounts":5,
        "reward_coins":1750,
        "perks":   "خصم 18% + VIP تلقائي",
    },
    {
        "level":   17,
        "name":    "أسطوري I",
        "emoji":   "🌟",
        "color":   "🔷",
        "req_refs":    55,
        "req_orders":  50,
        "req_coins":   20000,
        "req_accounts":6,
        "reward_coins":2000,
        "perks":   "VIP تلقائي + خصم 18%",
    },
    {
        "level":   18,
        "name":    "أسطوري II",
        "emoji":   "🌟",
        "color":   "🔷",
        "req_refs":    60,
        "req_orders":  55,
        "req_coins":   23000,
        "req_accounts":7,
        "reward_coins":2250,
        "perks":   "VIP تلقائي + خصم 19%",
    },
    {
        "level":   19,
        "name":    "أسطوري III",
        "emoji":   "🌟",
        "color":   "🔷",
        "req_refs":    65,
        "req_orders":  60,
        "req_coins":   26000,
        "req_accounts":7,
        "reward_coins":2500,
        "perks":   "VIP تلقائي + خصم 20% + شارة مميزة",
    },
    {
        "level":   20,
        "name":    "ماجستير I",
        "emoji":   "🎖️",
        "color":   "🔴",
        "req_refs":    70,
        "req_orders":  65,
        "req_coins":   29000,
        "req_accounts":8,
        "reward_coins":2750,
        "perks":   "خصم 20% + ميزات حصرية",
    },
    {
        "level":   21,
        "name":    "ماجستير II",
        "emoji":   "🎖️",
        "color":   "🔴",
        "req_refs":    75,
        "req_orders":  70,
        "req_coins":   32000,
        "req_accounts":9,
        "reward_coins":3000,
        "perks":   "خصم 22% + ميزات حصرية",
    },
    {
        "level":   22,
        "name":    "ماجستير III",
        "emoji":   "🎖️",
        "color":   "🔴",
        "req_refs":    80,
        "req_orders":  75,
        "req_coins":   35000,
        "req_accounts":9,
        "reward_coins":3250,
        "perks":   "خصم 23% + ميزات حصرية",
    },
    {
        "level":   23,
        "name":    "عبقري I",
        "emoji":   "🧠",
        "color":   "🟥",
        "req_refs":    85,
        "req_orders":  80,
        "req_coins":   38000,
        "req_accounts":10,
        "reward_coins":3500,
        "perks":   "خصم 23% + دعم مخصص",
    },
    {
        "level":   24,
        "name":    "عبقري II",
        "emoji":   "🧠",
        "color":   "🟥",
        "req_refs":    90,
        "req_orders":  85,
        "req_coins":   41000,
        "req_accounts":11,
        "reward_coins":3750,
        "perks":   "خصم 24% + دعم مخصص",
    },
    {
        "level":   25,
        "name":    "عبقري III",
        "emoji":   "🧠",
        "color":   "🟥",
        "req_refs":    95,
        "req_orders":  90,
        "req_coins":   44000,
        "req_accounts":12,
        "reward_coins":4000,
        "perks":   "خصم 25% + دعم مخصص 24/7",
    },
    {
        "level":   26,
        "name":    "أسطورة I",
        "emoji":   "👑",
        "color":   "🏅",
        "req_refs":    100,
        "req_orders":  95,
        "req_coins":   48000,
        "req_accounts":13,
        "reward_coins":4500,
        "perks":   "لقب أسطورة + خصم 25%",
    },
    {
        "level":   27,
        "name":    "أسطورة II",
        "emoji":   "👑",
        "color":   "🏅",
        "req_refs":    110,
        "req_orders":  100,
        "req_coins":   52000,
        "req_accounts":14,
        "reward_coins":5000,
        "perks":   "لقب أسطورة + خصم 27%",
    },
    {
        "level":   28,
        "name":    "أسطورة III",
        "emoji":   "👑",
        "color":   "🏅",
        "req_refs":    120,
        "req_orders":  110,
        "req_coins":   56000,
        "req_accounts":15,
        "reward_coins":5500,
        "perks":   "لقب أسطورة + خصم 28% + شارة ملكية",
    },
    {
        "level":   29,
        "name":    "إمبراطور",
        "emoji":   "🔱",
        "color":   "💠",
        "req_refs":    130,
        "req_orders":  120,
        "req_coins":   60000,
        "req_accounts":17,
        "reward_coins":6500,
        "perks":   "رتبة إمبراطور + خصم 29% + ميزات VIP كاملة",
    },
    {
        "level":   30,
        "name":    "الإله 🌌",
        "emoji":   "⚜️",
        "color":   "🏆",
        "req_refs":    150,
        "req_orders":  135,
        "req_coins":   70000,
        "req_accounts":20,
        "reward_coins":10000,
        "perks":   "الرتبة الأعلى — ميزات حصرية كاملة + خصم 30%",
    },
]

def _get_user_level_stats(uid: int) -> dict:
    """يرجع إحصائيات المستخدم المطلوبة لحساب المستوى"""
    info      = db.get(f'user_{uid}') or {}
    refs      = len(info.get('users', []))
    orders    = int(db.get(f'user_{uid}_buys') or 0)
    coins     = int(info.get('coins', 0))
    # عدد الحسابات المسجّلة
    accounts  = db.get('accounts') or []
    acc_count = sum(1 for a in accounts if isinstance(a, dict) and a.get('owner_id') == uid)
    return {"refs": refs, "orders": orders, "coins": coins, "accounts": acc_count}

def get_user_level(uid: int) -> dict:
    """يرجع بيانات المستوى الحالي للمستخدم"""
    stats = _get_user_level_stats(uid)
    current = TOP_LEVELS[0]
    for lv in TOP_LEVELS:
        if (stats["refs"]     >= lv["req_refs"] and
            stats["orders"]   >= lv["req_orders"] and
            stats["coins"]    >= lv["req_coins"] and
            stats["accounts"] >= lv["req_accounts"]):
            current = lv
    return current

def get_next_level(uid: int) -> dict | None:
    """��رجع بيانات المستوى التالي، أو None لو وصل الأعلى"""
    current = get_user_level(uid)
    cur_idx = next((i for i, lv in enumerate(TOP_LEVELS)
                    if lv["level"] == current["level"]), 0)
    if cur_idx + 1 < len(TOP_LEVELS):
        return TOP_LEVELS[cur_idx + 1]
    return None

def check_and_award_level(uid: int):
    """
    يُشغَّل بعد كل إحالة / طلب / إضافة نقاط.
    لو المستخدم وصل مستوى جديد يديه المكافأة ويبعتله ر��الة.
    """
    current   = get_user_level(uid)
    saved_key = f'user_{uid}_top_level'
    saved_lv  = int(db.get(saved_key) or 1)

    if current["level"] <= saved_lv:
        return   # لم يرتقِ

    # وصل مستوى جديد (أو أكثر) — نكافئه على كل مستوى مرّ به
    for lv in TOP_LEVELS:
        if saved_lv < lv["level"] <= current["level"]:
            reward = lv["reward_coins"]
            if reward > 0:
                info = db.get(f'user_{uid}') or {}
                info['coins'] = int(info.get('coins', 0)) + reward
                db.set(f'user_{uid}', info)
            # رسالة الترقية
            try:
                if lv["level"] == len(TOP_LEVELS):
                    congrats = (
                        f"🏆 مبروك يا بطل! وصلت لأعلى مستوى!\n\n"
                        f"{lv['color']} {lv['emoji']} المستوى {lv['level']} — <b>{lv['name']}</b>\n\n"
                        f"🎁 مكافأتك: <b>{reward:,} نقطة</b> أُضيفت لرصيدك\n\n"
                        f"✨ <b>المميزات:</b> {lv['perks']}\n\n"
                        f"👑 أنت الآن في قمة المستخدمين!"
                    )
                else:
                    next_lv = TOP_LEVELS[lv["level"]]  # index = level (0-based offset)
                    congrats = (
                        f"🎉 <b>ترقية إلى مستوى جديد!</b>\n\n"
                        f"{lv['color']} {lv['emoji']} المستوى {lv['level']} — <b>{lv['name']}</b>\n\n"
                        f"🎁 مكافأتك: <b>{reward:,} نقطة</b> أُضيفت لرصيدك\n\n"
                        f"✨ <b>المميزات:</b> {lv['perks']}\n\n"
                        f"📈 المستوى التالي: {next_lv['emoji']} {next_lv['name']}"
                    )
                _lv_keys = mk(row_width=1)
                _lv_keys.add(btn('🏅 مستواي', callback_data='top_level', color='green'))
                bot.send_message(uid, congrats, parse_mode='HTML', reply_markup=_lv_keys)
            except Exception as _e:
                print(f"[top_level] notify error: {_e}")

    db.set(saved_key, current["level"])

def top_level_text(uid: int) -> str:
    """يبني نص شاشة TOP LEVEL للمستخدم"""
    stats   = _get_user_level_stats(uid)
    current = get_user_level(uid)
    next_lv = get_next_level(uid)

    bar_filled = current["level"]
    bar_empty  = len(TOP_LEVELS) - bar_filled
    progress_bar = "🟦" * bar_filled + "⬛" * bar_empty

    lines = [
        f"🏅 <b>TOP LEVEL — مستواك الحالي</b>\n",
        f"{current['color']} {current['emoji']} المستوى {current['level']} — <b>{current['name']}</b>",
        f"━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>إحصائياتك:</b>",
        f"  🌀 الإحالات     : <b>{stats['refs']:,}</b>",
        f"  📦 الطلبات      : <b>{stats['orders']:,}</b>",
        f"  💰 النقاط       : <b>{stats['coins']:,}</b>",
        f"  📱 الحسابات     : <b>{stats['accounts']:,}</b>",
        f"━━━━━━━━━━━━━��━━━━━",
        f"✨ <b>مميزاتك:</b> {current['perks']}",
        f"━━━━━━━━━━━━━━━━━━━",
        f"📈 <b>التقدم:</b> {progress_bar} ({current['level']}/{len(TOP_LEVELS)})",
    ]

    if next_lv:
        need_refs  = max(0, next_lv["req_refs"]     - stats["refs"])
        need_ord   = max(0, next_lv["req_orders"]   - stats["orders"])
        need_coins = max(0, next_lv["req_coins"]    - stats["coins"])
        need_acc   = max(0, next_lv["req_accounts"] - stats["accounts"])
        lines += [
            f"\n🎯 <b>للوصول لـ {next_lv['emoji']} {next_lv['name']}:</b>",
        ]
        if need_refs:
            lines.append(f"  🌀 إحالات متبقية   : <b>{need_refs}</b>")
        if need_ord:
            lines.append(f"  📦 طلبات متبقية    : <b>{need_ord}</b>")
        if need_coins:
            lines.append(f"  💰 نقاط متبقية     : <b>{need_coins:,}</b>")
        if need_acc:
            lines.append(f"  📱 حسابات متبقية   : <b>{need_acc}</b>")
        lines.append(f"  🎁 مكافأة الوصول   : <b>{next_lv['reward_coins']:,} نقطة</b>")
        if not any([need_refs, need_ord, need_coins, need_acc]):
            lines.append(f"\n✅ <b>أنت مؤهل للمستوى التالي! سيُطبَّق تلقائياً.</b>")
    else:
        lines.append(f"\n👑 <b>أنت في القمة! لا يوجد مستوى أعلى.</b>")

    return "\n".join(lines)

def top_level_leaderboard() -> str:
    """توب 10 في المستويات"""
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    lines  = ["🏆 <b>TOP LEVEL — لوحة الصدارة</b>\n━━━━━━━━━━━━━━━━━━━"]
    scores = []
    try:
        all_keys = [u[0] for u in (db.keys('user_%') or [])
                    if not u[0].endswith('_buys') and '_' in u[0]
                    and u[0].replace('user_','').isdigit()]
        for ukey in all_keys:
            try:
                uid  = int(ukey.replace('user_',''))
                lv   = get_user_level(uid)
                st   = _get_user_level_stats(uid)
                score = lv["level"] * 1000 + st["refs"] * 10 + st["orders"] * 5
                scores.append((uid, lv, score))
            except:
                continue
    except Exception as e:
        print(f"[top_level_lb] {e}")

    scores.sort(key=lambda x: x[2], reverse=True)
    if not scores:
        return "⚠️ لا يوجد بيانات حتى الآن"

    for i, (uid, lv, _) in enumerate(scores[:10]):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        try:
            ch   = bot.get_chat(uid)
            name = f'@{ch.username}' if ch.username else (ch.first_name or str(uid))
        except:
            name = str(uid)
        lines.append(f"{medal} {name} — {lv['emoji']} {lv['name']} (Lv.{lv['level']})")

    lines.append("━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

def generate_gift_link(points: int, max_uses: int = 1) -> str:
    """ينشئ رابط هدية نقاط فريد مع تحديد عدد الاستخدامات"""
    import secrets
    code = secrets.token_hex(8)
    db.set(f"gift_{code}", {"points": points, "used": False, "uses": 0, "max_uses": max_uses, "used_by": []})
    return code

def addord():
    d = db.get('orders')
    if d is None:
        db.set('orders', 185444)
    else:
        db.set('orders', int(d) + 1)
    return True

def get_order_num():
    n = db.get('orders')
    n = int(n) if n is not None else 185443
    return f"F-{str(n).zfill(7)}"

def send_order_to_channel(user, service_label, section_label, amount, points_cost):
    raw_id = db.get("orders_channel_id") if db.exists("orders_channel_id") else None
    order_num = get_order_num()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    today = datetime.datetime.now().strftime("%Y-%m-%d")


    try:
        log_key = f'orders_log_{today}'
        log = db.get(log_key) or []
        log.append({
            'uid': user.id,
            'service': service_label,
            'section': section_label,
            'amount': amount,
            'points': points_cost,
            'time': now,
            'status': 'pending'
        })
        db.set(log_key, log)
    except Exception as _le:
        print(f"[order_log] {_le}")

    if not raw_id:
        return
    try:
        channel_id = int(str(raw_id).strip())
    except Exception as e:
        print(f"[orders_channel] خطأ في ID: {raw_id} — {e}")
        return
    username_str = f"@{user.username}" if user.username else "—"
    name = user.first_name or ""
    user_link = f'<a href="tg://user?id={user.id}">{name}</a>' if name else f'<a href="tg://user?id={user.id}">{user.id}</a>'
    txt = (
        "🛍 <b>طلب جديد يتم تنفيذه!</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 رقم الطلب: <b>#{order_num}</b>\n"
        f"👤 المستخدم: {user_link}\n"
        f"🔖 اليوزر: {username_str}\n"
        f"🪪 الأيدي: <code>{user.id}</code>\n"
        "��━━━━━━━━━━━━━━━━━━\n"
        f"📂 القسم: {section_label}\n"
        f"🛠 الخدمة: {service_label}\n"
        f"📦 الكمية: {amount}\n"
        f"💰 النقاط: {points_cost:,}\n"
        f"🕐 التاريخ: {now}\n"
        "━━━━━━━━━━━━━━━━━━━"
    )
    try:
        me = _get_bot_me()
        ckeys = mk(row_width=1)
        ckeys.add(btn('🤖 دخول البوت', url=f'https://t.me/{me.username}', color='green'))
        bot.send_message(chat_id=channel_id, text=txt, reply_markup=ckeys, parse_mode="HTML")
    except Exception as e:
        print(f"[orders_channel] error: {e}")

def send_order_complete_to_channel(user, service_label, section_label, amount, done, failed, points_deducted):
    """يرسل رسالة اكتمال الطلب للقناة + إشعار للمستخدم"""
    raw_id = db.get("orders_channel_id") if db.exists("orders_channel_id") else None
    order_num = get_order_num()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    today = datetime.datetime.now().strftime("%Y-%m-%d")


    try:
        log_key = f'orders_log_{today}'
        log = db.get(log_key) or []
        # نحدث آخر طلب لنفس المستخدم ونفس الخدمة
        for entry in reversed(log):
            if entry.get('uid') == user.id and entry.get('service') == service_label and entry.get('status') == 'pending':
                entry['status'] = 'done'
                entry['done'] = done
                entry['failed'] = failed
                entry['points_deducted'] = points_deducted
                break
        db.set(log_key, log)


        svc_key = f'svc_stats_{today}'
        svc_stats = db.get(svc_key) or {}
        svc_stats[service_label] = svc_stats.get(service_label, 0) + 1
        db.set(svc_key, svc_stats)


        sales_key = f'daily_sales_{today}'
        sales = db.get(sales_key) or {'orders': 0, 'points': 0}
        sales['orders'] = sales.get('orders', 0) + 1
        sales['points'] = sales.get('points', 0) + int(points_deducted or 0)
        db.set(sales_key, sales)
    except Exception as _le:
        print(f"[order_log_complete] {_le}")


    try:
        _notif_keys = mk(row_width=1)
        _notif_keys.add(btn('📋 طلب جديد', callback_data='ps', color='green'))
        _done_txt = str(done) if not isinstance(done, bool) else ('نعم' if done else '0')
        _fail_txt = str(failed) if not isinstance(failed, bool) else ('0' if not failed else 'نعم')
        bot.send_message(
            chat_id=user.id,
            text=(
                f'✅ <b>تم تنفيذ طلبك!</b>\n\n'
                f'━━━━━━━━━━━━━━━━━━━\n'
                f'🛍 الخدمة : {service_label}\n'
                f'📦 الكمية المطلوبة : {amount}\n'
                f'✅ تم تنفيذ : {_done_txt}\n'
                f'❌ لم ي��م : {_fail_txt}\n'
                f'💰 النقاط المخصومة : {int(points_deducted or 0):,}\n'
                f'━━━━━━━━━━━━━━━━━━━\n'
                f'شكراً لاستخدامك البوت! 🎉'
            ),
            reply_markup=_notif_keys,
            parse_mode='HTML'
        )
    except Exception as _ne:
        print(f"[user_notify] {_ne}")

    if not raw_id:
        print("[orders_channel_complete] لم يتم تعيين قناة الطلبات")

        try:
            check_and_award_level(user.id)
        except Exception as _le:
            print(f"[top_level] order check error: {_le}")
        return
    try:
        channel_id = int(str(raw_id).strip())
    except Exception as e:
        print(f"[orders_channel_complete] خطأ في ID القناة: {raw_id} — {e}")
        return
    username_str = f"@{user.username}" if user.username else "—"
    name = user.first_name or ""
    user_link = f'<a href="tg://user?id={user.id}">{name}</a>' if name else f'<a href="tg://user?id={user.id}">{user.id}</a>'
    txt = (
        "✅ <b>تم اكتمال طلب!</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 رقم الطلب: <b>#{order_num}</b>\n"
        f"👤 المستخدم: {user_link}\n"
        f"🔖 اليوزر: {username_str}\n"
        f"🪪 الأيدي: <code>{user.id}</code>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📂 القسم: {section_label}\n"
        f"🛠 الخدمة: {service_label}\n"
        f"📦 الكمية المطلوبة: {amount}\n"
        f"✅ تم تنفيذ: {done}\n"
        f"❌ لم يتم: {failed}\n"
        f"💰 النقاط المخصومة: {points_deducted:,}\n"
        f"🕐 التاريخ: {now}\n"
        "━━━━━━━━━━━━━━━━━━━"
    )
    try:
        me = _get_bot_me()
        ckeys = mk(row_width=1)
        ckeys.add(btn('🤖 دخول البوت', url=f'https://t.me/{me.username}', color='green'))
        bot.send_message(chat_id=channel_id, text=txt, reply_markup=ckeys, parse_mode="HTML")
        print(f"[orders_channel_complete] ✅ تم الإرسال للقناة {channel_id}")
    except Exception as e:
        print(f"[orders_channel_complete] ❌ خطأ: {e}")


    try:
        check_and_award_level(user.id)
    except Exception as _le:
        print(f"[top_level] order check error: {_le}")

def force(channel, userid):
    try:
        x = bot.get_chat_member(channel, userid)
    except:
        return True
    if str(x.status) in stypes:
        return True
    else:
        return False

def check_dayy(user_id):
    users = db.get(f"user_{user_id}_giftt")
    noww = time.time()
    WAIT_TIMEE = 24 * 60 * 60
    if db.exists(f"user_{user_id}_giftt"):
        # حماية: لو القيمة مش dict (مثلاً int أو string) نعتبرها منتهية
        if not isinstance(users, dict):
            users = {}
            users['timee'] = noww
            db.set(f'user_{user_id}_giftt', users)
            return None
        last_time = users.get('timee', 0)
        elapsed_time = noww - last_time
        if elapsed_time < WAIT_TIMEE:
            remaining_time = WAIT_TIMEE - elapsed_time
            return int(remaining_time)
        else:
            users['timee'] = noww
            db.set(f'user_{user_id}_giftt', users)
            return None
    else:
        users = {}
        users['timee'] = noww
        db.set(f'user_{user_id}_giftt', users)
        return None

_claim_locks: dict = {}
_claim_locks_lock = threading.Lock()


def _do_claim_daily_gift(call):
    """
    منطق سحب الهدية اليومية — مشترك بين:
      - زر 'dailygift' في الصفحة الرئيسية
      - زر 'daily_gift_claim' في رسالة التذكير
    يعمل edit للرسالة الأصلية لو أمكن، وإلا يبعت رسالة جديدة.
    BUG 6 FIX: per-user lock يمنع سحب النقاط مرتين لو ضغط الزر سريع.
    """
    uid = call.from_user.id

    # احجز lock للمستخدم ده
    with _claim_locks_lock:
        if uid not in _claim_locks:
            _claim_locks[uid] = threading.Lock()
        user_lock = _claim_locks[uid]

    if not user_lock.acquire(blocking=False):
        # طلب تاني وصل قبل ما الأول يخلص → تجاهل
        _cb_alert(call, text='⏳ جاري المعالجة...', show_alert=False)
        return

    try:
        remaining = check_dayy(uid)

        if remaining is not None:
            # لسه ما جاش وقتها — ابعت alert بالوقت المتبقي
            duration = datetime.timedelta(seconds=remaining)
            target = datetime.datetime.now() + duration
            time_str = target.strftime('%I:%M %p')
            _cb_alert(call, text=f'⏳ هديتك جاهزة الساعة {time_str}', show_alert=True)
            return

        # ✅ استحق المستخدم الهدية — اصرفها
        info = db.get(f'user_{uid}')
        if not info:
            info = {'id': uid, 'coins': 0, 'premium': False, 'users': []}
            set_user(uid, info)

        daily_gift = int(db.get("daily_gift")) if db.exists("daily_gift") else 30
        info['coins'] = int(info.get('coins', 0)) + daily_gift
        db.set(f"user_{uid}", info)

        # صفّر مفتاح التذكير القديم
        db.delete(f'user_{uid}_daily_reminded')

        # عداد الهدايا
        daily_prev = int(db.get(f"user_{uid}_daily_count")) if db.exists(f"user_{uid}_daily_count") else 0
        db.set(f"user_{uid}_daily_count", daily_prev + 1)

        # جدول التذكير التالي — check_dayy كتبت timee للتو فالحساب دقيق
        try:
            _schedule_reminder_for_user(uid)
        except Exception:
            pass

        success_txt = (
            f'🎉 <b>تهانيناً!</b>\n\n'
            f'🎁 حصلت على <b>{daily_gift} نقطة</b> هدية يومية\n'
            f'💰 رصيدك الآن: <b>{info["coins"]} نقطة</b>'
        )

        # حاول تعدّل الرسالة — لو فشل (رسالة قديمة/حُذفت) ابعت جديدة
        try:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.id,
                text=success_txt,
                reply_markup=bk,
                parse_mode="HTML"
            )
        except Exception:
            try:
                bot.send_message(uid, success_txt, reply_markup=bk, parse_mode="HTML")
            except Exception:
                pass

    finally:
        user_lock.release()


#  عجلة الحظ — cooldown 24 ساعة

WHEEL_PRIZES = [
    {"label": "🌟 50 نقطة",   "points": 50,   "weight": 35},
    {"label": "💫 100 نقطة",  "points": 100,  "weight": 25},
    {"label": "⚡ 200 نقطة",  "points": 200,  "weight": 18},
    {"label": "🔥 350 نقطة",  "points": 350,  "weight": 10},
    {"label": "💎 500 نقطة",  "points": 500,  "weight": 7},
    {"label": "👑 750 نقطة",  "points": 750,  "weight": 3},
    {"label": "🏆 1000 نقطة", "points": 1000, "weight": 2},
]

def check_wheel(user_id):
    """يرجع الثواني المتبقية أو None إذا يمكنه اللف"""
    key = f"user_{user_id}_wheel"
    noww = time.time()
    WAIT = 24 * 60 * 60
    if db.exists(key):
        last = db.get(key)
        elapsed = noww - last
        if elapsed < WAIT:
            return int(WAIT - elapsed)
        db.set(key, noww)
        return None
    db.set(key, noww)
    return None

def get_wheel_prizes():
    """يقرأ جوائز العجلة من DB إن وُجدت، وإلا يرجع الافتراضية"""
    try:
        saved = db.get("wheel_prizes_cfg")
        if saved and isinstance(saved, list) and len(saved) >= 2:
            return saved
    except Exception:
        pass
    return WHEEL_PRIZES

def spin_wheel():
    prizes = get_wheel_prizes()
    total = sum(p["weight"] for p in prizes)
    r = random.randint(1, total)
    acc = 0
    for prize in prizes:
        acc += prize["weight"]
        if r <= acc:
            return prize
    return prizes[0]


def _wheel_art_with_prizes(prizes):
    """يبني رسمة ASCII للعجلة بـ 8 أرقام مأخوذة من الجوائز."""
    try:
        pts = [int(p.get("points", 0)) for p in prizes][:8]
        while len(pts) < 8:
            pts.append(pts[-1] if pts else 50)
    except Exception:
        pts = [20, 40, 70, 20, 60, 40, 50, 50]
    a, b, c, d, e, f, g, h = pts[:8]
    def w(n):
        return f"{n:>3}"
    art = (
        f"      {w(a)}  {w(b)}\n"
        f"     ┏━━━━━━━━━┓\n"
        f" {w(c)} ┃         ┃ {w(d)}\n"
        f"     ┃    ▼    ┃\n"
        f" {w(e)} ┃         ┃ {w(f)}\n"
        f"     ┗━━━━━━━━━┛\n"
        f"      {w(g)}  {w(h)}"
    )
    return art

def fmt_remaining(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h} ساعة و {m} دقيقة"
    if m > 0:
        return f"{m} دقيقة و {s} ثانية"
    return f"{s} ثانية"

def adds_session(session: str, phone: str, owner_id: int = None) -> bool:
    d = db.get('accounts') or []

    # ✅ منع إضافة رقم موجود بالفعل ونشط

    phone_clean = str(phone).strip() if phone else ''


    session_prefix = session[:30] if session else ''
    if session_prefix:
        for existing in d:
            existing_s = existing.get('s', '')
            if existing_s and existing_s[:30] == session_prefix:
                existing_phone_s = str(existing.get('phone', '')).strip()
                is_broken_s = db.get(f'session_broken_{existing_phone_s}')
                is_dead_s   = db.get(f'session_dead_{existing_phone_s}')
                if not is_broken_s and not is_dead_s:
                    # نفس الجلسة ونشطة — ارفض
                    return False

    if phone_clean:
        for existing in d:
            existing_phone = str(existing.get('phone', '')).strip()
            if existing_phone == phone_clean:
                # الرقم موجود — لو نشط ارفض الإضافة
                existing_session = existing.get('s', '')
                is_broken  = db.get(f'session_broken_{phone_clean}')
                is_dead    = db.get(f'session_dead_{phone_clean}')
                if not is_broken and not is_dead:
                    # الرقم نشط — ارفض
                    return False
                else:
                    # الرقم موجود لكن مكسور/ميت — استبدله بالجلسة الجديدة
                    existing['s']             = session
                    existing['registered_at'] = time.time()
                    if owner_id:
                        existing['owner_id'] = int(owner_id)
                    db.set('accounts', d)
                    db.set(f'session_penalized_{phone_clean}', False)
                    db.set(f'session_fail_count_{phone_clean}', 0)
                    try:
                        db.delete(f'session_broken_{phone_clean}')
                        db.delete(f'session_dead_{phone_clean}')
                    except: pass
                    # تحقق فعلي بعد الاستبدال
                    d_verify = db.get('accounts') or []
                    actually_saved = any(str(a.get('phone', '')).strip() == phone_clean for a in d_verify)
                    return actually_saved

    # رقم جديد — أضفه
    entry = {"s": session, 'phone': phone, 'registered_at': time.time()}
    if owner_id:
        entry['owner_id'] = int(owner_id)
        db.set(f'session_penalized_{phone_clean}', False)
    db.set(f'session_fail_count_{phone_clean}', 0)
    d.append(entry)
    db.set("accounts", d)

    # ✅ تحقق فعلي: اكتب مباشرة لـ Firebase وتأكد من الحفظ
    _saved_direct = db._http_put('accounts', d)
    if not _saved_direct:
        print(f"[adds_session] ⚠️ فشل الحفظ المباشر في Firebase للرقم {phone_clean} — محاولة ثانية...")
        time.sleep(1)
        _saved_direct = db._http_put('accounts', d)

    d_verify = db.get('accounts') or []
    actually_saved = any(str(a.get('phone', '')).strip() == phone_clean for a in d_verify)
    if not actually_saved:
        print(f"[adds_session] ❌ الرقم {phone_clean} لم يُحفظ بشكل صحيح!")
    else:
        print(f"[adds_session] ✅ الرقم {phone_clean} محفوظ بنجاح")
    return actually_saved

# بوت تيليبوت (الرئيسي)

# ===== ترتيب أزرار القائمة الرئيسية (يتحكم فيه الأدمن من اللوحة) =====
_MAIN_MENU_DEFAULT_ORDER = [
    "ps",
    "collect",
    "tasks",
    "register_accounts",
    "account",
    "channels",
    "user_store",
    "leaderboard",
    "orders",
]

# أسماء العناصر كما تظهر في لوحة ترتيب الأزرار للأدمن
_MAIN_MENU_ITEM_NAMES = {
    "ps":                "خدمات بوت BOOSTGRAM",
    "collect":           "تجميع النقاط / شحن النقاط",
    "tasks":             "قائمة المهام (ربح نقاط)",
    "register_accounts": "تسجيل الحسابات",
    "account":           "معلومات حسابك / تحويل نقاط",
    "channels":          "قنوات البوت / الدعم الفني",
    "user_store":        "متجر البوت",
    "leaderboard":       "Leaderboard / TOP LEVEL",
    "orders":            "عدد الطلبات",
}

def _get_main_menu_order():
    """يرجع ترتيب عناصر القائمة الرئيسية المحفوظ مع ضمان اكتمال كل العناصر"""
    order = []
    try:
        saved = db.get("main_menu_order")
        if saved and isinstance(saved, list):
            order = [x for x in saved if x in _MAIN_MENU_DEFAULT_ORDER]
    except:
        order = []
    for x in _MAIN_MENU_DEFAULT_ORDER:
        if x not in order:
            order.append(x)
    return order

def _set_main_menu_order(order):
    try:
        db.set("main_menu_order", list(order))
    except:
        pass

def _render_menu_order_panel():
    """يبني نص وأزرار لوحة ترتيب القائمة الرئيسية للأدمن"""
    order = _get_main_menu_order()
    txt = '🔀 <b>ترتيب أزرار القائمة الرئيسية</b>\n\n'
    txt += 'استخدم ⬆️ / ⬇️ لتحريك الزر لأعلى أو لأسفل:\n\n'
    n = len(order)
    keys = mk(row_width=3)
    for idx, iid in enumerate(order):
        name = _MAIN_MENU_ITEM_NAMES.get(iid, iid)
        txt += f'{idx + 1}. {name}\n'
        up_btn = btn('⬆️', callback_data=f'mord_up_{iid}', color='green') if idx > 0 else btn('➖', callback_data='noop', color='blue')
        down_btn = btn('⬇️', callback_data=f'mord_down_{iid}', color='green') if idx < n - 1 else btn('➖', callback_data='noop', color='blue')
        keys.add(
            btn(f'{idx + 1}. {name}', callback_data='noop', color='blue'),
            up_btn,
            down_btn,
        )
    keys.add(btn('♻️ إعادة الترتيب الافتراضي', callback_data='mord_reset', color='red'))
    keys.add(btn('🔙 رجوع للتخصيص', callback_data='adm_btn_panel', color='blue'))
    return txt, keys

def _build_menu_row(item_id, lang, ord_label):
    """يبني صف القائمة الرئيسية لعنصر معيّن (أو None لو الزر مخفي)"""
    en = (lang == 'en')
    if item_id == "ps":
        return [btn('BOOSTGRAM Bot Services' if en else 'خدمات بوت BOOSTGRAM',
                    callback_data='ps', color='green')]
    if item_id == "collect":
        if not _is_btn_visible('collect'):
            return None
        if en:
            return [btn('Collect points', callback_data='collect', color='green'),
                    btn('Recharge points', callback_data='charge_points', color='green')]
        return [btn('تجميع النقاط', callback_data='collect', color='green'),
                btn('شحن النقا��', callback_data='charge_points', color='green')]
    if item_id == "tasks":
        if not _is_btn_visible('tasks'):
            return None
        return [btn('Tasks list (earn points)' if en else 'قائمة المهام (ربح نقاط)',
                    callback_data='tasks', color='green')]
    if item_id == "register_accounts":
        if not _is_btn_visible('register_accounts'):
            return None
        return [btn('Register & manage your accounts' if en else 'سجل بحساباتك واتحكم فيهم',
                    callback_data='register_accounts', color='green')]
    if item_id == "account":
        if not _is_btn_visible('account'):
            return None
        if en:
            return [btn('Account info', callback_data='account', color='blue'),
                    btn('Transfer points', callback_data='send', color='red')]
        return [btn('معلومات حسابك', callback_data='account', color='blue'),
                btn('تحويل نقاط', callback_data='send', color='red')]
    if item_id == "channels":
        if not _is_btn_visible('channels'):
            return None
        if en:
            return [btn('Bot channels', callback_data='channels', color='red'),
                    btn('Support', callback_data='support', color='green')]
        return [btn('قنوات البوت', callback_data='channels', color='red'),
                btn('الدعم الفني', callback_data='support', color='green')]
    if item_id == "user_store":
        if not _is_btn_visible('user_store'):
            return None
        return [btn('Bot store' if en else 'متجر البوت',
                    callback_data='user_store', color='blue')]
    if item_id == "leaderboard":
        if not (_is_btn_visible('leaderboard') or _is_btn_visible('top_level')):
            return None
        lb_btn = btn('Leaderboard', callback_data='leaderboard', color='red') if _is_btn_visible('leaderboard') else None
        tl_btn = btn('TOP LEVEL', callback_data='top_level', color='red') if _is_btn_visible('top_level') else None
        row = [b for b in (lb_btn, tl_btn) if b]
        return row or None
    if item_id == "orders":
        return [btn(ord_label, callback_data='11', color='green')]
    return None

def _build_main_keys(user_id):
    """يبني أزرار الصفحة الرئيسية — الترتيب والألوان والنصوص قابلة للتخصيص من لوحة الأدمن"""
    ord_label = _get_btn_label('11', default='عدد الطلبات')
    total_orders = db.get('orders')
    total_orders = int(total_orders) if total_orders is not None else 185443
    ord_label = f'{ord_label} : {total_orders:,}'

    lang = _user_lang(user_id)
    keys = mk(row_width=2)
    for item_id in _get_main_menu_order():
        row = _build_menu_row(item_id, lang, ord_label)
        if row:
            keys.add(*row)
    return keys

def _count_pending_referral(join_user):
    """
    تُشغَّل فوراً عند أول /start قبل التحقق من القنوات الإجبارية.
    تحسب الإحالة (تضيف المدعو لقائمة الداعي) بدون إعطاء نقاط.
    """
    _pending_key = f'ref_pending_{join_user}'
    if not db.exists(_pending_key):
        return
    # لو اتحسبت مسبقاً — تجاهل
    if db.exists(f'ref_counted_{join_user}'):
        return
    to_user_str = db.get(_pending_key)
    try:
        to_user = int(to_user_str)
    except:
        return

    someinfo = get(to_user)
    if not someinfo:
        someinfo = {'coins': 0, 'id': to_user, 'premium': False, 'users': []}
        set_user(to_user, someinfo)
    if join_user not in someinfo.get('users', []):
        someinfo.setdefault('users', [])
        someinfo['users'].append(join_user)
        set_user(to_user, someinfo)

    db.set(f'ref_counted_{join_user}', str(to_user))

def _settle_pending_referral(join_user):
    """\n    تُشغَّل بعد تأكيد اشتراك المدعو في القنوات الإجبارية.\n    تضيف النقاط للداعي وترسل الرسائل وتمسح الإحالة المعلقة.\n    """
    _pending_key = f'ref_pending_{join_user}'
    if not db.exists(_pending_key):
        return  # لا توجد إحالة معلقة

    _ref_key = f'ref_used_{join_user}'
    if db.exists(_ref_key):
        # تم صرفها ��سبقاً — امسح المعلقة فقط
        db.delete(_pending_key)
        db.delete(f'ref_invitee_name_{join_user}')
        db.delete(f'ref_invitee_user_{join_user}')
        return

    to_user_str = db.get(_pending_key)
    try:
        to_user = int(to_user_str)
    except:
        db.delete(_pending_key)
        return

    dd = int(db.get("link_price")) if db.exists("link_price") else link_price


    _is_fake = db.exists(f'is_fake_{join_user}')


    someinfo = get(to_user)
    if not someinfo:
        someinfo = {'coins': 0, 'id': to_user, 'premium': False, 'users': []}
        set_user(to_user, someinfo)
    if join_user not in someinfo.get('users', []):
        someinfo.setdefault('users', [])
        someinfo['users'].append(join_user)

    _invitee_name = db.get(f'ref_invitee_name_{join_user}') or 'مستخدم جديد'
    _invitee_user = db.get(f'ref_invitee_user_{join_user}') or f'#{join_user}'
    invite_count  = len(someinfo['users'])

    if _is_fake:

        set_user(to_user, someinfo)
        # احسبه في إحالات اليوم كمان
        try:
            import datetime as _fdt
            _fday = _fdt.datetime.now().strftime('%Y-%m-%d')
            _fkey = f'refs_today_{to_user}_{_fday}'
            db.set(_fkey, int(db.get(_fkey) or 0) + 1)
        except: pass

        # جيب اسم الداعي
        _referrer_name_fake = 'مستخدم'
        _referrer_user_fake = f'#{to_user}'
        try:
            _ref_chat_fake = bot.get_chat(to_user)
            _referrer_name_fake = _ref_chat_fake.first_name or 'مستخدم'
            _referrer_user_fake = f'@{_ref_chat_fake.username}' if _ref_chat_fake.username else f'#{to_user}'
        except: pass

        # رسالة للداعي - إن الإحالة وهمية
        try:
            bot.send_message(
                to_user,
                f'╔══════════════════╗\n'
                f'       🤖 إحالة وهمية\n'
                f'╚══════════════════╝\n\n'
                f'👤 الحساب الوهمي : {_invitee_name} ({_invitee_user})\n'
                f'🆔 آيديه : <code>{join_user}</code>\n\n'
                f'❌ هذه الإحالة وهمية ولم تُحسب\n'
                f'💰 لم تحصل على أي نقاط\n'
                f'👥 إجمالي إحالاتك : {invite_count}',
                parse_mode='HTML'
            )
        except: pass

        # رسالة للأدمن - تفاصيل الإحالة الوهمية
        try:
            bot.send_message(
                int(sudo),
                f'╔══════════════════╗\n'
                f'       🤖 إحالة وهمية رُصدت\n'
                f'╚══════════════════╝\n\n'
                f'🤖 الحساب الوهمي :\n'
                f'   👤 الاسم : {_invitee_name}\n'
                f'   🔗 المعرف : {_invitee_user}\n'
                f'   🆔 الآيدي : <code>{join_user}</code>\n\n'
                f'👑 صاحب الدعوة :\n'
                f'   👤 الاسم : {_referrer_name_fake}\n'
                f'   🔗 المعرف : {_referrer_user_fake}\n'
                f'   🆔 الآيدي : <code>{to_user}</code>\n\n'
                f'❌ لم تُضف أي نقاط\n'
                f'👥 إجمالي إحالاته : {invite_count}',
                parse_mode='HTML'
            )
        except: pass
    else:

        someinfo['coins'] = int(someinfo.get('coins', 0)) + dd
        set_user(to_user, someinfo)

        vip_msg = ''
        VIP_INVITE_THRESHOLD = int(db.get('vip_invite_threshold')) if db.exists('vip_invite_threshold') else 2
        if invite_count >= VIP_INVITE_THRESHOLD and not someinfo.get('premium'):
            someinfo['premium'] = True
            set_user(to_user, someinfo)
            vip_msg = f'\n\n👑 مبروك! تم تفعيل اشتراك VIP تلقائياً لأنك دعوت {VIP_INVITE_THRESHOLD} أشخاص! 🎉'
            try:
                bot.send_message(
                    to_user,
                    f'🎊 *مبروك! تم ترقيتك إلى VIP تلقائياً!*\n\n'
                    f'👑 لقد دعوت {invite_count} شخصاً وحصلت على عضوية VIP مجاناً!\n\n'
                    f'💎 يمكنك الآن استخدام جميع خدمات قسم VIP',
                    parse_mode='Markdown'
                )
            except: pass

        _new_balance = int(someinfo.get('coins', 0))
        try:
            bot.send_message(
                to_user,
                f'╔══════════════════╗\n'
                f'       🎉 إحالة ناجحة!\n'
                f'╚══════════════════╝\n\n'
                f'👤 قام {_invitee_name} ({_invitee_user}) بالانضمام عبر رابطك\n'
                f'✅ اشترك في جميع القنوات المطلوبة\n\n'
                f'💰 حصلت على: +{dd:,} نقطة\n'
                f'👛 رصيدك الجديد: {_new_balance:,} نقطة\n'
                f'👥 إجمالي إحالاتك: {invite_count}{vip_msg}'
            )
        except: pass

        _referrer_name = 'مستخدم'
        try:
            _ref_chat = bot.get_chat(to_user)
            _referrer_name = _ref_chat.first_name or 'مستخدم'
        except: pass
        _welcome_keys = mk(row_width=1)
        _welcome_keys.add(btn('الرئيسية', callback_data='back', color='green'))
        try:
            bot.send_message(
                join_user,
                f'╔══════════════════╗\n'
                f'       🌟 أهلاً وسهلاً!\n'
                f'╚══════════════════╝\n\n'
                f'🎊 لقد انضممت عبر رابط إحالة {_referrer_name}\n\n'
                f'✨ استمتع بجميع خدمات البوت واكسب النقاط!\n'
                f'🔮 يمكنك أنت أيضاً مشاركة رابط الدعوة الخاص بك\n'
                f'💰 وتحصل على {dd:,} نقطة لكل شخص يدخل عبر رابطك',
                reply_markup=_welcome_keys
            )
        except: pass


    good = 0
    try:
        for ix in db.keys('user_%'):
            try:
                db.get(ix[0])['id']
                good += 1
            except: continue
        bot.send_message(
            chat_id=int(sudo),
            text=(
                f'٭ *دخول جديد عبر إحالة 🔗*\n\n'
                f'• الاسم : {_invitee_name}\n'
                f'• المعرف : {_invitee_user}\n'
                f'• الأيدي : {join_user}\n'
                f'• دُعي بواسطة : {to_user}\n\n'
                f'*• عدد الأعضاء الكلي : {good}*'
            ),
            parse_mode="Markdown"
        )
    except: pass


    db.set(_ref_key, str(to_user))
    db.delete(_pending_key)
    db.delete(f'ref_counted_{join_user}')
    db.delete(f'ref_invitee_name_{join_user}')
    db.delete(f'ref_invitee_user_{join_user}')


    try:
        check_and_award_level(to_user)
    except Exception as _le:
        print(f"[top_level] ref check error: {_le}")

# دوال مساعدة لمتجر المستخدمين

import uuid as _uuid_mod

def _gen_market_listing_id():
    return str(_uuid_mod.uuid4().hex[:12])

def _handle_mkt_add_step(message):
    cid = message.from_user.id
    if not message.text:
        bot.reply_to(message, '❌ أرسل نصاً وليس ملفاً أو صورة')
        return
    txt = message.text.strip()
    data = pending_market_data.get(cid)
    if not data:
        return
    step = data.get("step")
    if step == "phone":
        if len(txt) < 5:
            bot.reply_to(message, '❌ الرقم قصير جداً، أرسل رقم صحيح')
            bot.register_next_step_handler(message, _handle_mkt_add_step)
            return
        data["phone"] = txt
        data["step"] = "price"
        pending_market_data[cid] = data
        msg = bot.reply_to(
            message,
            '💰 <b>سعر البيع</b>\n\nأرسل السعر الذي تريده (بالنقاط):\nمثال: 5000',
            parse_mode='HTML'
        )
        bot.register_next_step_handler(msg, _handle_mkt_add_step)
        return
    if step == "price":
        try:
            price = int(txt)
            if price < 100:
                bot.reply_to(message, '❌ الحد الأدنى للسعر 100 نقطة')
                bot.register_next_step_handler(message, _handle_mkt_add_step)
                return
        except:
            bot.reply_to(message, '❌ أرسل رقماً صحيحاً')
            bot.register_next_step_handler(message, _handle_mkt_add_step)
            return
        data["price"] = price
        data["step"] = "confirm"
        pending_market_data[cid] = data
        confirm_keys = mk(row_width=1)
        confirm_keys.add(btn('✅ تأكيد الإعلان', callback_data='mkt_confirm_add', color='green'))
        confirm_keys.add(btn('إلغاء', callback_data='user_store', color='red'))
        bot.reply_to(
            message,
            f'📋 <b>مراجعة الإعلان</b>\n\n'
            f'📱 الحساب: {data["phone"]}\n'
            f'💰 السعر: {data["price"]:,} نقطة\n\n'
            f'هل تريد نشر الإعلان؟',
            reply_markup=confirm_keys, parse_mode='HTML'
        )
        return

# دوال مساعدة للألعاب والإدارة

def _handle_guess(message):
    cid = message.from_user.id
    if not message.text:
        bot.reply_to(message, '❌ أرسل رقماً فقط')
        return
    txt = message.text.strip()
    game = guess_games.get(cid)
    if not game:
        bot.reply_to(message, '❌ لا توجد لعبة نشطة، استخدم /guess لبدء لعبة جديدة')
        return
    try:
        guess = int(txt)
        if guess < 1 or guess > 100:
            bot.reply_to(message, '❌ الرقم يجب أن يكون بين 1 و 100، حاول مرة أخرى')
            return
    except:
        bot.reply_to(message, '❌ أرسل رقماً صحيحاً فقط (1-100)')
        return
    secret = game["secret"]
    game["attempts"] += 1
    guess_prize = int(db.get("guess_prize") or 500)
    if guess == secret:
        info = get(cid)
        info["coins"] = int(info.get("coins", 0)) + guess_prize
        set_user(cid, info)
        guess_games.pop(cid, None)
        bot.reply_to(
            message,
            f'🎉 <b>تهانينا! لقد فزت!</b>\n\n'
            f'🔢 الرقم الصحيح: {secret}\n'
            f'🎯 عدد المحاولات: {game["attempts"]}\n'
            f'🏆 الجائزة: {guess_prize:,} نقطة\n'
            f'💰 رصيدك الجديد: {int(info["coins"]):,} نقطة',
            reply_markup=bk, parse_mode='HTML'
        )
    else:
        hint = "أكبر" if guess < secret else "أصغر"
        keys = mk(row_width=1)
        keys.add(btn('🔙 إنهاء اللعبة', callback_data='back', color='red'))
        bot.reply_to(
            message,
            f'❌ رقم {guess} خطأ!\n'
            f'💡 الرقم {hint} من {guess}\n'
            f'📝 المحاولات: {game["attempts"]}\n\n'
            f'أرسل رقماً آخر:',
            reply_markup=keys, parse_mode='HTML'
        )

def _handle_set_market_fee(message):
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    if not message.text:
        bot.reply_to(message, '❌ أرسل رقماً فقط')
        return
    txt = message.text.strip()
    try:
        fee = int(txt)
        if fee < 0 or fee > 100:
            bot.reply_to(message, '❌ النسبة يجب أن تكون بين 0 و 100')
            return
    except:
        bot.reply_to(message, '❌ أرسل رقماً صحيحاً')
        return
    db.set("market_fee", fee)
    bot.reply_to(message, f'✅ تم تعيين نسبة العمولة إلى {fee}%', reply_markup=bk)

def _handle_admin_task_step(message):
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    if not message.text:
        bot.reply_to(message, '❌ أرسل نصاً')
        return
    txt = message.text.strip()
    action = pending_admin_action.get(cid)
    if not action:
        return
    step = action.get("step")
    if step == "target":
        action["target"] = txt
        action["step"] = "description"
        pending_admin_action[cid] = action
        msg = bot.reply_to(message, '📝 أرسل وصف المهمة (نص يظهر للمستخدم):')
        bot.register_next_step_handler(msg, _handle_admin_task_step)
        return
    if step == "description":
        action["description"] = txt
        action["step"] = "reward"
        pending_admin_action[cid] = action
        msg = bot.reply_to(message, '💰 أرسل مكافأة المهمة (عدد النقاط):')
        bot.register_next_step_handler(msg, _handle_admin_task_step)
        return
    if step == "reward":
        try:
            reward = int(txt)
            if reward < 1:
                bot.reply_to(message, '❌ المكافأة يجب أن تكون 1 على الأقل')
                bot.register_next_step_handler(message, _handle_admin_task_step)
                return
        except:
            bot.reply_to(message, '❌ أرسل رقماً صحيحاً')
            bot.register_next_step_handler(message, _handle_admin_task_step)
            return
        task_type = action.get("type", "channel_join")
        task_target = action.get("target", "")
        task_desc = action.get("description", "مهمة جديدة")
        task_id = f"task_{int(time.time())}_{random.randint(100,999)}"
        new_task = {
            "id": task_id,
            "type": task_type,
            "target": task_target,
            "description": task_desc,
            "reward": reward,
            "enabled": True
        }
        tasks_list = db.get("tasks_list") or []
        tasks_list.append(new_task)
        db.set("tasks_list", tasks_list)
        pending_admin_action.pop(cid, None)
        bot.reply_to(
            message,
            f'✅ <b>تم إضافة المهمة بنجاح!</b>\n\n'
            f'📝 الوصف: {task_desc}\n'
            f'💰 المكافأة: {reward:,} نقطة\n'
            f'🎯 النو����: {task_type}\n'
            f'📍 الهدف: {task_target}',
            reply_markup=bk, parse_mode='HTML'
        )

def _handle_set_game_value(message):
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    if not message.text:
        bot.reply_to(message, '❌ أرسل رقماً')
        return
    db_key = db.get(f"_adm_pending_{cid}")
    if not db_key:
        bot.reply_to(message, '❌ انتهت الجلسة')
        return
    try:
        val = int(message.text.strip())
        if val < 0:
            bot.reply_to(message, '❌ القيمة يجب أن تكون 0 أو أكثر')
            return
    except:
        bot.reply_to(message, '❌ أرسل رقماً صحيحاً')
        return
    db.set(db_key, val)
    db.delete(f"_adm_pending_{cid}")
    bot.reply_to(message, f'✅ تم تعيين {db_key} = {val:,}', reply_markup=bk)

# Middleware — اشتراك إجباري لكل الأوامر والرسائل

_FSUB_EXEMPT_COMMANDS = {'/start'}  # الأوامر المستثناة من الفحص

def _fsub_check(message_or_call):
    """
    يتحقق من الاشتراك الإجباري.
    يرجع True لو المستخدم مشترك أو مفيش قنوات إجبارية.
    يرجع False ويبعت رسالة الاشتراك لو مش مشترك.
    """
    try:
        if hasattr(message_or_call, 'from_user'):
            user_id = message_or_call.from_user.id
            chat_id = message_or_call.chat.id if hasattr(message_or_call, 'chat') else user_id
            is_call = False
        else:
            return True

        # الأدمن والسودو مستثنيان
        _is_admin = (user_id == sudo) or (user_id in _get_admins_cached())
        if _is_admin:
            return True

        # لو مفيش قنوات إجبارية
        channels = _get_force_channels()
        if not channels:
            return True

        ok, not_sub = _check_user_subs(user_id)
        if ok:
            return True

        # مش مشترك — ابعت رسالة الاشتراك
        _send_force_sub_msg(bot, chat_id, not_sub)
        return False
    except Exception:
        return True  # في حالة خطأ — اس������ح للمستخدم

def _fsub_check_msg(message):
    """يتحقق من الاشتراك — يرجع True لو مسموح، False لو محظور"""
    try:
        user_id = message.from_user.id if message.from_user else None
        if not user_id:
            return True
        _is_admin = (user_id == sudo) or (user_id in _get_admins_cached())
        if _is_admin:
            return True
        # ── وضع الصيانة (cached) ──
        if db.get('maintenance_mode'):
            try:
                bot.reply_to(message,
                    '🔧 <b>البوت في وضع الصيانة حالياً</b>\n\n'
                    'سيعود للعمل قريباً، يرجى الانتظار. 🙏',
                    parse_mode='HTML'
                )
            except:
                pass
            return False
        if message.text and message.text.strip().split()[0] in _FSUB_EXEMPT_COMMANDS:
            return True
        channels = _get_force_channels()
        if not channels:
            return True
        ok, not_sub = _check_user_subs(user_id)
        if not ok:
            _send_force_sub_msg(bot, message.chat.id, not_sub, reply_to=message.message_id)
            return False
        return True
    except Exception:
        return True

def _fsub_check_call(call):
    """يتحقق من الاشتراك في الـ callbacks"""
    try:
        user_id = call.from_user.id if call.from_user else None
        if not user_id:
            return True
        _is_admin = (user_id == sudo) or (user_id in _get_admins_cached())
        if _is_admin:
            return True
        # ── وضع الصيانة ──
        if db.get('maintenance_mode'):
            try:
                _cb_alert(call,
                    '🔧 البوت في وضع الصيانة حالياً، يرجى الانتظار.',
                    show_alert=True
                )
            except:
                pass
            return False
        if call.data in ('check_force_sub',) or str(call.data).startswith(('setlang_', 'capans_')):
            return True
        channels = _get_force_channels()
        if not channels:
            return True
        ok, not_sub = _check_user_subs(user_id)
        if not ok:
            try:
                _cb_alert(call, '❌ يجب الاشتراك أولاً', show_alert=True)
            except:
                pass
            _send_force_sub_msg(bot, call.message.chat.id, not_sub)
            return False
        return True
    except Exception:
        return True

@bot.message_handler(commands=['lang', 'language'])
def _cmd_lang(message):
    try:
        _send_lang_picker(message.chat.id, message.from_user.id)
    except Exception:
        pass

@bot.message_handler(regexp='^/start$')
def start_message(message):
    user_id = message.from_user.id
    if not _check_rate_limit(user_id):
        return

    # ── فحص وضع الصيانة ──
    _is_admin_start = (user_id == sudo) or (user_id in _get_admins_cached())
    if not _is_admin_start and db.get('maintenance_mode'):
        try:
            bot.reply_to(message,
                '🔧 <b>البوت في وضع الصيانة حالياً</b>\n\n'
                'سيعود للعمل قريباً، يرجى الانتظار. 🙏',
                parse_mode='HTML'
            )
        except:
            pass
        return

    try:
        for temp in ['leave','member','vote','spam','userbot','forward','linkbot','view','poll','react','reacts','react_special','votes_fsub']:
            db.delete(f'{temp}_{user_id}_proccess')

        if user_id in (db.get('badguys') or []):
            return

        _is_admin = (user_id == sudo) or (user_id in _get_admins_cached())
        # تحديث بيانات المستخدم من Firebase لو الـ cache اتحمل حديثاً
        if db._cache_loaded and f'user_{user_id}' not in db._cache:
            db.refresh_user(user_id)
        # نتحقق من أول ستارت حقيقي بـ flag خاص مش بوجود المستخدم في الـ DB
        _is_new = not db.exists(f'first_started_{user_id}')
        if _is_new:
            db.set(f'first_started_{user_id}', True)


        if db.exists(f'is_fake_{user_id}') and not _is_admin:
            def _notify_fake_now():
                try:
                    import datetime as _fdt3
                    _fn  = message.from_user.first_name or ''
                    _fu  = f'@{message.from_user.username}' if message.from_user.username else 'لا يوجد'
                    _fid = message.from_user.id
                    # جيب معلومات الداعي
                    _ref_pending = db.get(f'ref_pending_{user_id}') or db.get(f'ref_counted_{user_id}')
                    _ref_info = '❌ لا يوجد داعي'
                    if _ref_pending:
                        try:
                            _rc2 = bot.get_chat(int(_ref_pending))
                            _rn2 = _rc2.first_name or str(_ref_pending)
                            _ru2 = f'@{_rc2.username}' if getattr(_rc2, 'username', None) else f'#{_ref_pending}'
                            _ref_info = (
                                f'👤 {_rn2}\n'
                                f'   📛 {_ru2}\n'
                                f'   🆔 <code>{_ref_pending}</code>'
                            )
                        except:
                            _ref_info = f'🆔 <code>{_ref_pending}</code>'
                    txt_fake = (
                        f'╔══════════════════╗\n'
                        f'       🤖 حساب وهمي دخل البوت\n'
                        f'╚══════════════════╝\n\n'
                        f'🤖 <b>بيانات الوهمي:</b>\n'
                        f'   👤 الاسم : {_fn}\n'
                        f'   📛 اليوزر : {_fu}\n'
                        f'   🆔 الأيدي : <code>{_fid}</code>\n\n'
                        f'👑 <b>الداعي:</b>\n'
                        f'   {_ref_info}\n\n'
                        f'━━━━━━━━━━━━━━━━━━━\n'
                        f'❌ لم تُضف أي نقاط للداعي\n'
                        f'📅 الوقت : {_fdt3.datetime.now().strftime("%Y-%m-%d %H:%M")}\n'
                        f'━━━━━━━━━━━━━━━━━━━'
                    )
                    _all_admins = set([int(sudo)])
                    _all_admins.update([int(a) for a in (db.get('admins') or [])])
                    for _nid in _all_admins:
                        try: bot.send_message(chat_id=_nid, text=txt_fake, parse_mode='HTML')
                        except: pass
                except Exception as _fe:
                    print(f'[fake notify] {_fe}')
            threading.Thread(target=_notify_fake_now, daemon=True).start()

        if _is_new:
            def _notify():
                try:
                    import datetime as _dt2
                    good = sum(1 for ix in db.keys('user_%') if db.get(ix[0]) and isinstance(db.get(ix[0]), dict) and db.get(ix[0]).get('id'))
                    _new_uname = f'@{message.from_user.username}' if message.from_user.username else 'لا يوجد'
                    _new_fname = message.from_user.first_name or ''


                    _ref_pending = db.get(f'ref_pending_{user_id}')
                    _ref_counted = db.get(f'ref_counted_{user_id}')
                    _ref_by_data = _ref_pending or _ref_counted
                    _stored_source = db.get(f'user_source_{user_id}') or ''

                    if _ref_by_data or _stored_source == 'referral_link':
                        # جاء عن طريق رابط إحالة شخص
                        _source_txt = '🔗 رابط إحالة شخص'
                        try:
                            _rc = bot.get_chat(int(_ref_by_data))
                            _rn = _rc.first_name or str(_ref_by_data)
                            _ru = f'@{_rc.username}' if getattr(_rc,'username',None) else f'#{_ref_by_data}'
                            _inviter_txt = (
                                f'👤 الاسم : {_rn}\n'
                                f'   📛 اليوزر : {_ru}\n'
                                f'   🆔 الأيدي : <code>{_ref_by_data}</code>'
                            )
                        except:
                            _inviter_txt = f'🆔 <code>{_ref_by_data}</code>' if _ref_by_data else '❌ لا يوجد'
                    elif _stored_source == 'invite_link':
                        _source_txt = '🔗 رابط دعوة (Invite Link)'
                        _inviter_txt = '❌ لا يوجد داعي محدد'
                    else:
                        # بحث مباشر أو غير محدد
                        _source_txt = '🔍 بحث مباشر أو مصدر غير محدد'
                        _inviter_txt = '❌ لا يوجد داعي'

                    _is_fake_new = db.exists(f'is_fake_{user_id}')
                    _acct_type = '🤖 وهمي (جلسة)' if _is_fake_new else '👤 حقيقي'
                    _today_key = f'new_users_{_dt2.datetime.now().strftime("%Y-%m-%d")}'
                    db.set(_today_key, int(db.get(_today_key) or 0) + 1)

                    if _is_fake_new:
                        txt = (
                            f'╔══════════════════╗\n'
                            f'       🤖 مستخدم وهمي دخل البوت!\n'
                            f'╚══════════════════╝\n\n'
                            f'👤 الاسم : {_new_fname}\n'
                            f'📛 اليوزر : {_new_uname}\n'
                            f'🆔 الأيدي : <code>{user_id}</code>\n\n'
                            f'━━━━━━━━━━━━━━━━━━━\n'
                            f'📌 المصدر : {_source_txt}\n'
                            f'👑 الداعي :\n   {_inviter_txt}\n\n'
                            f'❌ لم تُضف أي نقاط للداعي\n'
                            f'👥 إجمالي الأعضاء : {good + 1}\n'
                            f'📅 الوقت : {_dt2.datetime.now().strftime("%Y-%m-%d %H:%M")}\n'
                            f'━━━━━━━━━━━━━━━━━━━'
                        )
                    else:
                        txt = (
                            f'╔══════════════════╗\n'
                            f'       🌟 مستخدم جديد بدأ البوت!\n'
                            f'╚══════════════════╝\n\n'
                            f'👤 الاسم : {_new_fname}\n'
                            f'📛 اليوزر : {_new_uname}\n'
                            f'🆔 الأيدي : <code>{user_id}</code>\n'
                            f'🏷 النوع : {_acct_type}\n\n'
                            f'━━━━━━━━━━━━━━━━━━━\n'
                            f'📌 المصدر : {_source_txt}\n'
                            f'👑 الداعي :\n   {_inviter_txt}\n\n'
                            f'👥 إجمالي الأعضاء : {good + 1}\n'
                            f'📅 الوقت : {_dt2.datetime.now().strftime("%Y-%m-%d %H:%M")}\n'
                            f'━━━━━━━━━━━━━━━━━━━'
                        )
                    _all = set([int(sudo)])
                    _all.update([int(a) for a in (db.get('admins') or [])])
                    for _nid in _all:
                        try: bot.send_message(chat_id=_nid, text=txt, parse_mode='HTML')
                        except: pass
                except Exception as _ne:
                    print(f'[notify new user] {_ne}')
            threading.Thread(target=_notify, daemon=True).start()

            _count_pending_referral(user_id)

            # سجّل ال��ستخدم أولاً
            if not db.exists(f'user_{user_id}'):
                data = {'id': user_id, 'users': [], 'coins': 0, 'premium': False}
                set_user(user_id, data)

            if _onboarding_gate(user_id, message.chat.id):
                return
            if not _is_admin:
                _ok_sub, _not_sub = _check_user_subs(user_id)
                if not _ok_sub:
                    # مش مشترك — ابعت رسالة الترحيب + الاشتراك الإجباري
                    keys = _build_main_keys(user_id)
                    bot.reply_to(message, get_welcome_msg(user_id), reply_markup=keys, parse_mode="HTML")
                    _send_force_sub_msg(bot, message.chat.id, _not_sub, reply_to=message.message_id)
                    return

            # مشترك — صرف النقاط وابعت رسالة الترحيب
            _settle_pending_referral(user_id)
            keys = _build_main_keys(user_id)
            bot.reply_to(message, get_welcome_msg(user_id), reply_markup=keys, parse_mode="HTML")

        else:
            if _onboarding_gate(user_id, message.chat.id):
                return
            if not _is_admin:
                _ok_sub2, _not_sub2 = _check_user_subs(user_id)
                if not _ok_sub2:
                    _send_force_sub_msg(bot, message.chat.id, _not_sub2, reply_to=message.message_id)
                    return
                else:
                    _settle_pending_referral(user_id)

            keys = _build_main_keys(user_id)
            bot.reply_to(message, get_welcome_msg(user_id), reply_markup=keys, parse_mode="HTML")

    except Exception as _e:
        print(f'[start] error: {_e}')

def admin_panel_cmd(message):
    user_id = message.from_user.id
    if user_id not in (db.get("admins") or []) and user_id != sudo:
        return
    stars_rate   = int(db.get("charge_stars_rate"))   if db.exists("charge_stars_rate")   else 600
    stars_post   = db.get("charge_stars_post")         if db.exists("charge_stars_post")   else "غير محدد"
    cash_rate    = int(db.get("charge_cash_rate"))    if db.exists("charge_cash_rate")     else 150000
    usdt_rate    = int(db.get("charge_usdt_rate"))    if db.exists("charge_usdt_rate")     else 150000
    usdt_wallet  = db.get("charge_usdt_wallet")        if db.exists("charge_usdt_wallet")  else "غير محدد"
    ckeys = mk(row_width=1)
    ckeys.add(btn('سعر النجوم (نجمة = كم نقطة)', callback_data='chset_stars_rate', color='green'))
    ckeys.add(btn('⭐ منشور استقبال النجوم', callback_data='chset_stars_post', color='green'))
    ckeys.add(btn('سعر الكاش ($ = كم نقطة)', callback_data='chset_cash_rate', color='blue'))
    ckeys.add(btn('سعر USDT (USDT = كم نقطة)', callback_data='chset_usdt_rate', color='blue'))
    ckeys.add(btn('رقم فودافون كاش', callback_data='chset_cash_contact', color='green'))
    ckeys.add(btn('عرض إعدادات الشحن', callback_data='chset_view', color='blue'))
    ckeys.add(btn('━━ إعدادات الاشتراك الإجباري ━━', callback_data='none', color='blue'))
    ckeys.add(btn('🔢 عدد الأعضاء في الباقة', callback_data='chset_fsub_amount', color='green'))
    ckeys.add(btn('📅 مدة الباقة (أيام)', callback_data='chset_fsub_duration', color='green'))
    ckeys.add(btn('⭐ سعر النجوم للباقة', callback_data='chset_fsub_stars', color='green'))
    ckeys.add(btn('📱 سعر فودافون كاش للباقة', callback_data='chset_fsub_cash', color='green'))
    ckeys.add(btn('💎 سعر USDT للباقة', callback_data='chset_fsub_usdt', color='green'))
    ckeys.add(btn('🔙 رجوع للوحة', callback_data='adm_cat_settings', color='red'))
    txt = (
        "إعدادات الشحن\n\n"
        f"النجوم: 1 نجمة = {stars_rate} نقطة\n"
        f"⭐ منشور النجوم: {stars_post}\n"
        f"الكاش: $1 = {cash_rate} نقطة\n"
        f"USDT: 1 USDT = {usdt_rate} نقطة\n"
        f"محفظة USDT: {usdt_wallet}"
    )
    bot.reply_to(message, txt, reply_markup=ckeys, parse_mode="HTML")

@bot.message_handler(regexp='^/start (.*)')
def start_asinvite(message):
    join_user = message.from_user.id
    param = message.text.split("/start ")[1]

    if not _check_rate_limit(join_user):
        return


    if param.startswith("btask_"):
        try:
            parts = param.split('_')
            # btask_{task_id_part1}_{task_id_part2}_{task_id_part3}_{user_id}
            # مثال: btask_task_1234567890_123_987654321
            inviter_uid = int(parts[-1])
            task_id = '_'.join(parts[1:-1])  # كل حاجة بين btask_ و الـ user_id
            _bot_task_key = f'bot_task_done_{task_id}_{inviter_uid}'
            _bot_task_first_key = f'bot_task_first_{task_id}_{join_user}'
            # تسجيل إن المستخدم ده (join_user) فعّل البوت من رابط inviter_uid
            # بس لو أول مرة يفعّل البوت ده
            _already_started_key = f'bot_ever_started_{join_user}'
            _already_started_this_bot = db.exists(_already_started_key)
            if not _already_started_this_bot:
                # أول مرة يفعّل — سجّل
                db.set(_already_started_key, True)
                db.set(_bot_task_key, join_user)        # مين فعّل الرابط
                db.set(_bot_task_first_key, True)        # تأكيد إنه أول مرة
                # إشعار فوري للمستخدم الصاحب المهمة
                try:
                    bot.send_message(
                        inviter_uid,
                        f'⚡ <b>تم التحقق من مهمتك تلقائياً!</b>\n\n'
                        f'👤 المستخدم <code>{join_user}</code> فعّل البوت\n'
                        f'✅ يمكنك الآن الضغط على «تحقق تلقائي» لاستلام نقاطك',
                        parse_mode='HTML'
                    )
                except:
                    pass
            # أكمل الـ start العادي
        except Exception as _btask_err:
            print(f'[btask] error: {_btask_err}')
        start_message(message)
        return

    # معالجة روابط الهدية
    if param.startswith("gift_"):
        code = param.replace("gift_", "")
        gift = db.get(f"gift_{code}")
        if not gift:
            bot.reply_to(message, '❌ رابط الهدية غير صا��ح أو منتهي الصلاحية')
            start_message(message)
            return
        max_uses = int(gift.get("max_uses", 1))
        uses = int(gift.get("uses", 0))
        used_by = gift.get("used_by", [])
        if gift.get("used") or uses >= max_uses:
            bot.reply_to(message, '❌ تم استنفاد استخدامات هذا الرابط')
            start_message(message)
            return
        if join_user in used_by:
            bot.reply_to(message, '❌ لقد استخدمت هذا الرابط من قبل، لا يمكن استخدامه مرة أخرى')
            start_message(message)
            return
        # تسجيل المستخدم إن لم يكن موجوداً
        if not check_user(join_user):
            data = {'id': join_user, 'users': [], 'coins': 0, 'premium': False}
            set_user(join_user, data)
        info = get(join_user)
        pts = int(gift.get("points", 0))
        info['coins'] = int(info.get('coins', 0)) + pts
        set_user(join_user, info)
        uses += 1
        used_by.append(join_user)
        gift["uses"] = uses
        gift["used_by"] = used_by
        if uses >= max_uses:
            gift["used"] = True
        db.set(f"gift_{code}", gift)
        remaining = max_uses - uses
        remaining_txt = f'\n📊 الاستخدامات المتبقية: *{remaining}*' if max_uses > 1 else ''
        keys = mk(row_width=1)
        keys.add(btn('الرئيسية', callback_data='back', color='green'))
        bot.reply_to(
            message,
            f'🎁 *مبروك! استلمت هدية نقاط*\n\n🎉 حصلت على *{pts:,} نقطة*\n💰 رصيدك الجديد: *{int(info["coins"]):,} نقطة*{remaining_txt}',
            reply_markup=keys, parse_mode='Markdown'
        )

        try:
            _g_uname = f'@{message.from_user.username}' if message.from_user.username else 'لا يوجد'
            _g_fname = message.from_user.first_name or ''
            bot.send_message(
                chat_id=int(sudo),
                text=(
                    f'🎁 <b>مستخدم استخدم رابط هدية</b>\n\n'
                    f'👤 الاسم : {_g_fname}\n'
                    f'📛 اليوزر : {_g_uname}\n'
                    f'🆔 الأيدي : <code>{join_user}</code>\n'
                    f'💰 النقاط المستلمة : {pts:,} نقطة\n'
                    f'🎫 كود الهدية : <code>{code}</code>'
                ),
                parse_mode='HTML'
            )
        except Exception:
            pass
        start_message(message)
        return
    try:
        to_user = int(param)
    except:
        start_message(message)
        return

    # ✅ حماية من الوهميين

    user_obj = message.from_user

    # 1) رفض البوتات
    if getattr(user_obj, 'is_bot', False):
        start_message(message)
        return

    # 2) رفض الحسابات بدون اسم (حسابات وهمية فارغة)
    if not getattr(user_obj, 'first_name', None) or str(user_obj.first_name).strip() == '':
        start_message(message)
        return

    # 3) رفض الحسابات برقم ID صغير جداً (بوتات وهمية قديمة تبدأ من أرقام صغيرة)
    if join_user < 10000:
        start_message(message)
        return

    # ✅ منع الشخص من استخدام رابطه الخاص

    if join_user == to_user:
        bot.send_message(join_user, '❌ لا يمكنك استخدام رابط الإحالة الخاص بك!')
        start_message(message)
        return

    # ✅ فحص إذا المدعو استخدم إحالة قبل كده

    _ref_key = f'ref_used_{join_user}'
    if db.exists(_ref_key):
        # المستخدم سبق استخدم رابط إحالة — مش هيتعد تاني
        start_message(message)
        return

    # ✅ حفظ الإحالة مؤقتاً — النقاط تتضاف بعد الاشتراك في القنوات

    # تسجيل المدعو لو مش موجود
    if not check_user(join_user):
        info = {'coins': 0, 'id': join_user, 'premium': False, 'users': [], 'ref_by': to_user}
        set_user(join_user, info)
    else:
        info = get(join_user)
        if not info.get('ref_by'):
            info['ref_by'] = to_user
            set_user(join_user, info)

    # حفظ الإحالة المعلقة — ref_pending_{join_user} = to_user
    # لن تُحسب النقاط إلا بعد اشتراك ����لمدعو في القنوات
    db.set(f'ref_pending_{join_user}', str(to_user))

    # حفظ اسم/يوزر المدعو عشان نستخدمه في الرسالة لاحقاً
    db.set(f'ref_invitee_name_{join_user}', user_obj.first_name or 'مستخدم جديد')
    db.set(f'ref_invitee_user_{join_user}', f'@{user_obj.username}' if user_obj.username else f'#{join_user}')
    # حفظ مصدر الدخول
    db.set(f'user_source_{join_user}', 'referral_link')

    # سجّل المستخدم لو مش موجود
    if not db.exists(f'user_{join_user}'):
        _info = {'id': join_user, 'users': [], 'coins': 0, 'premium': False}
        set_user(join_user, _info)

    _count_pending_referral(join_user)


    _fast = bot.reply_to(message, '⏳')

    def _finish_invite():
        try:
            # فحص الاشتراك الإجباري
            _is_admin_inv = (join_user == sudo) or (join_user in (db.get('admins') or []))
            if not _is_admin_inv:
                _ok_sub_inv, _not_sub_inv = _check_user_subs(join_user)
                if not _ok_sub_inv:
                    try: bot.delete_message(message.chat.id, _fast.message_id)
                    except: pass
                    # رسالة الترحيب + رسالة الاشتراك الإجباري
                    _keys_inv = _build_main_keys(join_user)
                    bot.reply_to(message, get_welcome_msg(join_user), reply_markup=_keys_inv, parse_mode="HTML")
                    _send_force_sub_msg(bot, message.chat.id, _not_sub_inv, reply_to=message.message_id)
                    return

            _settle_pending_referral(join_user)
            _keys_inv = _build_main_keys(join_user)
            try: bot.delete_message(message.chat.id, _fast.message_id)
            except: pass
            bot.reply_to(message, get_welcome_msg(join_user), reply_markup=_keys_inv, parse_mode="HTML")
        except Exception as _e:
            print(f'[invite] error: {_e}')
            try: bot.delete_message(message.chat.id, _fast.message_id)
            except: pass

    threading.Thread(target=_finish_invite, daemon=True).start()

# ════════ تصدير/استيراد قاعدة البيانات (JSON) ════════
# الدوال دي كانت بتتنده في معالجات أزرار (تصدير/استيراد/نسخة احتياطية)
# بس ماكانتش معرّفة إطلاقاً في الكود، فالأزرار دي كانت بترمي NameError
# وما بتعملش حاجة. دي تعريفاتها الكاملة.
import io as _io_db
import json as _json_db
import time as _time_db

def _collect_db_snapshot(export_type="all"):
    """يجمع نسخة من البيانات من قاعدة البيانات حسب النوع."""
    snapshot = {}
    for _k_tuple in db.keys(''):
        k = _k_tuple[0]
        if str(k).startswith('_import_'):  # تجاهل مفاتيح مؤقتة
            continue
        v = db.get(k)
        if v is None:
            continue
        is_user    = str(k).startswith('user_')
        is_account = (k == 'accounts') or str(k).startswith('session_')
        is_setting = (not is_user) and (not is_account)
        if export_type == "all":
            snapshot[k] = v
        elif export_type == "users" and is_user:
            snapshot[k] = v
        elif export_type == "accounts" and is_account:
            snapshot[k] = v
        elif export_type == "settings" and is_setting:
            snapshot[k] = v
    return snapshot

def _send_db_export_file(cid, export_type="all", label="الكل"):
    """يصدّر البيانات JSON ويبعتها كملف للأدمن."""
    try:
        snapshot = _collect_db_snapshot(export_type)
        payload = {
            "_meta": {
                "export_type": export_type,
                "exported_at": int(_time_db.time()),
                "count": len(snapshot),
            },
            "data": snapshot,
        }
        raw = _json_db.dumps(payload, ensure_ascii=False, indent=2)
        bio = _io_db.BytesIO(raw.encode("utf-8"))
        fname = f"backup_{export_type}_{int(_time_db.time())}.json"
        bio.name = fname
        n_users = sum(1 for k in snapshot if str(k).startswith('user_'))
        accs = snapshot.get('accounts') or []
        n_accs = len(accs) if isinstance(accs, list) else 0
        bot.send_document(
            chat_id=cid,
            document=bio,
            visible_file_name=fname,
            caption=(
                f"✅ <b>نسخة احتياطية — {label}</b>\n\n"
                f"📦 العناصر: <b>{len(snapshot):,}</b>\n"
                f"👥 المستخدمون: <b>{n_users:,}</b>\n"
                f"📱 الأرقام: <b>{n_accs:,}</b>\n\n"
                f"<i>احتفظ بالملف لاستعادته لاحقاً ع��ر زر الاستيراد.</i>"
            ),
            parse_mode="HTML",
        )
    except Exception as _e:
        try:
            bot.send_message(cid, f"❌ فشل التصدير: {_e}")
        except:
            pass
        print(f"[export_db] خطأ: {_e}")

def _handle_import_db_panel(call):
    """يعرض لوحة اختيار نوع الاستيراد."""
    cid = call.from_user.id
    mid = call.message.id
    keys = mk(row_width=1)
    keys.add(btn('👥 استيراد المستخدمين', callback_data='adm_import_type_users', color='green'))
    keys.add(btn('📱 استيراد الحسابات (الأرقام)', callback_data='adm_import_type_accounts', color='green'))
    keys.add(btn('⚙️ استيراد الإعدادات', callback_data='adm_import_type_settings', color='blue'))
    keys.add(btn('📦 استيراد الكل', callback_data='adm_import_type_all', color='blue'))
    keys.add(btn('🔙 رجوع للوحة', callback_data='adm_cat_database', color='red'))
    try:
        bot.edit_message_text(
            chat_id=cid, message_id=mid,
            text=(
                "📥 <b>استيراد قاعدة البيانات</b>\n\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                "اختر نوع البيانات المراد استيرادها،\n"
                "ثم أرسل ملف JSON الذي صدّرته من البوت."
            ),
            reply_markup=keys, parse_mode="HTML",
        )
    except Exception as _e:
        print(f"[import_panel] خطأ: {_e}")

def _handle_import_db_file(message):
    """يستقبل ملف JSON المرفوع ويخزّنه مؤقتاً ثم يعرض زر التأكيد."""
    cid = message.from_user.id
    try:
        if not getattr(message, 'document', None):
            x = bot.reply_to(message, "❌ أرسل ملف JSON الذي صدّرته من البوت.")
            bot.register_next_step_handler(x, _handle_import_db_file)
            return
        import_type = db.get(f"_import_type_{cid}") or "all"
        finfo = bot.get_file(message.document.file_id)
        fbytes = bot.download_file(finfo.file_path)
        try:
            text = fbytes.decode("utf-8")
        except:
            text = fbytes.decode("utf-8", errors="ignore")
        parsed = _json_db.loads(text)
        # ندعم الصيغتين: {"data": {...}} أو {...} مباشرة
        if isinstance(parsed, dict) and isinstance(parsed.get("data"), dict):
            store_obj = parsed["data"]
        else:
            store_obj = parsed
        if not isinstance(store_obj, dict):
            bot.reply_to(message, "❌ محتوى الملف غير صالح (المتوقع JSON object).")
            return
        db.set(f"_import_pending_{cid}", _json_db.dumps(store_obj, ensure_ascii=False))
        confirm_kb = mk(row_width=1)
        confirm_kb.add(btn('✅ تأكيد الاستيراد', callback_data=f'adm_import_confirm_{import_type}', color='red'))
        confirm_kb.add(btn('إلغاء', callback_data='adm_cat_database', color='green'))
        cnt = len(store_obj)
        bot.send_message(
            cid,
            f"📥 <b>الملف جاهز للاستيراد</b>\n\n"
            f"📦 عدد العناصر في الملف: <b>{cnt:,}</b>\n"
            f"النوع: <b>{import_type}</b>\n\n"
            f"⚠️ الاستيراد سيستبدل القيم الحالية بنفس المفاتيح. اضغط تأكيد للمتابعة.",
            reply_markup=confirm_kb, parse_mode="HTML",
        )
    except Exception as _e:
        try:
            bot.reply_to(message, f"❌ ملف غير صالح أو خطأ في القراءة: {_e}")
        except:
            pass
        print(f"[import_file] خطأ: {_e}")

def _import_db_from_json(jdata, import_type="all"):
    """يستورد البيانات من dict ويرجع إحصائيات."""
    res = {
        "users_imported": 0, "users_updated": 0,
        "accounts_imported": 0, "accounts_skipped": 0,
        "settings_imported": 0, "errors": [],
    }
    if not isinstance(jdata, dict):
        res["errors"].append("صيغة الملف غير صحيحة")
        return res
    incoming_accounts = None
    for k, v in jdata.items():
        try:
            if str(k).startswith('_import_') or str(k).startswith('_meta'):
                continue
            is_user    = str(k).startswith('user_')
            is_account = (k == 'accounts') or str(k).startswith('session_')
            is_setting = (not is_user) and (not is_account)
            if is_user and import_type in ("users", "all"):
                if db.exists(k):
                    res["users_updated"] += 1
                else:
                    res["users_imported"] += 1
                db.set(k, v)
            elif is_account and import_type in ("accounts", "all"):
                if k == 'accounts':
                    incoming_accounts = v  # تُعالج بعد الحلقة (دمج بدون تكرار)
                else:
                    db.set(k, v)
            elif is_setting and import_type in ("settings", "all"):
                db.set(k, v)
                res["settings_imported"] += 1
        except Exception as _e:
            res["errors"].append(f"{k}: {_e}")
    # دمج الحسابات (الأرقام) بدون تكرار حسب رقم الهاتف/الجلسة
    if isinstance(incoming_accounts, list):
        try:
            current = db.get('accounts') or []
            existing_phones = set()
            existing_sessions = set()
            for a in current:
                if isinstance(a, dict):
                    existing_phones.add(str(a.get('phone', '')).strip())
                    existing_sessions.add((a.get('s', '') or '')[:30])
            for a in incoming_accounts:
                if not isinstance(a, dict):
                    continue
                ph = str(a.get('phone', '')).strip()
                s30 = (a.get('s', '') or '')[:30]
                if (ph and ph in existing_phones) or (s30 and s30 in existing_sessions):
                    res["accounts_skipped"] += 1
                    continue
                current.append(a)
                if ph: existing_phones.add(ph)
                if s30: existing_sessions.add(s30)
                res["accounts_imported"] += 1
            db.set('accounts', current)
        except Exception as _e:
            res["errors"].append(f"accounts: {_e}")
    return res

# 👑 لوحة الأدمن - أمر /admin

# تعريف فئات لوحة الأدمن — كل فئة بتجمع الأزرار المرتبطة ببعضها
_ADMIN_CATEGORIES = {
    'adm_cat_users': {
        'title': '👥 المستخدمين والصلاحيات',
        'buttons': [
            ('حظر شخص',        'banone',   'red'),
            ('فك حظر',          'unbanone', 'green'),
            ('اضافة ادمن',      'addadmin', 'green'),
            ('مسح ادمن',        'deladmin', 'red'),
            ('الادمنية',        'admins',   'blue'),
            ('عدد الارقام',     'numbers',  'blue'),
        ],
    },
    'adm_cat_points': {
        'title': '💰 النقاط و VIP',
        'buttons': [
            ('اضافه نقاط',          'addpoints',      'green'),
            ('خصم نقاط',            'lespoints',      'red'),
            ('تفعيل VIP',           'addvip',         'green'),
            ('الغاء VIP',           'lesvip',         'red'),
            ('عدد الدعوات للـ VIP', 'adm_vip_thresh', 'green'),
            ('صفر نقاط الجميع',     'adm_reset_coins','red'),
        ],
    },
    'adm_cat_subscription': {
        'title': '📡 الاشتراك والقنوات',
        'buttons': [
            ('تعيين قنوات الاشتراك',          'setforce',            'blue'),
            ('إحصائيات الاشتراك الإجباري',    'adm_fsub_stats',      'blue'),
            ('تعيين قنوات البوت',             'adm_set_channels',    'blue'),
            ('تعيين نص الدعم الفني',          'adm_set_support',     'blue'),
            ('قناة الطلبات',                  'chset_orders_channel','green'),
            ('📋 قناة سجل الأزرار',            'chset_logs_channel',  'blue'),
        ],
    },
    'adm_cat_settings': {
        'title': '⚙️ إعدادات البوت',
        'buttons': [
            ('إعدادات الخدمات',     'adm_svc_panel',         'green'),
            ('إعدادات الشحن',       'adm_charge_panel',      'blue'),
            ('إعدادات المتجر',      'adm_market_settings',   'green'),
            ('إعدادات الألعاب',     'adm_games_settings',    'blue'),
            ('لوحة تخصيص الأزرار',  'adm_btn_panel',         'green'),
            ('إخفاء/إظهار الأزرار', 'adm_visibility',        'red'),
            ('إعداد زر قناة البوت', 'adm_set_channel_btn',   'green'),
            ('إعداد الإيموجي المخصص','adm_set_emojis',       'green'),
        ],
    },
    'adm_cat_tasks': {
        'title': '📋 المهام والمكافآت',
        'buttons': [
            ('إدارة المهام',         'adm_tasks_panel',   'blue'),
            ('إعدادات المكافآت',     'adm_rewards_panel', 'green'),
            ('صنع رابط هدية نقاط',   'adm_gift_link',     'green'),
        ],
    },
    'adm_cat_database': {
        'title': '🗄️ قاعدة البيانات',
        'buttons': [
            ('adm_export_db', 'adm_export_db', 'blue'),
            ('adm_import_db', 'adm_import_db', 'green'),
        ],
    },
    'adm_cat_general': {
        'title': '📊 عام وإذاعة',
        'buttons': [
            ('📊 الاحصائيات',                       'stats',     'blue'),
            ('📢 اذاعة',                            'cast',      'green'),
            ('🤖 إدارة الدعم بالذكاء الاصطناعي',    'adm_ai_panel','green'),
            ('سحب اصوات',                           'dump_votes','red'),
            ('س��ام رسائل',                          'spams',     'red'),
            ('مغادرة كل الحسابات من قناة',          'leave',     'red'),
            ('مغادرة كل القنوات والمجموعات',        'lvall',     'red'),
        ],
    },
}


def _show_admin_panel(target, is_edit=False, mid=None):
    """تعرض لوحة الأدمن الرئيسية - target = chat_id أو message"""
    if isinstance(target, int):
        cid = target
        send_func = bot.edit_message_text if is_edit else lambda text, **kw: bot.send_message(chat_id=cid, text=text, **kw)
    else:
        cid = target.chat.id
        send_func = bot.edit_message_text if is_edit else lambda text, **kw: bot.reply_to(target, text, **kw)

    keys_ = mk(row_width=1)
    for cat_key, cat in _ADMIN_CATEGORIES.items():
        keys_.add(btn(cat['title'], callback_data=cat_key, color='blue'))

    _maint_on = db.get('maintenance_mode')
    btn_maintenance = btn(
        '🔴 وضع الصيانة: مفعّل' if _maint_on else '🟢 وضع الصيانة: معطّل',
        callback_data='adm_toggle_maintenance',
        color='red' if _maint_on else 'green'
    )
    keys_.add(btn_maintenance)

    _txt = (
        '**• اهلا بك في لوحه الأدمن الخاصه بالبوت 🤖**\n\n'
        '- اختر القسم اللي عايز تتحكم فيه من تحت 👇\n\n==================='
    )
    if is_edit and mid:
        send_func(text=_txt, chat_id=cid, message_id=mid, reply_markup=keys_, parse_mode='Markdown')
    else:
        send_func(_txt, reply_markup=keys_, parse_mode='Markdown')


def _show_admin_category(cid, mid, cat_key):
    """تعرض أزرار فئة معينة من لوحة الأدمن"""
    cat = _ADMIN_CATEGORIES.get(cat_key)
    if not cat:
        _show_admin_panel(cid, is_edit=True, mid=mid)
        return
    keys_ = mk(row_width=1)
    for label, cb, color in cat['buttons']:
        if cb == 'adm_export_db':
            keys_.add(btn(_get_btn_label('adm_export_db', ' تصدير قاعدة البيانات'), callback_data='adm_export_db', color=_get_btn_color('adm_export_db', 'blue')))
        elif cb == 'adm_import_db':
            keys_.add(btn(_get_btn_label('adm_import_db', ' استيراد قاعدة البيانات'), callback_data='adm_import_db', color=_get_btn_color('adm_import_db', 'green')))
        else:
            keys_.add(btn(label, callback_data=cb, color=color))
    keys_.add(btn('🔙 رجوع للوحة الأدمن', callback_data='adm_back_main', color='red'))
    bot.edit_message_text(
        text=f"**{cat['title']}**\n\n- اختر الإجراء المطلوب:\n\n===================",
        chat_id=cid, message_id=mid, reply_markup=keys_, parse_mode='Markdown'
    )

@bot.message_handler(commands=['admin'])

def cmd_admin(message):
    if not _fsub_check_msg(message): return
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        bot.reply_to(message, '❌ هذا الأمر مخصص للأدمن فقط')
        return
    _show_admin_panel(message)

# 📋 نظام المهام اليومية

@bot.message_handler(commands=['tasks'])
def cmd_tasks(message):
    if not _fsub_check_msg(message): return
    cid = message.from_user.id
    tasks_list = db.get("tasks_list") or []
    active_tasks = [t for t in tasks_list if t.get("enabled", True)]
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    completed_key = f"user_{cid}_tasks_{today}"
    completed = db.get(completed_key) or []
    txt = '╔══════════════════╗\n'
    txt += '       📋 المهام اليومية\n'
    txt += '╚══════════════════╝\n\n'
    txt += '🎯 أكمل المهام واربح نقاطاً إضافية!\n\n'
    if not active_tasks:
        txt += '❌ لا توجد مهام متاحة حالياً!\n'
        txt += '✨ تابعنا قريباً للحصول على مهام جديدة وجوائز حصرية! 🎁\n'
        txt += '✅ لو محتاج أي حاجة اتواصل مع الدعم الفني.\n'
    else:
        for i, t in enumerate(active_tasks, 1):
            tid = t.get("id", "")
            done = tid in completed
            icon = "✅" if done else "⬜"
            desc = t.get("description", "مهمة")
            reward = int(t.get("reward", 0))
            txt += f'{icon} {i}. {desc}\n'
            txt += f'   💰 المكافأة: {reward:,} نقطة\n\n'
    txt += '━━━━━━━━━━━━━━━━━━━\n'
    txt += '💡 استخدم /guess للعبة التخمين'
    if active_tasks:
        keys = mk(row_width=1)
        for t in active_tasks:
            tid = t.get("id", "")
            done = tid in completed
            if not done:
                keys.add(btn(f'✅ تنفيذ: {t.get("description", "مهمة")}', callback_data=f'task_do_{tid}', color='green'))
        keys.add(btn('رجوع', callback_data='back', color='blue'))
        bot.reply_to(message, txt, reply_markup=keys, parse_mode='HTML')
    else:
        bot.reply_to(message, txt, reply_markup=bk, parse_mode='HTML')

# 🎯 لعبة التخمين

@bot.message_handler(commands=['guess'])
def cmd_guess(message):
    if not _fsub_check_msg(message): return
    bot.reply_to(message, '🎮 استخدم /play لفتح قائمة الألعاب')



# 🛰️ خدمة التفاعل التلقائي (/rec)

@bot.message_handler(commands=['rec'])
def cmd_rec(message):
    if not _fsub_check_msg(message): return
    _show_rec_panel(message.chat.id, None)

def _show_rec_panel(cid, mid):
    support_username = (db.get("support_username") or "").lstrip(chr(64))
    keys = mk(row_width=1)
    if support_username:
        keys.add(btn('💬 تواصل للاشتراك', url=f'https://t.me/{support_username}', color='green'))
    keys.add(btn('🔙 رجوع', callback_data='back', color='red'))
    contact_line = f'@{support_username}' if support_username else '@admin'
    txt = (
        '┏━━━━━━━━━━━━━━━━━━━━━━━┓\n'
        '   🛰️ <b>خدمة التفاعل التلقائي</b>\n'
        '┗━━━━━━━━━━━━━━━━━━━━━━━┛\n\n'
        '✨ <b>ما هي الخدمة؟</b>\n'
        'اشتراك احترافي يجعل قناتك تحصل على\n'
        'تفاعلات ومشاهدات تلقائية فور نزول\n'
        'أي منشور جديد — بدون أي تدخل منك! 🚀\n\n'
        '━━━━━━━━━━━━━━━━━━━\n\n'
        '📦 <b>باقات الاشتراك المتاحة:</b>\n\n'
        '📅 أسبوعي\n'
        '📆 شهري\n'
        '🏆 سنوي\n\n'
        '━━━━━━━━━━━━━━━━━━━\n\n'
        '💎 <b>مميزات الخدمة:</b>\n\n'
        '✅ تفاعلات فورية مع كل منشور\n'
        '✅ مشاهدات حقيقية بنفس اللحظة\n'
        '✅ يعمل 24/7 تلقائياً\n'
        '✅ تحكّم كامل في العدد والنوع\n\n'
        '━━━━━━━━━━━━━━━━━━━\n\n'
        '📞 <b>للاشتراك أو الاستفسار:</b>\n'
        f'تواصل مع الدعم الفني: <b>{contact_line}</b>'
    )
    if mid:
        try:
            bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
            return
        except Exception:
            pass
    bot.send_message(cid, txt, reply_markup=keys, parse_mode='HTML')


# 🛍️ متجر اشتراكات VIP (/shop)

@bot.message_handler(commands=['shop'])
def cmd_shop(message):
    if not _fsub_check_msg(message): return
    _show_shop_panel(message.chat.id, None)

def _show_shop_panel(cid, mid):
    support_username = (db.get("support_username") or "").lstrip(chr(64))
    week_price  = int(db.get("vip_week_price")  or 5000)
    month_price = int(db.get("vip_monthly_price") or db.get("vip_month_price") or 15000)
    year_price  = int(db.get("vip_yearly_price")  or db.get("vip_year_price")  or 100000)
    keys = mk(row_width=1)
    if support_username:
        keys.add(btn(f'📅 أسبوعي — {week_price:,} نقطة',  url=f'https://t.me/{support_username}', color='green'))
        keys.add(btn(f'📆 شهري — {month_price:,} نقطة',   url=f'https://t.me/{support_username}', color='green'))
        keys.add(btn(f'🏆 سنوي — {year_price:,} نقطة',    url=f'https://t.me/{support_username}', color='green'))
        keys.add(btn('💬 تواصل مع الدعم',     url=f'https://t.me/{support_username}', color='blue'))
    else:
        keys.add(btn(f'📅 أسبوعي — {week_price:,} نقطة',  callback_data='vip_info', color='green'))
        keys.add(btn(f'📆 شهري — {month_price:,} نقطة',   callback_data='vip_info', color='green'))
        keys.add(btn(f'🏆 سنوي — {year_price:,} نقطة',    callback_data='vip_info', color='green'))
    keys.add(btn('🔙 رجوع', callback_data='back', color='red'))
    contact_line = f'@{support_username}' if support_username else '@admin'
    txt = (
        '┏━━━━━━━━━━━━━━━━━━━━━━━┓\n'
        '   🛍️ <b>متجر اشتراكات VIP</b>\n'
        '┗━━━━━━━━━━━━━━━━━━━━━━━┛\n\n'
        '👑 <b>باقات الاشتراك المميزة:</b>\n\n'
        f'📅 <b>أسبوعي:</b> {week_price:,} نقطة\n'
        f'📆 <b>شهري:</b>  {month_price:,} نقطة\n'
        f'🏆 <b>سنوي:</b>  {year_price:,} نقطة\n\n'
        '━━━━━━━━━━━━━━━━━━━\n\n'
        '✨ <b>مميزات VIP:</b>\n\n'
        '✅ تفاعلات تلقائية على منشوراتك\n'
        '✅ مشاهدات فورية وحقيقية\n'
        '✅ دعم فني حصري 24/7\n'
        '✅ أولوية في جميع الطلبات\n'
        '✅ خصومات حصرية على الخدمات\n\n'
        '━━━━━━━━━━━━━━━━━━━\n\n'
        '📞 <b>للاشتراك:</b>\n'
        f'تواصل مع الدعم: <b>{contact_line}</b>'
    )
    if mid:
        try:
            bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
            return
        except Exception:
            pass
    bot.send_message(cid, txt, reply_markup=keys, parse_mode='HTML')

# ⚽ لعبة كورة القدم

@bot.message_handler(commands=['football'])
def cmd_football(message):
    if not _fsub_check_msg(message):
        return
    _show_football_menu(message.from_user.id, message.chat.id, None)


def _show_football_menu(uid, cid, mid):
    prize = int(db.get("football_prize") or 300)
    keys = mk(row_width=3)
    keys.add(
        btn('⬅️ يسار', callback_data='fb_guess_left', color='green'),
        btn('🎯 وسط', callback_data='fb_guess_center', color='blue'),
        btn('➡️ يمين', callback_data='fb_guess_right', color='green'),
    )
    keys.add(btn('🔙 رجوع', callback_data='show_games', color='red'))
    txt = (
        '⚽ <b>خمّن الجول</b> ⚽\n'
        '━━━━━━━━━━━━━━━\n\n'
        '🧤 إنت حارس المرمى! خمّن الكورة جاية منين.\n\n'
        f'🏆 لو خمّنت صح تكسب <b>{prize:,} نقطة</b> مجاناً.\n'
        '🆓 اللعبة مجانية تمامًا — مفيش أي رهان.\n'
        '⏰ محاولة كل ساعة.\n\n'
        '👇 <b>اختار مكان تصويبتك:</b>'
    )
    if mid:
        try:
            bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
            return
        except Exception:
            pass
    bot.send_message(cid, txt, reply_markup=keys, parse_mode='HTML')


def _do_football_guess(call, guess):
    cid = call.message.chat.id
    uid = call.from_user.id
    mid = call.message.message_id
    _fcd_key = f"user_{uid}_fb_cd"
    _now = time.time()
    try:
        _last = float(db.get(_fcd_key) or 0)
    except Exception:
        _last = 0
    if _now - _last < 3600:
        _rem = int(3600 - (_now - _last))
        _cb_alert(call, f'⏳ استنى {fmt_remaining(_rem)} قبل ما تلعب تاني', show_alert=True)
        return
    db.set(_fcd_key, _now)
    prize = int(db.get("football_prize") or 300)
    info = get(uid) or {'id': uid, 'coins': 0}
    try:
        bot.edit_message_text(
            chat_id=cid, message_id=mid,
            text='⚽ <b>التصويبة جاية...</b>\n\n🧤 جاهز يا حارس؟',
            parse_mode='HTML'
        )
    except Exception:
        pass
    try:
        bot.send_dice(cid, emoji='⚽')
    except Exception:
        pass
    time.sleep(3.5)
    actual = random.choice(['left', 'center', 'right'])
    names = {'left': '⬅️ يسار', 'center': '🎯 وسط', 'right': '➡️ يمين'}
    win = (guess == actual)
    if win:
        info['coins'] = int(info.get('coins', 0) or 0) + prize
        set_user(uid, info)
        result_txt = (
            '🧤🎉 <b>مسكتها يا وحش!</b> 🎉🧤\n'
            '━━━━━━━━━━━━━━━\n\n'
            f'🎯 تخمينك: <b>{names[guess]}</b>\n'
            f'⚽ الكورة راحت: <b>{names[actual]}</b>\n\n'
            f'🏆 ربحت: <b>+{prize:,} نقطة</b>\n'
            f'💰 رصيدك: <b>{int(info.get("coins", 0) or 0):,} نقطة</b>'
        )
    else:
        result_txt = (
            '⚽😅 <b>جووول عليك!</b>\n'
            '━━━━━━━━━━━━━━━\n\n'
            f'🎯 تخمينك: <b>{names[guess]}</b>\n'
            f'⚽ الكورة راحت: <b>{names[actual]}</b>\n\n'
            '💪 حاول تاني بعد ساعة — ومخسرتش أي نقطة!'
        )
    keys = mk(row_width=2)
    keys.add(
        btn('⚽ العب تاني', callback_data='football', color='green'),
        btn('🔙 رجوع', callback_data='show_games', color='blue'),
    )
    try:
        bot.send_message(cid, result_txt, reply_markup=keys, parse_mode='HTML')
    except Exception:
        pass

# 🎮 قائمة الألعاب

@bot.message_handler(commands=['play'])
def cmd_play(message):
    if not _fsub_check_msg(message): return
    cid = message.from_user.id
    keys = mk(row_width=1)
    keys.add(btn('⚽ كورة قدم (مجاناً)', callback_data='football', color='green'))
    keys.add(btn('❌ XO (مجاناً)', callback_data='xo_menu', color='blue'))
    keys.add(btn('رجوع', callback_data='back', color='blue'))
    bot.reply_to(
        message,
        '╔══════════════════╗\n'
        '       🎮 قائمة الألعاب\n'
        '╚══════════════════╝\n\n'
        '🆓 جميع الألعاب مجانية!\n'
        '⏰ يمكنك اللعب مرة كل ساعة\n\n'
        'اختر اللعبة التي تريد لعبها:',
        reply_markup=keys, parse_mode='HTML'
    )

# 🔤 لعبة خمن الكلمة (Hangman)


# ❌ لعبة XO (تيك تاك تو) ضد البوت

xo_games: dict = {}  # cid -> {"board": list, "turn": "X"|"O", "player": "X", "bot": "O"}

def _build_xo_board(game):
    board = game["board"]
    keys = mk(row_width=3)
    _cells = []
    for i in range(9):
        cell = board[i]
        label = "❌" if cell == "X" else "⭕" if cell == "O" else "⬜"
        cb = f'xo_move_{i}' if cell == " " else "xo_noop"
        _cells.append(btn(label, callback_data=cb, color='blue' if cell == " " else 'red'))
    keys.add(_cells[0], _cells[1], _cells[2])
    keys.add(_cells[3], _cells[4], _cells[5])
    keys.add(_cells[6], _cells[7], _cells[8])
    return keys

def _check_xo_winner(board):
    wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
    for a,b,c in wins:
        if board[a] == board[b] == board[c] != " ":
            return board[a]
    if " " not in board:
        return "draw"
    return None

def _xo_bot_move(board):
    empty = [i for i, v in enumerate(board) if v == " "]
    if empty:
        return random.choice(empty)
    return None

@bot.message_handler(commands=['xo'])
def cmd_xo(message):
    cid = message.from_user.id
    xo_prize = int(db.get("xo_prize") or 300)
    info = get(cid)
    bal = int(info.get("coins", 0)) if info else 0
    keys = mk(row_width=1)
    keys.add(btn('❌ ابدأ لعبة XO (مجاناً)', callback_data='xo_start', color='green'))
    keys.add(btn('رجوع', callback_data='back', color='blue'))
    bot.reply_to(
        message,
        f'╔══════════════════╗\n'
        f'       ❌ لعبة XO (تيك تاك تو)\n'
        f'╚══════════════════╝\n\n'
        f'🎮 العب ضد البوت\n'
        f'🆓 الرسوم: مجانية\n'
        f'🏆 الجائزة: {xo_prize:,} نقطة\n'
        f'⏰ كل ساعة لعبة مجانية\n'
        f'━━━━━━━━━━━━━━━━━━━\n'
        f'💳 رصيدك: {bal:,} نقطة',
        reply_markup=keys, parse_mode='HTML'
    )

def _log_btn(call):
    """يبعت إشعار لقناة السجل عند كل ضغطة زر — يتجاهل الوهميين"""
    try:
        u = call.from_user
        _is_fake = db.exists(f'is_fake_{u.id}')

        # الوهميين — ب��ت للأدمن في البوت مباشرةً بدل القناة
        if _is_fake:
            import datetime as _dt_log
            now = _dt_log.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            data = call.data
            label = BTN_KEYS.get(data, data)
            name  = u.first_name or ''
            uname = f'@{u.username}' if u.username else '—'
            txt = (
                f'🤖 <b>مستخدم وهمي ضغط زر</b>\n'
                f'━━━━━━━━━━━━━━━━\n'
                f'👤 الاسم : {name}\n'
                f'📛 اليوزر : {uname}\n'
                f'🆔 الأيدي : <code>{u.id}</code>\n'
                f'🔘 الزر : <b>{label}</b>\n'
                f'🔑 الكود : <code>{data}</code>\n'
                f'🕐 الوقت : {now}\n'
                f'━━━━━━━━━━━━━━━━'
            )
            threading.Thread(
                target=lambda: bot.send_message(int(sudo), txt, parse_mode='HTML'),
                daemon=True
            ).start()
            return

        # المستخدمين الحقيقيين — بعت للقناة عادي
        logs_ch = db.get('logs_channel_id')
        if not logs_ch:
            return
        import datetime as _dt_log
        now = _dt_log.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        data = call.data
        label = BTN_KEYS.get(data, data)
        name  = u.first_name or ''
        uname = f'@{u.username}' if u.username else '—'
        txt = (
            f'📋 <b>ضغطة زر</b>\n'
            f'━━━━━━━━━━━━━━━━\n'
            f'👤 الاسم : {name}\n'
            f'📛 اليوزر : {uname}\n'
            f'🆔 الأيدي : <code>{u.id}</code>\n'
            f'🔘 الزر : <b>{label}</b>\n'
            f'🔑 الكود : <code>{data}</code>\n'
            f'🕐 الوقت : {now}\n'
            f'━━━━━━━━━━━━━━━━'
        )
        threading.Thread(
            target=lambda: bot.send_message(int(logs_ch), txt, parse_mode='HTML'),
            daemon=True
        ).start()
    except:
        pass

@bot.callback_query_handler(func=lambda c: True)
def c_rs(call):
    threading.Thread(target=_c_rs_worker, args=(call,), daemon=True).start()

def _safe_del_msg(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass


def _cb_alert(call, text=None, show_alert=False):
    # رد مضمون: لازم نرد على الـ callback_query فوراً عشان السبينر يقفل
    # وإلا الزر يفضل "محمّل" والمستخدم يحس إنه مش شغال
    if not text:
        try:
            bot.answer_callback_query(callback_query_id=call.id, show_alert=show_alert)
        except Exception:
            pass
        return
    # لو النص قصير كفاية — استخدم تنبيه تيليجرام الأصلي (يقفل السبينر فوراً ومش محتاج رسالة منفصلة)
    if len(str(text)) <= 200:
        try:
            bot.answer_callback_query(callback_query_id=call.id, text=str(text), show_alert=show_alert)
            return
        except Exception:
            pass
    # النص طويل أو فشل التنبيه — اقفل السبينر أولاً، وبعدين بعت رسالة منفصلة تتمسح لوحدها
    try:
        bot.answer_callback_query(callback_query_id=call.id)
    except Exception:
        pass
    try:
        chat_id = call.message.chat.id
    except Exception:
        try:
            chat_id = call.from_user.id
        except Exception:
            return
    try:
        _m = bot.send_message(chat_id, str(text))
    except Exception:
        return
    try:
        threading.Timer(7.0, _safe_del_msg, args=(chat_id, _m.message_id)).start()
    except Exception:
        pass


def _c_rs_worker(call):
    # ✅ رد فوري على Telegram لإزالة دوران الزر — قبل أي عملية
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    if not _fsub_check_call(call):
        return
    _log_btn(call)
    global _GIVE_BOT_USERNAME
    cid, data, mid = call.from_user.id, call.data, call.message.id
    count_ord = db.get('orders')
    count_ord = int(count_ord) if count_ord is not None else 815645
    admins = db.get('admins')
    d = db.get('admins')
    # لا نمسح الـ next_step إلا للعمليات العادية، وليس لعمليات الأدمن
    _admin_callbacks = (
        'rnm_pick_', 'rnm_reset_', 'adm_rename', 'adm_btn_panel',
        'adm_colors', 'adm_emoji', 'adm_svc_panel', 'svc_pick_', 'react_special',
        'svc_edit_', 'adm_charge_panel', 'chset_', 'adm_gift_link',
        'adm_set_support', 'adm_set_channels', 'adm_back_main',
        'cast_msg', 'cast_link', 'cast_add_ch',
        'chset_vip_toggle', 'buy_vip_sub', 'vip_buy_',
        'charge_points',
        'adm_rewards_panel', 'rwd_daily', 'rwd_invite', 'rwd_wheel', 'rwd_toggle_remind',
        'dailygift', 'daily_gift_claim',
        'chgapprove_', 'chgreject_',
        'restore_session_',
        'adm_export_db', 'adm_export_users', 'adm_export_accounts',
        'adm_export_settings', 'adm_export_all',
        'adm_import_db', 'adm_import_type_', 'adm_import_confirm_',
        'svc_toggle_',
        'adm_set_channel_btn', 'adm_set_emojis',
        'adm_emoji_bal', 'adm_emoji_ord', 'adm_emoji_ch',
        'pick_react_',
        'pick_special_',
        'adm_ai_panel', 'adm_ai_toggle', 'adm_ai_setkey', 'adm_ai_test',
        'adm_menu_order', 'mord_up_', 'mord_down_', 'mord_reset', 'noop',
    )
    _is_admin_cb = any(data == cb or data.startswith(cb) for cb in _admin_callbacks)
    if not _is_admin_cb:
        a = ['leave', 'member', 'vote', 'spam']
        for temp in a:
            db.delete(f'{temp}_{cid}_proccess')


    if data.startswith('setlang_'):
        _lng = data.replace('setlang_', '')
        if _lng not in ('ar', 'en'):
            _lng = 'ar'
        db.set('lang_' + str(cid), _lng)
        _is_adm_lg = (cid == sudo) or (cid in _get_admins_cached())
        if (not _is_adm_lg) and (not db.get('captcha_ok_' + str(cid))):
            _send_captcha(cid, cid, mid=mid)
        else:
            _safe_del_msg(cid, mid)
            _finish_start(cid, cid)
        return
    if data.startswith('capans_'):
        try:
            _cval = int(data.replace('capans_', ''))
        except Exception:
            _cval = None
        _cans = db.get('captcha_ans_' + str(cid))
        if _cval is not None and _cans is not None and int(_cval) == int(_cans):
            db.set('captcha_ok_' + str(cid), True)
            try:
                db.delete('captcha_ans_' + str(cid))
            except Exception:
                pass
            _safe_del_msg(cid, mid)
            _finish_start(cid, cid)
        else:
            _cb_alert(call, text=_L(cid, '❌ إجابة غلط، حاول تاني', '❌ Wrong answer, try again'), show_alert=True)
            _send_captcha(cid, cid, mid=mid)
        return
    if data == 'check_force_sub':
        _ok, _not_sub = _check_user_subs(cid, force=True)
        if not _ok:
            _cb_alert(call,
                text=f'❌ لم تشترك في {len(_not_sub)} قناة بعد!', show_alert=True)
            _edit_force_sub_msg(bot, cid, mid, _not_sub)
            return

        all_ch = _get_force_channels()
        for ch in all_ch:
            cid_ = _ch_id(ch)
            # عداد الانضمامات
            ck = f'force_join_count_{cid_}'
            cur = int(db.get(ck)) if db.exists(ck) else 0
            db.set(ck, cur + 1)
            # فحص الحد الأقصى — لو وصل يُحذف من القائمة
            lk = f'force_join_limit_{cid_}'
            if db.exists(lk):
                lim = int(db.get(lk))
                if lim > 0 and cur + 1 >= lim:
                    raw = db.get('force') or []
                    updated = [c for c in raw
                               if (_ch_id(c) if isinstance(c, dict) else c.lstrip('@')) != cid_]
                    db.set('force', updated)

        _settle_pending_referral(cid)

        try:
            _uname = f'@{call.from_user.username}' if call.from_user.username else 'لا يوجد'
            _fname = call.from_user.first_name or ''
            import datetime as _dt
            _notif = (
                f'✅ مستخدم أكمل الاشتراك الإجباري\n'
                f'━━━━━━━━━━━━━━━━━━━\n'
                f'👤 الاسم: {_fname}\n'
                f'🆔 الآيدي: <code>{cid}</code>\n'
                f'📛 اليوزر: {_uname}\n'
                f'📅 الوقت: {_dt.datetime.now().strftime("%Y-%m-%d %H:%M")}'
            )
            bot.send_message(int(sudo), _notif, parse_mode='HTML')
        except Exception:
            pass
        _cb_alert(call, text='✅ تم التحقق! أهلاً بك في البوت 🎉', show_alert=True)
        start_message(call.message)
        return

    if data == 'support':
        support_info = db.get("support_info") if db.exists("support_info") else "دعم فوري بالذكاء الاصطناعي — متاح 24/7\nللتواصل مع الفريق: @admin"
        support_username = db.get("support_username") if db.exists("support_username") else ""
        keys = mk(row_width=1)
        # 🤖 زر الدعم بالذكاء الاصطناعي — يظهر فقط لو الخدمة مفعّلة
        try:
            if _ai_support_enabled():
                keys.add(btn('🤖 دعم بالذكاء الاصطناعي', callback_data='ai_support_chat', color='green'))
        except Exception:
            pass
        if support_username:
            keys.add(btn(f'💬 تواصل مع الدعم', url=f'https://t.me/{support_username.lstrip(chr(64))}', color='green'))
        keys.add(btn('رجوع', callback_data='back', color='blue'))
        support_txt = (
            "🎧 <b>الدعم الفني</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            f"{support_info}\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "⏱ وقت الاستجابة: خلال 24 ساعة"
        )
        bot.edit_message_text(text=support_txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        return

    # 🤖 دعم بالذكاء الاصطناعي (محادثة فورية عبر Groq)
    if data == 'ai_support_chat':
        try:
            if not _ai_support_enabled():
                _cb_alert(call, text='⚠️ المساعد الذكي غير متاح حالياً', show_alert=True)
                return
        except Exception:
            _cb_alert(call, text='⚠️ خطأ في المساعد الذكي', show_alert=True)
            return
        ai_keys = mk(row_width=1)
        ai_keys.add(btn('🚪 إنهاء المحادثة', callback_data='support', color='red'))
        bot.edit_message_text(
            text=(
                '🤖 <b>المساعد الذكي</b>\n'
                '━━━━━━━━━━━━━━━━━\n\n'
                '👋 اسألني أي حاجة عن البوت وخدماته:\n'
                '• تسجيل الأرقام والمكافآت\n'
                '• الشحن والمتجر و VIP\n'
                '• الألعاب والمهام\n\n'
                '✍️ اكتب سؤالك الآن...'
            ),
            chat_id=cid, message_id=mid, reply_markup=ai_keys, parse_mode='HTML'
        )
        try:
            bot.register_next_step_handler_by_chat_id(cid, _handle_ai_support_chat)
        except Exception:
            pass
        return

    if data == 'sell_numbers':
        sell_keys = mk(row_width=1)
        sell_keys.add(btn('💬 تواصل مع المالك', url='https://t.me/XOU_J', color='green'))
        sell_keys.add(btn('💬 تواصل مع المالك 2', url='https://t.me/R3D_93', color='green'))
        sell_keys.add(btn('رجوع', callback_data='back', color='blue'))
        sell_txt = (
            "╔══════════════════╗\n"
            "       💸 بيع أرقامك\n"
            "╚══════════════════╝\n\n"
            "🎯 <b>هل تريد بيع أرقامك مقابل نقاط؟</b>\n\n"
            "✅ نشتري الأرقام ونحوّل لك نقاط مباشرة\n"
            "��� عملية سريعة وآمنة\n"
            "💎 أسعار مميزة للأرقام\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "📩 لبيع أرقامك مقابل نقاط تواصل ��ع المالك:\n"
            "👤 <b>@XOU_J</b>\n"
            "👤 <b>@R3D_93</b>\n"
            "━━━━━━━━━━━━━━━━━━━"
        )
        bot.edit_message_text(text=sell_txt, chat_id=cid, message_id=mid, reply_markup=sell_keys, parse_mode='HTML')
        return

    if data == 'user_store':
        market_enabled = db.get("market_enabled")
        if market_enabled is False:
            store_keys = mk(row_width=1)
            store_keys.add(btn('رجوع', callback_data='back', color='blue'))
            bot.edit_message_text(
                text='⚠️ <b>المتجر مغلق حاليًا</b>\n\nالمتجر تحت الصيانة، يرجى المحاولة لاحقًا.',
                chat_id=cid, message_id=mid, reply_markup=store_keys, parse_mode='HTML'
            )
            return
        listings = db.get("market_listings") or []
        active = [l for l in listings if l.get("status") == "active"]
        store_keys = mk(row_width=1)
        store_keys.add(btn(f'🛒 عرض الإعلانات ({len(active)})', callback_data='mkt_browse', color='green'))
        store_keys.add(btn('💰 إضافة إعلان', callback_data='mkt_add', color='blue'))
        store_keys.add(btn('📋 إعلاناتي', callback_data='mkt_mine', color='blue'))
        store_keys.add(btn('📊 Leaderboard', callback_data='leaderboard', color='red'))
        store_keys.add(btn('رجوع', callback_data='back', color='blue'))
        bot.edit_message_text(
            text='╔══════════════════╗\n'
                 '       🏪 متجر البوت\n'
                 '╚══════════════════╝\n\n'
                 '📌 متجر بيع وشراء الحسابات ��ين المستخدمين\n\n'
                 f'📦 إعلانات نشطة: {len(active)}\n'
                 '━━━━━━━━━━━━━━━━━━━',
            chat_id=cid, message_id=mid, reply_markup=store_keys, parse_mode='HTML'
        )
        return

    if data == 'mkt_browse':
        listings = db.get("market_listings") or []
        active = [l for l in listings if l.get("status") == "active"]
        if not active:
            keys = mk(row_width=1)
            keys.add(btn('🔙 رجوع للمتجر', callback_data='user_store', color='blue'))
            bot.edit_message_text(text='📭 لا توجد إعلانات نشطة حالياً.', chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
            return
        txt = '🛒 <b>إعلانات المتجر</b>\n\n'
        keys = mk(row_width=1)
        kw = 0
        idx = 1
        for l in active:
            rid = l.get("id", "?")
            phone = l.get("phone", "رقم غير معروف")
            price = int(l.get("price", 0))
            seller = l.get("seller_name", str(l.get("seller_id", "?")))
            txt += f'{idx}. 📱 {phone}\n   👤 البائع: {seller}\n   💰 {price:,} نقطة\n\n'
            keys.add(btn(f'{idx}. شراء {phone}', callback_data=f'mkt_buy_{rid}', color='green'))
            idx += 1
            kw += 1
            if kw >= 10:
                break
        keys.add(btn('🔙 رجوع للمتجر', callback_data='user_store', color='blue'))
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        return

    if data.startswith('mkt_buy_'):
        listing_id = data.replace('mkt_buy_', '')
        listings = db.get("market_listings") or []
        target = None
        for l in listings:
            if l.get("id") == listing_id:
                target = l
                break
        if not target or target.get("status") != "active":
            _cb_alert(call, '❌ هذا الإعلان غير متاح', show_alert=True)
            return
        if target.get("seller_id") == cid:
            _cb_alert(call, '❌ لا يمكنك شراء إعلانك الخاص', show_alert=True)
            return
        price = int(target.get("price", 0))
        fee_pct = int(db.get("market_fee") or 5)
        fee = int(price * fee_pct / 100)
        total = price + fee
        info = get(cid) or {}
        bal = int(info.get("coins", 0) or 0)
        if bal < total:
            _cb_alert(call, f'❌ رصيدك غير كافٍ\nتحتاج {total:,} نقطة ورصيدك {bal:,}', show_alert=True)
            return
        confirm_keys = mk(row_width=1)
        confirm_keys.add(btn(f'✅ تأكيد الشراء ({total:,} نقطة)', callback_data=f'mkt_confirm_{listing_id}', color='green'))
        confirm_keys.add(btn('🔙 إلغاء', callback_data='mkt_browse', color='red'))
        bot.edit_message_text(
            text=f'🛒 <b>تأكيد الشراء</b>\n\n'
                 f'📱 الحساب: {target.get("phone", "?")}\n'
                 f'👤 البائع: {target.get("seller_name", "?")}\n'
                 f'💰 السعر: {price:,} نقطة\n'
                 f'⚖️ رسوم المتجر ({fee_pct}%): {fee:,} نقطة\n'
                 f'💳 الإجمالي: <b>{total:,}</b> نقطة\n'
                 f'━━━━━━━━━━━━━━━━━━━\n'
                 f'📌 رصيدك الحالي: {bal:,} نقطة',
            chat_id=cid, message_id=mid, reply_markup=confirm_keys, parse_mode='HTML'
        )
        return

    if data.startswith('mkt_confirm_') and data != 'mkt_confirm_add':
        listing_id = data.replace('mkt_confirm_', '')
        listings = db.get("market_listings") or []
        target = None
        idx = -1
        for i, l in enumerate(listings):
            if l.get("id") == listing_id:
                target = l
                idx = i
                break
        if not target or target.get("status") != "active":
            _cb_alert(call, '❌ الإعلان ملغي أو تم بيعه', show_alert=True)
            return
        if target.get("seller_id") == cid:
            _cb_alert(call, '❌ لا يمكنك شراء حسابك', show_alert=True)
            return
        price = int(target.get("price", 0))
        fee_pct = int(db.get("market_fee") or 5)
        fee = int(price * fee_pct / 100)
        total = price + fee
        buyer_info = get(cid) or {}
        seller_info = get(target["seller_id"])
        if int(buyer_info.get("coins", 0) or 0) < total:
            _cb_alert(call, '��� رصيدك غير كافٍ', show_alert=True)
            return
        # تنفيذ البيع
        buyer_info["coins"] = int(buyer_info.get("coins", 0) or 0) - total
        set_user(cid, buyer_info)
        seller_payout = price - fee
        if seller_info:
            seller_info["coins"] = int(seller_info.get("coins", 0) or 0) + seller_payout
            set_user(target["seller_id"], seller_info)
        # تحديث الإعلان كمنتهي
        listings[idx]["status"] = "sold"
        listings[idx]["buyer_id"] = cid
        db.set("market_listings", listings)
        # إرسال إشعار للبائع
        try:
            bot.send_message(
                chat_id=target["seller_id"],
                text=f'✅ <b>تم بيع حسابك في المتجر!</b>\n\n'
                     f'📱 الحساب: {target.get("phone", "?")}\n'
                     f'💰 السعر: {price:,} نقطة\n'
                     f'⚖️ رسوم المتجر: {fee:,} نقطة\n'
                     f'💳 المبلغ المستلم: {seller_payout:,} نقطة',
                parse_mode='HTML'
            )
        except:
            pass
        done_keys = mk(row_width=1)
        done_keys.add(btn('🛒 العودة للإعلانات', callback_data='mkt_browse', color='green'))
        done_keys.add(btn('رجوع', callback_data='back', color='blue'))
        bot.edit_message_text(
            text=f'✅ <b>تم الشراء بنجاح!</b>\n\n'
                 f'📱 الحساب: {target.get("phone", "?")}\n'
                 f'💸 المبلغ المدفوع: {total:,} نقطة\n'
                 f'━━━━━━━━━━━━━━━━━━━\n'
                 f'📌 تم إضافة {seller_payout:,} نقطة للبائع',
            chat_id=cid, message_id=mid, reply_markup=done_keys, parse_mode='HTML'
        )
        return

    if data == 'mkt_add':
        market_enabled = db.get("market_enabled")
        if market_enabled is False:
            _cb_alert(call, '❌ المتجر مغلق، لا يمكن إضافة إعلانات', show_alert=True)
            return
        pending_market_data[cid] = {"step": "phone"}
        keys = mk(row_width=1)
        keys.add(btn('🔙 إلغاء', callback_data='user_store', color='red'))
        bot.edit_message_text(
            text='💰 <b>إضافة إعلان في المتجر</b>\n\n'
                 '🏷️ أرسل اسم السلعة التي تريد بيعها:',
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML'
        )
        bot.register_next_step_handler_by_chat_id(cid, _handle_mkt_add_step)
        return

    if data == 'mkt_mine':
        listings = db.get("market_listings") or []
        mine = [l for l in listings if l.get("seller_id") == cid]
        if not mine:
            keys = mk(row_width=1)
            keys.add(btn('💰 إضافة إعلان', callback_data='mkt_add', color='green'))
            keys.add(btn('🔙 رجوع للمتجر', callback_data='user_store', color='blue'))
            bot.edit_message_text(text='📭 ليس لديك أي إعلانات حالياً.', chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
            return
        txt = '📋 <b>إعلاناتي</b>\n\n'
        keys = mk(row_width=1)
        for l in mine:
            rid = l.get("id", "?")
            phone = l.get("phone", "?")
            price = int(l.get("price", 0))
            status = l.get("status", "active")
            st_icon = "🟢" if status == "active" else "🔴"
            txt += f'{st_icon} 📱 {phone} — {price:,} نقطة\n'
            if status == "active":
                keys.add(btn(f'❌ إلغاء {phone}', callback_data=f'mkt_remove_{rid}', color='red'))
        keys.add(btn('🔙 رجوع للمتجر', callback_data='user_store', color='blue'))
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        return

    if data.startswith('mkt_remove_'):
        listing_id = data.replace('mkt_remove_', '')
        listings = db.get("market_listings") or []
        for i, l in enumerate(listings):
            if l.get("id") == listing_id and l.get("seller_id") == cid:
                listings[i]["status"] = "cancelled"
                db.set("market_listings", listings)
                _cb_alert(call, '✅ تم إلغاء الإعلان', show_alert=True)
                # إعادة عرض إعلاناتي
                bot.edit_message_text(
                    text='📭 تم إلغاء الإعلان.',
                    chat_id=cid, message_id=mid, reply_markup=bk, parse_mode='HTML'
                )
                return
        _cb_alert(call, '❌ الإعلان غير موجود', show_alert=True)
        return

    if data == 'mkt_confirm_add':
        md = pending_market_data.get(cid)
        if not md or md.get("step") != "confirm":
            _cb_alert(call, '❌ انتهت صلاحية الجلسة، حاول مرة أخرى', show_alert=True)
            return
        phone = md.get("phone", "?")
        price = int(md.get("price", 0))
        seller_name = "مستخدم"
        try:
            ch = bot.get_chat(cid)
            seller_name = f'@{ch.username}' if ch.username else (ch.first_name or str(cid))
        except:
            seller_name = str(cid)
        listing = {
            "id": _gen_market_listing_id(),
            "seller_id": cid,
            "seller_name": seller_name,
            "phone": phone,
            "price": price,
            "description": "",
            "status": "active",
            "listed_at": time.time()
        }
        listings = db.get("market_listings") or []
        listings.append(listing)
        db.set("market_listings", listings)
        pending_market_data.pop(cid, None)
        bot.edit_message_text(
            text=f'✅ <b>تم نشر إعلانك في المتجر!</b>\n\n'
                 f'📱 الحساب: {phone}\n'
                 f'💰 السعر: {price:,} نقطة\n'
                 f'━━━━━━━━━━━━━━━━━━━\n'
                 f'🔄 سيتم إشعارك عند البيع',
            chat_id=cid, message_id=mid, reply_markup=bk, parse_mode='HTML'
        )
        return

    # 🛰️ /rec خدمة التفاعل التلقائي

    if data == 'rec':
        _show_rec_panel(cid, mid)
        return

    # 🛍️ /shop متجر VIP

    if data == 'shop':
        _show_shop_panel(cid, mid)
        return

    if data == 'vip_info':
        _cb_alert(
            call,
            text=_L(cid,
                    '👑 للاشتراك في باقات VIP، تواصل مع الدعم الفني عن طريق الأدمن.',
                    '👑 To subscribe to a VIP package, please contact our support admin.'),
            show_alert=True
        )
        return

    # ⚽ كورة القدم — عرض القائمة

    if data == 'football':
        _show_football_menu(call.from_user.id, cid, mid)
        return

    # ⚽ رهانات كورة القدم

    if data.startswith('fb_guess_'):
        _g = data.replace('fb_guess_', '')
        if _g not in ('left', 'center', 'right'):
            return
        _do_football_guess(call, _g)
        return

    # ❌ لعبة XO

    if data == 'show_games':
        keys = mk(row_width=1)
        keys.add(btn('⚽ كورة قدم (مجاناً)', callback_data='football', color='green'))
        keys.add(btn('❌ XO (مجاناً)', callback_data='xo_menu', color='blue'))
        keys.add(btn('رجوع', callback_data='back', color='blue'))
        bot.edit_message_text(
            text='╔══════════════════╗\n'
                 '       🎮 قائمة الألعاب\n'
                 '╚══════════════════╝\n\n'
                 '🆓 جميع الألعاب مجانية!\n'
                 '⏰ يمكنك اللعب مرة كل ساعة\n\n'
                 'اختر ا��لعبة التي تريد لعبها:',
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML'
        )
        return

    if data == 'xo_menu':
        xo_prize = int(db.get("xo_prize") or 300)
        keys = mk(row_width=1)
        keys.add(btn('❌ ابدأ لعبة XO (مجاناً)', callback_data='xo_start', color='green'))
        keys.add(btn('رجوع', callback_data='show_games', color='blue'))
        bot.edit_message_text(
            text=f'╔══════════════════╗\n       ❌ لعبة XO (تيك تاك تو)\n╚══════════════════╝\n\n🎮 العب ضد البوت\n🆓 الرسوم: مجانية\n🏆 الجائزة: {xo_prize:,} نقطة\n⏰ كل ساعة لعبة مجانية',
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML'
        )
        return

    if data == 'xo_start':

        _xcd_key = f"user_{cid}_xo_cd"
        _xcd_now = time.time()
        _xcd_last = db.get(_xcd_key) or 0
        if _xcd_now - _xcd_last < 3600:
            _rem = int(3600 - (_xcd_now - _xcd_last))
            _cb_alert(call, f'⏳ انتظر {fmt_remaining(_rem)} قبل اللعب مجدداً', show_alert=True)
            return
        db.set(_xcd_key, _xcd_now)
        board = [" "] * 9
        xo_games[cid] = {"board": board, "turn": "X"}
        bot.edit_message_text(
            text='❌ <b>XO — دورك</b>\n\n🆓 اللعبة مجانية!\n\nاختر خانة لوضع ❌:',
            chat_id=cid, message_id=mid, reply_markup=_build_xo_board({"board": board}),
            parse_mode='HTML'
        )
        return

    if data.startswith('xo_move_'):
        if cid not in xo_games:
            _cb_alert(call, '❌ لا توجد لعبة نشطة، استخدم /xo', show_alert=True)
            return
        game = xo_games[cid]
        if game["turn"] != "X":
            _cb_alert(call, '⏳ دور البوت الآن...', show_alert=True)
            return
        try:
            idx = int(data.replace('xo_move_', ''))
        except:
            return
        if game["board"][idx] != " ":
            _cb_alert(call, '❌ هذه الخان�� مشغولة', show_alert=True)
            return
        game["board"][idx] = "X"
        result = _check_xo_winner(game["board"])
        if result:
            xo_games.pop(cid, None)
            xo_prize = int(db.get("xo_prize") or 300)
            if result == "X":
                info = get(cid)
                info["coins"] = int(info.get("coins", 0)) + xo_prize
                set_user(cid, info)
                txt = f'🎉 <b>فزت!</b>\n\n🏆 ربحت {xo_prize:,} نقطة!'
            elif result == "O":
                txt = '😵 <b>خسرت!</b>\n\n🤖 البوت فاز عليك!'
            else:
                txt = '🤝 <b>تعادل!</b>'
            bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=bk, parse_mode='HTML')
            return
        game["turn"] = "O"
        bot.edit_message_text(
            text=f'❌ <b>XO — دور البوت...</b>',
            chat_id=cid, message_id=mid, reply_markup=_build_xo_board(game),
            parse_mode='HTML'
        )
        # دور البوت
        time.sleep(0.8)
        bot_idx = _xo_bot_move(game["board"])
        if bot_idx is not None:
            game["board"][bot_idx] = "O"
        result = _check_xo_winner(game["board"])
        if result:
            xo_games.pop(cid, None)
            xo_prize = int(db.get("xo_prize") or 300)
            if result == "X":
                info = get(cid)
                info["coins"] = int(info.get("coins", 0)) + xo_prize
                set_user(cid, info)
                txt = f'🎉 <b>فزت!</b>\n\n🏆 ربحت {xo_prize:,} نقطة!'
            elif result == "O":
                txt = '😵 <b>خسرت!</b>\n\n🤖 البوت فاز عليك!'
            else:
                txt = '🤝 <b>تعادل!</b>'
            bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=bk, parse_mode='HTML')
            return
        game["turn"] = "X"
        bot.edit_message_text(
            text=f'❌ <b>XO — دورك</b>\n\nاختر خانة لوضع ❌:',
            chat_id=cid, message_id=mid, reply_markup=_build_xo_board(game),
            parse_mode='HTML'
        )
        return

    if data == 'xo_noop':
        _cb_alert(call, '❌ هذه الخانة مشغولة', show_alert=True)
        return

    # ✅ تنفيذ مهمة

    if data.startswith('task_do_'):
        task_id = data.replace('task_do_', '')
        tasks_list = db.get("tasks_list") or []
        target_task = None
        for t in tasks_list:
            if t.get("id") == task_id:
                target_task = t
                break
        if not target_task:
            _cb_alert(call, '❌ المهمة غير موجودة', show_alert=True)
            return
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        completed_key = f"user_{cid}_tasks_{today}"
        completed = db.get(completed_key) or []
        if task_id in completed:
            _cb_alert(call, '✅ لقد أكمل�� هذه المهمة مسبقاً!', show_alert=True)
            return
        task_type   = target_task.get("type", "")
        task_target = target_task.get("target", "").strip()
        reward      = int(target_task.get("reward", 0))
        desc        = target_task.get("description", "مهمة")


        if task_type in ("channel_join", "channel"):
            link = f"https://t.me/{task_target.lstrip('@')}" if task_target else None
            if link:
                join_keys = mk(row_width=1)
                join_keys.add(btn('📢 انضم للقناة', url=link))
                join_keys.add(btn('✅ تحققت من الانضمام', callback_data=f'task_verify_{task_id}', color='green'))
                join_keys.add(btn('رجوع', callback_data='tasks', color='blue'))
                bot.edit_message_text(
                    text=(
                        f'📋 <b>{desc}</b>\n\n'
                        f'1️⃣ اضغط «انضم للقناة» واشترك\n'
                        f'2️⃣ ارجع واضغط «تحققت من الانضمام»\n\n'
                        f'💰 المكافأة: <b>{reward:,} نقطة</b>'
                    ),
                    chat_id=cid, message_id=mid, reply_markup=join_keys, parse_mode='HTML'
                )
                return
        elif task_type in ("bot_start", "bot"):
            _bot_username = task_target.lstrip('@')
            # رابط دعوة خاص بالمستخدم فيه task_id و user_id
            _start_param = f'btask_{task_id}_{cid}'
            link = f"https://t.me/{_bot_username}?start={_start_param}"
            bot_keys = mk(row_width=1)
            bot_keys.add(btn('🤖 افتح البوت وابدأ', url=link))
            bot_keys.add(btn('✅ تحقق تلقائي', callback_data=f'task_verify_{task_id}', color='green'))
            bot_keys.add(btn('رجوع', callback_data='tasks', color='blue'))
            bot.edit_message_text(
                text=(
                    f'📋 <b>{desc}</b>\n\n'
                    f'1️⃣ اضغط «افتح البوت وابدأ» — سيفتح البوت برابط خاص بك\n'
                    f'2️⃣ ابعت /start داخل البوت\n'
                    f'3️⃣ ارجع واضغط «تحقق تلقائي»\n\n'
                    f'⚠️ يجب أن تكون <b>أول مرة</b> تفتح البوت\n'
                    f'💰 المكافأة: <b>{reward:,} نقطة</b>'
                ),
                chat_id=cid, message_id=mid, reply_markup=bot_keys, parse_mode='HTML'
            )
            return
        # نوع غير معروف — لا نعطي نقاط
        _cb_alert(call, '❌ نوع المهمة غير مدعوم', show_alert=True)
        return

    if data.startswith('task_verify_'):
        task_id = data.replace('task_verify_', '')
        tasks_list = db.get("tasks_list") or []
        target_task = None
        for t in tasks_list:
            if t.get("id") == task_id:
                target_task = t
                break
        if not target_task:
            _cb_alert(call, '❌ المهمة غير موجودة', show_alert=True)
            return
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        completed_key = f"user_{cid}_tasks_{today}"
        completed = db.get(completed_key) or []
        if task_id in completed:
            _cb_alert(call, '✅ لقد أكملت هذه المهمة مسبقاً!', show_alert=True)
            return
        task_type   = target_task.get("type", "")
        task_target = target_task.get("target", "").strip()
        reward      = int(target_task.get("reward", 0))
        success     = False

        if task_type in ("channel_join", "channel"):
            try:
                member = bot.get_chat_member(chat_id=task_target, user_id=cid)
                if str(member.status).lower() in ['member', 'administrator', 'creator']:
                    success = True
            except Exception as _e:
                print(f'[task_verify] channel check error: {_e}')

        elif task_type in ("bot_start", "bot"):
            _bot_task_key   = f'bot_task_done_{task_id}_{cid}'
            _bot_task_first = f'bot_task_first_{task_id}_{cid}'
            if db.exists(_bot_task_key) and db.exists(_bot_task_first):
                success = True
            else:
                success = False

        if success:
            completed.append(task_id)
            db.set(completed_key, completed)
            info = get(cid)
            info["coins"] = int(info.get("coins", 0)) + reward
            set_user(cid, info)
            _cb_alert(call, f'✅ تم إكمال المهمة! +{reward:,} نقطة', show_alert=True)
            back_keys = mk(row_width=1)
            back_keys.add(btn('🔙 رجوع للمهام', callback_data='tasks', color='blue'))
            bot.edit_message_text(
                text=(
                    f'✅ <b>تم إكمال المهمة بنجاح!</b>\n\n'
                    f'💰 حصلت على <b>+{reward:,} نقطة</b>\n'
                    f'💳 رصيدك الآن: <b>{int(info["coins"]):,} نقطة</b>'
                ),
                chat_id=cid, message_id=mid, reply_markup=back_keys, parse_mode='HTML'
            )
        else:
            back_keys = mk(row_width=1)
            back_keys.add(btn('🔄 حاول مرة أخرى', callback_data=f'task_do_{task_id}', color='green'))
            back_keys.add(btn('🔙 رجوع', callback_data='tasks', color='blue'))
            _cb_alert(call, '❌ لم يتم التحقق — تأكد من تنفيذ المطلوب أولاً', show_alert=True)
            bot.edit_message_text(
                text=(
                    f'❌ <b>لم يتم التحقق بعد</b>\n\n'
                    f'تأكد إنك نفّذت المطلوب ثم اضغط «حاول مرة أخرى»'
                ),
                chat_id=cid, message_id=mid, reply_markup=back_keys, parse_mode='HTML'
            )
        return

    # 📋 عرض المهام (من الأزرار)

    if data == 'tasks':
        tasks_list = db.get("tasks_list") or []
        active_tasks = [t for t in tasks_list if t.get("enabled", True)]
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        completed_key = f"user_{cid}_tasks_{today}"
        completed = db.get(completed_key) or []
        txt = '╔══════════════════╗\n'
        txt += '       📋 المهام اليومية\n'
        txt += '╚══════════════════╝\n\n'
        txt += '🎯 أكمل المهام واربح نقاطاً إضافية!\n\n'
        if not active_tasks:
            txt += '❌ لا توجد مهام متاحة حالياً!\n'
            txt += '✨ تابعنا قريباً للحصول على مهام جديدة وجوائز حصرية! 🎁\n'
            txt += '✅ لو محتاج أي حاجة اتواصل مع الدعم الفني.\n'
        else:
            for i, t in enumerate(active_tasks, 1):
                tid = t.get("id", "")
                done = tid in completed
                icon = "✅" if done else "⬜"
                desc = t.get("description", "مهمة")
                reward = int(t.get("reward", 0))
                txt += f'{icon} {i}. {desc}\n'
                txt += f'   💰 المكافأة: {reward:,} نقطة\n\n'
        txt += '━━━━━━━━━━━━━━━━━━━\n'
        txt += '💡 استخدم /guess للعبة التخمين'
        keys = mk(row_width=1)
        for t in active_tasks:
            tid = t.get("id", "")
            done = tid in completed
            if not done:
                keys.add(btn(f'✅ تنفيذ: {t.get("description", "مهمة")}', callback_data=f'task_do_{tid}', color='green'))
        keys.add(btn('رجوع', callback_data='back', color='blue'))
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        return

    # 🔀 ترتيب أزرار القائمة الرئيسية (للأدمن)

    if data == 'adm_menu_order':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        txt, keys = _render_menu_order_panel()
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        return

    if data.startswith('mord_up_') or data.startswith('mord_down_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        is_up = data.startswith('mord_up_')
        item_id = data[len('mord_up_'):] if is_up else data[len('mord_down_'):]
        order = _get_main_menu_order()
        if item_id in order:
            i = order.index(item_id)
            j = i - 1 if is_up else i + 1
            if 0 <= j < len(order):
                order[i], order[j] = order[j], order[i]
                _set_main_menu_order(order)
        try:
            _cb_alert(call)
        except Exception:
            pass
        txt, keys = _render_menu_order_panel()
        try:
            bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        except Exception:
            pass
        return

    if data == 'mord_reset':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        _set_main_menu_order(list(_MAIN_MENU_DEFAULT_ORDER))
        _cb_alert(call, '✅ تم إعادة الترتيب الافتراضي', show_alert=True)
        txt, keys = _render_menu_order_panel()
        try:
            bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        except Exception:
            pass
        return

    if data == 'noop':
        try:
            _cb_alert(call)
        except Exception:
            pass
        return

    # 👁 لوحة إخفاء/إظهار الأزرار (للأدمن)

    if data == 'adm_visibility':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        keys = mk(row_width=1)
        txt = '👁 <b>إخفاء / إظهار الأزرار</b>\n\n'
        txt += '🟢 = ظاهر | 🔴 = مخفي\n\n'
        main_buttons = ['ps', 'collect', 'tasks', 'user_store', 'account', 'guess', 'channels', 'register_accounts', 'leaderboard', 'top_level']
        for cb in main_buttons:
            label = _get_btn_label(cb, default=BTN_KEYS.get(cb, cb))
            visible = _is_btn_visible(cb)
            icon = "🟢" if visible else "🔴"
            txt += f'{icon} {label}\n'
            keys.add(btn(f'{"إخفاء" if visible else "إظهار"} {label}', callback_data=f'vis_toggle_{cb}', color='green' if visible else 'red'))
        keys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_settings', color='blue'))
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        return

    if data.startswith('vis_toggle_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cb_target = data.replace('vis_toggle_', '')
        visible = _toggle_btn_visibility(cb_target)
        _cb_alert(call, f'✅ تم {"إظهار" if visible else "إخفاء"} الزر', show_alert=True)
        # إعادة عرض اللوحة
        keys = mk(row_width=1)
        txt = '👁 <b>إخفاء / إظهار الأزرار</b>\n\n🟢 = ظاهر | 🔴 = مخفي\n\n'
        main_buttons = ['ps', 'collect', 'tasks', 'user_store', 'account', 'guess', 'channels', 'register_accounts', 'leaderboard', 'top_level']
        for cb in main_buttons:
            label = _get_btn_label(cb, default=BTN_KEYS.get(cb, cb))
            vis = _is_btn_visible(cb)
            icon = "🟢" if vis else "🔴"
            txt += f'{icon} {label}\n'
            keys.add(btn(f'{"إخفاء" if vis else "إظهار"} {label}', callback_data=f'vis_toggle_{cb}', color='green' if vis else 'red'))
        keys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_settings', color='blue'))
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        return

    # 🎮 إعدادات الألعاب (للأدمن)

    if data == 'adm_games_settings':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        gp = int(db.get("guess_prize") or 500)
        xp = int(db.get("xo_prize") or 300)
        wp = int(db.get("word_prize") or 200)
        keys = mk(row_width=1)
        keys.add(btn(f'🎯 تخمين — جائزة ({gp})', callback_data='adm_set_guess_prize', color='green'))
        keys.add(btn(f'❌ XO — جائزة ({xp})', callback_data='adm_set_xo_prize', color='green'))
        keys.add(btn(f'🔤 كلمة — جائزة ({wp})', callback_data='adm_set_word_prize', color='green'))
        keys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_settings', color='blue'))
        bot.edit_message_text(
            text='🎮 <b>إعدادات الألعاب</b>\n\n🆓 الألعاب مجانية — كل ساعة\n\nعدّل الجوائز:',
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML'
        )
        return

    for _gs_key, _gs_label in [
        ('adm_set_guess_prize', 'guess_prize'),
        ('adm_set_xo_prize', 'xo_prize'),
        ('adm_set_word_prize', 'word_prize'),
    ]:
        if data == _gs_key:
            if cid not in (db.get("admins") or []) and cid != sudo:
                return
            db.set(f"_adm_pending_{cid}", _gs_label)
            keys = mk(row_width=1)
            keys.add(btn('🔙 إلغاء', callback_data='adm_games_settings', color='red'))
            bot.edit_message_text(
                text=f'🏆 <b>تغيير جائزة {_gs_label}</b>\n\nأرسل القيمة الجديدة (رقم):',
                chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML'
            )
            bot.register_next_step_handler_by_chat_id(cid, _handle_set_game_value)
            return

    # 🏪 إعدادات المتجر (للأدمن)

    if data == 'adm_market_settings':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        market_enabled = db.get("market_enabled")
        if market_enabled is None:
            market_enabled = True
        fee = int(db.get("market_fee") or 5)
        listings = db.get("market_listings") or []
        active = len([l for l in listings if l.get("status") == "active"])
        sold = len([l for l in listings if l.get("status") == "sold"])
        keys = mk(row_width=1)
        status_btn = '🟢 تفعيل' if not market_enabled else '🔴 تعطيل'
        keys.add(btn(f'{status_btn} المتجر', callback_data='mkt_toggle', color='green' if not market_enabled else 'red'))
        keys.add(btn('💰 تغيير نسبة العمولة', callback_data='mkt_set_fee', color='blue'))
        keys.add(btn('📊 إحصائيات المتجر', callback_data='mkt_stats', color='blue'))
        keys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_settings', color='blue'))
        bot.edit_message_text(
            text=f'🏪 <b>إعدادات المتجر</b>\n\n'
                 f'🟢 الحالة: {"مفعل" if market_enabled else "معطل"}\n'
                 f'💰 العمولة: {fee}%\n'
                 f'📦 إعلانات نشطة: {active}\n'
                 f'✅ تم بيعها: {sold}\n'
                 f'━━���━━━━━━━━━━━━━━━━',
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML'
        )
        return

    if data == 'mkt_toggle':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        current = db.get("market_enabled")
        if current is None:
            current = True
        db.set("market_enabled", not current)
        _cb_alert(call, f'✅ تم {"تعطيل" if current else "تفعيل"} المتجر', show_alert=True)
        # فتح إعدادات المتجر
        market_enabled = db.get("market_enabled")
        if market_enabled is None:
            market_enabled = True
        fee = int(db.get("market_fee") or 5)
        listings = db.get("market_listings") or []
        active = len([l for l in listings if l.get("status") == "active"])
        sold = len([l for l in listings if l.get("status") == "sold"])
        keys = mk(row_width=1)
        status_btn = '🟢 تفعيل' if not market_enabled else '🔴 تعطيل'
        keys.add(btn(f'{status_btn} المتجر', callback_data='mkt_toggle', color='green' if not market_enabled else 'red'))
        keys.add(btn('💰 تغيير نسبة العمولة', callback_data='mkt_set_fee', color='blue'))
        keys.add(btn('📊 إحصائيات المتجر', callback_data='mkt_stats', color='blue'))
        keys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_settings', color='blue'))
        bot.edit_message_text(
            text=f'🏪 <b>إعدادات المتجر</b>\n\n🟢 الحالة: {"مفعل" if market_enabled else "معطل"}\n💰 العمولة: {fee}%\n📦 إعلانات نشطة: {active}\n✅ تم بيعها: {sold}',
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML'
        )
        return

    if data == 'mkt_set_fee':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        keys = mk(row_width=1)
        keys.add(btn('🔙 إلغاء', callback_data='adm_market_settings', color='red'))
        bot.edit_message_text(
            text='💰 <b>تغيير نسبة العمولة</b>\n\n'
                 'أرسل النسبة المئوية (رقم فقط):\n'
                 'مثال: 5 (يعني 5%)',
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML'
        )
        bot.register_next_step_handler_by_chat_id(cid, _handle_set_market_fee)
        return

    if data == 'mkt_stats':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        listings = db.get("market_listings") or []
        active = [l for l in listings if l.get("status") == "active"]
        sold = [l for l in listings if l.get("status") == "sold"]
        total_sales = sum(int(l.get("price", 0)) for l in sold)
        total_fees = sum(int(int(l.get("price", 0)) * int(db.get("market_fee") or 5) / 100) for l in sold)
        keys = mk(row_width=1)
        keys.add(btn('🔙 رجوع للإعدادات', callback_data='adm_market_settings', color='blue'))
        bot.edit_message_text(
            text=f'📊 <b>إحصائيات المتجر</b>\n\n'
                 f'📦 إجمالي الإعلانات: {len(listings)}\n'
                 f'🟢 نشطة: {len(active)}\n'
                 f'✅ مباعة: {len(sold)}\n'
                 f'💰 إجمالي المبيعات: {total_sales:,} نقطة\n'
                 f'⚖️ إجمالي العمولات: {total_fees:,} نقطة',
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML'
        )
        return

    # 📋 إدارة المهام (للأدمن)

    if data == 'adm_tasks_panel':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        tasks_list = db.get("tasks_list") or []
        keys = mk(row_width=1)
        keys.add(btn('➕ إضافة مهمة', callback_data='adm_task_add', color='green'))
        txt = '📋 <b>إدارة المهام اليومية</b>\n\n'
        if not tasks_list:
            txt += '📭 لا توجد مهام مضافة بعد.\n'
        else:
            for i, t in enumerate(tasks_list, 1):
                tid = t.get("id", "?")
                desc = t.get("description", "مهمة")
                reward = int(t.get("reward", 0))
                enabled = t.get("enabled", True)
                icon = "🟢" if enabled else "🔴"
                txt += f'{icon} {i}. {desc} — {reward:,} نقطة\n'
                keys.add(btn(f'{"تعطيل" if enabled else "تفعيل"} {desc}', callback_data=f'task_toggle_{tid}', color='red' if enabled else 'green'))
                keys.add(btn(f'🗑️ حذف {desc}', callback_data=f'task_del_{tid}', color='red'))
        keys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_tasks', color='blue'))
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        return

    if data == 'adm_task_add':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        pending_admin_action[cid] = {"action": "add_task", "step": "type"}
        keys = mk(row_width=1)
        keys.add(btn('📢 انضمام قناة', callback_data='adm_task_type_channel', color='green'))
        keys.add(btn('🤖 تشغيل البوت', callback_data='adm_task_type_bot', color='blue'))
        keys.add(btn('🔙 إلغاء', callback_data='adm_tasks_panel', color='red'))
        bot.edit_message_text(
            text='📋 <b>إضافة مهمة جديدة</b>\n\nاختر نوع المهمة:',
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML'
        )
        return

    if data.startswith('adm_task_type_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        task_type = data.replace('adm_task_type_', '')
        pending_admin_action[cid] = {"action": "add_task", "step": "target", "type": task_type}
        keys = mk(row_width=1)
        keys.add(btn('🔙 إلغاء', callback_data='adm_tasks_panel', color='red'))
        bot.edit_message_text(
            text='📋 <b>إضافة مهمة جديدة</b>\n\n'
                 'أرسل معرف الهدف:\n'
                 '- للقناة: أرسل معرف القناة (مثال: @mychannel)\n'
                 '- للبوت: أرسل معرف البوت (مثال: @mybot)',
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML'
        )
        bot.register_next_step_handler_by_chat_id(cid, _handle_admin_task_step)
        return

    if data.startswith('task_toggle_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        task_id = data.replace('task_toggle_', '')
        tasks_list = db.get("tasks_list") or []
        for t in tasks_list:
            if t.get("id") == task_id:
                t["enabled"] = not t.get("enabled", True)
                break
        db.set("tasks_list", tasks_list)
        _cb_alert(call, '✅ تم تبديل حالة المهمة', show_alert=True)
        # إعادة عرض لوحة المهام
        tasks_list = db.get("tasks_list") or []
        keys = mk(row_width=1)
        keys.add(btn('➕ إضافة مهمة', callback_data='adm_task_add', color='green'))
        txt = '📋 <b>إدارة المهام اليومية</b>\n\n'
        if not tasks_list:
            txt += '📭 لا توجد مهام مضافة بعد.\n'
        else:
            for i, t in enumerate(tasks_list, 1):
                tid = t.get("id", "?")
                desc = t.get("description", "مهمة")
                reward = int(t.get("reward", 0))
                enabled = t.get("enabled", True)
                icon = "🟢" if enabled else "🔴"
                txt += f'{icon} {i}. {desc} — {reward:,} نقطة\n'
                keys.add(btn(f'{"تعطيل" if enabled else "تفعيل"} {desc}', callback_data=f'task_toggle_{tid}', color='red' if enabled else 'green'))
                keys.add(btn(f'🗑️ حذف {desc}', callback_data=f'task_del_{tid}', color='red'))
        keys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_tasks', color='blue'))
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        return

    if data.startswith('task_del_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        task_id = data.replace('task_del_', '')
        tasks_list = db.get("tasks_list") or []
        tasks_list = [t for t in tasks_list if t.get("id") != task_id]
        db.set("tasks_list", tasks_list)
        _cb_alert(call, '✅ تم حذف المهمة', show_alert=True)
        # إعادة عرض لوحة المهام
        tasks_list = db.get("tasks_list") or []
        keys = mk(row_width=1)
        keys.add(btn('➕ إضافة مهمة', callback_data='adm_task_add', color='green'))
        txt = '📋 <b>إدارة المهام اليومية</b>\n\n'
        if not tasks_list:
            txt += '📭 لا توجد مهام مضافة بعد.\n'
        else:
            for i, t in enumerate(tasks_list, 1):
                tid = t.get("id", "?")
                desc = t.get("description", "مهمة")
                reward = int(t.get("reward", 0))
                enabled = t.get("enabled", True)
                icon = "🟢" if enabled else "🔴"
                txt += f'{icon} {i}. {desc} — {reward:,} نقطة\n'
                keys.add(btn(f'{"تعطيل" if enabled else "تفع��ل"} {desc}', callback_data=f'task_toggle_{tid}', color='red' if enabled else 'green'))
                keys.add(btn(f'🗑️ حذف {desc}', callback_data=f'task_del_{tid}', color='red'))
        keys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_tasks', color='blue'))
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        return

    if data == 'register_accounts':
        _gu = _GIVE_BOT_USERNAME or "nnnlllq1_bot"
        if not _gu:
            try:
                import telebot as _tb_reg
                _gu = _tb_reg.TeleBot(GIVE_BOT_TOKEN).get_me().username or "nnnlllq1_bot"
            except:
                _gu = "nnnlllq1_bot"
        _give_bot_link = f'https://t.me/{_gu}?start=earn_{cid}'
        _my_submitted = int(db.get(f'user_{cid}_rent_submitted') or 0)
        _rent_pts_val = int(db.get("rent_reward")) if db.exists("rent_reward") else 100
        reg_keys = mk(row_width=1)
        reg_keys.add(btn('📲 تسجيل حساب الآن', url=_give_bot_link, color='green'))
        reg_keys.add(btn('🏆 توب 5 تسجيل الحسابات', callback_data='rent_top', color='red'))
        reg_keys.add(btn('رجوع', callback_data='back', color='blue'))
        reg_txt = (
            "╔══════════════════╗\n"
            "   📲 تسجيل حساباتك للتحكم فيها\n"
            "╚══════════════════╝\n\n"
            f"📱 <b>حساباتك المسجلة :</b> {_my_submitted} حساب\n"
            f"💰 <b>نقاط كل حساب :</b> {_rent_pts_val:,} نقطة\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "✅ تتبع حساباتك المسجلة\n"
            "⚡ إدارة سهلة وسريعة\n"
            "🎁 احصل على نقاط مكافأة عند التسجيل\n"
            "🛡️ حماية كاملة لبياناتك\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "📌 اضغط الزر أدناه لبدء التسجيل\n"
            "━━━━━━━━━━━━━━━━━━━"
        )
        bot.edit_message_text(text=reg_txt, chat_id=cid, message_id=mid, reply_markup=reg_keys, parse_mode='HTML')
        return

    if data == 'bot_channel_btn':
        ch_username = db.get("bot_channel_username") if db.exists("bot_channel_username") else ""
        keys = mk(row_width=1)
        if ch_username:
            keys.add(btn('📢 انضم للقناة', url=f'https://t.me/{ch_username.lstrip("@")}', color='blue'))
        keys.add(btn('رجوع', callback_data='back', color='blue'))
        ch_desc = db.get("bot_channel_desc") if db.exists("bot_channel_desc") else "قناة البوت الرسمية"
        bot.edit_message_text(
            text=f"📢 <b>قناة البوت</b>\n\n{ch_desc}",
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML'
        )
        return

    if data == 'channels':
        chs = db.get('channels_list') if db.exists('channels_list') else []
        keys = mk(row_width=1)
        if chs:
            for ch in chs:
                un  = ch.get('username', '').lstrip('@')
                dsc = ch.get('desc', '') or un
                if un:
                    keys.add(btn(f'📢 {dsc}', url=f'https://t.me/{un}', color='blue'))
        keys.add(btn('رجوع', callback_data='back', color='blue'))
        ch_count = len(chs)
        desc_txt = '\n'.join(f"• @{ch.get('username','').lstrip('@')}" + (f" — {ch.get('desc','')}" if ch.get('desc') else '') for ch in chs) if chs else 'لا توجد قنوات مضافة بعد'
        bot.edit_message_text(
            text=f"📢 <b>قنوات البوت</b>\n\n{desc_txt}",
            chat_id=cid, message_id=mid,
            reply_markup=keys, parse_mode='HTML'
        )
        return

    if data == 'stats':
        today = datetime.datetime.now().strftime("%Y-%m-%d")


        good = 0
        fake_count = 0
        users = db.keys('user_%')
        for ix in users:
            try:
                if db.get(ix[0]) and db.get(ix[0]).get('id'):
                    good += 1
                    _uid_str = ix[0].replace('user_', '')
                    if db.exists(f'is_fake_{_uid_str}'):
                        fake_count += 1
            except:
                continue


        sales_today = db.get(f'daily_sales_{today}') or {'orders': 0, 'points': 0}
        orders_today = sales_today.get('orders', 0)
        points_today = sales_today.get('points', 0)


        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        sales_yesterday = db.get(f'daily_sales_{yesterday}') or {'orders': 0, 'points': 0}
        orders_yesterday = sales_yesterday.get('orders', 0)
        points_yesterday = sales_yesterday.get('points', 0)


        svc_stats = db.get(f'svc_stats_{today}') or {}
        top_services = sorted(svc_stats.items(), key=lambda x: x[1], reverse=True)[:5]
        top_txt = ''
        medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
        for i, (svc, cnt) in enumerate(top_services):
            top_txt += f'\n  {medals[i]} {svc} — {cnt} طلب'
        if not top_txt:
            top_txt = '\n  لا توجد بيانات اليوم'


        total_orders = db.get('orders') or 185443


        new_today = 0
        try:
            all_log = db.get(f'new_users_{today}') or 0
            new_today = int(all_log)
        except:
            pass

        stats_text = (
            f'📊 <b>لوحة الإحصائيات</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'👥 <b>إجمالي الأعضاء :</b> {good:,}\n'
            f'👤 <b>أعضاء حقيقيون :</b> {good - fake_count:,}\n'
            f'🤖 <b>حسابات وهمية :</b> {fake_count:,}\n'
            f'🆕 <b>أعضاء جدد اليوم :</b> {new_today:,}\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'📦 <b>طلبات اليوم ({today}) :</b>\n'
            f'  • عدد الطلبات : {orders_today:,}\n'
            f'  • نقاط مُنفق�� : {points_today:,}\n\n'
            f'📦 <b>طلبات الأمس :</b>\n'
            f'  • عدد الطلبات : {orders_yesterday:,}\n'
            f'  • نقاط مُنفقة : {points_yesterday:,}\n\n'
            f'🔢 <b>إج��الي الطلبات الكلي :</b> {total_orders:,}\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'🏆 <b>الخدمات الأكثر طلباً اليوم :</b>'
            f'{top_txt}\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'🕐 آخر تحديث : {datetime.datetime.now().strftime("%H:%M:%S")}'
        )
        stats_kb = mk(row_width=1)
        stats_kb.add(btn('🔄 تحديث', callback_data='stats', color='blue'))
        stats_kb.add(btn('رجوع', callback_data='admin', color='red'))
        bot.edit_message_text(text=stats_text, chat_id=cid, message_id=mid,
                              reply_markup=stats_kb, parse_mode='HTML')
        return
    d = db.get('admins')
    user_id = call.from_user.id
    if data in ('dailygift', 'daily_gift_claim'):
        _do_claim_daily_gift(call)
        return


    if data == 'wheel':
        remaining = check_wheel(user_id)
        keys_w = mk(row_width=1)
        if remaining is not None:
            keys_w.add(btn('رجوع', callback_data='collect'))
            _wheel_arts = _wheel_art_with_prizes(get_wheel_prizes())
            bot.edit_message_text(
                chat_id=cid, message_id=mid,
                text=(
                    "🎡 <b>عجلة الحظ</b>\n"
                    "━━━━━━━━━━━━━━\n\n"
                    f"<code>{_wheel_arts}</code>\n\n"
                    f"⏳ لقد استخدمت العجلة مؤخراً!\n\n"
                    f"⏱ الوقت المتبقي: <b>{fmt_remaining(remaining)}</b>\n\n"
                    "🔄 تُجدَّد كل <b>24 ساعة</b>"
                ),
                parse_mode='HTML',
                reply_markup=keys_w
            )
        else:
            # أنيميشن الدوران
            frames = [
                "🎡 ━━━━━━━━━━━━━━\n┃ 🌟 💫 ⚡ 🔥 💎 👑 🏆 ┃\n━━━━━━━━━━━━━━\n\n⏳ <b>العجلة تدور...</b>",
                "🎡 ━━━━━━━━━━━━━━\n┃ 💫 ⚡ 🔥 💎 👑 🏆 🌟 ┃\n━━━━━━━━━━━━━━\n\n⏳ <b>العجلة تدور...</b>",
                "🎡 ━━━━━━━━━━━━━━\n┃ ⚡ 🔥 💎 👑 🏆 🌟 💫 ┃\n━━━━━━━━━━━━━━\n\n⏳ <b>العجلة تدور...</b>",
                "🎡 ━━━━━━━━━━━━━━\n┃ 🔥 💎 👑 🏆 🌟 💫 ⚡ ┃\n━━━━━━━━━━━━━━\n\n🎲 <b>على وشك التوقف...</b>",
            ]
            msg = bot.edit_message_text(chat_id=cid, message_id=mid, text=frames[0], parse_mode='HTML')
            for frame in frames[1:]:
                time.sleep(0.7)
                try:
                    bot.edit_message_text(chat_id=cid, message_id=msg.message_id, text=frame, parse_mode='HTML')
                except Exception:
                    pass

            prize = spin_wheel()
            pts   = prize["points"]
            label = prize["label"]

            info = db.get(f'user_{user_id}')
            if not info:
                info = {'id': user_id, 'coins': 0, 'premium': False, 'users': []}
                set_user(user_id, info)
            info['coins'] = int(info.get('coins', 0)) + pts
            db.set(f'user_{user_id}', info)
            new_bal = info['coins']

            prizes_list = "\n".join(
                f"{'◀️' if p['label'] == label else '▫️'} {p['label']}"
                for p in get_wheel_prizes()
            )

            keys_w.add(btn('رجوع', callback_data='collect'))
            time.sleep(0.4)
            bot.edit_message_text(
                chat_id=cid, message_id=msg.message_id,
                text=(
                    "🎡 <b>عجلة الحظ</b>\n"
                    "━━━━━━━━━━━━━━\n\n"
                    f"🎉 <b>مبروك! فزت بـ {label}</b>\n\n"
                    f"💰 رصيدك الجديد: <b>{new_bal:,} نقطة</b>\n\n"
                    "━━━━━━━━━━━━━━\n"
                    "📋 <b>جدول الجوائز:</b>\n"
                    f"{prizes_list}\n"
                    "━━━━━━━━━━━━━━\n"
                    "⏱ العجلة تُجدَّد بعد <b>24 ساعة</b>"
                ),
                parse_mode='HTML',
                reply_markup=keys_w
            )
        return
    if data == 'numbers':
        d = len(db.get('accounts') or [])
        _num_kb = mk(row_width=1)
        _num_kb.add(btn('🔙 رجوع للوحة الأدمن', callback_data='adm_cat_users', color='red'))
        bot.edit_message_text(
            chat_id=cid, message_id=mid,
            text=f'📱 <b>عدد أرقام البوت</b>\n\n🔢 الأرقام المسجلة: <b>{d}</b>',
            reply_markup=_num_kb, parse_mode='HTML'
        )
        return
    if data == '11':
        total_orders = db.get('orders')
        total_orders = int(total_orders) if total_orders is not None else 185443
        _cb_alert(call, text=_L(cid, f'🔢 إجمالي الطلبات: {total_orders:,}', f'🔢 Total orders: {total_orders:,}'), show_alert=True)
        return
    if data == 'addpoints':
        x = bot.edit_message_text(text='• ارسل ايدي الشخص المراد اضافة النقاط له', chat_id=cid, message_id=mid, reply_markup=bk_cancel_adm)
        bot.register_next_step_handler(x, addpoints)
    if data == 'send':
        if cid in (db.get("admins") or []) or cid == sudo:
            x = bot.edit_message_text(text='• ارسل ايدي الشخص المراد تحويل النقاط له.', chat_id=cid, message_id=mid, reply_markup=bk_cancel_adm)
            bot.register_next_step_handler(x, send)
        else:
            keys = mk(row_width=2)
            keys.add(btn('رجوع', callback_data='back'))
            bot.edit_message_text(text='• عذرا ، التحويل مقفل للاعضاء ، يمكن للادمنية فقط تحويل النقاط', chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")
    if data == 'addadmin':
        x = bot.edit_message_text(text=f'• ارسل ايدي العضو المراد اضافته ادمن بالبوت ', chat_id=cid, message_id=mid, reply_markup=bk_cancel_adm)
        bot.register_next_step_handler(x, adminss, 'add')
    if data == 'addvip':
        x = bot.edit_message_text(text=f'• ارسل ايدي العضو المراد تفعيل vip له', chat_id=cid, message_id=mid, reply_markup=bk_cancel_adm)
        bot.register_next_step_handler(x, vipp, 'add')
    if data == 'lesvip':
        x = bot.edit_message_text(text=f'• ارسل ايدي العضو المراد ازالة vip منه', chat_id=cid, message_id=mid, reply_markup=bk_cancel_adm)
        bot.register_next_step_handler(x, vipp, 'les')
    if data == 'deladmin':
        x = bot.edit_message_text(text=f'• ارسل ايدي العضو المراد ازالته من الادمن', chat_id=cid, message_id=mid, reply_markup=bk_cancel_adm)
        bot.register_next_step_handler(x, adminss, 'delete')
    if data == 'banone':
        if cid in (db.get("admins") or []) or cid == sudo:
            x = bot.edit_message_text(text=f'• ارسل ايدي العضو لمراد حظرة من استخدام البوت', chat_id=cid, message_id=mid, reply_markup=bk_cancel_adm)
            bot.register_next_step_handler(x, banned, 'ban')
    if data == 'unbanone':
        if cid in (db.get("admins") or []) or cid == sudo:
            x = bot.edit_message_text(text=f'• ارسل ايدي العضو المراد الغاء حظره من استخدام البوت ', chat_id=cid, message_id=mid, reply_markup=bk_cancel_adm)
            bot.register_next_step_handler(x, banned, 'unban')
    if data == 'cast':
        if cid in (db.get("admins") or []) or cid == sudo:
            cast_channels = db.get('cast_channels') or []

            try:
                total_users = sum(
                    1 for k, v in db._cache.items()
                    if k.startswith('user_') and isinstance(v, dict) and v.get('id')
                )
            except Exception:
                total_users = 0
            ckeys = mk(row_width=1)
            ckeys.add(btn('📝 إذاعة نص/صورة/فيديو', callback_data='cast_msg', color='blue'))
            ckeys.add(btn('🔗 إذاعة مع زر رابط', callback_data='cast_link', color='blue'))
            ckeys.add(btn('➕ إضافة قناة يدوياً', callback_data='cast_add_ch', color='green'))
            ckeys.add(btn('📊 القنوات المكتشفة', callback_data='cast_discovered', color='green'))
            ckeys.add(btn('🔍 مسح وإضافة القنوات تلقائياً', callback_data='cast_auto_scan', color='blue'))
            ckeys.add(btn('رجوع', callback_data='adm_cat_general', color='red'))
            bot.edit_message_text(
                chat_id=cid, message_id=mid,
                text=(
                    f'📡 *نظام الإذاعة المتطور*\n'
                    f'━━━━━━━━━━━━━━━━━━━\n'
                    f'👥 المستخدمون: *{total_users:,}*\n'
                    f'📢 القنوات المتاحة للإذاعة: *{len(cast_channels)}*\n\n'
                    f'اختر نوع الإذاعة أو أضف قنوات:'
                ),
                reply_markup=ckeys, parse_mode='Markdown'
            )
            return
    if data == 'cast_msg':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        x = bot.edit_message_text(
            text='📝 أرسل الرسالة التي تريد إذاعتها (نص، صورة، فيديو، ملصق...):',
            chat_id=cid, message_id=mid
        , reply_markup=bk_cancel_adm)
        bot.register_next_step_handler(x, casting)
    if data == 'cast_link':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        x = bot.edit_message_text(
            text='🔗 أرسل الرسالة التي تريد إذاعتها مع زر رابط:',
            chat_id=cid, message_id=mid
        , reply_markup=bk_cancel_adm)
        bot.register_next_step_handler(x, casting_with_link)
    if data == 'cast_add_ch':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        x = bot.edit_message_text(
            text='➕ أرسل معرف القناة أو يوزرها (مثال: @channel أو -1001234567890):',
            chat_id=cid, message_id=mid
        , reply_markup=bk_cancel_adm)
        bot.register_next_step_handler(x, _cast_add_channel_manual)
    if data == 'cast_discovered':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cast_channels = db.get('cast_channels') or []
        if not cast_channels:
            ckeys = mk(row_width=1)
            ckeys.add(btn('🔍 مسح تلقائي', callback_data='cast_auto_scan', color='green'))
            ckeys.add(btn('➕ إضافة يدوي', callback_data='cast_add_ch', color='blue'))
            ckeys.add(btn('رجوع', callback_data='cast', color='red'))
            bot.edit_message_text(text='📊 لا توجد قنوات مضافة بعد.', chat_id=cid, message_id=mid, reply_markup=ckeys)
            return
        txt = f'📊 *القنوات المتاحة للإذاعة ({len(cast_channels)}):*\n\n'
        ckeys = mk(row_width=1)
        for i, ch in enumerate(cast_channels[:20], 1):
            txt += f'{i}. `{ch}`\n'
            ckeys.add(btn(f'🗑 حذف {ch}', callback_data=f'cast_del_ch_{ch}', color='red'))
        ckeys.add(btn('رجوع', callback_data='cast', color='blue'))
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=ckeys, parse_mode='Markdown')
    if data.startswith('cast_del_ch_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        ch_to_del = data.replace('cast_del_ch_', '')
        cast_channels = db.get('cast_channels') or []
        if ch_to_del in cast_channels:
            cast_channels.remove(ch_to_del)
            db.set('cast_channels', cast_channels)
        ckeys = mk(row_width=1)
        ckeys.add(btn('🔙 رجوع ��لقنوات', callback_data='cast_discovered', color='blue'))
        bot.edit_message_text(text=f'✅ تم حذف القناة: `{ch_to_del}`', chat_id=cid, message_id=mid, reply_markup=ckeys, parse_mode='Markdown')
    if data == 'cast_auto_scan':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        accounts = db.get('accounts') or []
        if not accounts:
            _cb_alert(call, text='❌ لا توجد حسابات في البوت', show_alert=True)
            return
        bot.edit_message_text(text='🔍 جاري مسح القنوات تلقائياً من الحسابات...', chat_id=cid, message_id=mid)
        found = set(db.get('cast_channels') or [])
        import asyncio as _aio
        async def _scan_all():
            for acc in accounts[:5]:  # نمسح أول 5 حسابات
                try:
                    c = Client('::memory::', in_memory=True, api_hash=API_HASH, api_id=API_ID,
                               no_updates=True, session_string=acc['s'])
                    await c.start()
                    async for dialog in c.get_dialogs():
                        if str(dialog.chat.type) in ['ChatType.CHANNEL']:
                            try:
                                ch_id = str(dialog.chat.id)
                                found.add(ch_id)
                            except: pass
                    await c.stop()
                except: pass
        _pyro_run(_scan_all())
        new_list = list(found)
        db.set('cast_channels', new_list)
        ckeys = mk(row_width=1)
        ckeys.add(btn('📊 عرض القنوات', callback_data='cast_discovered', color='green'))
        ckeys.add(btn('رجوع', callback_data='cast', color='blue'))
        bot.edit_message_text(
            text=f'✅ اكتمل المسح!\n📢 عدد القنوات المكتشفة: *{len(new_list)}*',
            chat_id=cid, message_id=mid, reply_markup=ckeys, parse_mode='Markdown'
        )
    if data == 'lespoints':
        x = bot.edit_message_text(text='• ارسل ايدي الشخص المراد تخصم النقاط منه', chat_id=cid, message_id=mid, reply_markup=bk_cancel_adm)
        bot.register_next_step_handler(x, lespoints)
    if data == 'back':
        bot.clear_step_handler_by_chat_id(cid)  # إلغاء أي خطوة معلّقة
        a = ['leave', 'member', 'vote', 'spam', 'userbot', 'forward', 'linkbot', 'view', 'poll', 'react', 'reacts', 'react_special', 'votes_fsub']
        for temp in a:
            db.delete(f'{temp}_{user_id}_proccess')
        keys = _build_main_keys(user_id)
        bot.edit_message_text(text=get_welcome_msg(user_id), chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")
    if data == 'getinfo':
        x = bot.edit_message_text(text='• ارسل ايدي الشخص الذي تريد معرفة معلوماته', chat_id=cid, message_id=mid, reply_markup=bk_cancel_adm)
        bot.register_next_step_handler(x, get_info)
    if data == 'lvall':
        keys = mk(row_width=2)
        btn2 = btn('تاكيد المغادرة', callback_data='lvallc')
        btn3 = btn('الغاء', callback_data='cancel')
        keys.add(btn2)
        keys.add(btn3)
        bot.edit_message_text(text='هل انت متاكد من مغادرة كل القنوات والمجموعات ؟', chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")
    if data == 'ps':
        keys = mk(row_width=1)
        btn_normal = btn('🛍️ الخدمات العادية',    callback_data='normal',         color='blue')
        btn_vip    = btn('👑 الخدمات الـ ViP',     callback_data='vips',           color='red')
        btn_free_r = btn('الخدمات المجانية FREE',    callback_data='free_reactions',  color='green')
        keys.add(btn_normal)
        keys.add(btn_vip)
        keys.add(btn_free_r)
        keys.add(btn('رجوع', callback_data='back', color='blue'))
        bot.edit_message_text(
            text=(
                '🛒 <b>قسم الخدمات</b>\n\n'
                '• 🛍️ <b>الخدمات العادية</b> — خدمات مدفوعة بالنقاط للجميع\n'
                '• 👑 <b>الخدمات الـ ViP</b> — خدمات حصرية للمشتركين\n'
                '• <b>الخدمات المجانية FREE</b> — تفاعلات ومشاهدات مجاناً بدون نقاط\n\n'
                'اختر القسم الذي تريده 👇'
            ),
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML"
        )
        return
    if data == 'normal':

        keys = mk(row_width=1)
        if svc_enabled('member'):
            keys.add(btn('رشق أعضاء مجانية', callback_data='free_member', color='green'))
        if svc_enabled('votes'):
            keys.add(btn('تصويت مسابقات', callback_data='votes', color='blue'))
        # تفاعلات اختياري وعشوائي جنب بعض
        _react_row = []
        if svc_enabled('react'):
            _react_row.append(btn('تفاعلات اختياري', callback_data='react', color='green'))
        if svc_enabled('reacts'):
            _react_row.append(btn('تفاعلات عشوائي', callback_data='reacts', color='green'))
        if _react_row:
            keys.row(*_react_row)
        if svc_enabled('react_special'):
            keys.add(btn('رشق ايموجي مميز', callback_data='react_special', color='red'))
        # توجيهات ومشاهدات جنب بعض
        _fwd_row = []
        if svc_enabled('forward'):
            _fwd_row.append(btn('توجيهات منشور', callback_data='forward', color='blue'))
        if svc_enabled('view'):
            _fwd_row.append(btn('مشاهدات', callback_data='view', color='green'))
        if _fwd_row:
            keys.row(*_fwd_row)
        if svc_enabled('poll'):
            keys.add(btn('استفتاء', callback_data='poll', color='blue'))
        if svc_enabled('linkbot'):
            keys.add(btn('روابط دعوة مجانية', callback_data='linkbot', color='green'))
        keys.add(btn('رجوع', callback_data='ps', color='blue'))
        bot.edit_message_text(
            text=(
                '🛍️ <b>الخدمات العادية</b>\n\n'
                '• خدمات مدفوعة بالنقاط متاحة للجميع\n\n'
                'اختر الخدمة التي تريدها 👇'
            ),
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML"
        )
        return
    if data == 'vips':

        keys = mk(row_width=1)

        # صف 1: اعضاء قناة خاصة + اعضاء قناة عامة (جنب بعض)
        row1 = []
        if svc_enabled('membersp'):
            row1.append(btn('🔐 اعضاء قناة خاصة', callback_data='membersp', color='red'))
        if svc_enabled('member'):
            row1.append(btn('👥 اعضاء قناة عامة', callback_data='members', color='green'))
        if row1:
            keys.row(*row1)

        # صف 2: مستخدمين بوت — عرض كامل
        if svc_enabled('userbot'):
            keys.add(btn('🤖 مستخدمين بوت (بدون اشتراك)', callback_data='userbot', color='blue'))

        # صف 3: تعليقات اختياري — عرض كامل
        if svc_enabled('comments'):
            keys.add(btn('💬 تعليقات اختياري كمثال (يستحق)', callback_data='comments', color='green'))

        # صف 4: رابط دعوة باشتراك اجباري — عرض كامل
        if svc_enabled('linkbot2'):
            keys.add(btn('🔗 رابط دعوه باشتراك اجباري (10) للبوتات', callback_data='linkbot2', color='red'))

        # صف 5: تصويت مسابقات اشتراك إجباري — عرض كامل
        if svc_enabled('votes_fsub'):
            keys.add(btn('🏆 تصويت مسابقات اشتراك إجباري', callback_data='votes_fsub', color='green'))

        # صف 6: سبام رسائل — عرض كامل
        if svc_enabled('spam'):
            keys.add(btn('💣 سبام رسائل', callback_data='spams', color='blue'))

        # صف 7: رشق ايموجي مميز — عرض كامل
        if svc_enabled('react_special'):
            keys.add(btn('✨ رشق ايموجي ( مميز )', callback_data='react_special', color='red'))

        keys.add(btn('رجوع', callback_data='ps', color='blue'))
        bot.edit_message_text(
            text=(
                '👑 <b>الخدمات المميزة (VIP)</b>\n\n'
                '• خدمات حصرية للمشتركين VIP فقط\n'
                '• للاشتراك اضغط على زر <b>اشترك في VIP</b>\n\n'
                'اختر الخدمة التي تريدها 👇'
            ),
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML"
        )
        return
    if data == 'free_member':
        if not svc_enabled('member'):
            _cb_alert(call, text='⛔ هذه الخدمة معطّلة حالياً', show_alert=True)
            return
        db.set(f'free_member_{cid}_proccess', True)
        _min = svc_min('free_member')
        _max = svc_max('free_member')
        _price = svc_price('free_member')
        _svc_txt_fm = (
            f'👥 <b>رشق أعضاء قناة عامة</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'💰 السعر : <b>{_price} نقطة / عضو</b>\n'
            f'📉 الحد الأدنى : <b>{_min}</b>\n'
            f'📈 الحد الأقصى : <b>{_max}</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'أرسل الآن العدد الذي تريده (<b>{_min}</b> - <b>{_max}</b>):'
        )
        x = bot.edit_message_text(
            text=_svc_txt_fm,
            reply_markup=_bk_cancel_svc('normal'), chat_id=cid, message_id=mid, parse_mode="HTML"
        )
        bot.register_next_step_handler(x, get_amount, 'free_member')

    if data == 'free_reactions':
        keys = mk(row_width=1)
        keys.add(btn('⚡ تفاعلات مجانية على منشور',        callback_data='free_react_go',   color='green'))
        keys.add(btn('🚀 50 تفاعل + مشاهدات 10 منشورات', callback_data='free_react_plus', color='purple'))
        keys.add(btn('رجوع', callback_data='ps', color='blue'))
        bot.edit_message_text(
            text=(
                '🎁 <b>الخدمات المجانية FREE</b>\n'
                '━━━━━━━━━━━━━━━━━━━\n\n'
                '⚡ <b>تفاعلات مجانية</b>\n'
                '   أرسل رابط منشورك وسنضيف 50 تفاعل مجاناً\n\n'
                '🚀 <b>50 تفاعل + مشاهدات مستقبلية</b>\n'
                '   50 تفاعل على منشورك + مشاهدات تلقائية على 10 منشورات قادمة\n\n'
                '━━━━━━━━━━━━━━━━━━━\n'
                '🎁 لا تحتاج نقاط — مجاناً تماماً\n\n'
                'اختر الخدمة التي تريدها 👇'
            ),
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML"
        )
        return

    if data == 'free_react_go':
        keys = mk(row_width=1)
        keys.add(btn('إلغاء و رجوع', callback_data='free_reactions', color='red'))
        x = bot.edit_message_text(
            text=(
                '⚡ <b>تفاعلات مجانية</b>\n\n'
                '━━━━━━━━━━━━━━━━━━━\n'
                '📎 أرسل الآن رابط المنشور\n'
                '━━━━━━━━━━━━━━━━━━━\n\n'
                '• مثال: https://t.me/channel/123\n'
                '• سيتم إضافة <b>50 تفاعل</b> مجاناً'
            ),
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML"
        )
        bot.register_next_step_handler(x, handle_free_reaction)
        return

    if data == 'free_react_plus':
        keys = mk(row_width=1)
        keys.add(btn('إل��ا���� و رجوع', callback_data='free_reactions', color='red'))
        x = bot.edit_message_text(
            text=(
                '🚀 <b>50 تفاعل + مشاهدات 10 منشورات مستقبلية</b>\n\n'
                '━━━━━━━━━━━━━━━━━━━\n'
                '📎 أرسل الآن رابط المنشور\n'
                '━━━━━━━━━━━━━━━━━━━\n\n'
                '• مثال: https://t.me/channel/123\n'
                '• سيتم إضافة <b>50 تفاعل</b> على المنشور\n'
                '• + <b>مشاهدات تلقائية</b> على أول 10 منشورات قادمة في القناة'
            ),
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML"
        )
        bot.register_next_step_handler(x, handle_free_react_plus)
        return

    if data == 'collect':
        keys = mk(row_width=2)
        btn1    = btn('🎁 الهدية اليومية',  callback_data='dailygift',      color='green')
        btn3    = btn('🌀 رابط الدعوة',      callback_data='share_link',     color='green')
        btn_w   = btn('🎡 عجلة الحظ',        callback_data='wheel',          color='red')
        btn_sell= btn('💸 بيع الأرقام',       callback_data='sell_numbers',   color='green')
        btn_lvl = btn('🏅 TOP LEVEL',         callback_data='top_level',      color='red')
        btn_tasks= btn('📋 المهام اليومية',   callback_data='tasks',          color='green')
        keys.add(btn3, btn1)
        keys.add(btn_w)
        keys.add(btn_tasks)
        keys.add(btn_sell)
        keys.add(btn_lvl)
        keys.add(btn('رجوع', callback_data='back', color='blue'))
        bot.edit_message_text(text='💰 مرحباً بك في قسم تجميع النقاط\n\n• اختر إحدى الطرق التالية لجمع النقاط:', chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")
        return

    if data == 'submit_account':
        _gu = _GIVE_BOT_USERNAME or "nnnlllq1_bot"
        if not _GIVE_BOT_USERNAME:
            try:
                import telebot as _tb
                _gu = _tb.TeleBot(GIVE_BOT_TOKEN).get_me().username or "nnnlllq1_bot"
                _GIVE_BOT_USERNAME = _gu
            except:
                _gu = "nnnlllq1_bot"
        _rent_reward_val = int(db.get("rent_reward")) if db.exists("rent_reward") else 100
        give_link = f'https://t.me/{_gu}?start=earn_{cid}'
        keys = mk(row_width=1)
        keys.add(btn('📱 تسجيل الحساب', url=give_link, color='green'))
        keys.add(btn('🏆 توب 5 تسجيل الحسابات', callback_data='rent_top', color='blue'))
        keys.add(btn('رجوع', callback_data='collect', color='blue'))
        txt = (
            "📱 <b>تسجيل الحسابات مقابل نقاط</b>\n\n"
            "ملاحظه : الحساب مش بيخرج من عندك ولا بيتحظر ولا بيحصل اي حاجه\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"💰 مكافأة تسليم حساب واحد : <b>{_rent_reward_val:,} نقطة</b>\n"
            f"⚠️ خصم لو طلعت الجلسة    : <b>500 نقطة</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            "اضغط على الزر بالأسفل لتسجيل حسابك والحصول على النقاط فور التسليم"
        )
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")
        return

    if data == 'confirm_transfer':
        order = _pending_orders.pop(cid, None)
        if not order or order.get('type') != 'transfer':
            _cb_alert(call, "⚠️ انتهت صلاحية الطلب", show_alert=True)
            return
        uid    = order['uid']
        amount = order['amount']
        name   = order['name']
        from_user = db.get(f'user_{cid}') or {}
        to_user   = db.get(f'user_{uid}')  or {}
        if int(from_user.get('coins', 0)) < amount + 500:
            _cb_alert(call, "❌ نقاطك غير كافية (المبلغ + 500 عمولة)", show_alert=True)
            return
        old_to = int(to_user.get('coins', 0))
        from_user['coins'] = int(from_user.get('coins', 0)) - amount - 500
        to_user['coins']   = old_to + amount
        db.set(f'user_{cid}', from_user)
        db.set(f'user_{uid}', to_user)
        try:
            bot.edit_message_reply_markup(chat_id=cid, message_id=mid, reply_markup=None)
        except: pass
        # إشعار المُستقبِل
        try:
            bot.send_message(uid,
                f"💸 <b>استلمت نقاطاً!</b>\n\n"
                f"👤 من: <code>{cid}</code>\n"
                f"💰 المبلغ: <b>{amount:,} نقطة</b>\n"
                f"💳 رصيدك الآن: <b>{to_user['coins']:,} نقطة</b>",
                parse_mode='HTML'
            )
        except: pass
        # إشعار الأدمن
        try:
            bot.send_message(int(sudo),
                f"💸 تحويل نقاط\n"
                f"من: <code>{cid}</code> → إلى: <code>{uid}</code>\n"
                f"المبلغ: {amount:,} نقطة | العمولة: 500 نقطة",
                parse_mode='HTML'
            )
        except: pass
        # تحديث عد��د التحويلات
        trans = int(db.get(f'user_{cid}_trans') or 0) + 1
        db.set(f'user_{cid}_trans', trans)
        _cb_alert(call, "✅ تم التحويل بنجاح!")
        keys = mk(row_width=1)
        keys.add(btn('🔙 رجوع للقائمة', callback_data='back', color='blue'))
        bot.send_message(cid,
            f"✅ <b>تم التحويل ب��جاح!</b>\n\n"
            f"👤 إلى: {name}\n"
            f"💰 المبلغ المحوّل: <b>{amount:,} نقطة</b>\n"
            f"⚠️ العمولة المخصومة: <b>500 نقطة</b>\n"
            f"💳 رصيدك الآن: <b>{from_user['coins']:,} نقطة</b>",
            reply_markup=keys, parse_mode='HTML'
        )
        return

    if data == 'confirm_order':
        order = _pending_orders.get(cid)
        if not order:
            _cb_alert(call, "⚠️ انتهت صلاحية الطلب أو تم تن��يذه بالفعل", show_alert=True)
            return
        try:
            bot.edit_message_reply_markup(chat_id=cid, message_id=mid, reply_markup=None)
        except: pass
        _cb_alert(call, "⏳ جارٍ تنفيذ الطلب...")
        def_execute_order(cid, call)
        return

    if data == 'cancel_order':
        _pending_orders.pop(cid, None)
        try:
            bot.edit_message_reply_markup(chat_id=cid, message_id=mid, reply_markup=None)
        except: pass
        _cb_alert(call, "✅ تم إلغاء الطلب", show_alert=False)
        keys = mk(row_width=1)
        keys.add(btn('🔙 رجوع للقائمة', callback_data='back', color='blue'))
        bot.send_message(cid, "❌ <b>تم إلغاء الطلب</b>", reply_markup=keys, parse_mode='HTML')
        return

    if data == 'rent_top':
        try:
            txt = leaderboard_rent()
        except Exception as _e:
            txt = f"⚠️ حدث خطأ أثناء تحميل البيانات\n{_e}"
        keys = mk(row_width=1)
        keys.add(btn('رجوع', callback_data='submit_account', color='blue'))
        try:
            bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        except Exception:
            # لو في رمز خاص يكسر Markdown — ابعت بدون parse_mode
            bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys)
        return

    if data == 'leaderboard':
        lb_text = leaderboard_coins()
        keys = mk(row_width=1)
        keys.add(btn('رجوع', callback_data='back', color='blue'))
        bot.edit_message_text(text=lb_text, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='Markdown')
        return


    if data == 'top_level':
        check_and_award_level(cid)   # فحص لو في ترقية جديدة
        txt  = top_level_text(cid)
        keys = mk(row_width=2)
        keys.add(btn('🏆 لوحة الصدارة', callback_data='top_level_lb', color='red'))
        keys.add(btn('📊 جميع المستويات', callback_data='top_level_all', color='blue'))
        keys.add(btn('رجوع', callback_data='collect', color='blue'))
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        return

    if data == 'top_level_lb':
        txt  = top_level_leaderboard()
        keys = mk(row_width=1)
        keys.add(btn('🏅 مستواي', callback_data='top_level', color='green'))
        keys.add(btn('رجوع',   callback_data='collect',   color='blue'))
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        return

    if data.startswith('top_level_all'):
        PAGE_SIZE = 6
        try:
            page = int(data.split('_p')[-1]) if '_p' in data else 0
        except:
            page = 0
        total_pages = (len(TOP_LEVELS) + PAGE_SIZE - 1) // PAGE_SIZE
        page = max(0, min(page, total_pages - 1))
        start_i = page * PAGE_SIZE
        chunk = TOP_LEVELS[start_i: start_i + PAGE_SIZE]
        _lines = [f"📋 <b>جميع مستويات TOP LEVEL</b>  [{page+1}/{total_pages}]\n━━━━━━━━━━━━━━━━━━━"]
        for lv in chunk:
            _lines.append(
                f"\n{lv['color']} {lv['emoji']} <b>المستوى {lv['level']}</b>\n"
                f"  🌀 إحالات : {lv['req_refs']:,}  |  📦 طلبات : {lv['req_orders']:,}\n"
                f"  💰 نقاط   : {lv['req_coins']:,}  |  📱 حسابات: {lv['req_accounts']:,}\n"
                f"  🎁 مكافأة : {lv['reward_coins']:,} نقطة"
            )
        _lines.append("\n━━━━━━━━━━━━━━━━━━━")
        txt  = "\n".join(_lines)
        keys = mk(row_width=2)
        if page > 0:
            keys.add(btn('◀️ السابق', callback_data=f'top_level_all_p{page-1}', color='blue'))
        if page < total_pages - 1:
            keys.add(btn('التالي ▶️', callback_data=f'top_level_all_p{page+1}', color='blue'))
        keys.add(btn('🏅 مستواي', callback_data='top_level', color='green'))
        keys.add(btn('رجوع',   callback_data='collect',   color='blue'))
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='HTML')
        return

    if data == 'leave':
        if cid in admins:
            db.set(f'leave_{cid}_proccess', True)
            x = bot.edit_message_text(text='ارسل رابط اذا القناة خاصه، اذا عامه ارسل معرفها فقط؟', reply_markup=bk_cancel_adm, chat_id=cid, message_id=mid, parse_mode="HTML")
            bot.register_next_step_handler(x, get_amount, 'leavs')
    if data == 'account':
        if not check_user(cid):
            return start_message(call.message)
        acc = get(cid)
        coins = acc['coins']
        users_count = len(get(cid)['users'])
        info = db.get(f"user_{call.from_user.id}")
        daily_count = int(db.get(f"user_{user_id}_daily_count")) if db.exists(f"user_{user_id}_daily_count") else 0
        daily_gift = int(db.get("daily_gift")) if db.exists("daily_gift") else 30
        all_gift = daily_count * daily_gift
        buys = int(db.get(f"user_{user_id}_buys")) if db.exists(f"user_{user_id}_buys") else 0
        trans = int(db.get(f"user_{user_id}_trans")) if db.exists(f"user_{user_id}_trans") else 0
        y = trend()
        prem = 'Premium' if info['premium'] is True else 'Free'
        _phones_list = acc.get('phones', [])
        _phones_txt  = '\n'.join([f'  📞 {p}' for p in _phones_list]) if _phones_list else '  لا يوجد'
        textt = f'''\n• [❇️] عدد نقاط حسابك : {coins}\n• [🌀] عدد عمليات الاحاله التي قمت بها : {users_count}\n• [👤] نوع اشتراكك داخل البوت : {prem}\n• [🎁] عدد الهدايا اليومية التي جمعتها : {daily_count}\n• [❇️] عدد النقاط اللي جمعتها من الهدايا اليومية : {all_gift}\n• [📮] عدد الطلبات التي طلبتها : {buys}\n• [♻️] عدد التحويلات التي قمت بها : {trans}\n• [📱] الأرقام المسجلة ({len(_phones_list)}) :\n{_phones_txt}\n\n{y}'''
        bot.edit_message_text(text=textt, chat_id=cid, message_id=mid, reply_markup=bk_cancel, parse_mode="HTML")
        return
    if data == 'setforce':
        force_ch = _get_force_channels()
        ch_list  = '\n'.join([f'• {_ch_name(c)} → {_ch_url(c)}' for c in force_ch]) if force_ch else 'لا توجد قنوات بعد'

        stats_txt = ''
        if force_ch:
            stats_txt = '\n📊 <b>إحصائيات الانضمام:</b>\n'
            for _ch in force_ch:
                _cid_clean = _ch_id(_ch) if isinstance(_ch, dict) else _ch.lstrip('@')
                _count = int(db.get(f'force_join_count_{_cid_clean}')) if db.exists(f'force_join_count_{_cid_clean}') else 0
                _limit = db.get(f'force_join_limit_{_cid_clean}') if db.exists(f'force_join_limit_{_cid_clean}') else None
                _limit_txt = f'{int(_limit):,}' if _limit else 'غير محدود'
                stats_txt += f'  • @{_cid_clean} : 👥 {_count:,} | حد: {_limit_txt}\n'

        _se  = (db.get('fsub_sub_emoji')   or '📢').strip()
        _st  = (db.get('fsub_sub_text')    or 'اشترك').strip()
        _ce  = (db.get('fsub_check_emoji') or '✅').strip()
        _ct  = (db.get('fsub_check_text')  or 'تحققت من الاشتراك').strip()
        ckeys_sf = mk(row_width=1)
        ckeys_sf.add(btn('➕ إضافة قناة جديدة', callback_data='fsub_add', color='green'))
        if force_ch:
            ckeys_sf.add(btn('🗑 حذف قناة', callback_data='fsub_remove', color='red'))
            ckeys_sf.add(btn('✏️ تعيين حد الانضمام', callback_data='adm_fsub_stats', color='blue'))
        ckeys_sf.add(btn(f'✏️ زر الاشتراك: {_se} {_st}', callback_data='fsub_edit_sub_btn', color='green'))
        ckeys_sf.add(btn(f'✏️ زر التحقق: {_ce} {_ct}',   callback_data='fsub_edit_check_btn', color='blue'))
        ckeys_sf.add(btn('🔙 رجوع للوحة الأدمن', callback_data='adm_cat_subscription', color='red'))
        bot.edit_message_text(
            text=(
                '📡 <b>إدارة قنوات الاشتراك الإجباري</b>\n\n'
                f'<b>القنوات الحالية ({len(force_ch)}):</b>\n{ch_list}\n'
                f'{stats_txt}\n'
                '• اختر إجراء:'
            ),
            reply_markup=ckeys_sf, chat_id=cid, message_id=mid, parse_mode='HTML'
        )

    if data == 'fsub_add':
        if cid not in (db.get('admins') or []) and cid != sudo:
            return
        x = bot.edit_message_text(
            text=(
                '➕ <b>إضافة قناة اشتراك إجباري</b>\n\n'
                'أرسل بيانات القناة بهذا الشكل:\n\n'
                '<code>@معرف | اسم القناة | رابط الجوين | حد الأعضاء</code>\n\n'
                '<b>مثال:</b>\n'
                '<code>@mychannel | قناتي الرسمية | https://t.me/+xxxx | 1000</code>\n\n'
                '• الحد = 0 يعني بلا حد\n'
                '• لو مفيش رابط جوين خاص اكتب 0'
            ),
            reply_markup=bk_cancel, chat_id=cid, message_id=mid, parse_mode='HTML'
        )
        bot.register_next_step_handler(x, setfo_add)

    if data == 'fsub_remove':
        if cid not in (db.get('admins') or []) and cid != sudo:
            return
        _fc = _get_force_channels()
        r_keys = mk(row_width=1)
        for _ch in _fc:
            r_keys.add(btn(f'🗑 {_ch_name(_ch)}', callback_data=f'fsub_del_{_ch_id(_ch)}', color='red'))
        r_keys.add(btn('رجوع', callback_data='setforce', color='blue'))
        bot.edit_message_text(
            text='🗑 <b>اختر القناة التي تريد حذفها:</b>',
            reply_markup=r_keys, chat_id=cid, message_id=mid, parse_mode='HTML'
        )

    if data.startswith('fsub_del_'):
        if cid not in (db.get('admins') or []) and cid != sudo:
            return
        del_id = data.replace('fsub_del_', '').lstrip('@')
        _raw = db.get('force') or []
        _upd = [c for c in _raw if (_ch_id(c) if isinstance(c, dict) else c.lstrip('@')) != del_id]
        db.set('force', _upd)
        _cb_alert(call, f'✅ تم حذف @{del_id}', show_alert=True)
        _fc2 = _get_force_channels()
        _cl2 = '\n'.join([f'• {_ch_name(c)} → {_ch_url(c)}' for c in _fc2]) if _fc2 else 'لا توجد قنوات'
        _ck2 = mk(row_width=1)
        _ck2.add(btn('➕ إضافة قناة جديدة', callback_data='fsub_add', color='green'))
        if _fc2:
            _ck2.add(btn('🗑 حذف قناة', callback_data='fsub_remove', color='red'))
        _ck2.add(btn('🔙 رجوع للوحة الأدمن', callback_data='adm_cat_subscription', color='red'))
        bot.edit_message_text(
            text=f'📡 <b>إدارة قنوات الاشتراك الإجباري</b>\n\n<b>القنوات ({len(_fc2)}):</b>\n{_cl2}',
            reply_markup=_ck2, chat_id=cid, message_id=mid, parse_mode='HTML'
        )

    # تخصيص نص وإيموجي أزرار الاشتراك الإجباري

    if data == 'fsub_edit_sub_btn':
        if cid not in (db.get('admins') or []) and cid != sudo:
            return
        _se = (db.get('fsub_sub_emoji') or '📢').strip()
        _st = (db.get('fsub_sub_text')  or 'اشترك').strip()
        _ek = mk(row_width=2)
        for _em in ['📢','🔔','📣','⚡','🚀','🔥','💎','👑','✨','🌟','📡','🎯']:
            _ek.add(btn(_em, callback_data=f'fsub_sub_emo_{_em}', color='green'))
        _ek.add(btn('✏️ تغيير النص', callback_data='fsub_sub_text_edit', color='blue'))
        _ek.add(btn('رجوع', callback_data='setforce', color='blue'))
        bot.edit_message_text(
            text=(
                '✏️ <b>تخصيص زر الاشتراك</b>\n\n'
                f'الحالي: <b>{_se} {_st} • اسم القناة</b>\n\n'
                '🎨 اختر إيموجي للزر:'
            ),
            reply_markup=_ek, chat_id=cid, message_id=mid, parse_mode='HTML'
        )
        return

    if data.startswith('fsub_sub_emo_'):
        if cid not in (db.get('admins') or []) and cid != sudo:
            return
        new_emo = data.replace('fsub_sub_emo_', '')
        db.set('fsub_sub_emoji', new_emo)
        _cb_alert(call, f'تم تغيير الإيموجي إلى {new_emo}', show_alert=False)
        _st = (db.get('fsub_sub_text') or 'اشترك').strip()
        _ek = mk(row_width=2)
        for _em in ['📢','🔔','📣','⚡','🚀','🔥','💎','👑','✨','🌟','📡','🎯']:
            _ek.add(btn(_em, callback_data=f'fsub_sub_emo_{_em}', color='green'))
        _ek.add(btn('✏️ تغيير النص', callback_data='fsub_sub_text_edit', color='blue'))
        _ek.add(btn('رجوع', callback_data='setforce', color='blue'))
        bot.edit_message_text(
            text=(
                '✏️ <b>تخصيص زر الاشتراك</b>\n\n'
                f'الحالي: <b>{new_emo} {_st} • اسم القناة</b>\n\n'
                '🎨 اختر إيموجي للزر:'
            ),
            reply_markup=_ek, chat_id=cid, message_id=mid, parse_mode='HTML'
        )
        return

    if data == 'fsub_sub_text_edit':
        if cid not in (db.get('admins') or []) and cid != sudo:
            return
        x = bot.edit_message_text(
            text=(
                '✏️ <b>تغيير نص زر الاشتراك</b>\n\n'
                'أرسل النص الجديد للزر:\n'
                '<i>مثال: اشترك الآن</i>'
            ),
            reply_markup=bk_cancel, chat_id=cid, message_id=mid, parse_mode='HTML'
        )
        def _save_sub_text(msg):
            if not msg or not msg.text or msg.text.strip() == '':
                bot.reply_to(msg, 'النص لا يمكن ان يكون فارغا')
                return
            db.set('fsub_sub_text', msg.text.strip())
            bot.reply_to(msg, f'تم تغيير نص زر الاشتراك الى:\n<b>{msg.text.strip()}</b>', parse_mode='HTML')
        bot.register_next_step_handler(x, _save_sub_text)
        return

    if data == 'fsub_edit_check_btn':
        if cid not in (db.get('admins') or []) and cid != sudo:
            return
        _ce = (db.get('fsub_check_emoji') or '✅').strip()
        _ct = (db.get('fsub_check_text')  or 'تحققت من الاشتراك').strip()
        _ck = mk(row_width=2)
        for _em in ['✅','☑️','✔️','💯','🎯','🏆','🥇','⭐','🔓','🎉','👍','💪']:
            _ck.add(btn(_em, callback_data=f'fsub_chk_emo_{_em}', color='blue'))
        _ck.add(btn('✏️ تغيير النص', callback_data='fsub_check_text_edit', color='green'))
        _ck.add(btn('رجوع', callback_data='setforce', color='blue'))
        bot.edit_message_text(
            text=(
                '✏️ <b>تخصيص زر التحقق</b>\n\n'
                f'الحالي: <b>{_ce} {_ct}</b>\n\n'
                '🎨 اختر إيموجي للزر:'
            ),
            reply_markup=_ck, chat_id=cid, message_id=mid, parse_mode='HTML'
        )
        return

    if data.startswith('fsub_chk_emo_'):
        if cid not in (db.get('admins') or []) and cid != sudo:
            return
        new_emo = data.replace('fsub_chk_emo_', '')
        db.set('fsub_check_emoji', new_emo)
        _cb_alert(call, f'تم تغيير الإيموجي الى {new_emo}', show_alert=False)
        _ct = (db.get('fsub_check_text') or 'تحققت من الاشتراك').strip()
        _ck = mk(row_width=2)
        for _em in ['✅','☑️','✔️','💯','🎯','🏆','🥇','⭐','🔓','🎉','👍','💪']:
            _ck.add(btn(_em, callback_data=f'fsub_chk_emo_{_em}', color='blue'))
        _ck.add(btn('✏️ تغيير النص', callback_data='fsub_check_text_edit', color='green'))
        _ck.add(btn('رجوع', callback_data='setforce', color='blue'))
        bot.edit_message_text(
            text=(
                '✏️ <b>تخصيص زر التحقق</b>\n\n'
                f'الحالي: <b>{new_emo} {_ct}</b>\n\n'
                '🎨 اختر إيموجي للزر:'
            ),
            reply_markup=_ck, chat_id=cid, message_id=mid, parse_mode='HTML'
        )
        return

    if data == 'fsub_check_text_edit':
        if cid not in (db.get('admins') or []) and cid != sudo:
            return
        x = bot.edit_message_text(
            text=(
                '✏️ <b>تغيير نص زر التحقق</b>\n\n'
                'أرسل النص الجديد للزر:\n'
                '<i>مثال: تحققت من الاشتراك</i>'
            ),
            reply_markup=bk_cancel, chat_id=cid, message_id=mid, parse_mode='HTML'
        )
        def _save_check_text(msg):
            if not msg or not msg.text or msg.text.strip() == '':
                bot.reply_to(msg, 'النص لا يمكن ان يكون فارغا')
                return
            db.set('fsub_check_text', msg.text.strip())
            bot.reply_to(msg, f'تم تغيير نص زر التحقق الى:\n<b>{msg.text.strip()}</b>', parse_mode='HTML')
        bot.register_next_step_handler(x, _save_check_text)
        return

    if data == 'adm_fsub_stats':
        if cid not in (db.get('admins') or []) and cid != sudo:
            return
        force_channels = db.get('force') or []
        if not force_channels:
            bot.edit_message_text(
                text='📊 إحصائيات الاشتراك الإجباري\n\n⚠️ لا توجد قنوات اشتراك إجباري مضافة بعد',
                chat_id=cid, message_id=mid, reply_markup=bk
            )
            return
        txt = '📊 <b>إحصائيات الاشتراك الإجباري</b>\n'
        txt += '━━━━━━━━━━━━━━━━━━━\n'
        keys_s = mk(row_width=1)
        for ch in force_channels:

            if isinstance(ch, dict):
                ch_clean = str(ch.get('id', ch.get('username', ''))).lstrip('@')
            else:
                ch_clean = str(ch).lstrip('@')
            if not ch_clean:
                continue
            count    = int(db.get(f'force_join_count_{ch_clean}')) if db.exists(f'force_join_count_{ch_clean}') else 0
            limit    = db.get(f'force_join_limit_{ch_clean}') if db.exists(f'force_join_limit_{ch_clean}') else None
            limit_txt = f'{int(limit):,}' if limit else 'غير محدود'
            txt += f'\n📢 @{ch_clean}\n'
            txt += f'   👥 عدد الداخلين : <b>{count:,}</b>\n'
            txt += f'   🔢 الحد الأقصى  : <b>{limit_txt}</b>\n'
            keys_s.add(btn(f'✏️ تعيين حد @{ch_clean}', callback_data=f'adm_fsub_limit_{ch_clean}', color='green'))
        txt += '━━━━━━━━━━━━━━━━━━━'
        keys_s.add(btn('رجوع', callback_data='setforce', color='blue'))
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys_s, parse_mode='HTML')
        return

    if data.startswith('adm_fsub_limit_'):
        if cid not in (db.get('admins') or []) and cid != sudo:
            return
        ch_clean = data.replace('adm_fsub_limit_', '')
        cur_limit = db.get(f'force_join_limit_{ch_clean}') if db.exists(f'force_join_limit_{ch_clean}') else None
        cur_txt = f'{int(cur_limit):,}' if cur_limit else 'غير محدود'
        x = bot.edit_message_text(
            text=(
                f'✏️ <b>تعيين حد الدخول لقناة @{ch_clean}</b>\n\n'
                f'الحد الحالي : <b>{cur_txt}</b>\n\n'
                f'أرسل الرقم الجديد (أو أرسل 0 لإلغاء الحد):'
            ),
            reply_markup=bk_cancel, chat_id=cid, message_id=mid, parse_mode='HTML'
        )
        def _save_limit(m, channel=ch_clean):
            try:
                val = int(m.text.strip())
                if val <= 0:
                    db.delete(f'force_join_limit_{channel}')
                    bot.reply_to(m, f'✅ تم إلغاء الحد لقناة @{channel}')
                else:
                    db.set(f'force_join_limit_{channel}', val)
                    bot.reply_to(m, f'✅ تم تعيين الحد لـ @{channel} : {val:,} عضو')
            except:
                bot.reply_to(m, '❌ أرسل رقم صحيح فقط')
        bot.register_next_step_handler(x, _save_limit)
        return
    if data == 'admins':
        get_admins = db.get('admins')
        _adm_back_kb = mk(row_width=1)
        _adm_back_kb.add(btn('🔙 رجوع للوحة الأدمن', callback_data='adm_cat_users', color='red'))
        if get_admins:
            if len(get_admins) >= 1:
                txt = 'الادمنية : \n'
                for ran, admin_id in enumerate(get_admins, 1):
                    try:
                        info = bot.get_chat(admin_id)
                        username = f'{ran} @' + str(info.username) + f' | {admin_id}\n' if info.username else f'{ran} {admin_id} .\n'
                        txt += username
                    except:
                        txt += f'{ran} {admin_id}\n'
                bot.edit_message_text(chat_id=cid, message_id=mid, text=txt, reply_markup=_adm_back_kb)
                return
            else:
                bot.edit_message_text(chat_id=cid, message_id=mid, text='لا يوجد ادمنية بالبوت', reply_markup=_adm_back_kb)
                return
        else:
            bot.edit_message_text(chat_id=cid, message_id=mid, text='لا يوجد ادمنية بالبوت', reply_markup=_adm_back_kb)
            return
    if data == 'votes':
        _pr = svc_price('votes'); _mn = svc_min('votes'); _mx = svc_max('votes')
        _svc_txt = (
            f'🗳️ <b>خدمة تصويت مسابقات</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'💰 السعر : <b>{_pr * 100}</b> نقطة لكل 100\n'
            f'📉 الحد الأدنى : <b>{_mn}</b>\n'
            f'📈 الحد الأقصى : <b>{_mx}</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'أرسل الآن العدد الذي تريده (<b>{_mn}</b> - <b>{_mx}</b>):'
        )
        db.set(f'vote_{cid}_proccess', True)
        x = bot.edit_message_text(text=_svc_txt, reply_markup=_bk_cancel_svc('normal'), chat_id=cid, message_id=mid, parse_mode="HTML")
        bot.register_next_step_handler(x, get_amount, 'votes')
    if data == 'votes_fsub':
        info = db.get(f'user_{cid}')
        if not (info and info.get('premium')):
            _cb_alert(call, '⛔ هذه الخدمة للمشتركين VIP فقط!', show_alert=True)
            return
        _pr = svc_price('votes_fsub'); _mn = svc_min('votes_fsub'); _mx = svc_max('votes_fsub')
        _svc_txt = (
            f'🏆 <b>خدمة تصويت مسابقات اشتراك إجباري</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'📌 <b>كيف تعمل؟</b>\n'
            f'• كل حساب يشترك في قناتك أولاً ثم يصوت تلقائياً\n\n'
            f'💰 السعر : <b>{_pr * 100}</b> نقطة لكل 100\n'
            f'📉 الحد الأدنى : <b>{_mn}</b>\n'
            f'📈 الحد الأقصى : <b>{_mx}</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'أرسل الآن العدد الذي تريده (<b>{_mn}</b> - <b>{_mx}</b>):'
        )
        db.set(f'votes_fsub_{cid}_proccess', True)
        x = bot.edit_message_text(text=_svc_txt, reply_markup=_bk_cancel_svc('vips'), chat_id=cid, message_id=mid, parse_mode="HTML")
        bot.register_next_step_handler(x, get_amount, 'votes_fsub')
    if data == 'buy':
        # إعدادات الشحن من DB
        stars_rate   = int(db.get("charge_stars_rate"))   if db.exists("charge_stars_rate")   else 600
        cash_rate    = int(db.get("charge_cash_rate"))    if db.exists("charge_cash_rate")     else 150000
        usdt_rate    = int(db.get("charge_usdt_rate"))    if db.exists("charge_usdt_rate")     else 150000
        usdt_wallet  = db.get("charge_usdt_wallet")       if db.exists("charge_usdt_wallet")   else "لم يتم تعيينه بعد"
        cash_contact = db.get("charge_cash_contact")      if db.exists("charge_cash_contact")  else "لم يتم تعيينه بعد"
        agent_info   = db.get("charge_agent_info")        if db.exists("charge_agent_info")    else "يمكنك التواصل مع الأدمن للشحن عبر الوكيل"
        vf_rate      = int(db.get("charge_vf_rate"))      if db.exists("charge_vf_rate")      else 1000
        keys = mk(row_width=1)
        keys.add(btn('⭐ شحن بالنجوم (Stars)', callback_data='charge_stars', color='green'))
        keys.add(btn('📱 شحن بفودافون كاش', callback_data='charge_vf', color='red'))
        keys.add(btn('💵 شحن بالكاش (يدوي)', callback_data='charge_cash', color='blue'))
        keys.add(btn('💎 شحن بـ USDT', callback_data='charge_usdt', color='green'))
        keys.add(btn('🤝 شحن عبر الوكيل', callback_data='charge_agent', color='blue'))
        keys.add(btn('🔙 رجوع للقائمة', callback_data='back', color='red'))
        txt = (
            "شحن النقاط\n\n"
            f"⭐ نجوم تليجرام: 1 نجمة = {stars_rate} نقطة\n"
            f"📱 فودافون كاش: 1 جنيه = {vf_rate} نقطة\n"
            f"💵 كاش: $1 = {cash_rate} نقطة\n"
            f"💎 USDT: 1 USDT = {usdt_rate} نقطة\n"
            "🤝 عبر الوكيل: بأسعار خاصة\n\n"
            "اختر طريقة الشحن:"
        )
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")

    # 🛡️ شراء اشتراك إجباري

    if data == 'buy_force_sub':
        fsub_amount   = int(db.get("fsub_amount"))     if db.exists("fsub_amount")   else 500
        fsub_duration = int(db.get("fsub_duration"))   if db.exists("fsub_duration") else 1
        fsub_stars    = int(db.get("fsub_stars"))      if db.exists("fsub_stars")    else 100
        fsub_cash     = int(db.get("fsub_cash"))       if db.exists("fsub_cash")     else 50
        fsub_usdt     = db.get("fsub_usdt")            if db.exists("fsub_usdt")     else "1.0"
        keys = mk(row_width=1)
        keys.add(btn('دفع بالنجوم', callback_data='fsub_pay_stars', color='green'))
        keys.add(btn('دفع بفودافون كاش', callback_data='fsub_pay_vf', color='blue'))
        keys.add(btn('دفع بـ USDT', callback_data='fsub_pay_usdt', color='blue'))
        keys.add(btn('رجوع', callback_data='back', color='red'))
        txt = (
            f"🔐 {fsub_amount:,} اشتراك اجباري\n\n"
            f"المدة: {fsub_duration} يوم\n"
            "اعضاء حقيقيه متفاعلين\n\n"
            "طرق الدفع:\n"
            f"نجوم: {fsub_stars} نجمة\n"
            f"فودافون كاش: {fsub_cash} جنيه\n"
            f"دولار USDT: {fsub_usdt} دولار\n\n"
            "اختر طريقة الدفع:"
        )
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")
        return

    if data == 'fsub_pay_stars':
        fsub_stars = int(db.get("fsub_stars")) if db.exists("fsub_stars") else 100
        stars_post = db.get("charge_stars_post") if db.exists("charge_stars_post") else None
        keys = mk(row_width=1)
        if stars_post:
            keys.add(btn('⭐ أرسل النجوم الآن', url=stars_post, color='green'))
        keys.add(btn('رجوع', callback_data='buy_force_sub', color='red'))
        txt = f"⭐ دفع بالنجوم\n\nالمبلغ المطلوب: {fsub_stars} نجمة\n\n"
        if stars_post:
            txt += "اضغط الزر ��دناه لإرسال النجوم\n\nبعد الدفع تواصل مع الأدمن لتأكيد الطلب وإضافة قناتك ✅"
        else:
            txt += "تواصل مع الأدمن لإتمام الدفع وإضافة قناتك."
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")
        return

    if data == 'fsub_pay_vf':
        fsub_cash  = int(db.get("fsub_cash"))      if db.exists("fsub_cash")         else 50
        vf_number  = db.get("charge_vf_number")    if db.exists("charge_vf_number")  else "لم يتم تعيينه بعد"
        vf_contact = db.get("charge_vf_contact")   if db.exists("charge_vf_contact") else None
        keys = mk(row_width=1)
        keys.add(btn('رجوع', callback_data='buy_force_sub', color='red'))
        contact_line = f"\n📞 للتواصل: @{vf_contact}" if vf_contact else "\n📞 تواصل مع الأدمن لإتمام الدفع"
        txt = (
            f"📱 دفع بفودافون كاش\n\n"
            f"💰 المبلغ المطلوب: {fsub_cash} جنيه\n"
            f"📲 رقم فودافون كاش:\n<code>{vf_number}</code>"
            f"{contact_line}\n\n"
            "📌 الخطوات:\n"
            "1️⃣ حوّل المبلغ للرقم أعلاه\n"
            "2️⃣ احتفظ برقم العملية\n"
            "3️⃣ أرسل لقطة شاشة للأدمن مع اسم قناتك"
        )
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")
        return

    if data == 'fsub_pay_usdt':
        fsub_usdt   = db.get("fsub_usdt")          if db.exists("fsub_usdt")          else "1.0"
        usdt_wallet = db.get("charge_usdt_wallet") if db.exists("charge_usdt_wallet") else "لم يتم تعيينه بعد"
        keys = mk(row_width=1)
        keys.add(btn('رجوع', callback_data='buy_force_sub', color='red'))
        txt = (
            f"💎 دفع بـ USDT\n\n"
            f"💰 المبلغ المطلوب: {fsub_usdt} دولار\n"
            f"عنوان المحفظة (TRC20):\n<code>{usdt_wallet}</code>\n\n"
            "بعد الدفع أرسل لقطة إثبات التحويل للأدمن مع اسم قناتك"
        )
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")
        return


    if data == 'charge_points':
        keys = mk(row_width=1)
        keys.add(btn('��� شحن تلقائي بالنجوم', callback_data='charge_stars', color='green'))
        keys.add(btn('📱 شحن بفودافون كاش', callback_data='charge_vf', color='red'))
        keys.add(btn('💎 شحن بيوستد', callback_data='charge_usdt', color='blue'))
        keys.add(btn('💵 شحن بالكاش (يدوي)', callback_data='charge_cash', color='blue'))
        keys.add(btn('🤝 شحن عبر الوكيل', callback_data='charge_agent', color='blue'))
        keys.add(btn('رجوع', callback_data='back', color='blue'))
        bot.edit_message_text(
            text='💳 شحن النقاط\n\nاختر طريقة الشحن:',
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML"
        )


    if data == 'charge_stars':
        stars_rate = int(db.get("charge_stars_rate")) if db.exists("charge_stars_rate") else 600
        stars_post = db.get("charge_stars_post") if db.exists("charge_stars_post") else None
        keys = mk(row_width=3)
        for amt in [1, 5, 10, 20, 50, 70, 100, 300, 1000]:
            keys.add(btn(f'⭐ {amt}', callback_data=f'stars_buy_{amt}', color='green'))
        keys.add(btn('��جوع', callback_data='charge_points', color='red'))
        txt = (
            "شحن بنجوم تليجرام\n\n"
            f"سعر الشحن: 1 نجمة = {stars_rate} نقطة\n\n"
            "اختر الك��ية:"
        )
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")

    if data.startswith('stars_buy_'):
        amt = int(data.replace('stars_buy_', ''))
        stars_rate = int(db.get("charge_stars_rate")) if db.exists("charge_stars_rate") else 600
        pts = amt * stars_rate
        try:
            # إرسال فاتورة دفع تلقائية بنجوم تليجرام
            bot.send_invoice(
                chat_id=cid,
                title=f"شحن {amt} نجمة ⭐",
                description=f"شحن {pts:,} نقطة عبر {amt} نجمة تليجرام",
                invoice_payload=f"stars_{amt}_{cid}",
                provider_token="",          # فارغ = دفع بالنجوم Stars
                currency="XTR",             # XTR = نجوم تليجرام
                prices=[telebot.types.LabeledPrice(label=f"⭐ {amt} نجمة", amount=amt)],
            )
            # نرد على الضغطة بصمت
            bot.answer_callback_query(call.id)
        except Exception as e:
            print(f"[stars_invoice] خطأ: {e}")
            _cb_alert(call, text="❌ حدث خطأ، حاول مجدداً", show_alert=True)


    if data == 'charge_cash':
        cash_rate    = int(db.get("charge_cash_rate"))    if db.exists("charge_cash_rate")    else 150000
        cash_contact = db.get("charge_cash_contact")      if db.exists("charge_cash_contact") else None
        keys = mk(row_width=1)
        keys.add(btn('رجوع', callback_data='charge_points', color='red'))
        contact_line = f"طريقة الدفع: تواصل مع @{cash_contact}" if cash_contact else "تواصل مع الأدمن لإتمام الدفع"
        txt = (
            "شحن بالكاش\n\n"
            f"سعر الشحن: $1 = {cash_rate} نقطة\n"
            f"{contact_line}\n\n"
            "بعد الدفع أرسل لقطة إثبات الدفع (صورة أو نص):"
        )
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler_by_chat_id(cid, _charge_proof_received, 'cash')


    if data == 'charge_vf':
        vf_rate    = int(db.get("charge_vf_rate"))    if db.exists("charge_vf_rate")    else 1000
        vf_number  = db.get("charge_vf_number")       if db.exists("charge_vf_number")  else "لم يتم تعيينه بعد"
        vf_contact = db.get("charge_vf_contact")      if db.exists("charge_vf_contact") else None
        keys = mk(row_width=1)
        keys.add(btn('رجوع', callback_data='charge_points', color='red'))
        contact_line = f"\n📞 للتواصل: @{vf_contact}" if vf_contact else "\n📞 تواصل مع الأدمن لإتمام الدفع"
        txt = (
            "📱 شحن بفودافون كاش\n\n"
            f"💰 سعر الشحن: 1 جنيه = {vf_rate} نقطة\n"
            f"📲 رقم فودافون كاش:\n<code>{vf_number}</code>"
            f"{contact_line}\n\n"
            "📌 الخطوات:\n"
            "1️⃣ حوّل المبلغ للرقم أعلاه\n"
            "2️⃣ احتفظ برقم العملية\n"
            "3️⃣ أرسل لقطة شاشة إثبات التحويل هنا ⬇️"
        )
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler_by_chat_id(cid, _charge_proof_received, 'vf')


    if data == 'charge_usdt':
        usdt_rate   = int(db.get("charge_usdt_rate"))   if db.exists("charge_usdt_rate")   else 150000
        usdt_wallet = db.get("charge_usdt_wallet")       if db.exists("charge_usdt_wallet") else "لم يتم تعيينه بعد"
        keys = mk(row_width=1)
        keys.add(btn('رجوع', callback_data='charge_points', color='red'))
        txt = (
            "شحن بـ USDT\n\n"
            f"سعر الشحن: 1 USDT = {usdt_rate} نقطة\n"
            f"عنوان المحفظة (TRC20):\n<code>{usdt_wallet}</code>\n\n"
            "بعد الدفع أرسل لقطة إثبات التحويل هنا ⬇️"
        )
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler_by_chat_id(cid, _charge_proof_received, 'usdt')


    if data == 'charge_agent':
        agent_info = db.get("charge_agent_info") if db.exists("charge_agent_info") else "بأسعار خاصة — تواصل مع الأدمن"
        keys = mk(row_width=1)
        keys.add(btn('رجوع', callback_data='charge_points', color='red'))
        txt = f"شحن عبر الوكيل\n\n{agent_info}"
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")
    if data == 'share_link':
        bot_user = None
        try:
            x = _get_bot_me()
            bot_user = x.username
        except:
            bot.edit_message_text(text=f'• حدث خطا ما في البوت', chat_id=cid, message_id=mid, reply_markup=bk_cancel, parse_mode="HTML")
            return
        link = f'https://t.me/{bot_user}?start={cid}'
        try:
            y = trend()
        except:
            y = ""
        keys = mk(row_width=2)
        keys.add(btn('رجوع', callback_data='collect'))
        _user_data = get(cid)
        _users_count = len(_user_data["users"]) if _user_data and _user_data.get("users") else 0
        xyz = f'''\n \nانسخ الرابط ثم قم بمشاركته مع اصدقائك !!\n \n~  كل شخص يقوم بالدخول ستحصل على  {int(db.get("link_price")) if db.exists("link_price") else link_price}  نقطه\n\n~ بإمكانك عمل اعلان خاص برابط الدعوة الخاص بك \n\n🌀 رابط الدعوة : \n {link}  .\n\n~ مشاركتك للرابط :  {_users_count}  .\n\n{y}\n        '''
        try:
            bot.edit_message_text(text=xyz, chat_id=cid, message_id=mid, reply_markup=keys, parse_mode="HTML")
        except Exception as e:
            bot.send_message(chat_id=cid, text=xyz, reply_markup=keys, parse_mode="HTML")
        return
    if data == 'members':
        if not svc_enabled('member'):
            _cb_alert(call, text='⛔ هذه الخدمة معطّلة حالياً', show_alert=True)
            return
        _vip_info = db.get(f'user_{cid}')
        _is_prem = _vip_info.get('premium', False) if _vip_info else False
        if not _is_prem:
            _inv_count = len(_vip_info.get('users', [])) if _vip_info else 0
            _vip_thresh = int(db.get('vip_invite_threshold')) if db.exists('vip_invite_threshold') else 2
            _remaining = max(0, _vip_thresh - _inv_count)
            _keys_vip = mk(row_width=1)
            _keys_vip.add(btn('🔮 رابط الدعوة', callback_data='share_link', color='green'))
            _keys_vip.add(btn('رجوع', callback_data='vips', color='blue'))
            bot.edit_message_text(
                text=(
                    '👑 لازم تعمل دعوتين عشان تفعل قسم VIP\n\n'
                    f'📊 دعواتك: {_inv_count} من {_vip_thresh} المطلوبة\n'
                    f'🎯 باقي عليك: {_remaining} دعوة فقط للحصول على VIP مجاناً!\n\n'
                    '💡 شارك رابط الدعوة وادعُ أصدقاءك للحصول على VIP تلقائياً'
                ),
                chat_id=cid, message_id=mid, reply_markup=_keys_vip, parse_mode="HTML"
            )
            return
        _pr = svc_price('member'); _mn = svc_min('member'); _mx = svc_max('member')
        _svc_txt = (
            f'👥 <b>خدمة أعضاء قناة عامة</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'💰 السعر : <b>{_pr * 100}</b> نقطة لكل 100\n'
            f'📉 الحد الأدنى : <b>{_mn}</b>\n'
            f'�� الحد الأقصى : <b>{_mx}</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'أرسل الآن العدد الذي تريده (<b>{_mn}</b> - <b>{_mx}</b>):'
        )
        db.set(f'member_{cid}_proccess', True)
        x = bot.edit_message_text(text=_svc_txt, reply_markup=_bk_cancel_svc('vips'), chat_id=cid, message_id=mid, parse_mode="HTML")
        bot.register_next_step_handler(x, get_amount, 'members')
    if data == 'membersp':
        _vip_info = db.get(f'user_{cid}')
        _is_prem = _vip_info.get('premium', False) if _vip_info else False
        if not _is_prem:
            _inv_count = len(_vip_info.get('users', [])) if _vip_info else 0
            _vip_thresh = int(db.get('vip_invite_threshold')) if db.exists('vip_invite_threshold') else 2
            _remaining = max(0, _vip_thresh - _inv_count)
            _keys_vip = mk(row_width=1)
            _keys_vip.add(btn('🔮 رابط الدعوة', callback_data='share_link', color='green'))
            _keys_vip.add(btn('رجوع', callback_data='vips', color='blue'))
            bot.edit_message_text(
                text=(
                    '👑 لازم تعمل دعوتين عشان تفعل قسم VIP\n\n'
                    f'📊 دعواتك: {_inv_count} من {_vip_thresh} المطلوبة\n'
                    f'🎯 باقي عليك: {_remaining} دعوة فقط للحصول على VIP مجاناً!\n\n'
                    '💡 شارك رابط الدعوة وادعُ أصدقاءك للحصول على VIP تلقائياً'
                ),
                chat_id=cid, message_id=mid, reply_markup=_keys_vip, parse_mode="HTML"
            )
            return
        _pr = svc_price('membersp'); _mn = svc_min('membersp'); _mx = svc_max('membersp')
        _svc_txt = (
            f'🔐 <b>خدمة أعضاء قناة خاصة</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'💰 السعر : <b>{_pr * 100}</b> نقطة لكل 100\n'
            f'📉 الحد الأدنى : <b>{_mn}</b>\n'
            f'📈 الحد الأقصى : <b>{_mx}</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'أرسل الآن العدد الذي تريده (<b>{_mn}</b> - <b>{_mx}</b>):'
        )
        db.set(f'memberp_{cid}_proccess', True)
        x = bot.edit_message_text(text=_svc_txt, reply_markup=_bk_cancel_svc('vips'), chat_id=cid, message_id=mid, parse_mode="HTML")
        bot.register_next_step_handler(x, get_amount, 'membersp')
    if data == 'spams':
        if not svc_enabled('spam'):
            _cb_alert(call, text='⛔ هذه الخدمة معطّلة حالياً', show_alert=True)
            return
        _vip_info = db.get(f'user_{cid}')
        _is_prem = _vip_info.get('premium', False) if _vip_info else False
        if not _is_prem:
            _inv_count = len(_vip_info.get('users', [])) if _vip_info else 0
            _vip_thresh = int(db.get('vip_invite_threshold')) if db.exists('vip_invite_threshold') else 2
            _remaining = max(0, _vip_thresh - _inv_count)
            _keys_vip = mk(row_width=1)
            _keys_vip.add(btn('🔮 رابط الدعوة', callback_data='share_link', color='green'))
            _keys_vip.add(btn('رجوع', callback_data='vips', color='blue'))
            bot.edit_message_text(
                text=(
                    '👑 لازم تعمل دعوتين عشان تفعل قسم VIP\n\n'
                    f'📊 دعواتك: {_inv_count} من {_vip_thresh} المطلوبة\n'
                    f'🎯 باقي عليك: {_remaining} دعوة فقط للحصول على VIP مجاناً!\n\n'
                    '💡 شارك رابط الدعوة وادعُ أصدقاءك للحصول على VIP تلقائياً'
                ),
                chat_id=cid, message_id=mid, reply_markup=_keys_vip, parse_mode="HTML"
            )
            return
        _pr = svc_price('spam'); _mn = svc_min('spam'); _mx = svc_max('spam')
        _svc_txt = (
            f'💬 <b>خدمة سبام رسائل</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'💰 السعر : <b>{_pr * 100}</b> نقطة لكل 100\n'
            f'📉 الحد الأدنى : <b>{_mn}</b>\n'
            f'📈 الحد الأقصى : <b>{_mx}</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'أرسل الآن العدد الذي تريده (<b>{_mn}</b> - <b>{_mx}</b>):'
        )
        db.set(f'spam_{cid}_proccess', True)
        x = bot.edit_message_text(text=_svc_txt, reply_markup=_bk_cancel_svc('vips'), chat_id=cid, message_id=mid, parse_mode="HTML")
        bot.register_next_step_handler(x, get_amount, 'spam')
    if data == 'react':
        _pr = svc_price('react'); _mn = svc_min('react'); _mx = svc_max('react')
        _svc_txt = (
            f'⚡ <b>خدمة تفاعلات اختياري</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'💰 السعر : <b>{_pr * 100}</b> نقطة لكل 100\n'
            f'📉 الحد الأدنى : <b>{_mn}</b>\n'
            f'📈 الحد الأقصى : <b>{_mx}</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'أرسل الآن العدد الذي تريده (<b>{_mn}</b> - <b>{_mx}</b>):'
        )
        db.set(f'react_{cid}_proccess', True)
        x = bot.edit_message_text(text=_svc_txt, reply_markup=_bk_cancel_svc('normal'), chat_id=cid, message_id=mid, parse_mode="HTML")
        bot.register_next_step_handler(x, get_amount, 'react')
    if data == 'reacts':
        _pr = svc_price('reacts'); _mn = svc_min('reacts'); _mx = svc_max('reacts')
        _svc_txt = (
            f'🎲 <b>خدمة تفاعلات عشوائي</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'💰 السعر : <b>{_pr * 100}</b> نقطة لكل 100\n'
            f'📉 الحد الأدنى : <b>{_mn}</b>\n'
            f'���� الحد الأقصى : <b>{_mx}</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'أرسل الآن العدد الذي تريده (<b>{_mn}</b> - <b>{_mx}</b>):'
        )
        db.set(f'reacts_{cid}_proccess', True)
        x = bot.edit_message_text(text=_svc_txt, reply_markup=_bk_cancel_svc('normal'), chat_id=cid, message_id=mid, parse_mode="HTML")
        bot.register_next_step_handler(x, get_amount, 'reactsrandom')
    if data == 'react_special':
        if not svc_enabled('react_special'):
            _cb_alert(call, text='⛔ هذه الخدمة معطّلة حالياً', show_alert=True)
            return
        _pr = svc_price('react_special'); _mn = svc_min('react_special'); _mx = svc_max('react_special')
        _svc_txt = (
            f'✦ ✨ <b>رشق إيموجي مميز</b> ✨ ✦\n\n'
            f'┌─────────────────────\n'
            f'│ 💰 السعر : <b>{_pr * 100}</b> نقطة / 100 تفاعل\n'
            f'│ 📉 الحد الأدنى : <b>{_mn}</b>\n'
            f'│ 📈 الحد الأقصى : <b>{_mx}</b>\n'
            f'└─────────────────────\n\n'
            f'🔢 <b>أرسل الكمية المطلوبة ({_mn} - {_mx})</b>'
        )
        db.set(f'react_special_{cid}_proccess', True)
        try:
            bot.edit_message_text(text=_svc_txt, reply_markup=_bk_cancel_svc('normal'), chat_id=cid, message_id=mid, parse_mode="HTML")
        except Exception:
            pass
        x = bot.send_message(chat_id=cid, text=f'🔢 أرسل الكمية ({_mn} - {_mx}):', reply_markup=_bk_cancel_svc('normal'))
        bot.register_next_step_handler(x, react_special_step1_amount)
    if data == 'forward':
        _pr = svc_price('forward'); _mn = svc_min('forward'); _mx = svc_max('forward')
        _svc_txt = (
            f'📤 <b>خدمة توجيهات منشور</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'💰 السعر : <b>{_pr * 100}</b> نقطة لكل 100\n'
            f'📉 الحد الأدنى : <b>{_mn}</b>\n'
            f'📈 الحد الأقصى : <b>{_mx}</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'أرسل الآن العدد الذي تريده (<b>{_mn}</b> - <b>{_mx}</b>):'
        )
        db.set(f'forward_{cid}_proccess', True)
        x = bot.edit_message_text(text=_svc_txt, reply_markup=_bk_cancel_svc('normal'), chat_id=cid, message_id=mid, parse_mode="HTML")
        bot.register_next_step_handler(x, get_amount, 'forward')
    if data == 'view':
        _pr = svc_price('view'); _mn = svc_min('view'); _mx = svc_max('view')
        _svc_txt = (
            f'🎯 <b>خدمة مشاهدات</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'💰 السعر : <b>{_pr * 100}</b> نقطة لكل 100\n'
            f'📉 الحد الأدنى : <b>{_mn}</b>\n'
            f'📈 الحد الأقصى : <b>{_mx}</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'أرسل الآن العدد الذي تريده (<b>{_mn}</b> - <b>{_mx}</b>):'
        )
        db.set(f'view_{cid}_proccess', True)
        x = bot.edit_message_text(text=_svc_txt, reply_markup=_bk_cancel_svc('normal'), chat_id=cid, message_id=mid, parse_mode="HTML")
        bot.register_next_step_handler(x, get_amount, 'view')
    if data == 'poll':
        _pr = svc_price('poll'); _mn = svc_min('poll'); _mx = svc_max('poll')
        _svc_txt = (
            f'📊 <b>خدمة استفتاء</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'💰 السعر : <b>{_pr * 100}</b> نقطة لكل 100\n'
            f'📉 الحد الأدنى : <b>{_mn}</b>\n'
            f'📈 الحد الأقصى : <b>{_mx}</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'أرسل الآن العدد الذي تريده (<b>{_mn}</b> - <b>{_mx}</b>):'
        )
        db.set(f'poll_{cid}_proccess', True)
        x = bot.edit_message_text(text=_svc_txt, reply_markup=_bk_cancel_svc('normal'), chat_id=cid, message_id=mid, parse_mode="HTML")
        bot.register_next_step_handler(x, get_amount, 'poll')
    if data == 'userbot':
        _vip_info = db.get(f'user_{cid}')
        _is_prem = _vip_info.get('premium', False) if _vip_info else False
        if not _is_prem:
            _inv_count = len(_vip_info.get('users', [])) if _vip_info else 0
            _vip_thresh = int(db.get('vip_invite_threshold')) if db.exists('vip_invite_threshold') else 2
            _remaining = max(0, _vip_thresh - _inv_count)
            _keys_vip = mk(row_width=1)
            _keys_vip.add(btn('🔮 رابط الدعوة', callback_data='share_link', color='green'))
            _keys_vip.add(btn('رجوع', callback_data='vips', color='blue'))
            bot.edit_message_text(
                text=(
                    '👑 لازم تعمل دعوتين عشان تفعل قسم VIP\n\n'
                    f'📊 دعواتك: {_inv_count} من {_vip_thresh} المطلوبة\n'
                    f'🎯 باقي عليك: {_remaining} دعوة فقط للحصول على VIP مجاناً!\n\n'
                    '💡 شارك رابط الدعوة وادعُ أصدقاءك للحصول على VIP تلقائياً'
                ),
                chat_id=cid, message_id=mid, reply_markup=_keys_vip, parse_mode="HTML"
            )
            return
        _pr = svc_price('userbot'); _mn = svc_min('userbot'); _mx = svc_max('userbot')
        _svc_txt = (
            f'🤖 <b>خدمة مستخدمين البوت</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'💰 السعر : <b>{_pr * 100}</b> نقطة لكل 100\n'
            f'📉 الحد الأدنى : <b>{_mn}</b>\n'
            f'📈 الحد الأقصى : <b>{_mx}</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'أرسل الآن العدد الذي تريده (<b>{_mn}</b> - <b>{_mx}</b>):'
        )
        db.set(f'userbot_{cid}_proccess', True)
        x = bot.edit_message_text(text=_svc_txt, reply_markup=_bk_cancel_svc('vips'), chat_id=cid, message_id=mid, parse_mode="HTML")
        bot.register_next_step_handler(x, get_amount, 'userbot')
    if data == 'linkbot':
        _pr = svc_price('linkbot'); _mn = svc_min('linkbot'); _mx = svc_max('linkbot')
        _svc_txt = (
            f'⚡️ <b>رشق بلص | إحالات حقيقية اشتراك إجباري</b>\n\n'
            f'🔑 <b>الباقة المجانية</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'💰 السعر : <b>{_pr * 100}</b> نقطة لكل 100\n'
            f'📉 الحد الأدنى : <b>{_mn}</b> إحالة\n'
            f'📈 الحد الأقصى : <b>{_mx}</b> إحالة\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'📨 أرسل الآن العدد المطلوب\n'
            f'<b>( {_mn} - {_mx} )</b>'
        )
        db.set(f'linkbot_{cid}_proccess', True)
        x = bot.edit_message_text(text=_svc_txt, reply_markup=_bk_cancel_svc('normal'), chat_id=cid, message_id=mid, parse_mode="HTML")
        bot.register_next_step_handler(x, get_amount, 'linkbot')
    if data == 'comments':
        _vip_info = db.get(f'user_{cid}')
        _is_prem = _vip_info.get('premium', False) if _vip_info else False
        if not _is_prem:
            _inv_count = len(_vip_info.get('users', [])) if _vip_info else 0
            _vip_thresh = int(db.get('vip_invite_threshold')) if db.exists('vip_invite_threshold') else 2
            _remaining = max(0, _vip_thresh - _inv_count)
            _keys_vip = mk(row_width=1)
            _keys_vip.add(btn('🔮 رابط الدعوة', callback_data='share_link', color='green'))
            _keys_vip.add(btn('رجوع', callback_data='vips', color='blue'))
            bot.edit_message_text(
                text=(
                    '👑 لازم تعمل دعوتين عشان تفعل قسم VIP\n\n'
                    f'📊 دعواتك: {_inv_count} من {_vip_thresh} المطلوبة\n'
                    f'🎯 باقي عليك: {_remaining} دعوة فقط للحصول على VIP مجاناً!\n\n'
                    '💡 شارك رابط الدعوة وادعُ أصدقاءك للحصول على VIP تلقائياً'
                ),
                chat_id=cid, message_id=mid, reply_markup=_keys_vip, parse_mode="HTML"
            )
            return
        _pr = svc_price('comments'); _mn = svc_min('comments'); _mx = svc_max('comments')
        _svc_txt = (
            f'💬 <b>خدمة تعليقات</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'💰 السعر : <b>{_pr * 100}</b> نقطة لكل 100\n'
            f'📉 الحد الأدنى : <b>{_mn}</b>\n'
            f'📈 الحد الأقصى : <b>{_mx}</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'أرسل الآن العدد الذي تريده (<b>{_mn}</b> - <b>{_mx}</b>):'
        )
        db.set(f'comments_{cid}_proccess', True)
        x = bot.edit_message_text(text=_svc_txt, reply_markup=_bk_cancel_svc('vips'), chat_id=cid, message_id=mid, parse_mode="HTML")
        bot.register_next_step_handler(x, get_amount, 'comments')
    if data == 'lvallc':
        _lvall_kb = mk(row_width=1)
        _lvall_kb.add(btn('🔙 رجوع للوحة الأدمن', callback_data='adm_cat_general', color='red'))
        bot.edit_message_text(text='⏳ جارٍ مغادرة كل القنوات والمجموعات...', chat_id=cid, message_id=mid, reply_markup=_lvall_kb)
        acc = db.get('accounts') or []
        true = 0
        for amount in acc:
            try:
                true += 1
                _pyro_run(leave_chats(amount['s']))
            except Exception as e:
                print(e)
                continue
        bot.send_message(chat_id=call.from_user.id, text=f'✅ تم بنجاح الخروج من كل القنوات والمجموعات\n• تم الخروج من <code>{true}</code> حساب بنجاح', parse_mode='HTML')
    if data == 'cancel':
        _cancel_kb = mk(row_width=1)
        _cancel_kb.add(btn('🔙 رجوع للوحة الأدمن', callback_data='adm_cat_general', color='red'))
        bot.edit_message_text(text='❌ تم إلغاء عملية المغادرة', chat_id=cid, message_id=mid, reply_markup=_cancel_kb)
    if data == 'linkbot2':
        _vip_info = db.get(f'user_{cid}')
        _is_prem = _vip_info.get('premium', False) if _vip_info else False
        if not _is_prem:
            _inv_count = len(_vip_info.get('users', [])) if _vip_info else 0
            _vip_thresh = int(db.get('vip_invite_threshold')) if db.exists('vip_invite_threshold') else 2
            _remaining = max(0, _vip_thresh - _inv_count)
            _keys_vip = mk(row_width=1)
            _keys_vip.add(btn('🔮 رابط الدعوة', callback_data='share_link', color='green'))
            _keys_vip.add(btn('رجوع', callback_data='vips', color='blue'))
            bot.edit_message_text(
                text=(
                    '👑 لازم تعمل دعوتين عشان تفعل قسم VIP\n\n'
                    f'📊 دعواتك: {_inv_count} من {_vip_thresh} المطلوبة\n'
                    f'🎯 باقي عليك: {_remaining} دعوة فقط للحصول على VIP مجاناً!\n\n'
                    '💡 شارك رابط الدعوة وادعُ أصدقاءك للحصول على VIP تلقائياً'
                ),
                chat_id=cid, message_id=mid, reply_markup=_keys_vip, parse_mode="HTML"
            )
            return
        db.set(f'linkbot2_{cid}_proccess', True)
        _pr2 = svc_price('linkbot2')
        _pr2_100 = _pr2 * 100
        x = bot.edit_message_text(
            text=(
                '👑 <b>رشق بلص | إحالات حقيقية اشتراك إجباري</b>\n\n'
                '💎 <b>الباقة VIP</b>\n'
                '━━━━━━━━━━━━━━━━━━━\n'
                '🚀 إحالات حقيقية بجودة عالية\n'
                '✅ اشتراك إجباري مضمون\n'
                f'💰 السعر : <b>{_pr2 * 100}</b> نقطة لكل 100\n'
                '━━━━━━━━━━━━━━━━━���━\n\n'
                '📨 أرسل الآن العدد المطلوب'
            ),
            reply_markup=_bk_cancel_svc('vips'), chat_id=cid, message_id=mid, parse_mode="HTML"
        )
        bot.register_next_step_handler(x, get_amount, 'linkbot2')
    if data == 'dump_votes':
        x = bot.edit_message_text(text='• ارسل الان رابط المنشور الذي تريد سحب اصواته', chat_id=cid, message_id=mid, reply_markup=bk_cancel_adm)
        bot.register_next_step_handler(x, dump_votes)

    # ⚙️ لوحة إعدادات الخدمات (السعر / الحد الأدنى / الأقصى)

    if data == 'adm_svc_panel':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        skeys = mk(row_width=1)
        for svc_key, svc_info in SERVICES.items():
            p  = svc_price(svc_key)
            mn = svc_min(svc_key)
            mx = svc_max(svc_key)
            on = svc_enabled(svc_key)
            status_icon = '🟢' if on else '🔴'
            price_str = f'💰{p}/عضو' if svc_key == 'free_member' else f'💰{p * 100}/100'
            skeys.add(btn(f'{status_icon} {svc_info["label"]} | {price_str} | {mn}~{mx}', callback_data=f'svc_pick_{svc_key}', color='green' if on else 'red'))
        skeys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_settings', color='blue'))
        bot.edit_message_text(
            text='⚙️ إعدادات الخدمات\n\nاضغط على أي خدمة لتعديل سعرها أو حدودها أو تفعيلها/تعطيلها\n\n🟢 = مفعّلة  |  🔴 = معطّلة\nا��تنسيق: 💰السعر لكل وحدة | الحد الأدنى ~ الأقصى',
            chat_id=cid, message_id=mid, reply_markup=skeys
        )

    if data.startswith('svc_pick_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        svc_key = data.replace('svc_pick_', '')
        if svc_key not in SERVICES:
            return
        svc_info = SERVICES[svc_key]
        p  = svc_price(svc_key)
        mn = svc_min(svc_key)
        mx = svc_max(svc_key)
        on = svc_enabled(svc_key)
        toggle_lbl = '🔴 تعطيل الخدمة' if on else '🟢 تفعيل الخدمة'
        toggle_col = 'red' if on else 'green'
        status_txt = '🟢 مفعّلة' if on else '🔴 معطّلة'
        skeys = mk(row_width=1)
        if svc_key == 'free_member':
            skeys.add(btn(f'💰 تعديل السعر لكل عضو (الحالي: {p})', callback_data=f'svc_edit_price_{svc_key}', color='green'))
            price_line = f'{p} نقطة / عضو'
        else:
            p100 = p * 100
            skeys.add(btn(f'💰 تعديل السعر لكل 100 (الحالي: {p100})', callback_data=f'svc_edit_price1000_{svc_key}', color='green'))
            price_line = f'{p100} نقطة لكل 100'
        skeys.add(btn(f'⬇️ تعديل الحد الأدنى (الحالي: {mn})', callback_data=f'svc_edit_min_{svc_key}', color='blue'))
        skeys.add(btn(f'⬆️ تعديل ال��د الأقصى (الحالي: {mx})', callback_data=f'svc_edit_max_{svc_key}', color='blue'))
        skeys.add(btn(toggle_lbl, callback_data=f'svc_toggle_{svc_key}', color=toggle_col))
        skeys.add(btn('🔄 إعادة القيم الافتراضية', callback_data=f'svc_reset_{svc_key}', color='red'))
        skeys.add(btn('🔙 رجوع للخدمات', callback_data='adm_svc_panel', color='blue'))
        bot.edit_message_text(
            text=f'⚙️ خدمة: {svc_info["label"]}\n\n📌 الحالة: {status_txt}\n💰 السعر: {price_line}\n⬇️ الحد الأدنى: {mn}\n⬆️ الحد الأقصى: {mx}\n\nاختر ما تريد تعديله:',
            chat_id=cid, message_id=mid, reply_markup=skeys
        )

    if data.startswith('svc_edit_price_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        svc_key = data.replace('svc_edit_price_', '')
        if svc_key not in SERVICES:
            return
        skeys = mk(row_width=1)
        skeys.add(btn('رجوع', callback_data=f'svc_pick_{svc_key}', color='blue'))
        p = svc_price(svc_key)
        if svc_key == 'free_member':
            x = bot.edit_message_text(
                text=f'💰 تعديل سعر خدمة: {SERVICES[svc_key]["label"]}\nالسعر الحالي: {p} نقطة / عضو\n\nأرسل ال��عر الجديد لكل عضو (رقم فقط):',
                chat_id=cid, message_id=mid, reply_markup=skeys
            )
            bot.clear_step_handler_by_chat_id(cid)
            bot.register_next_step_handler(x, _do_svc_edit, svc_key, 'price_direct')
        else:
            x = bot.edit_message_text(
                text=f'💰 تعديل سعر خدمة: {SERVICES[svc_key]["label"]}\nالسعر الحالي: {p * 100} نقطة لكل 100\n\nمثال: 50 يعني 50 نقطة لكل 100\n\nأرسل السعر الجديد لكل 100 (رقم فقط):',
                chat_id=cid, message_id=mid, reply_markup=skeys
            )
            bot.clear_step_handler_by_chat_id(cid)
            bot.register_next_step_handler(x, _do_svc_edit, svc_key, 'price')

    if data.startswith('svc_edit_price1000_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        svc_key = data.replace('svc_edit_price1000_', '')
        if svc_key not in SERVICES:
            return
        skeys = mk(row_width=1)
        skeys.add(btn('رجوع', callback_data=f'svc_pick_{svc_key}', color='blue'))
        p = svc_price(svc_key)
        p100 = p * 100
        x = bot.edit_message_text(
            text=f'💰 تعديل سعر خدمة: {SERVICES[svc_key]["label"]}\nالسعر الحالي: {p100} نقطة لكل 100\n\nأرسل السعر الجديد لكل 100 (رقم فقط):',
            chat_id=cid, message_id=mid, reply_markup=skeys
        )
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_svc_edit, svc_key, 'price1000')

    if data.startswith('svc_edit_min_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        svc_key = data.replace('svc_edit_min_', '')
        if svc_key not in SERVICES:
            return
        skeys = mk(row_width=1)
        skeys.add(btn('رجوع', callback_data=f'svc_pick_{svc_key}', color='blue'))
        mn = svc_min(svc_key)
        x = bot.edit_message_text(
            text=f'⬇️ تعديل الحد الأدنى لـ: {SERVICES[svc_key]["label"]}\nالحالي: {mn}\n\nأرسل الحد الأدنى الجديد (رقم فقط):',
            chat_id=cid, message_id=mid, reply_markup=skeys
        )
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_svc_edit, svc_key, 'min')

    if data.startswith('svc_edit_max_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        svc_key = data.replace('svc_edit_max_', '')
        if svc_key not in SERVICES:
            return
        skeys = mk(row_width=1)
        skeys.add(btn('رجوع', callback_data=f'svc_pick_{svc_key}', color='blue'))
        mx = svc_max(svc_key)
        x = bot.edit_message_text(
            text=f'⬆️ تعديل الحد الأقصى لـ: {SERVICES[svc_key]["label"]}\nالحالي: {mx}\n\nأرسل الحد الأقصى الجديد (رقم فقط):',
            chat_id=cid, message_id=mid, reply_markup=skeys
        )
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_svc_edit, svc_key, 'max')

    if data.startswith('svc_reset_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        svc_key = data.replace('svc_reset_', '')
        if svc_key not in SERVICES:
            return
        svc_info = SERVICES[svc_key]
        db.delete(svc_info["price_key"])
        db.delete(svc_info["min_key"])
        db.delete(svc_info["max_key"])
        skeys = mk(row_width=1)
        skeys.add(btn('🔙 رجوع للخدمة', callback_data=f'svc_pick_{svc_key}', color='blue'))
        bot.edit_message_text(
            text=f'✅ تم إعادة إعدادات {svc_info["label"]} للقيم الافتراضية\n💰 السعر: {svc_info["default_price"]} | {svc_info["default_min"]}~{svc_info["default_max"]}',
            chat_id=cid, message_id=mid, reply_markup=skeys
        )

    if data.startswith('svc_toggle_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        svc_key = data.replace('svc_toggle_', '')
        if svc_key not in SERVICES:
            return
        svc_info = SERVICES[svc_key]
        current = svc_enabled(svc_key)
        new_state = not current
        ekey = svc_info.get("enabled_key", f"svc_enabled_{svc_key}")
        db.set(ekey, new_state)
        state_txt = '🟢 مفعّلة' if new_state else '🔴 معطّلة'
        try:
            _cb_alert(call, text=f'تم تغيير حالة {svc_info["label"]} إلى: {state_txt}', show_alert=True)
        except:
            pass
        # أعد تحميل صفحة الخدمة
        p  = svc_price(svc_key)
        mn = svc_min(svc_key)
        mx = svc_max(svc_key)
        on = new_state
        toggle_lbl = '🔴 تعطيل الخدمة' if on else '🟢 تفعيل الخدمة'
        toggle_col = 'red' if on else 'green'
        skeys2 = mk(row_width=1)
        skeys2.add(btn(f'💰 تعديل السعر (الحالي: {p})', callback_data=f'svc_edit_price_{svc_key}', color='green'))
        skeys2.add(btn(f'⬇️ تعديل الحد الأدنى (الحالي: {mn})', callback_data=f'svc_edit_min_{svc_key}', color='blue'))
        skeys2.add(btn(f'⬆️ تعديل الحد الأقصى (الحالي: {mx})', callback_data=f'svc_edit_max_{svc_key}', color='blue'))
        skeys2.add(btn(toggle_lbl, callback_data=f'svc_toggle_{svc_key}', color=toggle_col))
        skeys2.add(btn('🔄 إعادة القيم الافتراضية', callback_data=f'svc_reset_{svc_key}', color='red'))
        skeys2.add(btn('🔙 رجوع للخدمات', callback_data='adm_svc_panel', color='blue'))
        try:
            bot.edit_message_text(
                text=f'⚙️ خدمة: {svc_info["label"]}\n\n📌 الحالة: {state_txt}\n💰 السعر لكل وحدة: {p} نقطة\n⬇️ الحد الأدنى: {mn}\n⬆️ الحد الأقصى: {mx}\n\nاختر ما تريد تعديله:',
                chat_id=cid, message_id=mid, reply_markup=skeys2
            )
        except:
            pass

    # 💰 لوحة إعدادات الشحن

    if data == 'adm_charge_panel':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        stars_rate   = int(db.get("charge_stars_rate"))   if db.exists("charge_stars_rate")   else 600
        stars_post   = db.get("charge_stars_post")         if db.exists("charge_stars_post")   else "غير محدد"
        cash_rate    = int(db.get("charge_cash_rate"))    if db.exists("charge_cash_rate")     else 150000
        usdt_rate    = int(db.get("charge_usdt_rate"))    if db.exists("charge_usdt_rate")     else 150000
        usdt_wallet  = db.get("charge_usdt_wallet")        if db.exists("charge_usdt_wallet")  else "غير محدد"
        vf_rate      = int(db.get("charge_vf_rate"))      if db.exists("charge_vf_rate")      else 1000
        vf_number    = db.get("charge_vf_number")          if db.exists("charge_vf_number")   else "غير محدد"
        vip_monthly  = int(db.get("vip_monthly_price"))    if db.exists("vip_monthly_price")  else 5000
        vip_yearly   = int(db.get("vip_yearly_price"))     if db.exists("vip_yearly_price")   else 40000
        vip_lifetime = int(db.get("vip_lifetime_price"))   if db.exists("vip_lifetime_price") else 100000
        vip_sub_on   = db.get("vip_sub_enabled")           if db.exists("vip_sub_enabled")    else True
        orders_ch    = db.get("orders_channel_id")          if db.exists("orders_channel_id")  else "غير محدد"
        vip_toggle_lbl = '🔴 تعطيل شراء VIP بالنقاط' if vip_sub_on else '🟢 تفعيل شراء VIP بالنقاط'
        vip_toggle_col = 'red' if vip_sub_on else 'green'
        ckeys = mk(row_width=1)
        ckeys.add(btn('━━━ ⭐ النجوم ━━━', callback_data='none', color='blue'))
        ckeys.add(btn('سعر النجوم (نجمة = كم نقطة)', callback_data='chset_stars_rate', color='green'))
        ckeys.add(btn('⭐ منشور استقبال النجوم', callback_data='chset_stars_post', color='green'))
        ckeys.add(btn('━━━ 📱 فودافون كاش ━━━', callback_data='none', color='blue'))
        ckeys.add(btn(f'سعر فودافون كاش (1 جنيه = {vf_rate} ن)', callback_data='chset_vf_rate', color='red'))
        ckeys.add(btn(f'رقم فودافون: {vf_number}', callback_data='chset_vf_number', color='red'))
        ckeys.add(btn('معرف تواصل فودافون كاش', callback_data='chset_vf_contact', color='red'))
        ckeys.add(btn('━━━ 💵 كاش / USDT ━━━', callback_data='none', color='blue'))
        ckeys.add(btn('سعر الكاش ($ = كم نقطة)', callback_data='chset_cash_rate', color='blue'))
        ckeys.add(btn('معرف تواصل الكاش', callback_data='chset_cash_contact', color='blue'))
        ckeys.add(btn('سعر USDT (USDT = كم نقطة)', callback_data='chset_usdt_rate', color='blue'))
        ckeys.add(btn('محفظة USDT (TRC20)', callback_data='chset_usdt_wallet', color='blue'))
        ckeys.add(btn('معلومات الوكيل', callback_data='chset_agent_info', color='green'))
        ckeys.add(btn('━━━ 👑 اشتراك VIP بالنقاط ━━━', callback_data='none', color='blue'))
        ckeys.add(btn(f'سعر الشهري ({vip_monthly:,} نقطة)', callback_data='chset_vip_monthly', color='green'))
        ckeys.add(btn(f'سعر السنوي ({vip_yearly:,} نقطة)', callback_data='chset_vip_yearly', color='green'))
        ckeys.add(btn(f'سعر مدى الحياة ({vip_lifetime:,} نقطة)', callback_data='chset_vip_lifetime', color='green'))
        ckeys.add(btn(vip_toggle_lbl, callback_data='chset_vip_toggle', color=vip_toggle_col))
        ckeys.add(btn('━━���━━━━━━━━━━━', callback_data='none', color='blue'))
        ckeys.add(btn(f'📢 قناة الطلبات (ID: {orders_ch})', callback_data='chset_orders_channel', color='blue'))
        ckeys.add(btn('👁 عرض كل الإعدادات', callback_data='chset_view', color='blue'))
        ckeys.add(btn('🔙 رجوع للوحة', callback_data='adm_cat_settings', color='red'))
        txt = (
            "💰 إعدادات الشحن والاشتراكات\n\n"
            f"⭐ النجوم: 1 نجمة = {stars_rate} نقطة\n"
            f"📱 فودافون كاش: 1 جنيه = {vf_rate} نقطة | رقم: {vf_number}\n"
            f"💵 الكاش: $1 = {cash_rate} نقطة\n"
            f"💎 USDT: 1 USDT = {usdt_rate} نقطة\n\n"
            f"👑 VIP شهري: {vip_monthly:,} | سنوي: {vip_yearly:,} | حياة: {vip_lifetime:,}\n"
            f"📌 شراء VIP: {'✅ مفعّل' if vip_sub_on else '❌ معطّل'}"
        )
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=ckeys, parse_mode="HTML")
        return

    if data == 'chset_vip_toggle':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        current = db.get("vip_sub_enabled") if db.exists("vip_sub_enabled") else True
        db.set("vip_sub_enabled", not current)
        new_state = '✅ مفعّل' if not current else '❌ معطّل'
        _cb_alert(call, text=f'تم تغيير حالة شراء VIP إلى: {new_state}', show_alert=True)
        # أعد تحميل اللوحة
        call.data = 'adm_charge_panel'
        data = 'adm_charge_panel'

    if data == 'chset_view':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        stars_rate   = int(db.get("charge_stars_rate"))   if db.exists("charge_stars_rate")   else 600
        stars_post   = db.get("charge_stars_post")         if db.exists("charge_stars_post")   else "غير محدد"
        cash_rate    = int(db.get("charge_cash_rate"))    if db.exists("charge_cash_rate")     else 150000
        cash_contact = db.get("charge_cash_contact")       if db.exists("charge_cash_contact") else "غير محدد"
        usdt_rate    = int(db.get("charge_usdt_rate"))    if db.exists("charge_usdt_rate")     else 150000
        usdt_wallet  = db.get("charge_usdt_wallet")        if db.exists("charge_usdt_wallet")  else "غير محدد"
        agent_info   = db.get("charge_agent_info")         if db.exists("charge_agent_info")   else "غير محدد"
        vf_rate      = int(db.get("charge_vf_rate"))      if db.exists("charge_vf_rate")      else 1000
        vf_number    = db.get("charge_vf_number")          if db.exists("charge_vf_number")   else "غير محدد"
        vf_contact   = db.get("charge_vf_contact")         if db.exists("charge_vf_contact")  else "غير محدد"
        vip_monthly  = int(db.get("vip_monthly_price"))    if db.exists("vip_monthly_price")  else 5000
        vip_yearly   = int(db.get("vip_yearly_price"))     if db.exists("vip_yearly_price")   else 40000
        vip_lifetime = int(db.get("vip_lifetime_price"))   if db.exists("vip_lifetime_price") else 100000
        vip_sub_on   = db.get("vip_sub_enabled")           if db.exists("vip_sub_enabled")    else True
        ckeys = mk(row_width=1)
        ckeys.add(btn('🔙 رجوع لإعدادات الشحن', callback_data='adm_charge_panel', color='blue'))
        txt = (
            "📋 كل إعدادات الشحن\n\n"
            f"⭐ النجوم: 1 نجمة = {stars_rate} نقطة\n"
            f"📮 منشور النجوم: {stars_post}\n\n"
            f"📱 فودافون كاش: 1 جنيه = {vf_rate} نقطة\n"
            f"📲 رقم فودافون: {vf_number}\n"
            f"👤 تواصل فودافون: @{vf_contact}\n\n"
            f"💵 الكاش: $1 = {cash_rate} نقطة\n"
            f"👤 تواصل الكاش: @{cash_contact}\n\n"
            f"💎 USDT: 1 USDT = {usdt_rate} نقطة\n"
            f"🔑 محفظة USDT: {usdt_wallet}\n\n"
            f"🤝 الوكيل: {agent_info}\n\n"
            f"👑 VIP شهري: {vip_monthly:,} نقطة\n"
            f"👑 VIP سنوي: {vip_yearly:,} نقطة\n"
            f"👑 VIP مدى الحياة: {vip_lifetime:,} نقطة\n"
            f"📌 شراء VIP: {'✅ مفعّل' if vip_sub_on else '❌ معطّل'}"
        )
        bot.edit_message_text(text=txt, chat_id=cid, message_id=mid, reply_markup=ckeys, parse_mode="HTML")

    for _chset_key, _chset_label, _chset_prompt, _db_key in [
        ('chset_stars_rate',     'سعر النجوم',                  'أرسل عدد النقاط مقابل كل نجمة (مثال: 600):',               'charge_stars_rate'),
        ('chset_stars_post',     'منشور استقبال النجوم',         'أرسل رابط المنشور لاستقبال ال��جوم:',                       'charge_stars_post'),
        ('chset_cash_rate',      'سعر الكاش',                   'أرسل عدد النقاط مقابل كل $1 (مثال: 150000):',              'charge_cash_rate'),
        ('chset_usdt_rate',      'سعر USDT',                    'أرسل عدد النقاط مقابل كل 1 USDT (مثال: 150000):',          'charge_usdt_rate'),
        ('chset_cash_contact',   'معرف تواصل الكاش',             'أرسل معرف تيليجرام للتواصل للكاش (بدون @):',              'charge_cash_contact'),
        ('chset_usdt_wallet',    'محفظة USDT',                   'أرسل عنوان محفظة USDT (TRC20):',                          'charge_usdt_wallet'),
        ('chset_agent_info',     'معلومات الوكيل',                'أرسل نص معلومات الشحن عبر الوكيل:',                       'charge_agent_info'),
        ('chset_orders_channel', 'قناة الطلبات',                  'أرسل ID القناة (مثال: -1001234567890)\nتأكد أن البوت أدمن في القناة:', 'orders_channel_id'),
        ('chset_logs_channel',   'قناة سجل الأزرار',               'أرسل ID قناة اللوجز (مثال: -1001234567890)\nتأكد أن البوت أدمن في القناة:', 'logs_channel_id'),
        ('chset_vf_rate',        'سعر فودافون كاش',               'أرسل عدد النقاط مقابل كل 1 جنيه (مثال: 1000):',           'charge_vf_rate'),
        ('chset_vf_number',      'رقم فودافون كاش',               'أرسل رقم فودافون كاش الذي يستلم التحويلات:',              'charge_vf_number'),
        ('chset_vf_contact',     'معرف تواصل فودافون كاش',        'أرسل معرف تيليجرام للتواصل بخصوص فودافون كاش (بدون @):', 'charge_vf_contact'),
        ('chset_vip_monthly',    'سعر اشتراك VIP الشهري',         'أرسل عدد النقاط للاشتراك الشهري (مثال: 5000):',           'vip_monthly_price'),
        ('chset_vip_yearly',     'سعر اشتراك VIP السنوي',         'أرسل عدد النقاط للاشتراك السنوي (مثال: 40000):',          'vip_yearly_price'),
        ('chset_vip_lifetime',   'سعر اشتراك VIP مدى الحياة',     'أرسل عدد النقاط للاشتراك مدى الحياة (مثال: 100000):',    'vip_lifetime_price'),
    ]:
        if data == _chset_key:
            if cid not in (db.get("admins") or []) and cid != sudo:
                return
            ckeys = mk(row_width=1)
            ckeys.add(btn('رجوع', callback_data='adm_charge_panel', color='blue'))
            x = bot.edit_message_text(
                text=f'⚙️ تعديل: {_chset_label}\n\n{_chset_prompt}',
                chat_id=cid, message_id=mid, reply_markup=ckeys
            )
            bot.clear_step_handler_by_chat_id(cid)
            bot.register_next_step_handler(x, _do_charge_setting, _db_key)

    # 🎛️ لوحة تخصيص الأزرار (الألوان + الأسماء معاً)

    if data == 'adm_btn_panel':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        keys = mk(row_width=2)
        keys.add(
            btn('🎨 تغيير ألوان الأزرار', callback_data='adm_colors', color='blue'),
            btn('✏️ تغيير أسماء الأزرار', callback_data='adm_rename', color='green'),
        )
        keys.add(btn('✨ رموز تعبيرية مميزة للأزرار', callback_data='adm_emoji', color='green'))
        keys.add(btn('🔀 ترتيب أزرار القائمة الرئيسية', callback_data='adm_menu_order', color='blue'))
        keys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_settings', color='blue'))
        # عرض كل الأزرار مع لونها واسمها الحالي
        txt = '🎛️ *لوحة تخصيص الأزرار*\n\n'
        txt += '📋 *الأزرار الحالية:*\n'
        for cb, default_label in BTN_KEYS.items():
            cur_label = _get_btn_label(cb, default=default_label)
            cur_color = _get_btn_color(cb, "blue")
            color_icon = "🟢" if cur_color == "green" else "🔴" if cur_color == "red" else "🔵"
            txt += f'{color_icon} {cur_label}\n'
        txt += '\n💡 اختر ما تريد تعديله:'
        bot.edit_message_text(
            text=txt,
            chat_id=cid, message_id=mid,
            reply_markup=keys, parse_mode='Markdown'
        )

    if data == 'adm_colors':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        keys = mk(row_width=1)
        for cb, label in BTN_KEYS.items():
            cur = _get_btn_color(cb, "blue")
            color_icon = "🟢" if cur == "green" else "🔴" if cur == "red" else "🔵"
            keys.add(btn(f'{color_icon} {label}', callback_data=f'clr_pick_{cb}', color=cur))
        keys.add(btn('🔙 رجوع للتخصيص', callback_data='adm_btn_panel', color='blue'))
        bot.edit_message_text(
            text='🎨 *تحكم في ألوان الأزرار*\n\nاضغط على أي زر لتغيير لونه',
            chat_id=cid, message_id=mid,
            reply_markup=keys, parse_mode='Markdown'
        )

    if data.startswith('clr_pick_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cb_target = data.replace('clr_pick_', '')
        if cb_target not in BTN_KEYS:
            return
        label = BTN_KEYS[cb_target]
        cur = _get_btn_color(cb_target, "blue")
        keys = mk(row_width=3)
        keys.add(
            btn('��� أخضر', callback_data=f'clr_set_{cb_target}_green', color='green'),
            btn('🔴 أحمر', callback_data=f'clr_set_{cb_target}_red',   color='red'),
            btn('🔵 أزرق', callback_data=f'clr_set_{cb_target}_blue',  color='blue'),
        )
        keys.add(btn('🔙 رجوع للألوان', callback_data='adm_colors', color='blue'))
        color_icon = "🟢" if cur == "green" else "🔴" if cur == "red" else "🔵"
        bot.edit_message_text(
            text=f'🎨 اختر لون الزر:\n\n*{label}*\nاللون الحالي: {color_icon}',
            chat_id=cid, message_id=mid,
            reply_markup=keys, parse_mode='Markdown'
        )

    if data.startswith('clr_set_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        # clr_set_<callback>_<color>
        parts = data.replace('clr_set_', '').rsplit('_', 1)
        if len(parts) != 2:
            return
        cb_target, new_color = parts
        if cb_target not in BTN_KEYS or new_color not in _STYLE_MAP:
            return
        db.set(f'btn_color_{cb_target}', new_color)
        label = BTN_KEYS[cb_target]
        color_icon = "🟢" if new_color == "green" else "🔴" if new_color == "red" else "🔵"
        # رجوع لقائمة الألوان
        keys = mk(row_width=1)
        for cb, lbl in BTN_KEYS.items():
            cur = _get_btn_color(cb, "blue")
            ci = "🟢" if cur == "green" else "🔴" if cur == "red" else "🔵"
            keys.add(btn(f'{ci} {lbl}', callback_data=f'clr_pick_{cb}', color=cur))
        keys.add(btn('🔙 رجوع للألوان', callback_data='adm_colors', color='blue'))
        bot.edit_message_text(
            text=f'✅ تم تغيير لون *{label}* إلى {color_icon}\n\n🎨 *تحكم في ألوان الأزرار*\n\nاضغط على أي زر لتغيير لونه',
            chat_id=cid, message_id=mid,
            reply_markup=keys, parse_mode='Markdown'
        )

    if data in ('adm_back_main', 'admin'):
        # 'admin' كان مستخدَم في أزرار رجوع كتير من غير معالج → كانت مش بتشتغل
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        try:
            bot.clear_step_handler_by_chat_id(cid)
        except Exception:
            pass
        _show_admin_panel(cid, is_edit=True, mid=mid)

    elif data.startswith('adm_cat_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        try:
            bot.clear_step_handler_by_chat_id(cid)
        except Exception:
            pass
        _show_admin_category(cid, mid, data)

    elif data == 'adm_toggle_maintenance':
        if cid not in (db.get("admins") or []) and cid != sudo:
            _cb_alert(call, '❌ غير مصرح', show_alert=True)
            return
        current = db.get('maintenance_mode')
        db.set('maintenance_mode', not current)
        status = 'مفعّل 🔴' if not current else 'معطّل 🟢'
        try:
            _cb_alert(call, f'وضع الصيانة {status}', show_alert=True)
        except:
            pass
        _show_admin_panel(cid, is_edit=True, mid=mid)

    # 📦 تصدير قاعدة البيانات JSON

    if data == 'adm_export_db':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        try:
            _cb_alert(call, "⏳ جارٍ التصدير...", show_alert=False)
        except:
            pass
        _send_db_export_file(cid, export_type="all", label="الكل")

    if data in ('adm_export_users', 'adm_export_accounts', 'adm_export_settings', 'adm_export_all'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        _labels = {
            'adm_export_users':    ("users",    "المستخدمين"),
            'adm_export_accounts': ("accounts", "الحسابات"),
            'adm_export_settings': ("settings", "الإعدادات"),
            'adm_export_all':      ("all",      "الكل"),
        }
        exp_type, exp_label = _labels[data]
        try:
            _cb_alert(call, "⏳ جارٍ التصدير...", show_alert=False)
        except:
            pass
        _send_db_export_file(cid, export_type=exp_type, label=exp_label)

    # 📥 استيراد قاعدة البيانات

    if data == 'adm_import_db':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        _handle_import_db_panel(call)

    if data == 'adm_reset_coins':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        # تأكيد قبل التنفيذ
        confirm_kb = mk(row_width=2)
        confirm_kb.add(
            btn('✅ نعم، صفّر الجميع', callback_data='adm_reset_coins_confirm', color='red'),
            btn('إلغاء', callback_data='admin', color='green')
        )
        bot.edit_message_text(
            chat_id=cid, message_id=mid,
            text='⚠️ <b>تحذير!</b>\n\nهذا الإجراء سيصفّر نقاط <b>جميع المستخدمين</b> ولا يمكن التراجع عنه!\n\nهل أنت متأكد؟',
            reply_markup=confirm_kb, parse_mode='HTML'
        )

    if data == 'adm_reset_coins_confirm':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        _cb_alert(call, '⏳ جارٍ التصفير...', show_alert=False)
        try:
            count = 0
            all_keys = db.keys('user_%')
            for key_tuple in all_keys:
                key = key_tuple[0]
                try:
                    udata = db.get(key)
                    if isinstance(udata, dict) and 'coins' in udata:
                        udata['coins'] = 0
                        db.set(key, udata)
                        count += 1
                except:
                    continue
            back_kb = mk(row_width=1)
            back_kb.add(btn('🔙 رجوع للوحة الأدمن', callback_data='admin', color='blue'))
            bot.edit_message_text(
                chat_id=cid, message_id=mid,
                text=f'✅ <b>تم بنجاح!</b>\n\nتم تصفير نقاط <b>{count:,}</b> مستخدم.',
                reply_markup=back_kb, parse_mode='HTML'
            )
        except Exception as _e:
            _reset_err_kb = mk(row_width=1)
            _reset_err_kb.add(btn('🔙 رجوع للوحة الأدمن', callback_data='adm_cat_points', color='red'))
            bot.edit_message_text(
                chat_id=cid, message_id=mid,
                text=f'❌ خطأ: {_e}',
                reply_markup=_reset_err_kb, parse_mode='HTML'
            )

    if data.startswith('adm_import_type_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        import_type = data.replace('adm_import_type_', '')  # users / accounts / settings / all
        db.set(f"_import_type_{cid}", import_type)
        _type_labels = {
            "users":    "المستخدمين",
            "accounts": "الحسابات (الأرقام)",
            "settings": "الإعدادات",
            "all":      "الكل",
        }
        label = _type_labels.get(import_type, import_type)
        try:
            _cb_alert(call, f"✅ اخترت: {label}", show_alert=False)
        except:
            pass
        bot.edit_message_text(
            chat_id=cid, message_id=mid,
            text=(
                f"📥 <b>استيراد {label}</b>\n\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                "أرسل الآن ملف JSON الذي صدّرته من البوت\n\n"
                "<i>يجب أن يكون الملف من تصدير /exportdb</i>"
            ),
            parse_mode="HTML",
            reply_markup=bk_cancel_adm
        )
        bot.register_next_step_handler_by_chat_id(cid, _handle_import_db_file)

    if data.startswith('adm_import_confirm_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        import_type = data.replace('adm_import_confirm_', '')
        pending_key = f"_import_pending_{cid}"
        if not db.exists(pending_key):
            _cb_alert(call, "❌ انتهت صلاحية الاستيراد، أعد إرسال الملف", show_alert=True)
            return
        import json as _json
        try:
            raw   = db.get(pending_key)
            jdata = _json.loads(raw)
        except Exception as e:
            _cb_alert(call, f"❌ خطأ في قراءة البيانات: {e}", show_alert=True)
            db.delete(pending_key)
            return
        db.delete(pending_key)
        try:
            _cb_alert(call, "⏳ جارٍ الاستيراد...", show_alert=False)
        except:
            pass
        bot.edit_message_text(
            chat_id=cid, message_id=mid,
            text="⏳ <b>جارٍ الاستيراد... انتظر لحظة</b>",
            parse_mode="HTML"
        )
        try:
            res = _import_db_from_json(jdata, import_type=import_type)
            errors_txt = ""
            if res["errors"]:
                errors_txt = "\n\n⚠️ أخطاء:\n" + "\n".join(f"• {e}" for e in res["errors"][:5])
            done_keys = mk(row_width=1)
            done_keys.add(btn("🔙 العودة للوحة", callback_data="adm_cat_database", color="blue"))
            bot.edit_message_text(
                chat_id=cid, message_id=mid,
                text=(
                    "✅ <b>اكتمل ال��ستيراد!</b>\n\n"
                    "━━━━━━━━━━━━━━━━━━━\n"
                    f"👥 المستخدمون الجدد المستوردون: <b>{res['users_imported']:,}</b>\n"
                    f"👥 المستخدمون المُحدَّثون: <b>{res['users_updated']:,}</b>\n"
                    f"📱 الأرقام المستوردة: <b>{res['accounts_imported']:,}</b>\n"
                    f"📱 الأرقام المتجاهلة (موجودة): <b>{res['accounts_skipped']:,}</b>\n"
                    f"⚙️ الإعدادات المستوردة: <b>{res['settings_imported']}</b>\n"
                    "━━━━━━━━━━━━━━━━━━━\n"
                    "✅ تم استيراد: أسماء الأزرار، ألوانها، إيموجيها\n"
                    "✅ أسعار وحدود وحالة كل خدمة\n"
                    "✅ القنوات الإجبارية وعدد الطلبات\n"
                    "✅ إعدادات الشحن والـ VIP"
                    f"{errors_txt}"
                ),
                reply_markup=done_keys,
                parse_mode="HTML"
            )
        except Exception as e:
            _import_err_kb = mk(row_width=1)
            _import_err_kb.add(btn('🔙 رجوع للوحة الأدمن', callback_data='adm_cat_database', color='red'))
            bot.edit_message_text(
                chat_id=cid, message_id=mid,
                text=f"❌ <b>فشل الاستيراد:</b>\n{e}",
                reply_markup=_import_err_kb, parse_mode="HTML"
            )

    # ✏️ نظام تغيير أسماء الأزرار

    if data == 'adm_rename':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        keys = mk(row_width=1)
        for cb, default_label in BTN_KEYS.items():
            cur_label = _get_btn_label(cb, default=default_label)
            cur_color = _get_btn_color(cb, "blue")
            keys.add(btn(f'✏️ {cur_label}', callback_data=f'rnm_pick_{cb}', color=cur_color))
        keys.add(btn('🔙 رجوع للتخصيص', callback_data='adm_btn_panel', color='blue'))
        bot.edit_message_text(
            text='✏️ *تغيير أسماء الأزرار*\n\nاضغط على أي زر لتغيير اسمه',
            chat_id=cid, message_id=mid,
            reply_markup=keys, parse_mode='Markdown'
        )

    if data.startswith('rnm_pick_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cb_target = data.replace('rnm_pick_', '')
        if cb_target not in BTN_KEYS:
            return
        cur_label = _get_btn_label(cb_target, default=BTN_KEYS[cb_target])
        cur_color  = _get_btn_color(cb_target, "blue")
        color_icon = "🟢" if cur_color == "green" else "🔴" if cur_color == "red" else "🔵"
        keys = mk(row_width=1)
        keys.add(btn('🔄 إعادة الاسم الأصلي', callback_data=f'rnm_reset_{cb_target}', color='red'))
        keys.add(btn('رجوع', callback_data='adm_rename', color='blue'))
        bot.clear_step_handler_by_chat_id(cid)
        x = bot.edit_message_text(
            text=f'✏️ *تغيير اسم الزر*\n\nالزر: {color_icon} *{cur_label}*\n\nأرسل الاسم الجديد للزر الآن:',
            chat_id=cid, message_id=mid,
            reply_markup=keys, parse_mode='Markdown'
        )
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_rename_btn, cb_target)

    if data.startswith('rnm_reset_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cb_target = data.replace('rnm_reset_', '')
        if cb_target not in BTN_KEYS:
            return
        db.delete(f'btn_label_{cb_target}')
        keys = mk(row_width=1)
        for cb, default_label in BTN_KEYS.items():
            cur_label = _get_btn_label(cb, default=default_label)
            cur_color = _get_btn_color(cb, "blue")
            keys.add(btn(f'✏️ {cur_label}', callback_data=f'rnm_pick_{cb}', color=cur_color))
        keys.add(btn('🔙 رجوع للأسماء', callback_data='adm_rename', color='blue'))
        bot.edit_message_text(
            text=f'✅ تم إعادة اسم الزر للأصلي\n\n✏️ *تغيير أسماء الأزرار*\n\nاضغط على أي زر لتغيير اسمه',
            chat_id=cid, message_id=mid,
            reply_markup=keys, parse_mode='Markdown'
        )

    # ✨ رموز تعبيرية مميزة للأزرار

    if data == 'adm_emoji':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        ekeys = TelebotMarkup(row_width=1)
        count = sum(1 for cb in BTN_KEYS if _resolve_btn_emoji(cb))
        ekeys.add(btn(f'عرض/تعديل ({count} مضبوط)', callback_data='adm_emoji_list', color='blue'))
        ekeys.add(btn('مسح كل الرموز', callback_data='adm_emoji_clearall', color='red'))
        ekeys.add(btn('مساعدة', callback_data='adm_emoji_help', color='blue'))
        ekeys.add(btn('رجوع', callback_data='adm_btn_panel', color='blue'))
        bot.edit_message_text(
            text=f'✨ <b>إيموجي مميز للأزرار (Custom Emoji)</b>\n\nتقدر تضبط Custom Emoji Premium لأي زر في البوت.\n\n📌 يظهر الإيموجي كأيقونة في الزر مباشرة.\n\nعدد الأزرار المضبوط حالياً: <b>{count}</b>',
            chat_id=cid, message_id=mid, reply_markup=ekeys, parse_mode="HTML"
        )

    if data == 'adm_emoji_help':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        ekeys = TelebotMarkup(row_width=1)
        ekeys.add(btn('رجوع', callback_data='adm_emoji', color='blue'))
        bot.edit_message_text(
            text=(
                '<b>📖 مساعدة — الإيموجي المميز</b>\n\n'
                'الـ <b>Custom Emoji ID</b> رقم طويل خاص بكل إيموجي بريميوم.\n\n'
                '<b>طريقة الحصول عليه:</b>\n'
                '1⃣ ابعت الإيموجي المميز لبوت زي <code>@idstickerbot</code>\n'
                '2⃣ هتلاقي الرد فيه رقم طويل — ده الـ ID\n\n'
                '<b>أو:</b>\n'
                'أرسل الإيموجي المميز مباشرة والبوت يستخرج الـ ID تلقائياً\n\n'
                '<b>ملاحظة:</b> يتطلب Telegram Premium أو قناة/بوت مدفوع'
            ),
            chat_id=cid, message_id=mid, reply_markup=ekeys, parse_mode="HTML"
        )

    if data == 'adm_emoji_clearall':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        _db_clear_all_btn_emojis()
        _invalidate_btn_emoji_cache()
        ekeys = TelebotMarkup(row_width=1)
        ekeys.add(btn('رجوع', callback_data='adm_emoji', color='blue'))
        bot.edit_message_text(text='✅ تم مسح كل رموز الأزرار', chat_id=cid, message_id=mid, reply_markup=ekeys, parse_mode="HTML")

    if data == 'adm_emoji_list':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        ekeys = TelebotMarkup(row_width=1)
        for cb, lbl in BTN_KEYS.items():
            eid = _resolve_btn_emoji(cb)
            icon = '✅' if eid else '➕'
            cur_label = _get_btn_label(cb, default=lbl)
            ekeys.add(btn(f'{icon} {cur_label}', callback_data=f'emjbtn_{cb}', color='blue'))
        ekeys.add(btn('رجوع', callback_data='adm_emoji', color='blue'))
        bot.edit_message_text(
            text='اختر الزر الذي تريد تعيين إيموجي له:\n\n✅ = مضبوط  |  ➕ = بدون إيموجي',
            chat_id=cid, message_id=mid, reply_markup=ekeys
        )

    if data.startswith('emjbtn_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cb_target = data.replace('emjbtn_', '')
        if cb_target not in BTN_KEYS:
            return
        cur_label = _get_btn_label(cb_target, default=BTN_KEYS[cb_target])
        eid = _resolve_btn_emoji(cb_target)
        ekeys = TelebotMarkup(row_width=1)
        if eid:
            ekeys.add(btn('🗑 حذف الإيموجي', callback_data=f'emjbtndel_{cb_target}', color='red'))
        ekeys.add(btn('🔙 رجوع للقائمة', callback_data='adm_emoji_list', color='blue'))
        cur_txt = f'الإيموجي الحالي: <code>{eid}</code>' if eid else 'لا يوجد إيموجي حالياً'
        x = bot.edit_message_text(
            text=(
                f'🎨 <b>تعيين إيموجي للزر: {cur_label}</b>\n'
                f'{cur_txt}\n\n'
                '━━━━━━━━━━━━━━━━━━\n'
                '📤 أرسل الإيموجي المميز مباشرة أو أرسل الـ ID كأرقام فقط:\n\n'
                'مثال:\n'
                '<code>5368324170671202286</code>'
            ),
            chat_id=cid, message_id=mid, reply_markup=ekeys, parse_mode="HTML"
        )
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_set_btn_emoji, cb_target)

    if data.startswith('emjbtndel_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cb_target = data.replace('emjbtndel_', '')
        if cb_target not in BTN_KEYS:
            return
        _db_set_btn_emoji(cb_target, "")
        _invalidate_btn_emoji_cache()
        ekeys = TelebotMarkup(row_width=1)
        for cb, lbl in BTN_KEYS.items():
            eid = _resolve_btn_emoji(cb)
            icon = '✅' if eid else '➕'
            cur_label = _get_btn_label(cb, default=lbl)
            ekeys.add(btn(f'{icon} {cur_label}', callback_data=f'emjbtn_{cb}', color='blue'))
        ekeys.add(btn('رجوع', callback_data='adm_emoji', color='blue'))
        bot.edit_message_text(
            text='✅ تم حذف الإيموجي\n\nاختر الزر الذي تريد تعيين إيموجي له:',
            chat_id=cid, message_id=mid, reply_markup=ekeys
        )

    # 🎁 رابط هدية النقاط

    if data == 'adm_gift_link':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        ckeys = mk(row_width=1)
        ckeys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_tasks', color='blue'))
        x = bot.edit_message_text(
            text='🎁 *صنع رابط هدية نقاط*\n\nأرسل عدد النقاط التي تريد وضعها في رابط الهدية (مثال: 500):',
            chat_id=cid, message_id=mid, reply_markup=ckeys, parse_mode='Markdown'
        )
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_gift_ask_uses)

    # 🎧 تعيين نص الدعم الفني

    if data == 'adm_ai_panel':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        _show_ai_panel(cid, mid)

    if data == 'adm_ai_toggle':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        db.set('ai_support_enabled', (not _ai_support_enabled()))
        _show_ai_panel(cid, mid)

    if data == 'adm_ai_setkey':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        ckeys = mk(row_width=1)
        ckeys.add(btn('رجوع', callback_data='adm_ai_panel', color='blue'))
        x = bot.edit_message_text(
            text=('🔑 <b>ضبط Groq API Key</b>\n\n'
                  'أرسل المفتاح الآن (يبدأ عادةً بـ <code>gsk_</code>).\n'
                  'تحصل عليه من: https://console.groq.com/keys'),
            chat_id=cid, message_id=mid, reply_markup=ckeys, parse_mode='HTML'
        )
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_set_groq_key)

    if data == 'adm_ai_test':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        try:
            _cb_alert(call, 'جارٍ الاختبار...')
        except Exception:
            pass
        ans, err = _ai_ask('قل جملة قصيرة للتأكد أن الاتصال يعمل.')
        if ans:
            bot.send_message(cid, f'🧪 <b>نتيجة الاختبار</b>\n\n✅ الاتصال يعمل.\n\nرد النموذج:\n{ans[:500]}', parse_mode='HTML')
        else:
            bot.send_message(cid, f'🧪 <b>نتيجة الاختبار</b>\n\n{err}', parse_mode='HTML')

    if data == 'adm_set_support':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cur = db.get("support_info") if db.exists("support_info") else "غير محدد"
        ckeys = mk(row_width=1)
        ckeys.add(btn('رجوع', callback_data='adm_cat_subscription', color='blue'))
        x = bot.edit_message_text(
            text=f'🎧 *تعيين نص الدعم الفني*\n\nالحالي:\n{cur}\n\nأرسل النص الجديد (يمكن تضمين روابط تيليجرام):',
            chat_id=cid, message_id=mid, reply_markup=ckeys, parse_mode='Markdown'
        )
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_set_support_info)

    # 📣 إعداد زر قناة البوت

    if data == 'adm_set_channel_btn':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cur_user = db.get("bot_channel_username") if db.exists("bot_channel_username") else "غير محدد"
        cur_desc = db.get("bot_channel_desc")     if db.exists("bot_channel_desc")     else "غير محدد"
        ckeys = mk(row_width=1)
        ckeys.add(btn('رجوع', callback_data='adm_cat_settings', color='blue'))
        x = bot.edit_message_text(
            text=(
                f"📣 <b>إعداد زر قناة البوت</b>\n\n"
                f"يوزر القناة الحالي: <code>{cur_user}</code>\n"
                f"الوصف الحالي: {cur_desc}\n\n"
                "أرسل <b>سطرين</b>:\n"
                "السطر 1: يوزر القناة (مثال: <code>mychannel</code>)\n"
                "السطر 2: وصف القناة (يظهر عند الضغط على الزر)\n\n"
                "مثال:\n<code>mychannel\nقناتنا الرسمية للأخبار والتحديثات 🚀</code>"
            ),
            chat_id=cid, message_id=mid, reply_markup=ckeys, parse_mode='HTML'
        )
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_set_channel_btn)

    # ✨ إعداد الإيموجي المخصص

    if data == 'adm_set_emojis':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        em_bal = db.get("custom_emoji_balance") if db.exists("custom_emoji_balance") else "—"
        em_ord = db.get("custom_emoji_orders")  if db.exists("custom_emoji_orders")  else "—"
        em_ch  = db.get("custom_emoji_channel") if db.exists("custom_emoji_channel") else "—"
        ekeys = mk(row_width=1)
        ekeys.add(btn(f'💰 إيموجي الرصيد (حالي: {em_bal})',         callback_data='adm_emoji_bal', color='green'))
        ekeys.add(btn(f'✅ إيموجي الطلبات (حالي: {em_ord})',         callback_data='adm_emoji_ord', color='green'))
        ekeys.add(btn(f'📢 إيموجي قناة البوت (حالي: {em_ch})',       callback_data='adm_emoji_ch',  color='green'))
        ekeys.add(btn('رجوع', callback_data='adm_cat_settings', color='blue'))
        bot.edit_message_text(
            text=(
                "✨ <b>إعداد الإيموجي المخصص للأزرار</b>\n\n"
                "يمكنك تعيين إيموجي يظهر قبل نص كل زر في الصفحة الرئيسية.\n\n"
                "📌 أرسل الإي��وجي مباشرة كما هو، مثل:\n"
                "💰 أو 🌟 أو 🔥 أو ✅\n\n"
                "اضغط على أي زر لتعديله:"
            ),
            chat_id=cid, message_id=mid, reply_markup=ekeys, parse_mode='HTML'
        )

    if data == 'adm_emoji_bal':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cur = db.get("custom_emoji_balance") if db.exists("custom_emoji_balance") else "—"
        x = bot.edit_message_text(
            text=f'💰 <b>إيموجي زر الرصيد</b>\n\nالحالي: {cur}\n\nأرسل الإيموجي الجديد (مثل 💎 أو 🌟)\nأو أرسل <code>0</code> لإزالة الإيموجي:',
            chat_id=cid, message_id=mid, parse_mode='HTML'
        , reply_markup=bk_cancel)
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_set_emoji, 'custom_emoji_balance')

    if data == 'adm_emoji_ord':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cur = db.get("custom_emoji_orders") if db.exists("custom_emoji_orders") else "—"
        x = bot.edit_message_text(
            text=f'✅ <b>إيموجي زر الطلبات</b>\n\nالحالي: {cur}\n\nأرسل الإيموجي الجديد (مثل ✅ أو 📋)\nأو أرسل <code>0</code> لإزالة الإيموجي:',
            chat_id=cid, message_id=mid, parse_mode='HTML'
        , reply_markup=bk_cancel)
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_set_emoji, 'custom_emoji_orders')

    if data == 'adm_emoji_ch':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cur = db.get("custom_emoji_channel") if db.exists("custom_emoji_channel") else "—"
        x = bot.edit_message_text(
            text=f'📢 <b>إيموجي زر قناة البوت</b>\n\nالحالي: <code>{cur}</code>\n\nأرسل الـ emoji id الجديد (رقم فقط)\nأو أرسل <code>0</code> لإزالة الإيموجي:',
            chat_id=cid, message_id=mid, parse_mode='HTML'
        , reply_markup=bk_cancel)
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_set_emoji, 'custom_emoji_channel')

    # 📢 تعيين قنوات البوت

    if data == 'adm_vip_thresh':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cur = int(db.get('vip_invite_threshold')) if db.exists('vip_invite_threshold') else 2
        x = bot.edit_message_text(
            text=f'👑 عدد الدعوات المطلوبة للحصول على VIP تلقائياً\n\n🔢 الحالي: {cur} دعوات\n\n• أرسل العدد الجديد:',
            chat_id=cid, message_id=mid
        , reply_markup=bk_cancel_adm)
        bot.register_next_step_handler(x, _set_vip_thresh)

    # 🎯 لوحة إعدادات المكافآت

    if data == 'adm_rewards_panel':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        bot.edit_message_text(
            chat_id=cid, message_id=mid,
            text=_rewards_text(),
            reply_markup=_rewards_keys(),
            parse_mode='HTML'
        )

    if data == 'rwd_daily':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cur = int(db.get("daily_gift")) if db.exists("daily_gift") else 30
        x = bot.edit_message_text(
            chat_id=cid, message_id=mid,
            text=(f"🎁 <b>تعديل الهدية اليومية</b>\n\n"
                  f"القيمة الحالية: <b>{cur} نقطة</b>\n\n"
                  "أرسل القيمة الجديدة (رقم صحيح):"),
            parse_mode='HTML'
        , reply_markup=bk_cancel)
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_rwd_daily)

    if data == 'rwd_invite':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cur = int(db.get("link_price")) if db.exists("link_price") else link_price
        x = bot.edit_message_text(
            chat_id=cid, message_id=mid,
            text=(f"🔮 <b>تعديل مكافأة الإحالة</b>\n\n"
                  f"القيمة الحالية: <b>{cur} نقطة</b>\n\n"
                  "أرسل القيمة الجديدة (رقم صحيح):"),
            parse_mode='HTML'
        , reply_markup=bk_cancel)
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_rwd_invite)

    if data == 'rwd_wheel':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        prizes = get_wheel_prizes()
        cur_txt = "\n".join(f"{p['points']} {p['weight']}" for p in prizes)
        x = bot.edit_message_text(
            chat_id=cid, message_id=mid,
            text=("🎰 <b>تعديل جوائز عجلة الحظ</b>\n\n"
                  "أرسل الجوائز — كل سطر بالشكل:\n"
                  "<code>نقاط  احتمالية</code>\n\n"
                  "• الاحتمالية رقم نسبي (كلما زاد = أكثر ظهوراً)\n"
                  "• أضف جائزتين على الأقل\n\n"
                  "<b>مثال:</b>\n"
                  "<code>50 35\n100 25\n200 18\n350 10\n500 7\n750 3\n1000 2</code>\n\n"
                  "━━━━━━━━━━━━━━\n"
                  f"<b>الحالي:</b>\n<code>{cur_txt}</code>"),
            parse_mode='HTML'
        , reply_markup=bk_cancel)
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_rwd_wheel)

    if data == 'rwd_toggle_remind':
        cb_rwd_toggle_remind(call)
        return

    # 🔄 إرجاع الجلسة واسترداد النقاط

    if data.startswith('restore_session_'):
        phon = data.replace('restore_session_', '')
        broken = db.get(f'session_broken_{phon}') if db.exists(f'session_broken_{phon}') else None
        if not broken:
            _cb_alert(call, text='❌ لا توجد جلسة معلقة لهذا الرقم', show_alert=True)
            return
        if broken.get('owner_id') != cid:
            _cb_alert(call, text='❌ هذا الطلب ليس لك', show_alert=True)
            return
        # إخفاء الزر
        try:
            bot.edit_message_reply_markup(chat_id=cid, message_id=mid, reply_markup=None)
        except:
            pass
        x = bot.send_message(
            chat_id=cid,
            text=(
                f"🔄 <b>إعادة تسجيل جلسة الرقم</b> <code>{phon}</code>\n\n"
                "لاسترداد نقاطك أرسل الآن رابط تسجيل الدخول بالبوت الثاني:\n\n"
                f"👉 ابعت /start في @{_get_bot_me().username} من حساب التأجير لتوليد الجلسة\n\n"
                "أو أرسل session string مباشرة إذا لديك:"
            ),
            parse_mode='HTML'
        , reply_markup=bk_cancel)
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_restore_session, phon, broken)

    # ✅ قبول / ❌ رفض طلبات الشحن

    # ⚡ اختيار إيموجي التفاعل من أزرار المنشور

    if data.startswith('pick_special_num_'):
        try:
            rest = data[len('pick_special_num_'):]
            parts_n = rest.rsplit('_', 1)
            p_uid = int(parts_n[0])
            idx   = int(parts_n[1])
        except:
            _cb_alert(call, text='❌ خطأ، ابدأ الطلب من جديد', show_alert=True)
            return
        if cid != p_uid:
            _cb_alert(call, text='❌ هذا الطلب ليس لك', show_alert=True)
            return

        emoji_list = db.get(f'react_special_list_{cid}') or []
        if idx >= len(emoji_list):
            _cb_alert(call, text='❌ اختيار غير صحيح', show_alert=True)
            return

        emoji_char, custom_emoji_id = emoji_list[idx]
        url    = db.get(f'react_special_url_{cid}')    or ''
        amount = int(db.get(f'react_special_amount_{cid}') or 0)

        if not url or not amount:
            _cb_alert(call, text='❌ انتهت صلاحية الطلب', show_alert=True)
            return

        try:
            bot.edit_message_reply_markup(chat_id=cid, message_id=mid, reply_markup=None)
        except:
            pass

        if custom_emoji_id:
            emoji_display = f'<tg-emoji emoji-id="{custom_emoji_id}">{emoji_char}</tg-emoji>'
        else:
            emoji_display = emoji_char or '⭐'

        _cb_alert(call, text='✅ تم اختيار الإيموجي')
        db.set(f'react_special_chosen_{cid}', f'{emoji_char}|||{custom_emoji_id or ""}|||{url}|||{amount}')

        _svc_price = svc_price('react_special')
        _total_cost = _svc_price * amount
        confirm_kb = mk(row_width=2)
        confirm_kb.add(
            btn('✅ تأكيد وبدء التنفيذ', callback_data='react_special_confirm', color='green'),
            btn('❌ إلغاء', callback_data='back', color='red')
        )
        bot.send_message(
            cid,
            f'📋 <b>تأكيد الطلب</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'✨ الخدمة : رشق إيموجي مميز\n'
            f'😀 الإيموجي : {emoji_display}\n'
            f'🔢 الكمية : {amount}\n'
            f'🔗 الرابط : {url}\n'
            f'💰 التكلفة : {_total_cost:,} نقطة\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'هل تريد تأكيد الطلب؟',
            reply_markup=confirm_kb, parse_mode='HTML',
            disable_web_page_preview=True
        )
        return
        try:
            rest = data[len('pick_special_'):]
            uid_end = rest.index('_')
            p_uid = int(rest[:uid_end])
            remainder = rest[uid_end+1:]
            em_parts = remainder.split('|||')
            emoji_char = em_parts[0]
            custom_emoji_id = em_parts[1] if len(em_parts) > 1 else ''
        except:
            _cb_alert(call, text='❌ خطأ، ابدأ الطلب من جديد', show_alert=True)
            return
        if cid != p_uid:
            _cb_alert(call, text='❌ هذا الطلب ليس لك', show_alert=True)
            return

        url = db.get(f'react_special_url_{cid}') if db.exists(f'react_special_url_{cid}') else ''
        amount = int(db.get(f'react_special_amount_{cid}') or 0)
        if not url or not amount:
            _cb_alert(call, text='❌ انتهت صلاحية الطلب، ابدأ من جديد', show_alert=True)
            return

        try:
            bot.edit_message_reply_markup(chat_id=cid, message_id=mid, reply_markup=None)
        except:
            pass

        if custom_emoji_id:
            emoji_display = f'<tg-emoji emoji-id="{custom_emoji_id}">{emoji_char}</tg-emoji>'
        else:
            emoji_display = emoji_char

        try:
            _cb_alert(call, text='✅ تم اختيار الإيموجي')
        except:
            pass

        # نحفظ الاختيار
        db.set(f'react_special_chosen_{cid}', f'{emoji_char}|||{custom_emoji_id}|||{url}|||{amount}')

        # رسالة تأكيد الطلب
        _svc_price = svc_price('react_special')
        _total_cost = _svc_price * amount
        confirm_kb = mk(row_width=2)
        confirm_kb.add(
            btn('✅ تأكيد وبدء التنفيذ', callback_data='react_special_confirm', color='green'),
            btn('❌ إلغاء', callback_data='back', color='red')
        )
        bot.send_message(
            cid,
            f'📋 <b>تأكيد الطلب</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'✨ الخدمة : رشق إيموجي مميز\n'
            f'😀 الإيموجي : {emoji_display}\n'
            f'🔢 الكمية : {amount}\n'
            f'🔗 الرابط : {url}\n'
            f'💰 التكلفة : {_total_cost:,} نقطة\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'هل تريد تأكيد الطلب؟',
            reply_markup=confirm_kb, parse_mode='HTML',
            disable_web_page_preview=True
        )
        return

    if data == 'react_special_confirm':
        chosen = db.get(f'react_special_chosen_{cid}')
        if not chosen:
            _cb_alert(call, text='❌ انتهت صلاحية الطلب، ابدأ من جديد', show_alert=True)
            return

        parts = chosen.split('|||')
        emoji_char      = parts[0] if len(parts) > 0 else ''
        custom_emoji_id = parts[1] if len(parts) > 1 else ''
        url             = parts[2] if len(parts) > 2 else ''
        amount          = int(parts[3]) if len(parts) > 3 else 0

        if not url or not amount:
            _cb_alert(call, text='❌ انتهت صلاحية الطلب', show_alert=True)
            return

        _svc_price = svc_price('react_special')
        acc = db.get(f'user_{cid}') or {}
        pr = _svc_price * amount
        if int(pr) > int(acc.get('coins', 0)):
            _rsc_err_kb = mk(row_width=1)
            _rsc_err_kb.add(btn('🔙 رجوع', callback_data='react_special', color='red'))
            bot.edit_message_text(
                chat_id=cid, message_id=mid,
                text=f'❌ <b>نقاطك غير كافية</b>\n• تحتاج : {pr:,} نقطة\n• رصيدك : {int(acc.get("coins", 0)):,} نقطة',
                reply_markup=_rsc_err_kb, parse_mode='HTML'
            )
            return

        load_ = db.get('accounts') or []
        if len(load_) < amount:
            _rsc_err_kb2 = mk(row_width=1)
            _rsc_err_kb2.add(btn('🔙 رجوع', callback_data='react_special', color='red'))
            bot.edit_message_text(
                chat_id=cid, message_id=mid,
                text='❌ عدد حسابات البوت غير كافية حالياً', reply_markup=_rsc_err_kb2, parse_mode='HTML'
            )
            return

        # نحذف أزرار التأكيد
        try:
            bot.edit_message_reply_markup(chat_id=cid, message_id=mid, reply_markup=None)
        except:
            pass

        typerr = 'رشق ايموجي مميز'
        # نبعت الـ custom_emoji_id لو موجود، وإلا الـ emoji_char
        emoji_text = custom_emoji_id if custom_emoji_id and custom_emoji_id.strip() else emoji_char

        bot.send_message(
            cid,
            f'⏳ <b>جارٍ تنفيذ طلبك...</b>\n\n'
            f'✨ الإيموجي : {emoji_text}\n'
            f'🔢 الكمية : {amount}\n'
            f'🔗 الرابط : {url}',
            parse_mode='HTML', disable_web_page_preview=True
        )

        send_order_to_channel(call.from_user, typerr, "خدمات البوت", amount, pr)

        true, false = 0, 0
        for y in load_:
            if true >= amount or (true + false) >= amount * 2:
                break
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                x_res = loop.run_until_complete(reactions(y['s'], url, emoji_text))
                loop.close()
                if x_res == 'o':
                    continue
                if x_res is True:
                    true += 1
                else:
                    false += 1
            except Exception as e:
                print(e)
                continue

        if true >= 1:
            for _ in range(true):
                acc['coins'] -= _svc_price
            db.set(f'user_{cid}', acc)
        addord()
        buys = int(db.get(f"user_{cid}_buys")) if db.exists(f"user_{cid}_buys") else 0
        db.set(f"user_{cid}_buys", buys + 1)

        # تنظيف
        db.delete(f'react_special_{cid}_proccess')
        db.delete(f'react_special_chosen_{cid}')
        db.delete(f'react_special_url_{cid}')
        db.delete(f'react_special_amount_{cid}')

        bot.send_message(
            cid,
            f'✅ <b>تم اكتمال الطلب</b>\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'✨ الإيموجي : {emoji_text}\n'
            f'🔢 الكمية المطلوبة : {amount}\n'
            f'✅ تم تنفيذ : {true}\n'
            f'❌ لم يتم : {false}\n'
            f'💰 تم خصم : {true * _svc_price:,} نقطة\n'
            f'━━━━━━━━━━━━━━━━━━━',
            reply_markup=bk_cancel, parse_mode='HTML'
        )
        send_order_complete_to_channel(call.from_user, typerr, 'خدمات البوت', amount, true, false, true * _svc_price)
        return
        # صيغة: pick_react_{uid}_{amount}_{emoji}
        try:
            rest  = data[len('pick_react_'):]
            parts  = rest.split('_')
            p_uid  = int(parts[0])
            amount = int(parts[1])
            emoji  = '_'.join(parts[2:]) if len(parts) > 2 else parts[2]
        except:
            _cb_alert(call, text='❌ خطأ، ابدأ الطلب من جديد', show_alert=True)
            return
        if cid != p_uid:
            _cb_alert(call, text='❌ هذا الطلب ليس لك', show_alert=True)
            return
        url = db.get(f'react_url_{cid}') if db.exists(f'react_url_{cid}') else ''
        if not url:
            _cb_alert(call, text='❌ انتهت صلاحية الطلب، ابدأ من جديد', show_alert=True)
            return
        # إخفاء الأزرار وتأكيد الاختيار
        try:
            bot.edit_message_reply_markup(chat_id=cid, message_id=mid, reply_markup=None)
        except:
            pass
        try:
            _cb_alert(call, text=f'✅ تم اختيار {emoji}')
        except:
            pass
        db.delete(f'react_url_{cid}')
        # عرض شاشة التأكيد
        price = svc_price('react') * amount
        _pending_orders[cid] = {
            'type':    'تفاعلات اختياري',
            'amount':  amount,
            'url':     url,
            'price':   price,
            'extra':   {'like': emoji},
            'msg_id':  mid,
            'chat_id': cid,
        }
        info  = db.get(f'user_{cid}') or {}
        coins = int(info.get('coins', 0))
        confirm_txt = (
            f"╔══════════════════════╗\n"
            f"       ✅ تأكيد الطلب\n"
            f"╚══════════════════════╝\n\n"
            f"📋 <b>النوع</b>    : تفاعلات اختياري {emoji}\n"
            f"🔢 <b>الكمية</b>   : {amount:,}\n"
            f"�� <b>الرابط</b>   : <code>{url}</code>\n"
            f"💰 <b>السعر</b>    : {price:,} نقطة\n"
            f"💳 <b>رصيدك</b>   : {coins:,} نقطة\n"
            f"💳 <b>بعد الطلب</b>: {max(0, coins - price):,} نقطة\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"هل تريد تأكيد الطلب؟"
        )
        keys = mk(row_width=2)
        keys.add(
            btn('✅ تأكيد', callback_data='confirm_order', color='green'),
            btn('❌ إلغاء', callback_data='cancel_order',  color='red'),
        )
        bot.send_message(cid, confirm_txt, reply_markup=keys, parse_mode='HTML',
                         disable_web_page_preview=True)

    if data.startswith('chgapprove_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        try:
            target_uid = int(data.replace('chgapprove_', ''))
        except:
            return
        x = bot.send_message(
            chat_id=cid,
            text=f'✅ أرسل عدد النقاط التي تريد إضافتها للمستخدم <code>{target_uid}</code>:',
            parse_mode='HTML'
        , reply_markup=bk_cancel)
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_charge_approve, target_uid)
        try:
            _cb_alert(call, text='أرسل عدد النقاط')
        except:
            pass

    if data.startswith('chgreject_'):
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        try:
            target_uid = int(data.replace('chgreject_', ''))
        except:
            return
        # إشعار للأدمن
        try:
            bot.edit_message_reply_markup(
                chat_id=cid,
                message_id=mid,
                reply_markup=None
            )
        except:
            pass
        bot.send_message(cid, f'❌ تم رفض طلب الشحن للمستخدم <code>{target_uid}</code>', parse_mode='HTML')
        # إشعار للمستخدم
        try:
            bot.send_message(
                chat_id=target_uid,
                text=(
                    '❌ <b>تم رفض طلب الشحن</b>\n\n'
                    'تأكد من صحة إثبات الدفع وأعد المحاولة، أو تواصل مع الدعم الفني.'
                ),
                parse_mode='HTML'
            )
        except:
            pass
        try:
            _cb_alert(call, text='تم الرفض')
        except:
            pass

    if data == 'adm_set_channels':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        chs = db.get("channels_list") if db.exists("channels_list") else []
        cur_txt = ""
        for i, ch in enumerate(chs, 1):
            un  = ch.get("username", "")
            dsc = ch.get("desc", "")
            cur_txt += f"{i}. @{un.lstrip('@')}" + (f" — {dsc}" if dsc else "") + "\n"
        cur_txt = cur_txt.strip() or "لا توجد قنوات مضافة بعد"
        ckeys = mk(row_width=1)
        ckeys.add(btn('رجوع', callback_data='adm_cat_subscription', color='blue'))
        x = bot.edit_message_text(
            text=(
                f"📢 <b>تعيين قنوات البوت</b>\n\n"
                f"القنوات ال��الية:\n{cur_txt}\n\n"
                "أرسل قائمة القنوات — كل سطر:\n"
                "<code>@username | وصف القناة</code>\n\n"
                "مثال:\n"
                "<code>@mychannel1 | قناة الأخبار\n"
                "@mychannel2 | قناة التحديثات</code>\n\n"
                "الوصف اختياري"
            ),
            chat_id=cid, message_id=mid, reply_markup=ckeys, parse_mode='HTML'
        )
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_set_channels_info)

    # ⚙️ إعدادات الاشتراك الإجباري (أدمن)

    if data == 'chset_fsub_amount':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cur = db.get("fsub_amount") if db.exists("fsub_amount") else 500
        x = bot.edit_message_text(
            text=f'🔢 عدد الأعضاء في باقة الاشتراك الإجباري\n\nالحالي: {cur}\n\nأرسل العدد الجديد:',
            chat_id=cid, message_id=mid
        , reply_markup=bk_cancel)
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, lambda m: _do_set_fsub(m, 'fsub_amount'))

    if data == 'chset_fsub_duration':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cur = db.get("fsub_duration") if db.exists("fsub_duration") else 1
        x = bot.edit_message_text(
            text=f'📅 مدة باقة الاشتراك الإجباري (بالأيام)\n\nالحالية: {cur} يوم\n\nأرسل المدة الجديدة:',
            chat_id=cid, message_id=mid
        , reply_markup=bk_cancel)
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, lambda m: _do_set_fsub(m, 'fsub_duration'))

    if data == 'chset_fsub_stars':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cur = db.get("fsub_stars") if db.exists("fsub_stars") else 100
        x = bot.edit_message_text(
            text=f'⭐ سعر النجوم لباقة الاشتراك الإجباري\n\nالحالي: {cur} نجمة\n\nأرسل السعر الجديد:',
            chat_id=cid, message_id=mid
        , reply_markup=bk_cancel)
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, lambda m: _do_set_fsub(m, 'fsub_stars'))

    if data == 'chset_fsub_cash':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cur = db.get("fsub_cash") if db.exists("fsub_cash") else 50
        x = bot.edit_message_text(
            text=f'📱 سعر فودافون كاش لباقة الاشتراك الإجباري\n\nالحالي: {cur} جنيه\n\nأرسل السعر الجديد:',
            chat_id=cid, message_id=mid
        , reply_markup=bk_cancel)
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, lambda m: _do_set_fsub(m, 'fsub_cash'))

    if data == 'chset_fsub_usdt':
        if cid not in (db.get("admins") or []) and cid != sudo:
            return
        cur = db.get("fsub_usdt") if db.exists("fsub_usdt") else "1.0"
        x = bot.edit_message_text(
            text=f'💎 سعر USDT لباقة الاشتراك الإجباري\n\nالحالي: {cur} دولار\n\nأرسل السعر الجديد (مثال: 1.5):',
            chat_id=cid, message_id=mid
        , reply_markup=bk_cancel)
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, lambda m: _do_set_fsub(m, 'fsub_usdt', is_text=True))

    # استخدام رابط الهدية من المستخدم

    if data.startswith('use_gift_'):
        code = data.replace('use_gift_', '')
        gift = db.get(f"gift_{code}")
        if not gift:
            _cb_alert(call, text='❌ رابط الهدية غير صالح أو منتهي الصلاحية', show_alert=True)
            return
        max_uses = int(gift.get("max_uses", 1))
        uses = int(gift.get("uses", 0))
        used_by = gift.get("used_by", [])
        if gift.get("used") or uses >= max_uses:
            _cb_alert(call, text='❌ تم استنفاد استخدامات هذا الرابط', show_alert=True)
            return
        if cid in used_by:
            _cb_alert(call, text='❌ لقد استخدمت هذا الرابط من قبل', show_alert=True)
            return
        info = db.get(f'user_{cid}')
        if not info:
            _cb_alert(call, text='❌ سجّل في البوت أولاً', show_alert=True)
            return
        pts = int(gift.get("points", 0))
        info['coins'] = int(info.get('coins', 0)) + pts
        db.set(f'user_{cid}', info)
        uses += 1
        used_by.append(cid)
        gift["uses"] = uses
        gift["used_by"] = used_by
        if uses >= max_uses:
            gift["used"] = True
        db.set(f"gift_{code}", gift)
        remaining = max_uses - uses
        _cb_alert(call, text=f'🎉 تهانيك! حصلت على {pts:,} نقطة هدية!', show_alert=True)
        keys = mk(row_width=1)
        keys.add(btn('🔙 رجوع للرئيسية', callback_data='back', color='blue'))
        bot.edit_message_text(
            text=f'🎁 *تم استلام الهدية!*\n\n🎉 حصلت على *{pts:,} نقطة* هدية\n💰 رصيدك الجديد: *{int(info["coins"]):,} نقطة*',
            chat_id=cid, message_id=mid, reply_markup=keys, parse_mode='Markdown'
        )
        return

    # 🛟 شبكة أمان: أي زر مالوش معالج فوق ده، يقفل السبينر بدل ما يفضل عالق
    try:
        bot.answer_callback_query(callback_query_id=call.id)
    except Exception:
        pass

def _do_set_fsub(message, key, is_text=False):
    """يحفظ إعداد من إعدادات الاشتراك الإجباري"""
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    raw = (message.text or "").strip()
    if not raw:
        bot.reply_to(message, '❌ قيمة فارغة، حاول مرة أخرى')
        return
    if is_text:
        db.set(key, raw)
    else:
        try:
            val = int(raw)
            if val <= 0:
                raise ValueError
            db.set(key, val)
        except:
            bot.reply_to(message, '❌ أرسل رقماً صحيحاً أكبر من صفر')
            return
    labels = {
        'fsub_amount':   'عدد الأعضاء',
        'fsub_duration': 'مدة الباقة (أيام)',
        'fsub_stars':    'سعر النجوم',
        'fsub_cash':     'سعر فودافون كاش',
        'fsub_usdt':     'سعر USDT',
    }
    label = labels.get(key, key)
    keys = mk(row_width=1)
    keys.add(btn('🔙 رجوع لإعدادات الشحن', callback_data='adm_charge_panel', color='blue'))
    bot.reply_to(message, f'✅ تم تحديث {label} إ��ى: *{raw}*', reply_markup=keys, parse_mode='Markdown')

def _do_gift_ask_uses(message):
    """الخطوة الأولى: اس��لام النقاط ثم السؤال عن عدد الاستخدامات"""
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    try:
        pts = int(message.text.strip())
        if pts <= 0:
            raise ValueError
    except:
        bot.reply_to(message, '❌ أرسل رقماً صحيحاً أكبر من صفر')
        return
    x = bot.reply_to(
        message,
        f'✅ النقاط: *{pts:,}*\n\n🔢 الآن أرسل *عدد الأشخاص* الذين يمكنهم استخدام الرابط:\n(مثال: 1 لشخص واحد، 100 لمئة شخص)',
        parse_mode='Markdown'
    , reply_markup=bk_cancel)
    bot.register_next_step_handler(x, _do_create_gift_link, pts)

def _do_create_gift_link(message, pts):
    """ينشئ رابط هدية نقاط مع تحديد عدد الاستخدامات"""
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    try:
        max_uses = int(message.text.strip())
        if max_uses <= 0:
            raise ValueError
    except:
        bot.reply_to(message, '❌ أرسل رقماً صحيحاً أكبر من صفر')
        return
    code = generate_gift_link(pts, max_uses)
    try:
        me = _get_bot_me()
        link = f'https://t.me/{me.username}?start=gift_{code}'
    except:
        link = f'رمز الهدية: gift_{code}'
    uses_txt = 'مرة واحدة فقط ❗' if max_uses == 1 else f'{max_uses:,} مرة 🔁'
    keys = mk(row_width=1)
    keys.add(btn('🎁 صنع رابط هدية آخر', callback_data='adm_gift_link', color='green'))
    keys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_tasks', color='blue'))
    bot.reply_to(
        message,
        f'✅ *تم إنشاء رابط الهدية بنجاح!*\n\n'
        f'🎁 القيمة: *{pts:,} نقطة*\n'
        f'👥 عدد الاستخدامات: *{uses_txt}*\n\n'
        f'🔗 الرابط:\n`{link}`\n\n'
        f'⚠️ الرابط يُستخدم {uses_txt}',
        reply_markup=keys, parse_mode='Markdown'
    )

def _do_set_support_info(message):
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    txt = message.text.strip()
    if not txt:
        bot.reply_to(message, '❌ نص فارغ، حاول مرة أخرى')
        return
    db.set("support_info", txt)
    keys = mk(row_width=1)
    keys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_subscription', color='blue'))
    bot.reply_to(message, '✅ تم تحديث نص الدعم الفني بنجاح', reply_markup=keys)

def _do_set_channel_btn(message):
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    lines = [l.strip() for l in message.text.strip().split('\n') if l.strip()]
    if len(lines) < 2:
        bot.reply_to(message, '❌ أرسل سطرين:\nالسطر 1: يوزر القناة\nالسطر 2: وصف القناة')
        return
    username = lines[0].lstrip('@')
    desc     = '\n'.join(lines[1:])
    db.set("bot_channel_username", username)
    db.set("bot_channel_desc", desc)
    keys = mk(row_width=1)
    keys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_settings', color='blue'))
    bot.reply_to(
        message,
        f'✅ تم تحديث زر قناة البوت\n\n📣 القناة: @{username}\n📝 الوصف: {desc}',
        reply_markup=keys
    )

def _do_set_emoji(message, db_key):
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    val = message.text.strip()
    if val == '0':
        db.delete(db_key)
        bot.reply_to(message, '✅ تم إزالة الإيموجي المخصص')
        return
    try:
        int(val)  # تحقق إنه رقم
    except ValueError:
        bot.reply_to(message, '❌ أرسل الـ emoji id كرقم فقط\nمثال: <code>5368324170671202286</code>', parse_mode='HTML')
        return
    db.set(db_key, val)
    labels = {
        'custom_emoji_balance': 'زر الرصيد',
        'custom_emoji_orders':  'زر الطلبات',
        'custom_emoji_channel': 'زر قناة البوت',
    }
    keys = mk(row_width=1)
    keys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_settings', color='blue'))
    bot.reply_to(
        message,
        f'✅ تم تعيي�� إيموجي {labels.get(db_key, db_key)} بنجاح\nالـ ID: <code>{val}</code>',
        reply_markup=keys, parse_mode='HTML'
    )

def _do_set_channels_info(message):
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    txt = (message.text or "").strip()
    if not txt:
        bot.reply_to(message, '❌ نص فارغ، حاول مرة أخرى')
        return
    # حلل كل سطر: @username | وصف
    channels_list = []
    for line_raw in txt.splitlines():
        line_raw = line_raw.strip()
        if not line_raw: continue
        if '|' in line_raw:
            parts = line_raw.split('|', 1)
            un  = parts[0].strip().lstrip('@')
            dsc = parts[1].strip()
        else:
            un  = line_raw.lstrip('@')
            dsc = ''
        if un:
            channels_list.append({'username': un, 'desc': dsc})
    if not channels_list:
        bot.reply_to(message, '❌ لم يتم التعرف على أي قناة، تأكد من الصيغة وحاول مجدداً')
        return
    db.set('channels_list', channels_list)
    # احفظ نص قديم للتوافق
    db.set('channels_info', txt)
    summary = '\n'.join(f"• @{ch['username']}" + (f" — {ch['desc']}" if ch['desc'] else '') for ch in channels_list)
    keys = mk(row_width=1)
    keys.add(btn('🔙 رجوع للأدمن', callback_data='adm_cat_subscription', color='blue'))
    bot.reply_to(message,
        f"✅ تم حفظ {len(channels_list)} قناة بنجاح:\n\n{summary}",
        reply_markup=keys)

def _do_rename_btn(message, cb_target):
    """يحفظ الاسم الجديد للزر في قاعدة البيانات"""
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    new_name = (message.text or "").strip()
    if not new_name or new_name.startswith('/'):
        x = bot.reply_to(message, '❌ اسم غير صالح، أرسل الاسم الجديد مرة أخرى:', reply_markup=bk_cancel)
        bot.clear_step_handler_by_chat_id(cid)
        bot.register_next_step_handler(x, _do_rename_btn, cb_target)
        return
    try:
        db.set(f'btn_label_{cb_target}', new_name)
    except Exception as e:
        bot.reply_to(message, f'❌ حدث خطأ أثناء الحفظ: {e}')
        return
    keys = mk(row_width=1)
    keys.add(btn('✏️ تغيير اسم زر آخر', callback_data='adm_rename', color='green'))
    keys.add(btn('🔙 رجوع للتخصيص', callback_data='adm_btn_panel', color='blue'))
    bot.reply_to(
        message,
        f'✅ تم تغيير اسم الزر إلى: *{new_name}*',
        reply_markup=keys, parse_mode='Markdown'
    )

def _do_set_btn_emoji(message, cb_target):
    """يحفظ custom_emoji_id للزر في DB — يقبل ستيكر مميز أو رقم ID مباشرة"""
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return

    emoji_id = None

    # حالة: المستخدم بعت ستيكر/إيموجي مميز مباشرة
    if message.sticker and message.sticker.custom_emoji_id:
        emoji_id = message.sticker.custom_emoji_id
    elif message.text:
        raw = message.text.strip()
        if raw.lower() in ("cancel", "إلغاء"):
            bot.reply_to(message, "تم الإلغاء")
            return
        if raw.isdigit():
            emoji_id = raw
        else:
            bot.reply_to(
                message,
                '❌ أرسل <b>الإيموجي المميز مباشرة</b> من لوحة الإيموجي ✨\n'
                'أو أرسل الـ ID كأرقام فقط.\n\n'
                'أرسل <code>cancel</code> للإلغاء.',
                parse_mode="HTML"
            )
            return
    else:
        bot.reply_to(message, '❌ أرسل الإيموجي أو الـ ID.\nأرسل <code>cancel</code> للإلغاء.', parse_mode="HTML")
        return

    _db_set_btn_emoji(cb_target, emoji_id)
    _invalidate_btn_emoji_cache()
    cur_label = _get_btn_label(cb_target, default=BTN_KEYS.get(cb_target, cb_target))
    ekeys = TelebotMarkup(row_width=1)
    for cb, lbl in BTN_KEYS.items():
        eid = _resolve_btn_emoji(cb)
        icon = '✅' if eid else '➕'
        clabel = _get_btn_label(cb, default=lbl)
        ekeys.add(btn(f'{icon} {clabel}', callback_data=f'emjbtn_{cb}', color='blue'))
    ekeys.add(btn('رجوع', callback_data='adm_emoji', color='blue'))
    bot.reply_to(
        message,
        f'✅ تم تعيين الإيموجي للزر: <b>{cur_label}</b>\nID: <code>{emoji_id}</code>\n\nاختر زر آخر أو ارجع:',
        reply_markup=ekeys,
        parse_mode="HTML"
    )

def _do_svc_edit(message, svc_key, field):
    """يحفظ القيمة الجديدة للخدمة في DB"""
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 0:
        bot.reply_to(message, '❌ يجب إرسال رقم صحيح موجب فقط')
        return
    val = int(raw)
    svc_info = SERVICES[svc_key]
    if field == 'price_direct':
        # سعر مباشر لكل وحدة (مثل رشق أعضاء قناة عامة)
        db.set(svc_info["price_key"], val)
        label = f'💰 السعر الجديد: {val} نقطة / عضو'
    elif field in ('price1000', 'price'):
        # المستخدم يدخل السعر لكل 100 دائماً
        db.set(svc_info["price_key"], val // 100 if val % 100 == 0 else round(val / 100, 6))
        label = f'💰 السعر الجديد: {val} نقطة لكل 100'
    elif field == 'min':
        db.set(svc_info["min_key"], val)
        label = f'⬇️ الحد الأدنى الجديد: {val}'
    elif field == 'max':
        db.set(svc_info["max_key"], val)
        label = f'⬆️ الحد الأقصى الجديد: {val}'
    else:
        return
    skeys = TelebotMarkup(row_width=1)
    skeys.add(btn(f'🔙 رجوع لـ {svc_info["label"]}', callback_data=f'svc_pick_{svc_key}', color='blue'))
    skeys.add(btn('📋 قائمة الخدمات', callback_data='adm_svc_panel', color='green'))
    bot.reply_to(
        message,
        f'✅ تم تحديث إعدادات {svc_info["label"]}\n{label}',
        reply_markup=skeys
    )

def _do_charge_setting(message, db_key):
    """يحفظ إعداد الشحن في DB"""
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    val = (message.text or "").strip()
    if not val or val.startswith('/'):
        bot.reply_to(message, '❌ قيمة غير صالحة')
        return
    # المفاتيح التي تتطلب أرقام فقط
    _numeric_keys = {
        'charge_stars_rate', 'charge_cash_rate', 'charge_usdt_rate',
        'charge_vf_rate',
        'vip_monthly_price', 'vip_yearly_price', 'vip_lifetime_price',
    }
    if db_key == "orders_channel_id":
        try:
            val = int(val)
        except:
            bot.reply_to(message, '❌ ID القناة لازم يكون رقم مثل: -1001234567890')
            return
        try:
            bot.send_message(chat_id=val, text='✅ تم ربط قناة الطلبات بنجاح! ستصل هنا رسائل الطلبات.')
        except Exception as e:
            bot.reply_to(message, f'❌ فشل الإرسال للقناة: {e}\n\nتأكد أن البوت أدمن في القناة وأن الـ ID صحيح.')
            return
    elif db_key in _numeric_keys:
        if not val.isdigit() or int(val) < 0:
            bot.reply_to(message, '❌ يجب إرسال رقم صحيح موجب فقط')
            return
        val = int(val)
    db.set(db_key, val)
    ckeys = mk(row_width=1)
    ckeys.add(btn('🔙 رجوع لإعدادات الشحن', callback_data='adm_charge_panel', color='blue'))
    bot.reply_to(message, f'✅ تم حفظ: {val}', reply_markup=ckeys)

def handle_free_reaction(message):
    """تفاعلات مجانية — تستدعي API خارجي"""
    cid = message.from_user.id
    url = message.text.strip() if message.text else ''

    keys = mk(row_width=1)
    keys.add(btn('رجوع', callback_data='free_reactions', color='blue'))

    if not url.startswith('https://t.me/'):
        bot.reply_to(
            message,
            '❌ رابط غير صحيح\nأرسل رابط منشور تيليجرام فقط\nمثال: https://t.me/channel/123',
            reply_markup=keys, parse_mode='HTML'
        )
        return

    waiting = bot.reply_to(message, '⏳ جاري معالجة طلبك...')

    import threading, time as _time

    stop_progress = [False]
    progress_steps = [
        '🔄 جاري الاتصال بالخادم...       [▱▱▱▱▱▱▱▱▱▱] 0%',
        '📡 جاري إرسال الطلب...           [▰▰▱▱▱▱▱▱▱▱] 20%',
        '⚙️ جاري معالجة الطلب...          [▰▰▰▰▱▱▱▱▱▱] 40%',
        '🚀 جاري إضافة التفاعلات...       [▰▰▰▰▰▰▱▱▱▱] 60%',
        '✨ اكتمل الإرسال...               [▰▰▰▰▰▰▰▰▱▱] 80%',
        '✅ جاري التحقق من النتيجة...      [▰▰▰▰▰▰▰▰▰▰] 100%',
    ]

    def show_progress():
        for step in progress_steps:
            if stop_progress[0]:
                break
            try:
                bot.edit_message_text(step, chat_id=cid, message_id=waiting.message_id)
            except:
                pass
            _time.sleep(1.2)

    t = threading.Thread(target=show_progress)
    t.start()

    try:
        import requests as _req
        headers = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'accept-language': 'ar',
            'cache-control': 'no-cache',
            'content-type': 'application/json',
            'origin': 'https://tgpanel.org',
            'pragma': 'no-cache',
            'priority': 'u=1, i',
            'referer': 'https://tgpanel.org/',
            'daVTOOL': 'oosss44',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'cross-site',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'x-panel-origin': 'https://tgpanel.org',
            'x-panel-referer': 'https://tgpanel.org/free-telegram-reaction',
        }
        json_data = {
            'link': url,
            'quantity': '50',
            'provider_service_id': '10949',
            'username': 'guest',
        }
        resp = _req.post(
            'https://test.socialfruit.co/api/gateway',
            headers=headers, json=json_data, timeout=30
        )
        resp.raise_for_status()
        stop_progress[0] = True
        t.join()

        if 'success' in resp.text.lower():
            bot.edit_message_text(
                '✅ <b>اكتمل الطلب بنجاح!</b>\n\n🎉 تمت إضافة <b>50 تفاعل</b> على منشورك مجاناً\n[▰▰▰▰▰▰▰▰▰▰] 100% ✅',
                chat_id=cid, message_id=waiting.message_id,
                reply_markup=keys, parse_mode='HTML'
            )
        else:
            bot.edit_message_text(
                'الخدمة مش متاحة دلوقتي، حاول بعد شوية ❤️',
                chat_id=cid, message_id=waiting.message_id,
                reply_markup=keys, parse_mode='HTML'
            )
    except Exception as e:
        stop_progress[0] = True
        t.join()
        print(f'free_reaction error: {e}')
        try:
            bot.edit_message_text(
                '❌ حدث خطأ في الاتصال، حاول مرة أخرى.',
                chat_id=cid, message_id=waiting.message_id,
                reply_markup=keys, parse_mode='HTML'
            )
        except:
            pass


# {uid: {'channel': str, 'remaining': int}}
_future_views_subs = {}

def _start_future_views(uid: int, channel: str, count: int = 10):
    """يسجل اشتراك مشاهدات مستقبلية للمستخدم"""
    _future_views_subs[uid] = {'channel': channel, 'remaining': count}
    db.set(f'future_views_{uid}', {'channel': channel, 'remaining': count})
    print(f'[future_views] registered uid={uid} channel={channel} count={count}')

def _load_future_views():
    """يحمل الاشتراكات من DB عند بدء التشغيل"""
    try:
        users = db.keys('future_views_%') if hasattr(db, 'keys') else []
        for k in users:
            try:
                data = db.get(k[0] if isinstance(k, tuple) else k)
                if data and data.get('remaining', 0) > 0:
                    uid = int((k[0] if isinstance(k, tuple) else k).replace('future_views_', ''))
                    _future_views_subs[uid] = data
            except: pass
    except: pass

def _process_future_view(channel: str, msg_link: str):
    """يرسل مشاهدات لكل من اشترك في هذه القناة"""
    to_remove = []
    for uid, sub in list(_future_views_subs.items()):
        if sub.get('channel', '').lstrip('@') == channel.lstrip('@'):
            try:
                load_ = db.get('accounts') or []
                true = 0
                for y in load_:
                    if true >= 30:
                        break
                    try:
                        x = _pyro_run(view(y['s'], msg_link))
                        if x is True:
                            true += 1
                    except: continue
                sub['remaining'] -= 1
                if sub['remaining'] <= 0:
                    to_remove.append(uid)
                    db.delete(f'future_views_{uid}')
                    try:
                        bot.send_message(uid,
                            f'✅ <b>انتهت مشاهداتك المستقبلية!</b>\n\n'
                            f'🎉 تم تنفيذ المشاهدات على 10 منشورات بنجاح',
                            parse_mode='HTML'
                        )
                    except: pass
                else:
                    db.set(f'future_views_{uid}', sub)
            except Exception as e:
                print(f'[future_views] error: {e}')
    for uid in to_remove:
        _future_views_subs.pop(uid, None)

# تحميل الاشتراكات عند البدء
try:
    _load_future_views()
except: pass

def handle_free_react_plus(message):
    """50 تفاعل + مشاهدات 10 منشورات مستقبلية"""
    cid = message.from_user.id
    url = (message.text or '').strip()

    keys = mk(row_width=1)
    keys.add(btn('رجوع', callback_data='free_reactions', color='blue'))

    if not url.startswith('https://t.me/'):
        bot.reply_to(message,
            '❌ رابط غير صحيح\nأرسل رابط منشور تيليجرام فقط\nمثال: https://t.me/channel/123',
            reply_markup=keys, parse_mode='HTML')
        return

    # استخرج اسم القناة من ال��ابط
    try:
        parts = url.rstrip('/').split('/')
        channel = parts[-2] if len(parts) >= 4 else parts[-1]
    except:
        bot.reply_to(message, '❌ رابط غير صحيح', reply_markup=keys)
        return

    # تحقق لو مسجل بالفعل
    if cid in _future_views_subs or db.exists(f'future_views_{cid}'):
        bot.reply_to(message,
            '⚠️ <b>لديك اشتراك مشاهدات مستقبلية نشط بالفعل</b>\n\n'
            f'📢 القناة: @{channel}\n'
            f'📊 المتبقي: {_future_views_subs.get(cid, db.get(f"future_views_{cid}") or {}).get("remaining", 0)} منشور',
            reply_markup=keys, parse_mode='HTML')
        return

    load_ = db.get('accounts') or []
    if len(load_) < 1:
        bot.reply_to(message, '❌ لا توجد حسابات كافية', reply_markup=keys)
        return

    waiting = bot.reply_to(message, '⏳ جاري معالجة طلبك...')

    import threading, time as _time2

    stop_progress = [False]
    progress_steps = [
        '🔄 جاري الاتصال...          [▱▱▱▱▱▱▱▱▱▱] 0%',
        '⚡ جاري إضافة التفاعلات... [▰▰▰▰▱▱▱▱▱▱] 40%',
        '👁 جاري تسجيل المشاهدات... [▰▰▰▰▰▰▰▰▱▱] 80%',
        '✅ اكتمل الطلب...           [▰▰▰▰▰▰▰▰▰▰] 100%',
    ]
    def show_progress():
        for step in progress_steps:
            if stop_progress[0]: break
            try: bot.edit_message_text(step, chat_id=cid, message_id=waiting.message_id)
            except: pass
            _time2.sleep(1.5)
    t = threading.Thread(target=show_progress)
    t.start()

    try:
        import requests as _req
        headers = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'content-type': 'application/json',
            'origin': 'https://tgpanel.org',
            'referer': 'https://tgpanel.org/',
            'daVTOOL': 'oosss44',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'x-panel-origin': 'https://tgpanel.org',
            'x-panel-referer': 'https://tgpanel.org/free-telegram-reaction',
        }
        json_data = {
            'link': url,
            'quantity': '50',
            'provider_service_id': '10949',
            'username': 'guest',
        }
        react_ok = False
        for _ep in ['https://socialfruit.co/api/gateway', 'https://test.socialfruit.co/api/gateway']:
            try:
                resp = _req.post(_ep, headers=headers, json=json_data, timeout=30)
                if resp.status_code == 200 and 'success' in resp.text.lower():
                    react_ok = True
                    break
            except: continue

        stop_progress[0] = True
        t.join()

        # سجل المشاهدات المستقبلية بغض النظر عن التفاعلات
        _start_future_views(cid, channel, 10)

        if react_ok:
            result_txt = (
                '✅ <b>اكتمل الطلب بنجاح!</b>\n\n'
                '⚡ تمت إضافة <b>50 تفاعل</b> على منشورك\n'
                '👁 تم تسجيل <b>مشاهدات تلقائية</b> على أول 10 منشورات قادمة\n\n'
                f'📢 القناة المسجلة: @{channel}'
            )
        else:
            result_txt = (
                '⚠️ <b>التفاعلات غير متاحة حالياً</b>\n\n'
                '👁 تم تسجيل <b>مشاهدات تلقائية</b> على أول 10 منشورات قادمة بنجاح ✅\n\n'
                f'📢 القناة المسجلة: @{channel}'
            )

        bot.edit_message_text(result_txt,
            chat_id=cid, message_id=waiting.message_id,
            reply_markup=keys, parse_mode='HTML')

    except Exception as e:
        stop_progress[0] = True
        t.join()
        print(f'[free_react_plus] error: {e}')
        # حتى لو فشل API، سجل المشاهدات
        _start_future_views(cid, channel, 10)
        try:
            bot.edit_message_text(
                '👁 تم تسجيل <b>مشاهدات تلقائية</b> على أول 10 منشورات قادمة بنجاح ✅\n\n'
                f'📢 القناة: @{channel}',
                chat_id=cid, message_id=waiting.message_id,
                reply_markup=keys, parse_mode='HTML')
        except: pass

def get_amount(message, type_req):
    cid = message.from_user.id
    if type_req == 'leavs':
        if not db.get(f'leave_{cid}_proccess'):
            return
        db.delete(f'leave_{cid}_proccess')
        acc = db.get('accounts') or []
        if not acc:
            bot.reply_to(message, '• لا توجد حسابات في البوت ❌')
            return
        url = message.text.strip() if message.text else ''
        true, false = 0, 0
        for y in acc:
            try:
                _pyro_run(leave_chat(y['s'], url))
                true += 1
            except Exception as e:
                false += 1
                continue
        bot.reply_to(message,
            f'• تم الخروج من القناة/المجموعة ✅\n'
            f'• القناة : <code>{url}</code>\n'
            f'• نجح : {true} حساب\n'
            f'• فشل : {false} حساب',
            parse_mode='HTML', disable_web_page_preview=True)
        return

    if type_req == 'free_member':
        if not db.get(f'free_member_{cid}_proccess'):
            return
        if message.text:
            try:
                amount = int(message.text)
            except:
                r = bot.reply_to(message, f'• رجاء ارسل رقم فقط ، اعد المحاولة مره اخري')
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            _min, _max = svc_min('free_member'), svc_max('free_member')
            if amount < _min:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if amount > _max:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            _price_per = svc_price('free_member')
            _total_price = _price_per * amount
            acc = db.get(f'user_{message.from_user.id}')
            if _total_price > 0 and int(acc.get('coins', 0)) < _total_price:
                bot.reply_to(message,
                    f'• نقاطك غير كافية ❌\n'
                    f'• تحتاج إلى <b>{_total_price}</b> نقطة\n'
                    f'• رصيدك الحالي: <b>{acc["coins"]}</b> نقطة',
                    reply_markup=bk_cancel, parse_mode="HTML")
                return
            load_ = db.get('accounts') or []
            if len(load_) < amount:
                bot.reply_to(message, f'• عدد حسابات البوت غير كافية لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
                return
            _req_txt = (
                f'╔══════════════════════╗\n'
                f'       👥 طلب أعضاء قناة جديد\n'
                f'╚══════════════════════╝\n\n'
                f'✅ الكمية المطلوبة : {amount} عضو\n'
                f'💰 التكلفة الإجمالية : <b>{_total_price} نقطة</b>\n\n'
                f'🔗 أرسل الآن معرف قناتك أو رابطها\n'
                f'━━━━━━━━━━━━━━━━━━━━'
            )
            x = bot.reply_to(message, _req_txt, parse_mode="HTML")
            bot.register_next_step_handler(x, get_url_free_mem, amount)
            return

    if type_req == 'members':
        if not db.get(f'member_{cid}_proccess'):
            return
        if message.text:
            try:
                amount = int(message.text)
            except:
                r = bot.reply_to(message, f'• رجاء ارسل رقم فقط ، اعد المحاولة مره اخري')
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            _min, _max = svc_min('member'), svc_max('member')
            if amount < _min:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if amount > _max:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            pr = svc_price('member') * amount
            acc = db.get(f'user_{message.from_user.id}')
            if int(pr) > int(acc.get('coins', 0)):
                bot.reply_to(message, f'• نقاطك غير كافية ، تحتاج الي   {pr - amount}  نقطة')
                return
            load_ = db.get('accounts') or []
            if len(load_) < amount:
                bot.reply_to(message, f'• عدد حسابات البوت غير كافية لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
                return
            _req_txt = (
                f'╔══════════════════════╗\n'
                f'       👥 طلب أعضاء قناة عامة جديد\n'
                f'╚══════════════════════╝\n\n'
                f'✅ الكمية المطلوبة : {amount} عضو\n\n'
                f'🔗 أرسل الآن معرف قناتك أو رابطها\n'
                f'━━━━━━━━━━━━━━━━━━━━'
            )
            x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
            bot.register_next_step_handler(x, get_url_mem, amount)
            return

    if type_req == 'membersp':
        if not db.get(f'memberp_{cid}_proccess'):
            return
        if message.text:
            try:
                amount = int(message.text)
            except:
                r = bot.reply_to(message, f'• رجاء ارسل رقم فقط ، اعد المحاولة مره اخري')
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            _min, _max = svc_min('membersp'), svc_max('membersp')
            if amount < _min:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if amount > _max:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            pr = svc_price('member') * amount
            acc = db.get(f'user_{message.from_user.id}')
            if int(pr) > int(acc.get('coins', 0)):
                bot.reply_to(message, f'• نقاطك غير كافية ، تحتاج الي   {pr - amount}  نقطة')
                return
            load_ = db.get('accounts') or []
            if len(load_) < amount:
                bot.reply_to(message, f'• عدد حسابات البوت غير كافية لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
                return
            _req_txt = (
                f'╔══════════════════════╗\n'
                f'       🔐 طلب أعضاء قناة خاصة جديد\n'
                f'╚══════════════════════╝\n\n'
                f'✅ الكمية المطلوبة : {amount} عضو\n\n'
                f'🔗 أرسل الآن رابط الدعوة الخاص بقناتك الخاصة\n'
                f'━━━━━━━━━━━━━━━━━━━━'
            )
            x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
            bot.register_next_step_handler(x, get_url_memp, amount)
            return

    if type_req == 'react':
        if not db.get(f'react_{cid}_proccess'):
            return
        if message.text:
            try:
                amount = int(message.text)
            except:
                r = bot.reply_to(message, f'• رجاء ارسل رقم ف��ط ، اعد المحاولة مره اخري')
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            _min, _max = svc_min('react'), svc_max('react')
            if amount < _min:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if amount > _max:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            pr = svc_price('react') * amount
            acc = db.get(f'user_{message.from_user.id}')
            if int(pr) > int(acc.get('coins', 0)):
                bot.reply_to(message, f'• نقاطك غير كافية ، تحتاج الي   {pr - amount}  نقطة')
                return
            load_ = db.get('accounts') or []
            if len(load_) < amount:
                bot.reply_to(message, f'• عدد حسابات البوت غير كافية لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
                return
            _req_txt = (
                f'╔═══════════════════���══╗\n'
                f'       ⚡ طلب تفاعلات اختياري جديد\n'
                f'╚══════════════════════╝\n\n'
                f'✅ الكمية المطلوبة : {amount} تفاعل\n\n'
                f'🔗 أرسل الآن رابط المنشور\n'
                f'━━━━━━━━━━━━━━━━━━━━'
            )
            x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
            bot.register_next_step_handler(x, get_react_url_first, amount)
            return

    if type_req == 'forward':
        if not db.get(f'forward_{cid}_proccess'):
            return
        if message.text:
            try:
                amount = int(message.text)
            except:
                r = bot.reply_to(message, f'• رجاء ارسل رقم فقط ، اعد المحا��لة مره اخري')
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            _min, _max = svc_min('forward'), svc_max('forward')
            if amount < _min:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if amount > _max:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            pr = svc_price('forward') * amount
            acc = db.get(f'user_{message.from_user.id}')
            if int(pr) > int(acc.get('coins', 0)):
                bot.reply_to(message, f'• نقاطك غير كافية ، تحتاج الي   {pr - amount}  نقطة')
                return
            load_ = db.get('accounts') or []
            if len(load_) < amount:
                bot.reply_to(message, f'• عدد حسابات البوت غير كافية لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
                return
            _req_txt = (
                f'╔══════════════════════╗\n'
                f'       📤 طلب توجيهات منشور جديد\n'
                f'╚══════════════════════╝\n\n'
                f'✅ الكمية المطلوبة : {amount} توجيه\n\n'
                f'🔗 أرسل الآن رابط المنشور\n'
                f'━━━━━━━━━━━━━━━━━━━━'
            )
            x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
            bot.register_next_step_handler(x, get_url_forward, amount)
            return

    if type_req == 'poll':
        if not db.get(f'poll_{cid}_proccess'):
            return
        if message.text:
            try:
                amount = int(message.text)
            except:
                r = bot.reply_to(message, f'• رجاء ارسل رقم فقط ، اعد المحاولة مره اخري')
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            _min, _max = svc_min('poll'), svc_max('poll')
            if amount < _min:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if amount > _max:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            pr = svc_price('poll') * amount
            acc = db.get(f'user_{message.from_user.id}')
            if int(pr) > int(acc.get('coins', 0)):
                bot.reply_to(message, f'• نقاطك غير كافية ، تحتاج الي   {pr - amount}  نقطة')
                return
            load_ = db.get('accounts') or []
            if len(load_) < amount:
                bot.reply_to(message, f'• عدد حسابات البوت غير كافية لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
                return
            _req_txt = (
                f'╔══════════════════════╗\n'
                f'       📊 طلب استفتاء جديد\n'
                f'╚══════════════════════╝\n\n'
                f'✅ الكمية المطلوبة : {amount} صوت\n\n'
                f'🔗 أرسل الآن رابط المنشور\n'
                f'━━━━━━━━━━━━━━━━━━━━'
            )
            x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
            bot.register_next_step_handler(x, get_url_poll, amount)
            return

    if type_req == 'reactsrandom':
        if not db.get(f'reacts_{cid}_proccess'):
            return
        if message.text:
            try:
                amount = int(message.text)
            except:
                r = bot.reply_to(message, f'• رجاء ارسل رقم فقط ، اعد المحاولة مره اخري')
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            _min, _max = svc_min('reacts'), svc_max('reacts')
            if amount < _min:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if amount > _max:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            pr = svc_price('react') * amount
            acc = db.get(f'user_{message.from_user.id}')
            if int(pr) > int(acc.get('coins', 0)):
                bot.reply_to(message, f'• نقاطك غير كافية ، تحتاج الي   {pr - amount}  نقطة')
                return
            load_ = db.get('accounts') or []
            if len(load_) < amount:
                bot.reply_to(message, f'• عدد حسابات البوت غير كافية لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
                return
            _req_txt = (
                f'╔══════════════════════╗\n'
                f'       🎲 طلب تفاعلات عشوائي جديد\n'
                f'╚══════════════════════╝\n\n'
                f'✅ الكمية المطلوبة : {amount} تفاعل\n\n'
                f'🔗 أرسل الآن رابط المنشور\n'
                f'━━━━━━━━━━━━━━━━━━━━'
            )
            x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
            bot.register_next_step_handler(x, get_reacts_url, amount)
            return

    if type_req == 'react_special':
        return  # تم نقل المنطق لـ react_special_get_url

    if type_req == 'view':
        if not db.get(f'view_{cid}_proccess'):
            return
        if message.text:
            try:
                amount = int(message.text)
            except:
                r = bot.reply_to(message, f'• رجاء ارسل رقم فقط ، اعد المحاولة مره اخري')
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            _min, _max = svc_min('view'), svc_max('view')
            if amount < _min:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if amount > _max:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            pr = svc_price('view') * amount
            acc = db.get(f'user_{message.from_user.id}')
            if int(pr) > int(acc.get('coins', 0)):
                bot.reply_to(message, f'• نقاطك غير كافية ، تحتاج الي   {pr - amount}  نقطة')
                return
            load_ = db.get('accounts') or []
            if len(load_) < amount:
                bot.reply_to(message, f'• عدد حسابات البوت غير كافية لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
                return
            _req_txt = (
                f'╔══════════════════════╗\n'
                f'       👁 طلب مشاهدات جديد\n'
                f'╚══════════════════════╝\n\n'
                f'✅ الكمية المطلوبة : {amount} مشاهدة\n\n'
                f'🔗 أرسل الآن رابط المنشور\n'
                f'━━━━━━━━━━━━━━━━━━━━'
            )
            x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
            bot.register_next_step_handler(x, get_view_url, amount)
            return

    if type_req == 'votes':
        if not db.get(f'vote_{cid}_proccess'):
            return
        if message.text:
            try:
                amount = int(message.text)
            except:
                r = bot.reply_to(message, f'• رجاء ارسل رقم فقط ، اعد المحاولة مره اخري')
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            _min, _max = svc_min('votes'), svc_max('votes')
            if amount < _min:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if amount > _max:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            pr = svc_price('votes') * amount
            acc = db.get(f'user_{message.from_user.id}')
            if int(pr) > int(acc.get('coins', 0)):
                bot.reply_to(message, f'نقاطك غير كافية لتنفيذ طلبك ، تحتاج الى {pr - amount} نقطة .')
                return
            load_ = db.get('accounts') or []
            if len(load_) < amount:
                bot.reply_to(message, f'• عدد حسابات البوت لا تكفي لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
                return
            _req_txt = (
                f'╔══════════════════════╗\n'
                f'       🗳️ طلب تصويت مسابقات جديد\n'
                f'╚══════════════════════╝\n\n'
                f'✅ الكمية المطلوبة : {amount} صوت\n\n'
                f'⏱ أرسل الآن وقت الانتظار بين التصويت (بالثواني)\n'
                f'• أرسل 0 لتنفيذ فوري | الحد الأقصى 500\n'
                f'━━━━━━━━━━━━━━━━━━━━'
            )
            x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
            bot.register_next_step_handler(x, get_time_votes, amount)
            return

    if type_req == 'votes_fsub':
        if not db.get(f'votes_fsub_{cid}_proccess'):
            return
        if message.text:
            try:
                amount = int(message.text)
            except:
                r = bot.reply_to(message, f'• رجاء ارسل رقم فقط ، اعد المحاولة مره اخري')
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            _min, _max = svc_min('votes_fsub'), svc_max('votes_fsub')
            if amount < _min:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if amount > _max:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            pr = svc_price('votes_fsub') * amount
            acc = db.get(f'user_{message.from_user.id}')
            if int(pr) > int(acc.get('coins', 0)):
                bot.reply_to(message, f'نقاطك غير كافية لتنفيذ طلبك ، تحتاج الى {pr - amount} نقطة .')
                return
            load_ = db.get('accounts') or []
            if len(load_) < amount:
                bot.reply_to(message, f'• عدد حسابات البوت لا تكفي لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
                return
            _req_txt = (
                f'╔══════════════════════╗\n'
                f'       🏆 طلب تصويت مسابقات اشتراك إجباري\n'
                f'╚══════════════════════╝\n\n'
                f'✅ الكمية المطلوبة : {amount} صوت\n\n'
                f'⏱ أرسل الآن وقت الانتظار بين التصويت (بالثواني)\n'
                f'• أرسل 0 لتنفيذ فوري | الحد الأقصى 500\n'
                f'━━━━━━━━━━━━━━━━━━━━'
            )
            x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
            bot.register_next_step_handler(x, get_time_votes_fsub, amount)
            return

    if type_req == 'spam':
        if not db.get(f'spam_{cid}_proccess'):
            return
        if message.text:
            amount = None
            try:
                amount = int(message.text)
            except:
                bot.reply_to(message, f'• رجاء ارسل عدد فقط ، اعد المحاولة لاحقا', reply_markup=bk_cancel, parse_mode="HTML")
                return
            load_ = db.get('accounts')
            _min, _max = svc_min('spam'), svc_max('spam')
            if amount < _min:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if amount > _max:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if len(load_) < amount:
                bot.reply_to(message, text=f'• عدد حسابات البوت لا تكفي لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
                return
            pr = svc_price('spam') * amount
            acc = db.get(f'user_{message.from_user.id}')
            if acc.get('coins', 0) < pr:
                bot.reply_to(message, f'�� نقاطك غير كافية لتنفيذ طلبك ، تحتاج الي {pr - amount} نقطه', reply_markup=bk_cancel, parse_mode="HTML")
                return
            _req_txt = (
                f'╔══════════════════════╗\n'
                f'       💣 طلب سبام رسائل جديد\n'
                f'╚══════════════════════╝\n\n'
                f'✅ الكمية المطلوبة : {amount} رسالة\n\n'
                f'👤 أرسل الآن يوزر أو رابط الحساب المستهدف\n'
                f'━━━━━━━━━━━━━━━━━━━━'
            )
            x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
            bot.register_next_step_handler(x, get_url_spam, amount)
            return

    if type_req == 'userbot':
        if not db.get(f'userbot_{cid}_proccess'):
            return
        if message.text:
            try:
                amount = int(message.text)
            except:
                r = bot.reply_to(message, f'• رجاء ارسل رقم فقط ، اعد المحاولة مره اخري')
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            _min, _max = svc_min('userbot'), svc_max('userbot')
            if amount < _min:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if amount > _max:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            pr = svc_price('userbot') * amount
            acc = db.get(f'user_{message.from_user.id}')
            if int(pr) > int(acc.get('coins', 0)):
                bot.reply_to(message, f'• نقاطك غير كافية ، تحتاج الي   {pr - amount}  نقطة')
                return
            load_ = db.get('accounts') or []
            if len(load_) < amount:
                bot.reply_to(message, f'• عدد حسابات البوت غير كافية لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
                return
            _req_txt = (
                f'╔══════════════════════╗\n'
                f'       🤖 طلب مستخدمين بوت جديد\n'
                f'╚══════════════════════╝\n\n'
                f'✅ الكمية المطلوبة : {amount} مستخدم\n\n'
                f'🔗 أرسل الآن رابط أو معرف البوت المستهدف\n'
                f'━━━━━━━━━━━━━━━━━━━━'
            )
            x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
            bot.register_next_step_handler(x, get_bot_user, amount)
            return

    if type_req == 'linkbot':
        if not db.get(f'linkbot_{cid}_proccess'):
            return
        if message.text:
            try:
                amount = int(message.text)
            except:
                r = bot.reply_to(message, f'• رجاء ارسل رقم فقط ، اعد المحاولة مره اخري')
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            _min, _max = svc_min('linkbot'), svc_max('linkbot')
            if amount < _min:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if amount > _max:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            pr = svc_price('linkbot') * amount
            acc = db.get(f'user_{message.from_user.id}')
            if int(pr) > int(acc.get('coins', 0)):
                bot.reply_to(message, f'• نقاطك غير كافية ، تحتاج الي   {pr - amount}  نقطة')
                return
            load_ = db.get('accounts') or []
            if len(load_) < amount:
                bot.reply_to(message, f'• عدد حسابات البوت غير كافية لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
                return
            _req_txt = (
                f'╔══════════════════════╗\n'
                f'       🔑 طلب روابط دع��ة جديد\n'
                f'╚══════════════════════╝\n\n'
                f'✅ الكمية المطلوبة : {amount} رسالة\n\n'
                f'🔗 أرسل الآن رابط الدعوة الخاص بالبوت\n'
                f'━━━━━━━━━━━━━━━━━━━━'
            )
            x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
            bot.register_next_step_handler(x, link_bot, amount)
            return

    if type_req == 'linkbot2':
        if not db.get(f'linkbot2_{cid}_proccess'):
            return
        if message.text:
            try:
                amount = int(message.text)
            except:
                bot.reply_to(message, f'• رجاء ارسل رقم فقط ، اعد المحاولة مره اخري', reply_markup=bk_cancel, parse_mode='HTML')
                return
            _min, _max = svc_min('linkbot2'), svc_max('linkbot2')
            if amount < _min:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if amount > _max:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            pr = svc_price('linkbot2') * amount
            acc = db.get(f'user_{message.from_user.id}')
            if int(pr) > int(acc.get('coins', 0)):
                bot.reply_to(message, f'• نقاطك غير كافية ، تحتاج الي   {pr - amount}  نقطة')
                return
            load_ = db.get('accounts') or []
            if len(load_) < amount:
                bot.reply_to(message, f'• عدد حسابات البوت غير كافية لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
                return
            _req_txt = (
                f'╔══════════════════════╗\n'
                f'       💎 طلب روابط دعوة VIP جديد\n'
                f'╚══════════════════════╝\n\n'
                f'✅ الكمية المطلوبة : {amount} رسالة\n\n'
                f'🔗 أرسل الآن رابط الدعوة الخاص بك\n'
                f'━━━━━━━━━━━━━━━━━━━━'
            )
            x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel, parse_mode='HTML')
            bot.register_next_step_handler(x, link_bot2, amount)
            return

    if type_req == 'comments':
        if not db.get(f'comments_{cid}_proccess'):
            return
        if message.text:
            try:
                amount = int(message.text)
            except:
                r = bot.reply_to(message, f'• رجاء ارسل رقم فقط ، اعد المحاولة مره اخري')
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            _min, _max = svc_min('comments'), svc_max('comments')
            if amount < _min:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            if amount > _max:
                r = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=bk_cancel, parse_mode="HTML")
                bot.register_next_step_handler(r, get_amount, type_req)
                return
            pr = svc_price('comments') * amount
            acc = db.get(f'user_{message.from_user.id}')
            if int(pr) > int(acc.get('coins', 0)):
                bot.reply_to(message, f'• نقاطك غير كافية ، تحتاج الي   {pr - amount}  نقطة')
                return
            load_ = db.get('accounts') or []
            if len(load_) < amount:
                bot.reply_to(message, f'• عدد حسابات البوت غير كافية لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
                return
            _req_txt = (
                f'╔══════════════════════╗\n'
                f'       💬 طلب تعليقات جديد\n'
                f'╚══════════════════════╝\n\n'
                f'✅ الكمية المطلوبة : {amount} تعليق\n\n'
                f'🔗 أرسل الآن رابط المنشور\n'
                f'⚠️ انسخ الرابط من القناة مباشرة\n'
                f'━━━━━━━━━━━━━━━━━━━━'
            )
            x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
            bot.register_next_step_handler(x, get_comments_url, amount)
            return

def get_time_votes(message, amount):
    try:
        wait_time = int(message.text)
    except:
        bot.reply_to(message, text=f'• رجاء ارسل الوقت بشكل صحيح')
        return
    if wait_time < 0:
        bot.reply_to(message, text=f'• رجاء ارسل وقت الرشق بين 0 و 500')
        return
    if wait_time > 500:
        bot.reply_to(message, text=f'• رجاء ارسل وقت الرشق بين 0 و 500')
        return
    _req_txt = (
        f'╔══════════════════════╗\n'
        f'       🗳️ طلب تصويت مسابقات جديد\n'
        f'╚══════════════════════╝\n\n'
        f'✅ الكمية المطلوبة : {amount} صوت\n'
        f'⏱ الوقت بين التصويت : {wait_time} ثانية\n\n'
        f'🔗 أرسل الآن رابط المنشور\n'
        f'━━━━━━━━━━━━━━━━━━━━'
    )
    x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
    bot.register_next_step_handler(x, get_url_votes, amount, wait_time)

def get_time_votes_fsub(message, amount):
    try:
        wait_time = int(message.text)
    except:
        bot.reply_to(message, text=f'• رجاء ارسل الوقت بشكل صحيح')
        return
    if wait_time < 0 or wait_time > 500:
        bot.reply_to(message, text=f'• رجاء ارسل وقت بين 0 و 500')
        return
    _req_txt = (
        f'╔══════════════════════╗\n'
        f'       🏆 طلب تصويت مسابقات اشتراك إجباري\n'
        f'╚══════════════════════╝\n\n'
        f'✅ الكمية المطلوبة : {amount} صوت\n'
        f'⏱ الوقت بين التصويت : {wait_time} ثانية\n\n'
        f'🔗 أرسل الآن رابط منشور التصويت\n'
        f'━━━━━━━━━━━━━━━━━━━━'
    )
    x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
    bot.register_next_step_handler(x, get_url_votes_fsub, amount, wait_time)

def get_url_votes_fsub(message, amount, wait_time):
    url = message.text
    if not checks(url):
        bot.reply_to(message, text=f'• رجاء ارسل الرابط بشكل صحيح')
        return
    _req_txt = (
        f'╔══════════════════════╗\n'
        f'       🏆 طلب تصويت مسابقات اشتراك إجباري\n'
        f'╚══════════════════════╝\n\n'
        f'✅ الكمية : {amount} صوت\n'
        f'⏱ الوقت بين التصويت : {wait_time} ثانية\n'
        f'🔗 رابط التصويت : {url}\n\n'
        f'📢 أرسل الآن معرف قناة الاشتراك الإجباري\n'
        f'• لإضافة أكثر من قناة أرسل بهذا الشكل: @ch1 @ch2\n'
        f'• ندعم حتى 10 قنوات\n'
        f'━━━━━━━━━━━━━━━━━━━━'
    )
    x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
    bot.register_next_step_handler(x, votes_fsub_chforce, amount, wait_time, url)

def votes_fsub_chforce(message, amount, wait_time, vote_url):
    raw = message.text.replace('\n', ' ')
    channels_list = [
        c.strip().replace('https://t.me/', '').replace('@', '')
        for c in raw.split(' ')
        if c.strip()
    ]
    if not channels_list:
        bot.reply_to(message, text='• رجاء ارسل معرف قناة واحدة على الأقل')
        return
    if len(channels_list) > 10:
        bot.reply_to(message, text='• الحد الأقصى للقنوات هو 10 قنوات فقط')
        return
    channels_display = ' | '.join([f'@{c}' for c in channels_list])
    load_ = db.get('accounts')
    acc = db.get(f'user_{message.from_user.id}')
    typerr = 'تصويت مسابقات اشتراك إجباري'
    bot.reply_to(message, text=(
        f'• تم بدء طلبك بنجاح ✅\n\n'
        f'• النوع : {typerr}\n'
        f'• الرابط : {vote_url}\n'
        f'• الكمية : {amount}\n'
        f'• الوقت بين التصويت : {wait_time} ثانية\n'
        f'• قنوات الاشتراك : {channels_display}'
    ), disable_web_page_preview=True)
    prog = bot.send_message(chat_id=int(message.from_user.id), text=f'• عزيزي تبقي {amount} علي اكتمال طلبك ....')
    bot.send_message(chat_id=int(sudo), text=(
        f'• قام شخص بطلب من البوت\n'
        f'• النوع : {typerr}\n'
        f'• العدد : {amount}\n'
        f'• الرابط : {vote_url}\n'
        f'• القنوات : {channels_display}\n'
        f'• ايديه : {message.from_user.id}\n'
        f'• يوزره : @{message.from_user.username}\n'
        f'• الوقت : {wait_time} ثانية'
    ))
    send_order_to_channel(message.from_user, typerr, "خدمات البوت VIP", amount, 0)
    true, false = 0, 0
    nume = int(amount)
    for y in load_:
        if true >= amount or (true + false) >= amount * 2:
            break
        try:
            x = _pyro_run(vote_one_fsub(y['s'], vote_url, wait_time, channels_list))
            if x == 'o':
                continue
            if x is True:
                true += 1
                nume -= 1
                bot.edit_message_text(chat_id=message.from_user.id, message_id=prog.message_id, text=f'• عزيزي تبقي {nume} علي اكتمال طلبك ....')
            else:
                false += 1
        except Exception as e:
            print(e)
            continue
    if true >= 1:
        for ix in range(true):
            acc['coins'] -= votes_fsub_price
        db.set(f'user_{message.from_user.id}', acc)
    addord()
    user_id = message.from_user.id
    buys = int(db.get(f"user_{user_id}_buys")) if db.exists(f"user_{user_id}_buys") else 0
    buys += 1
    db.set(f"user_{user_id}_buys", int(buys))
    bot.reply_to(message, text=(
        f'• تم اكتمال طلبك بنجاح ✅\n'
        f'• تم ارسال : {true}\n'
        f'• لم يتم ارسال : {false}\n'
        f'• تم خصم : {true * votes_fsub_price}'
    ), reply_markup=bk_cancel, parse_mode="HTML")
    send_order_complete_to_channel(message.from_user, typerr, 'خد��ات البوت VIP', amount, true, false, true * votes_fsub_price)
    return
    url = message.text
    if 'https://t.me' in url:
        x = bot.reply_to(
            message,
            text=(
                f'أرسل الان معرف قناة الاشتراك الاجباري\n\n'
                f'لإضافة أكثر من قناة أرسل القنوات بهذا الشكل وبرسالة واحدة\n\n'
                f'• ملحوظه ندعم حتى 10 قنوات\n\n'
                f'@ch1 @ch2 @ch3\n\n'
                f'ضع فراغ واحد بين المعرف والآخر'
            )
        )
        bot.register_next_step_handler(x, linkbot_chforce, amount, url)
    else:
        bot.reply_to(message, text=f'• رجاء ارسل الرابط بشكل صحيح')
        return

def dump_votes(message):
    url = message.text
    load_ = db.get('accounts')
    acc = db.get(f'user_{message.from_user.id}')
    typerr = 'سحب تصويت'
    bot.reply_to(message, text=f'• تم بدء طليك بنجاح ✅ : \n\n• النوع : {typerr}\n• الرابط : {url} \n', disable_web_page_preview=True)
    bot.send_message(chat_id=int(sudo), text=f'• قام شخص بطلب من البوت\n• النوع : {typerr} \n• الرابط : {url} \n• ايديه : {message.from_user.id} \n• يوزره : @{message.from_user.username} ', disable_web_page_preview=True)
    send_order_to_channel(message.from_user, typerr, "خدمات البوت", 0, 0)
    true, false = 0, 0
    for num in load_:
        try:
            x = _pyro_run(dump_votess(num['s'], url))
            if x == 'o':
                continue
            if x is True:
                true += 1
            else:
                false += 1
        except Exception as e:
            print(f"Error: {e}")
            continue
    addord()
    user_id = message.from_user.id
    buys = int(db.get(f"user_{user_id}_buys")) if db.exists(f"user_{user_id}_buys") else 0
    buys += 1
    db.set(f"user_{user_id}_buys", int(buys))
    bot.reply_to(message, text=f'• تم اكتمال طلبك بنجاح ✅:\n\n• تم سحب : {false} تصويت\n• لم يتم سحب : {true}', reply_markup=bk_cancel, parse_mode="HTML")
    send_order_complete_to_channel(message.from_user, typerr, 'خدمات البوت', 0, true, false, 0)

def lespoints(message):
    if message.text == "/start":
        start_message(message)
        return
    try:
        uid = int(message.text)
    except:
        bot.reply_to(message, f'• ارسل الايدي بشكل صحيح رجاء')
        return
    x = bot.reply_to(message, '• ارسل الان الكمية :')
    bot.register_next_step_handler(x, lespoints_final, uid)

def lespoints_final(message, uid):
    if message.text == "/start":
        start_message(message)
        return
    try:
        amount = int(message.text)
    except:
        bot.reply_to(message, f'يجب ان تكون الكمية ارقام فقط')
        return
    b = db.get(f'user_{uid}')
    b['coins'] -= amount
    db.set(f'user_{uid}', b)
    bot.reply_to(message, f'تم بنجاح نقاطه الان : {b["coins"]} ')

def linkbot_chforce(message, amount, url):
    # دعم أكثر من قناة — مفصولة بفاصلة أو سطر جديد
    raw = message.text.replace('\n', ' ')
    channels_list = [
        c.strip().replace('https://t.me/', '').replace('@', '')
        for c in raw.split(' ')
        if c.strip()
    ]
    if not channels_list:
        bot.reply_to(message, text='• رجاء ارسل معرف قناة واحدة على الأقل')
        return
    if len(channels_list) > 10:
        bot.reply_to(message, text='• الحد الأقصى للقنوات هو 10 قنوات فقط')
        return

    bot_id = url.split("?start=")[0].split("/")[-1]
    user_id_param = url.split("?start=")[1]
    channel = "@" + bot_id
    tex = "/start " + user_id_param
    pr = svc_price('linkbot2') * amount
    load_ = db.get('accounts')
    acc = db.get(f'user_{message.from_user.id}')
    _lb2_price = svc_price('linkbot2')
    typerr = 'رابط دعوة اشتراك اجباري VIP'
    channels_display = ' | '.join([f'@{c}' for c in channels_list])
    db.delete(f'linkbot2_{message.from_user.id}_proccess')
    bot.reply_to(message, text=f'• تم بدء طلبك بنجاح ✅\n\n• النوع : {typerr}\n• الرابط : {url}\n• الكمية : {amount}\n• قنوات الاشتراك الاجباري : {channels_display}', disable_web_page_preview=True)
    bot.send_message(chat_id=int(sudo), text=f'• قام شخص بطلب من البوت\n• النوع : {typerr}\n• العدد : {amount}\n• الرابط : {url}\n• القنوات : {channels_display}\n• ايديه : {message.from_user.id}\n• يوزره : @{message.from_user.username}', disable_web_page_preview=True)
    send_order_to_channel(message.from_user, typerr, "خدمات البوت", amount, 0)
    true, false = 0, 0
    for y in load_:
        if true >= amount or (true + false) >= amount * 2:
            break
        try:
            x = _pyro_run(linkbot2(y['s'], channel, tex, channels_list))
            if x is True:
                true += 1
            else:
                false += 1
        except Exception as e:
            print(e)
            continue
    if true >= 1:
        acc['coins'] -= int(true * _lb2_price)
        db.set(f'user_{message.from_user.id}', acc)
    addord()
    user_id = message.from_user.id
    buys = int(db.get(f"user_{user_id}_buys")) if db.exists(f"user_{user_id}_buys") else 0
    db.set(f"user_{user_id}_buys", buys + 1)
    bot.reply_to(message, text=f'• تم اكتمال طلبك بنجاح ✅\n• تم ارسال : {true}\n• لم يتم ارسال : {false}\n• تم خصم : {true * _lb2_price}', reply_markup=bk_cancel, parse_mode="HTML")
    send_order_complete_to_channel(message.from_user, typerr, 'خدمات البوت', amount, true, false, true * _lb2_price)
    return

def show_order_confirm(message, order_type: str, amount: int, url: str, price: int, extra: dict = None):
    """يعرض شاشة تأكيد الطلب قبل التنفيذ"""
    uid = message.from_user.id
    _pending_orders[uid] = {
        'type':    order_type,
        'amount':  amount,
        'url':     url,
        'price':   price,
        'extra':   extra or {},
        'msg_id':  message.message_id,
        'chat_id': message.chat.id,
    }
    info  = db.get(f'user_{uid}') or {}
    coins = int(info.get('coins', 0))
    confirm_txt = (
        f"╔══════════════════════╗\n"
        f"       ✅ تأكيد الطلب\n"
        f"╚══════════════════════╝\n\n"
        f"📋 <b>النوع</b>    : {order_type}\n"
        f"🔢 <b>الكمية</b>   : {amount:,}\n"
        f"🔗 <b>الرابط</b>   : <code>{url}</code>\n"
        f"💰 <b>السعر</b>    : {price:,} نقطة\n"
        f"💳 <b>رصيدك</b>   : {coins:,} نقطة\n"
        f"💳 <b>بعد الطلب</b>: {max(0, coins - price):,} نقطة\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"هل تريد تأكيد الطلب؟"
    )
    keys = mk(row_width=2)
    keys.add(
        btn('✅ تأكيد', callback_data='confirm_order', color='green'),
        btn('❌ إلغاء', callback_data='cancel_order',  color='red'),
    )
    try:
        bot.send_message(
            uid, confirm_txt,
            reply_markup=keys,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"[show_order_confirm] error: {e}")

def def_execute_order(uid: int, cb=None):
    """ينفذ الطلب المعلق بعد التأكيد"""
    order = _pending_orders.pop(uid, None)
    if not order:
        if cb:
            try: bot.answer_callback_query(cb.id, "⚠️ انتهت صلاحية الطلب", show_alert=True)
            except: pass
        return

    otype   = order['type']
    amount  = order['amount']
    url     = order['url']
    price   = order['price']
    extra   = order['extra']
    chat_id = order['chat_id']

    info = db.get(f'user_{uid}') or {}
    coins = int(info.get('coins', 0))
    if coins < price:
        try:
            bot.send_message(uid, f"❌ نقاطك غير كافية\n💳 رصيدك: {coins:,}\n💰 المطلوب: {price:,}", parse_mode='HTML')
        except: pass
        return

    # إشعار بدء التنفيذ
    try:
        bot.send_message(uid,
            f"⚡ <b>جارٍ تنفيذ طلبك...</b>\n\n"
            f"📋 {otype}\n🔢 الكمية: {amount:,}\n💰 السعر: {price:,} نقطة",
            parse_mode='HTML'
        )
    except: pass

    load_ = db.get('accounts') or []
    true, false = 0, 0

    try:
        if otype == 'تعليقات':
            text = extra.get('text', '')
            for y in load_:
                if true >= amount or (true + false) >= amount * 2: break
                try:
                    _pyro_run(send_comment(y['s'], url, text))
                    true += 1
                except: false += 1
            unit_price = svc_price('comments')

        elif otype == 'أعضاء':
            for y in load_:
                if true >= amount or (true + false) >= amount * 2: break
                try:
                    x = _pyro_run(join_chat(y['s'], url))
                    if x is True: true += 1
                    else: false += 1
                except: false += 1
            unit_price = svc_price('member')

        elif otype == 'تفاعلات':
            like = extra.get('like', '👍')
            for y in load_:
                if true >= amount or (true + false) >= amount * 2: break
                try:
                    _pyro_run(reactions(y['s'], url, like))
                    true += 1
                except: false += 1
            unit_price = svc_price('react')

        elif otype == 'مشاهدات':
            for y in load_:
                if true >= amount or (true + false) >= amount * 2: break
                try:
                    _pyro_run(view(y['s'], url))
                    true += 1
                except: false += 1
            unit_price = svc_price('views')

        elif otype == 'تصويت':
            wait_time = extra.get('wait_time', 0)
            poll_idx  = extra.get('poll_idx', 0)
            for y in load_:
                if true >= amount or (true + false) >= amount * 2: break
                try:
                    _pyro_run(poll(y['s'], url, int(poll_idx)))
                    true += 1
                except: false += 1
            unit_price = svc_price('votes')

        elif otype == 'أعضاء قناة عامة':
            chat_target = url.replace('https://t.me/', '').replace('@', '') if not detect(url) else url
            for y in load_:
                if true >= amount or (true + false) >= amount * 2: break
                try:
                    x = _pyro_run(join_chat(y['s'], chat_target))
                    if x is True: true += 1
                    else: false += 1
                except: false += 1
            unit_price = svc_price('free_member')

        elif otype == 'أعضاء قناة خاصة VIP':
            for y in load_:
                if true >= amount or (true + false) >= amount * 2: break
                try:
                    x = _pyro_run(join_chatp(y['s'], url))
                    if x == 'o': continue
                    if x is True: true += 1
                    else: false += 1
                except: false += 1
            unit_price = member_price

        elif otype == 'توجيهات':
            for y in load_:
                if true >= amount or (true + false) >= amount * 2: break
                try:
                    x = _pyro_run(forward(y['s'], url))
                    if x == 'o': continue
                    if x is True: true += 1
                    else: false += 1
                except: false += 1
            unit_price = forward_price

        elif otype == 'استفتاء':
            poll_idx = extra.get('poll_idx', 0)
            for y in load_:
                if true >= amount or (true + false) >= amount * 2: break
                try:
                    x = _pyro_run(poll(y['s'], url, int(poll_idx)))
                    if x == 'o': continue
                    if x is True: true += 1
                    else: false += 1
                except: false += 1
            unit_price = poll_price

        elif otype == 'رس��ئل مزعجة VIP':
            text = extra.get('text', '')
            for y in load_:
                if true >= amount or (true + false) >= amount * 2: break
                try:
                    _pyro_run(send_message(y['s'], chat=url, text=text))
                    true += 1
                except: false += 1
            unit_price = spam_price

        elif otype == 'مستخدمين بوت':
            bot_url = url.replace('https://t.me/', '').replace('@', '')
            for y in load_:
                if true >= amount or (true + false) >= amount * 2: break
                try:
                    x = _pyro_run(userbot(y['s'], bot_url))
                    if x == 'o': continue
                    if x is True: true += 1
                    else: false += 1
                except: false += 1
            unit_price = userbot_price

        elif otype == 'رابط دعوة':
            bot_id = url.split('?start=')[0].split('/')[-1]
            user_id_param = url.split('?start=')[1]
            channel = '@' + bot_id
            tex = '/start ' + user_id_param
            for y in load_:
                if true >= amount or (true + false) >= amount * 2: break
                try:
                    x = _pyro_run(linkbot(y['s'], channel, tex))
                    if x == 'o': continue
                    if x is True: true += 1
                    else: false += 1
                except: false += 1
            unit_price = linkbot_price

        elif otype == 'تفاعلات اختياري':
            like = extra.get('like', '👍')
            for y in load_:
                if true >= amount or (true + false) >= amount * 2: break
                try:
                    x = _pyro_run(reactions(y['s'], url, like))
                    if x == 'o': continue
                    if x is True: true += 1
                    else: false += 1
                except: false += 1
            unit_price = svc_price('react')

        elif otype == 'تفاعلات عشوائي':
            for y in load_:
                if true >= amount or (true + false) >= amount * 2: break
                try:
                    x = _pyro_run(reaction(y['s'], url))
                    if x == 'o': continue
                    if x is True: true += 1
                    else: false += 1
                except: false += 1
            unit_price = svc_price('react')

        elif otype == 'رشق اي��وجي مميز':
            emoji_text  = extra.get('emoji_text', '')
            custom_id   = extra.get('custom_emoji_id', '')
            for y in load_:
                if true >= amount or (true + false) >= amount * 2: break
                try:
                    x = _pyro_run(reactions(y['s'], url, emoji_text))
                    if x == 'o': continue
                    if x is True: true += 1
                    else: false += 1
                except: false += 1
            unit_price = svc_price('react_special')

        else:
            unit_price = price // amount if amount else price

        actual_cost = true * unit_price
        if true >= 1:
            info['coins'] = coins - actual_cost
            db.set(f'user_{uid}', info)
        addord()
        buys = int(db.get(f'user_{uid}_buys') or 0) + 1
        db.set(f'user_{uid}_buys', buys)

        # إشعار ال��ستخد��
        _user_obj = type('U', (), {'id': uid, 'username': info.get('username',''), 'first_name': info.get('name','')})()
        bot.send_message(uid,
            f"✅ <b>اكتمل طلبك بنجاح!</b>\n\n"
            f"📋 {otype}\n"
            f"✔️ تم: {true:,} | ❌ فشل: {false:,}\n"
            f"💰 تم خصم: {actual_cost:,} نقطة\n"
            f"💳 رصيدك الآن: {int(info.get('coins',0)):,} نقطة",
            parse_mode='HTML'
        )
        send_order_complete_to_channel(_user_obj, otype, 'خدمات البوت', amount, true, false, actual_cost)
        try: check_and_award_level(uid)
        except: pass

    except Exception as e:
        bot.send_message(uid, f"❌ حدث خطأ أثناء التنفيذ: {e}")

def get_comments_url(message, amount):
    url = message.text
    if 'https://t.me' not in url:
        bot.reply_to(message, '• رجاء ارسل الرابط بشكل صحيح', reply_markup=bk_cancel)
        return
    x = bot.reply_to(message, '• الآن أرسل التعليق الذي تريد رشقه:', reply_markup=bk_cancel)
    bot.register_next_step_handler(x, comment_text, amount, url)

def comment_text(message, amount, url):
    text = message.text
    if not text:
        bot.reply_to(message, '• أرسل نص التعليق', reply_markup=bk_cancel)
        return
    if len(text) > 100:
        bot.reply_to(message, '• أرسل رسالة أقل من 100 حرف', reply_markup=bk_cancel)
        return
    price = svc_price('comments') * amount
    show_order_confirm(message, 'تعليقات', amount, url, price, extra={'text': text})

def link_bot(message, amount):
    url = message.text
    if not url or '?start=' not in url:
        bot.reply_to(message, '• رابط غير صحيح، أرسل رابط دعوة صحيح', reply_markup=bk_cancel)
        return
    acc = db.get(f'user_{message.from_user.id}')
    price = linkbot_price * amount
    if price > int(acc.get('coins', 0)):
        bot.reply_to(message, f'• نقاطك غير كافية ❌\n• تحتاج إلى <b>{price}</b> نقطة', reply_markup=bk_cancel, parse_mode="HTML")
        return
    show_order_confirm(message, 'رابط دعوة', amount, url, price)

def link_bot2(message, amount):
    """خطوة 1: استلام رابط الدعوة"""
    url = message.text
    if not url or 'https://t.me/' not in url or '?start=' not in url:
        x = bot.reply_to(
            message,
            '• رابط غير صحيح\nارسل رابط الدعوة حرفيا مثل:\nhttps://t.me/BotName?start=XXXXX',
            reply_markup=bk_cancel, parse_mode='HTML'
        )
        bot.register_next_step_handler(x, link_bot2, amount)
        return
    try:
        url.split('?start=')[0].split('/')[-1]
        url.split('?start=')[1]
    except Exception:
        x = bot.reply_to(message, '• تعذر قراءة الرابط، اعد الارسال.', reply_markup=bk_cancel, parse_mode='HTML')
        bot.register_next_step_handler(x, link_bot2, amount)
        return

    x = bot.reply_to(
        message,
        '• الكمية : ' + str(amount) + '\n• الرابط : ' + url +
        '\n\n🔗 ارسل الان معرف قناة الاشتراك الاجباري\n\n'
        'لاضافة اكثر من قناة ارسل المعرفات بهذا الشكل:\n'
        '@ch1 @ch2 @ch3\n\n'
        '• الحد الاقصى 10 قنوات',
        reply_markup=bk_cancel, parse_mode='HTML'
    )
    bot.register_next_step_handler(x, linkbot_chforce, amount, url)

def get_bot_user(message, amount):
    url = message.text.replace('https://t.me/', '').replace('@', '')
    acc = db.get(f'user_{message.from_user.id}')
    price = userbot_price * amount
    if price > int(acc.get('coins', 0)):
        bot.reply_to(message, f'• نقاطك غير كافية ❌\n• تحتاج إلى <b>{price}</b> نقطة', reply_markup=bk_cancel, parse_mode="HTML")
        return
    show_order_confirm(message, 'مستخدمين بوت', amount, url, price)

def get_url_spam(message, amount):
    url = message.text
    if 'https://t.me' in url or '@' in url:
        x = bot.reply_to(message, text=f'• الان ارسل الرسالة اللي تريد ترسلها للحساب')
        bot.register_next_step_handler(x, get_text, amount, url)
        return

def get_text(message, amount, url):
    text = message.text
    if text:
        if len(text) > 1000:
            bot.reply_to(message, text='• ارسل رسالة تكون اقل من 1000 حرف ')
            return
        acc = db.get(f'user_{message.from_user.id}')
        price = spam_price * amount
        if price > 0 and int(acc.get('coins', 0)) < price:
            bot.reply_to(message, f'• نقاطك غير كافية ❌\n• تحتاج إلى <b>{price}</b> نقطة', reply_markup=bk_cancel, parse_mode="HTML")
            return
        show_order_confirm(message, 'رسائل مزعجة VIP', amount, url, price, extra={'text': text})

def get_url_memp(message, amount):
    url = message.text
    info = get(message.from_user.id)
    price = member_price * amount
    if price > int(info['coins']):
        bot.reply_to(message, text=f'نقاطك غير كافية لتنفيذ طلبك تحتاج الي   {price - int(info["coins"])}  ', reply_markup=bk_cancel, parse_mode="HTML")
        return
    load = db.get('accounts')
    if len(load) < 1:
        bot.reply_to(message, text='عدد حسابات البوت لا تكفي لتنفيذ طلبك ', reply_markup=bk_cancel, parse_mode="HTML")
        return
    show_order_confirm(message, 'أعضاء قناة خاصة VIP', amount, url, price)

def get_url_mem(message, amount):
    url = message.text
    if 'https://t.me' in url or '@' in url:
        info = get(message.from_user.id)
        price = svc_price('member') * amount
        if price > int(info['coins']):
            bot.reply_to(message, f'• نقاطك غير كافية، تحتاج {price - int(info["coins"])} نقطة إضافية', reply_markup=bk_cancel, parse_mode="HTML")
            return
        show_order_confirm(message, 'أعضاء', amount, url, price)
    else:
        bot.reply_to(message, '• رجاء أرسل الرابط بشكل صحيح', reply_markup=bk_cancel)

def get_url_free_mem(message, amount):
    """رشق ��عضاء قناة عامة — مدفوع بسعر قابل للتعديل من لوحة الأدمن"""
    url = message.text
    if 'https://t.me' in url or '@' in url:
        if detect(url):
            chat_target = url
        else:
            chat_target = url.replace('https://t.me/', '').replace('@', '')
        load = db.get('accounts')
        if len(load) < 1:
            bot.reply_to(message, text='• عدد حسابات البوت لا تكفي لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
            return
        _price_per = svc_price('free_member')
        acc = db.get(f'user_{message.from_user.id}')
        _total_price = _price_per * amount
        # فحص أخير للنقاط قبل التنفيذ
        if _total_price > 0 and int(acc.get('coins', 0)) < _total_price:
            bot.reply_to(message,
                f'• نقاطك غير كافية ❌\n'
                f'• تحتاج إلى <b>{_total_price}</b> نقطة\n'
                f'• رصيدك الحالي: <b>{acc["coins"]}</b> نقطة',
                reply_markup=bk_cancel, parse_mode="HTML")
            return
        show_order_confirm(message, 'أعضاء قناة عامة', amount, url, _total_price)
    else:
        bot.reply_to(message, text='• رجاء ارسل معرف القناة او رابطها بشكل صحيح\n• مثال: @channel أو https://t.me/channel', reply_markup=bk_cancel, parse_mode="HTML")

def checks(link):
    pattern = r"https?://t\.me/(\w+)/(\d+)"
    match = re.match(pattern, link)
    if match:
        username = match.group(1)
        post_id = match.group(2)
        return username, post_id
    else:
        return False

def get_react_url_first(message, amount):
    """يستقبل رابط المنشور، يجيب إيموجيات القناة، يعرضها كأزرار"""
    url = message.text.strip() if message.text else ''
    cid = message.from_user.id
    if not checks(url):
        x = bot.reply_to(message, '• رجاء ارسل الرابط بشكل صحيح', reply_markup=bk_cancel)
        bot.register_next_step_handler(x, get_react_url_first, amount)
        return


    async def _fetch_reacts_special():
        """يجيب الـ custom emoji reactions من القناة باستخدام Raw API"""
        try:
            session = db.get('accounts')[0]['s']
            client = Client('::memory::', api_id=API_ID, api_hash=API_HASH,
                            in_memory=True, session_string=session)
            await client.start()
            parts_url = url.rstrip('/').split('/')
            ch = parts_url[-2]
            available = []
            try:
                from pyrogram.raw import functions as raw_fns, types as raw_types
                peer = await client.resolve_peer(ch)
                result = await client.invoke(
                    raw_fns.channels.GetFullChannel(channel=peer)
                )
                full_chat = result.full_chat
                av = getattr(full_chat, 'available_reactions', None)
                if av is not None:
                    # نوع 1: ChatReactionsSome (قائمة محددة)
                    reactions_list = getattr(av, 'reactions', [])
                    for r in reactions_list:
                        # Pyrogram raw: ReactionCustomEmoji has document_id
                        # ReactionEmoji has emoticon
                        ceid = getattr(r, 'document_id', None)
                        emoji_char = getattr(r, 'emoticon', None)
                        r_type = type(r).__name__
                        if ceid or 'Custom' in r_type:
                            em_char = emoji_char or '⭐'
                            available.append((em_char, str(ceid) if ceid else ''))
                        elif emoji_char:
                            available.append((emoji_char, None))
            except Exception as _raw_e:
                print(f"[raw_reactions] {_raw_e}")
                # fallback: نجيب من chat object
                try:
                    chat_obj = await client.get_chat(ch)
                    ar = getattr(chat_obj, 'available_reactions', None)
                    if ar and hasattr(ar, 'reactions'):
                        for r in ar.reactions:
                            em = getattr(r, 'emoji', None) or getattr(r, 'emoticon', None)
                            ceid = getattr(r, 'custom_emoji_id', None)
                            if ceid:
                                available.append((em or '⭐', str(ceid)))
                            elif em:
                                available.append((em, None))
                except Exception as _fb:
                    print(f"[fallback_reactions] {_fb}")
            await client.stop()
            return available
        except Exception as e:
            print(f"[fetch_reacts_special] {e}")
            return []

    try:
        available_raw = _pyro_run(_fetch_reacts_special())
    except:
        available_raw = []

    # لو ما قدرناش نجيب — نستخدم القائمة الافتراضية (بدون custom emoji)
    if not available_raw:
        available_raw = [(em, None) for em in ["👍","🤩","🎉","🔥","❤️","🥰","🥱","🥴","🌚","🍌","💔","🤨",
                     "😐","😈","👎","😁","😢","💩","🤮","🤔","🤯","🤬","💯","😍",
                     "🕊","🐳","🤝","👻","🗿","🍾","⚡️","🏆","🤡","🌭","🆒","💊"]]

    # نحفظ الرابط والكمية والإيموجيات
    db.set(f'react_special_url_{cid}', url)
    db.set(f'react_special_amount_{cid}', amount)
    db.set(f'react_special_list_{cid}', available_raw[:20])


    nums = ['1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣','7️⃣','8️⃣','9️⃣','🔟',
            '1⃣1⃣','1⃣2⃣','1⃣3⃣','1⃣4⃣','1⃣5⃣','1⃣6⃣','1⃣7⃣','1⃣8⃣','1⃣9⃣','2⃣0⃣']
    emoji_lines = ''
    ek = mk(row_width=5)
    for i, (em, ceid) in enumerate(available_raw[:20]):
        if ceid:
            emoji_lines += f'{nums[i]} <tg-emoji emoji-id="{ceid}">{em}</tg-emoji>\n'
        else:
            emoji_lines += f'{nums[i]} {em or "⭐"}\n'
        ek.add(TelebotButton(text=str(i+1), callback_data=f'pick_special_num_{cid}_{i}'))
    ek.add(btn('❌ إلغاء ورجوع', callback_data='back', color='red'))

    bot.reply_to(
        message,
        f'✨ <b>اختر الإيموجي المميز</b>\n\n'
        f'🔗 الرابط : {url}\n'
        f'🔢 الكمية : {amount}\n\n'
        f'⬇️ <b>الإيموجيات المتاحة:</b>\n'
        f'{emoji_lines}\n'
        f'اضغط رقم الإيموجي الذي تريده:',
        reply_markup=ek,
        parse_mode='HTML',
        disable_web_page_preview=True
    )

def get_react(message, amount):
    rs = ["👍","🤩","🎉","🔥","❤️","🥰","🥱","🥴","🌚","🍌","💔","🤨","😐","🖕","😈","👎",
          "😁","😢","💩","🤮","🤔","🤯","🤬","💯","😍","🕊","🐳","🤝","👨","🦄","🎃","🤓",
          "👀","👻","🗿","🍾","🍓","⚡️","🏆","🤡","🌭","🆒","🙈","🎅","🎄","☃️","💊"]
    if message.text in rs:
        _req_txt = (
            f'╔══════════════════════╗\n'
            f'       ⚡ طلب تفاعلات اختياري جديد\n'
            f'╚══════════════════════╝\n\n'
            f'✅ الكمية المطلوبة : {amount} تفاعل\n'
            f'😀 التفاعل المختار : {message.text}\n\n'
            f'🔗 أرسل الآن رابط المنشور\n'
            f'━━━━━━━━━━━━━━━━━━━━'
        )
        x = bot.reply_to(message, _req_txt, reply_markup=bk_cancel)
        bot.register_next_step_handler(x, get_url_react, amount, message)
    else:
        x = bot.reply_to(message, f'• رجاء ارسل التفاعل بشكل صحيح', reply_markup=bk_cancel)
        bot.register_next_step_handler(x, get_react, amount)
        return

def get_url_votes(message, amount, wait_time):
    url = message.text
    if not checks(url):
        bot.reply_to(message, text=f'• رجاء ارسل الرابط بشكل صحيح')
        return
    acc = db.get(f'user_{message.from_user.id}')
    price = vote_price * amount
    if price > int(acc.get('coins', 0)):
        bot.reply_to(message, f'• نقاطك غير كافية ❌\n• تحتاج إلى <b>{price}</b> نقطة', reply_markup=bk_cancel, parse_mode="HTML")
        return
    show_order_confirm(message, 'تصويت', amount, url, price, extra={'wait_time': wait_time})

def get_url_react(message, amount, like):
    url = message.text
    like = like.text
    if not checks(url):
        bot.reply_to(message, text=f'• رجاء ارسل الرابط بشكل صحيح')
        return
    acc = db.get(f'user_{message.from_user.id}')
    price = svc_price('react') * amount
    if price > int(acc.get('coins', 0)):
        bot.reply_to(message, f'• نقاطك غير كافية ❌\n• تحتاج إلى <b>{price}</b> نقطة', reply_markup=bk_cancel, parse_mode="HTML")
        return
    show_order_confirm(message, 'تفاعلات اخت��اري', amount, url, price, extra={'like': like})

def get_reacts_url(message, amount):
    url = message.text
    if not checks(url):
        bot.reply_to(message, text=f'• رجاء ارسل الرابط بشكل صحيح')
        return
    acc = db.get(f'user_{message.from_user.id}')
    price = svc_price('react') * amount
    if price > int(acc.get('coins', 0)):
        bot.reply_to(message, f'• نقاطك غير كافية ❌\n• تحتاج إلى <b>{price}</b> نقطة', reply_markup=bk_cancel, parse_mode="HTML")
        return
    show_order_confirm(message, 'تفاعلات عشوائي', amount, url, price)

def react_special_get_emoji_first(message):
    """الخطوة 1: استقبال الإي��وجي (عا��ي أو مميز) من المستخدم"""
    cid = message.from_user.id
    if not db.get(f'react_special_{cid}_proccess'):
        return
    if message.text and message.text.startswith('/'):
        bot.reply_to(message, '❌ تم إلغاء الطلب', reply_markup=bk)
        db.delete(f'react_special_{cid}_proccess')
        return

    # نستقبل الإيموجي — سواء text أو sticker/animation entity
    emoji_text   = ''
    custom_emoji_id = ''

    # فحص custom emoji entities
    if message.entities:
        for ent in message.entities:
            if ent.type == 'custom_emoji':
                custom_emoji_id = str(ent.custom_emoji_id)
                emoji_text = message.text[ent.offset: ent.offset + ent.length] if message.text else '✨'
                break

    # لو مش custom emoji — نأخذ النص كإيموجي عادي
    if not emoji_text:
        emoji_text = (message.text or '').strip()

    if not emoji_text:
        cancel_kb = mk(row_width=1)
        cancel_kb.add(btn('❌ إلغاء ورجوع', callback_data='back', color='red'))
        x = bot.reply_to(message, '⚠️ الرجاء إرسال إي��وجي صحيح', reply_markup=cancel_kb)
        bot.register_next_step_handler(x, react_special_get_emoji_first)
        return

    # حفظ الإيموجي
    db.set(f'react_special_emoji_{cid}', emoji_text)
    db.set(f'react_special_ceid_{cid}', custom_emoji_id)

    _mn = svc_min('react_special')
    _mx = svc_max('react_special')

    emoji_display = f'<tg-emoji emoji-id="{custom_emoji_id}">{emoji_text}</tg-emoji>' if custom_emoji_id else emoji_text
    emoji_type = '✨ مميز (animated)' if custom_emoji_id else '😀 عادي'

    cancel_kb = mk(row_width=1)
    cancel_kb.add(btn('❌ إلغاء ورجوع', callback_data='back', color='red'))
    x = bot.reply_to(
        message,
        f'╔══════════════════════╗\n'
        f'       ✨ رشق إيموجي مميز\n'
        f'╚══════════════════════╝\n\n'
        f'😀 الإيموجي : {emoji_display}\n'
        f'🏷 النوع : {emoji_type}\n\n'
        f'🔢 أرسل الآن العدد المطلوب ({_mn} - {_mx})',
        reply_markup=cancel_kb,
        parse_mode='HTML'
    )
    bot.register_next_step_handler(x, react_special_get_amount_new)

def react_special_get_amount_new(message):
    """الخطوة 2: استقبال الكمية"""
    cid = message.from_user.id
    cancel_kb = mk(row_width=1)
    cancel_kb.add(btn('❌ إلغاء ورجوع', callback_data='back', color='red'))

    if message.text and message.text.startswith('/'):
        bot.reply_to(message, '❌ تم إلغاء الطلب', reply_markup=bk)
        db.delete(f'react_special_{cid}_proccess')
        return

    try:
        amount = int((message.text or '').strip())
    except:
        x = bot.reply_to(message, '• رجاء ارسل رقم فقط، اعد المحاولة', reply_markup=cancel_kb)
        bot.register_next_step_handler(x, react_special_get_amount_new)
        return

    _min, _max = svc_min('react_special'), svc_max('react_special')
    if amount < _min:
        x = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=cancel_kb)
        bot.register_next_step_handler(x, react_special_get_amount_new)
        return
    if amount > _max:
        x = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=cancel_kb)
        bot.register_next_step_handler(x, react_special_get_amount_new)
        return

    pr = svc_price('react_special') * amount
    acc = db.get(f'user_{cid}')
    if int(pr) > int(acc.get('coins', 0)):
        bot.reply_to(message, f'• نقاطك غير كافية ❌\n• تحتاج إلى <b>{pr}</b> نقطة', reply_markup=bk_cancel, parse_mode='HTML')
        return

    load_ = db.get('accounts') or []
    if len(load_) < amount:
        bot.reply_to(message, '• عدد حسابات البوت غير كافية لتنفيذ طلبك', reply_markup=bk_cancel)
        return

    emoji_text = db.get(f'react_special_emoji_{cid}') or ''
    emoji_display = emoji_text

    x = bot.reply_to(
        message,
        f'╔══════════════════════╗\n'
        f'       ✨ رشق إيموجي مميز\n'
        f'╚══════════════════════╝\n\n'
        f'😀 الإيموجي : {emoji_display}\n'
        f'✅ الكمية : {amount} تفاعل\n\n'
        f'🔗 أرسل الآن رابط المنشور\n'
        f'⚠️ انسخ الرابط من القناة مباشرة\n'
        f'━━━━━━━━━━━━━━━━━━━━',
        reply_markup=cancel_kb
    )
    bot.register_next_step_handler(x, react_special_get_url_final, amount)

def react_special_get_url_final(message, amount):
    """الخطوة 3: استقبال الرابط وتنفيذ الطلب"""
    cid = message.from_user.id
    cancel_kb = mk(row_width=1)
    cancel_kb.add(btn('❌ إلغاء ورجوع', callback_data='back', color='red'))

    if message.text and message.text.startswith('/'):
        bot.reply_to(message, '❌ تم إلغاء الطلب', reply_markup=bk)
        db.delete(f'react_special_{cid}_proccess')
        return

    url = (message.text or '').strip()
    if not checks(url):
        x = bot.reply_to(message, '• رجاء ارسل الرابط بشكل صحيح', reply_markup=cancel_kb)
        bot.register_next_step_handler(x, react_special_get_url_final, amount)
        return

    emoji_text = db.get(f'react_special_emoji_{cid}') or ''
    _svc_price = svc_price('react_special')
    pr = _svc_price * amount
    acc = db.get(f'user_{cid}')
    if int(pr) > int(acc.get('coins', 0)):
        bot.reply_to(message, f'• نقاطك غير كافية ❌\n• تحتاج إلى <b>{pr}</b> نقطة', reply_markup=bk_cancel, parse_mode='HTML')
        return

    load_ = db.get('accounts') or []
    if len(load_) < amount:
        bot.reply_to(message, '• عدد حسابات البوت غير كافية', reply_markup=bk_cancel)
        return

    typerr = 'رشق ايموجي مميز'
    bot.reply_to(
        message,
        f'• تم بدء طلبك بنجاح ✅\n\n'
        f'• النوع : {typerr}\n'
        f'• الايموجي : {emoji_text}\n'
        f'• الرابط : {url}\n'
        f'• الكمية : {amount}',
        disable_web_page_preview=True
    )
    bot.send_message(
        chat_id=int(sudo),
        text=(
            f'• قام شخص بطلب من البوت\n'
            f'• النوع : {typerr}\n'
            f'• العدد : {amount}\n'
            f'• الرابط : {url}\n'
            f'• الايموجي : {emoji_text}\n'
            f'• ايديه : {cid}\n'
            f'• يوزره : @{message.from_user.username}'
        )
    )
    send_order_to_channel(message.from_user, typerr, "خدمات البوت", amount, 0)
    true, false = 0, 0
    for y in load_:
        if true >= amount or (true + false) >= amount * 2:
            break
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            x = loop.run_until_complete(reactions(y['s'], url, emoji_text))
            loop.close()
            if x == 'o':
                continue
            if x is True:
                true += 1
            else:
                false += 1
        except Exception as e:
            print(e)
            continue

    if true >= 1:
        for _ in range(true):
            acc['coins'] -= _svc_price
        db.set(f'user_{cid}', acc)
    addord()
    buys = int(db.get(f"user_{cid}_buys")) if db.exists(f"user_{cid}_buys") else 0
    db.set(f"user_{cid}_buys", buys + 1)

    # تنظيف
    db.delete(f'react_special_{cid}_proccess')
    db.delete(f'react_special_emoji_{cid}')
    db.delete(f'react_special_ceid_{cid}')

    bot.reply_to(
        message,
        f'• تم اكتمال طلبك بنجاح ✅\n'
        f'• تم ارسال : {true}\n'
        f'• لم يتم ارسال : {false}\n'
        f'• تم خصم : {true * _svc_price}',
        reply_markup=bk_cancel, parse_mode='HTML'
    )
    send_order_complete_to_channel(message.from_user, typerr, 'خدمات البوت', amount, true, false, true * _svc_price)

def react_special_step1_amount(message):
    """الخطوة 1: استقبال الكمية"""
    cid = message.from_user.id
    cancel_kb = mk(row_width=1)
    cancel_kb.add(btn('❌ إلغاء ورجوع', callback_data='back', color='red'))

    if message.text and message.text.startswith('/'):
        db.delete(f'react_special_{cid}_proccess')
        bot.reply_to(message, '❌ تم إلغاء الطلب', reply_markup=bk)
        return

    _mn = svc_min('react_special')
    _mx = svc_max('react_special')
    try:
        amount = int((message.text or '').strip())
        if amount < _mn or amount > _mx:
            raise ValueError()
    except ValueError:
        x = bot.reply_to(message, f'❌ أرسل رقم صحيح بين {_mn} و {_mx}:', reply_markup=cancel_kb)
        bot.register_next_step_handler(x, react_special_step1_amount)
        return

    # نحفظ الكمية وننتقل لطلب الرابط
    db.set(f'react_special_amount_{cid}', amount)
    x = bot.reply_to(
        message,
        f'✅ الكمية : {amount}\n\n'
        f'🔗 <b>أرسل الآن رابط المنشور</b>\n'
        f'⚠️ انسخ الرابط من القناة مباشرة',
        reply_markup=cancel_kb, parse_mode='HTML'
    )
    bot.register_next_step_handler(x, react_special_step2_url)

def react_special_step2_url(message):
    """الخطوة 2: استقبال الرابط وجلب إيموجيات القناة"""
    cid = message.from_user.id
    cancel_kb = mk(row_width=1)
    cancel_kb.add(btn('❌ إلغاء ورجوع', callback_data='back', color='red'))

    if message.text and message.text.startswith('/'):
        db.delete(f'react_special_{cid}_proccess')
        db.delete(f'react_special_amount_{cid}')
        bot.reply_to(message, '❌ تم إلغاء الطلب', reply_markup=bk)
        return

    url = (message.text or '').strip()
    if not checks(url):
        x = bot.reply_to(message, '❌ رجاء أرسل الرابط بشكل صحيح\nمثال: https://t.me/channel/123', reply_markup=cancel_kb)
        bot.register_next_step_handler(x, react_special_step2_url)
        return

    amount = int(db.get(f'react_special_amount_{cid}') or 0)
    _svc_price = svc_price('react_special')
    acc = db.get(f'user_{cid}') or {}
    if int(_svc_price * amount) > int(acc.get('coins', 0)):
        bot.reply_to(message,
            f'❌ <b>نقاطك غير كافية</b>\n'
            f'• تحتاج : {_svc_price * amount:,} نقطة\n'
            f'• رصيدك : {int(acc.get("coins", 0)):,} نقطة',
            reply_markup=bk_cancel, parse_mode='HTML')
        db.delete(f'react_special_{cid}_proccess')
        db.delete(f'react_special_amount_{cid}')
        return

    # نحفظ الرابط
    db.set(f'react_special_url_{cid}', url)

    # نجلب إيموجيات القناة
    wait_msg = bot.reply_to(message, '⏳ جارٍ جلب إيموجيات القناة...')
    try:
        parsed = checks(url)
        username_or_id = parsed[0] if parsed else None
        available = []

        async def _fetch_reactions():
            try:
                client = Client("::memory::", api_id=API_ID, api_hash=API_HASH, in_memory=True)
                # نستخ��م أول session متاحة
                sessions = db.get('accounts') or []
                if sessions:
                    client = Client("::memory::", api_id=API_ID, api_hash=API_HASH,
                                    session_string=sessions[0]['s'], in_memory=True)
                await client.start()
                try:
                    if username_or_id:
                        chat = await client.get_chat(username_or_id)
                        ar = await client.invoke(
                            functions.messages.GetAvailableReactions(hash=0)
                        )
                        # نحاول نجيب custom reactions من القناة
                        from pyrogram.raw import functions as raw_funcs
                        try:
                            peer = await client.resolve_peer(username_or_id)
                            full = await client.invoke(
                                raw_funcs.channels.GetFullChannel(channel=peer)
                            )
                            chat_full = full.full_chat
                            # نجيب الـ available reactions
                            if hasattr(chat_full, 'available_reactions'):
                                av_react = chat_full.available_reactions
                                if hasattr(av_react, 'reactions'):
                                    for r in av_react.reactions:
                                        ceid2 = getattr(r, 'document_id', None)
                                        emoticon2 = getattr(r, 'emoticon', None)
                                        r_type2 = type(r).__name__
                                        if ceid2 or 'Custom' in r_type2:
                                            available.append((emoticon2 or '⭐', str(ceid2) if ceid2 else ''))
                                        elif emoticon2:
                                            available.append((emoticon2, None))
                        except Exception as _fe:
                            print(f"[fetch_reactions] {_fe}")
                            # fallback: نجيب الـ reactions العامة
                            if hasattr(ar, 'reactions'):
                                for r in ar.reactions[:10]:
                                    em = getattr(r, 'emoticon', None) or getattr(r, 'emoji', None)
                                    if em:
                                        available.append((em, None))
                except Exception as _ce:
                    print(f"[fetch_reactions_chat] {_ce}")
                finally:
                    await client.stop()
            except Exception as _e:
                print(f"[fetch_reactions_main] {_e}")

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_fetch_reactions())
        loop.close()

        try:
            bot.delete_message(wait_msg.chat.id, wait_msg.message_id)
        except:
            pass

        if not available:
            # Fallback: إيموجيات افتراضية شائعة
            available = [
                ('👍', None), ('❤️', None), ('🔥', None), ('🎉', None),
                ('😮', None), ('😢', None), ('👏', None), ('🤩', None),
                ('🥰', None), ('💯', None), ('✅', None), ('🏆', None),
            ]

        # نبني أزرار الإيموجيات
        ek = mk(row_width=4)
        # نحفظ الإيموجيات للـ handler
        db.set(f'react_special_list_{cid}', available[:20])

        nums = ['1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣','7️⃣','8️⃣','9️⃣','🔟',
                '1⃣1⃣','1⃣2⃣','1⃣3⃣','1⃣4⃣','1⃣5⃣','1⃣6⃣','1⃣7⃣','1⃣8⃣','1⃣9⃣','2⃣0⃣']
        emoji_lines = ''
        ek = mk(row_width=5)
        for i, (em, ceid) in enumerate(available[:20]):
            if ceid:
                emoji_lines += f'{nums[i]} <tg-emoji emoji-id="{ceid}">{em}</tg-emoji>\n'
            else:
                emoji_lines += f'{nums[i]} {em or "⭐"}\n'
            ek.add(TelebotButton(text=str(i+1), callback_data=f'pick_special_num_{cid}_{i}'))
        ek.add(btn('❌ إلغاء ورجوع', callback_data='back', color='red'))

        bot.send_message(
            cid,
            f'✨ <b>اختر الإيموجي المميز</b>\n\n'
            f'🔗 الرابط : {url}\n'
            f'🔢 الكمية : {amount}\n\n'
            f'⬇️ <b>الإيموجيات المتاحة:</b>\n'
            f'{emoji_lines}\n'
            f'اضغط رقم الإيموجي الذي تريده:',
            reply_markup=ek, parse_mode='HTML',
            disable_web_page_preview=True
        )

    except Exception as e:
        try:
            bot.delete_message(wait_msg.chat.id, wait_msg.message_id)
        except:
            pass
        bot.reply_to(message, f'❌ خطأ في جلب الإيموجيات: {e}\nحاول مرة أخرى', reply_markup=cancel_kb)
        db.delete(f'react_special_{cid}_proccess')
        db.delete(f'react_special_amount_{cid}')
        db.delete(f'react_special_url_{cid}')

def react_special_get_url(message):
    """الخطوة 1: استقبال رابط المنشور ثم جلب الإيموجي المتاحة من القناة"""
    cid = message.from_user.id
    _proc = db.get(f'react_special_{cid}_proccess')
    if not _proc and _proc != True and str(_proc) not in ('True', '1', 'true'):
        return
    url = (message.text or '').strip()
    if message.text and message.text.startswith('/'):
        bot.reply_to(message, '❌ تم إلغاء الطلب', reply_markup=bk)
        db.delete(f'react_special_{cid}_proccess')
        return
    if not checks(url):
        cancel_kb = mk(row_width=1)
        cancel_kb.add(btn('❌ إلغاء ورجوع', callback_data='back', color='red'))
        x = bot.reply_to(message, '• رجاء ارسل الرابط بشكل صحيح، اعد المحاولة', reply_markup=cancel_kb)
        bot.register_next_step_handler(x, react_special_get_url)
        return

    # جيب الإيموجيات المتاحة في القناة مع دعم custom emoji
    async def _fetch_special_reacts():
        try:
            session = db.get('accounts')[0]['s']
            client = Client('::memory::', api_id=API_ID, api_hash=API_HASH,
                            in_memory=True, session_string=session)
            await client.start()
            parts = url.rstrip('/').split('/')
            ch = parts[-2]
            chat = await client.get_chat(ch)
            available = []  # [(emoji_char, custom_emoji_id or None)]
            if hasattr(chat, 'available_reactions'):
                ar = chat.available_reactions
                if hasattr(ar, 'reactions'):
                    for r in ar.reactions:
                        if hasattr(r, 'custom_emoji_id') and r.custom_emoji_id:
                            # custom emoji مميز - نحفظ الـ id كـ char لعرضه
                            emoji_char = getattr(r, 'emoji', None)
                            if not emoji_char or emoji_char == 'None':
                                emoji_char = str(r.custom_emoji_id)
                            available.append((emoji_char, str(r.custom_emoji_id)))
                        elif hasattr(r, 'emoji'):
                            available.append((r.emoji, None))
            await client.stop()
            return available
        except Exception as e:
            print(f'[fetch_special_reacts] {e}')
            return []

    try:
        available = _pyro_run(_fetch_special_reacts())
    except:
        available = []

    # لو ما لقيناش إيموجي — اطلب منه يكتب يدوياً
    if not available:
        cancel_kb = mk(row_width=1)
        cancel_kb.add(btn('❌ إلغاء ورجوع', callback_data='back', color='red'))
        _req_txt = (
            '╔══════════════════════╗\n'
            '       ✨ رشق إيموجي مميز\n'
            '╚══════════════════════╝\n\n'
            f'🔗 الرابط : {url}\n\n'
            '⚠️ لم يتم العثور على إيموجي مخصصة في هذه القناة\n'
            '😀 أرسل الإيموجي يدوياً\n'
            '━━━━━━━━━━━━━━━━━━━━'
        )
        x = bot.reply_to(message, _req_txt, reply_markup=cancel_kb)
        bot.register_next_step_handler(x, get_react_special, url)
        return

    # حفظ الرابط مؤقتاً
    db.set(f'react_special_url_{cid}', url)
    # حفظ الإيموجيات مع custom_emoji_id لاستخدامها في الكولباك
    emoji_data = {f'{e[0]}|||{e[1] or ""}': True for e in available}
    db.set(f'react_special_emojis_{cid}', emoji_data)

    # بناء أزرار الإيموجي (3 في صف)
    ek = mk(row_width=3)
    for (em, ceid) in available[:21]:
        if ceid:
            # custom emoji — نعرض الإيموجي مباشرة (الأزرار لا تدعم HTML)
            label = em if em and em.strip() else f'#{ceid[-6:]}'
            cb = f'pick_special_{cid}_{em}|||{ceid}'
        else:
            label = em
            cb = f'pick_special_{cid}_{em}|||'
        ek.add(TelebotButton(text=label, callback_data=cb))
    ek.add(btn('❌ إلغاء ورجوع', callback_data='back', color='red'))

    bot.reply_to(
        message,
        f'✨ <b>اختر الإيموجي المميز</b>\n\n'
        f'🔗 الرابط : {url}\n\n'
        f'#تحذير في حال الايموجي كان معطل سيتم احتساب المشاهدة وتخطي الا��موجي لذلك تأكد من الايموجي ا��مفعلة في المنشور قبل الرشق\n\n'
        f'الايموجي المميز يظهر بالترتيب حسب المنشور\n'
        f'قم باختياره من الأسفل بنفس الترتيب\n'
        f'──>',
        reply_markup=ek,
        parse_mode='HTML'
    , disable_web_page_preview=True)

def react_special_get_amount(message):
    """الخطوة 3: استقبال العدد وتنفيذ الطلب"""
    cid = message.from_user.id
    chosen = db.get(f'react_special_chosen_{cid}') if db.exists(f'react_special_chosen_{cid}') else ''
    if not chosen:
        bot.reply_to(message, '❌ انتهت صلاحية الطلب، ابدأ من جديد', reply_markup=bk)
        return
    parts = chosen.split('|||')
    emoji_char = parts[0]
    custom_emoji_id = parts[1] if len(parts) > 1 else ''
    url = parts[2] if len(parts) > 2 else ''
    emoji_text = custom_emoji_id if custom_emoji_id and custom_emoji_id.strip() else emoji_char
    cancel_kb = mk(row_width=1)
    cancel_kb.add(btn('❌ إلغاء ورجوع', callback_data='back', color='red'))
    if message.text and message.text.startswith('/'):
        bot.reply_to(message, '❌ تم إلغاء الطلب', reply_markup=bk)
        db.delete(f'react_special_{cid}_proccess')
        db.delete(f'react_special_chosen_{cid}')
        return
    try:
        amount = int((message.text or '').strip())
    except:
        x = bot.reply_to(message, '• رجاء ارسل رقم فقط، اعد المحاولة', reply_markup=cancel_kb)
        bot.register_next_step_handler(x, react_special_get_amount)
        return
    _min, _max = svc_min('react_special'), svc_max('react_special')
    if amount < _min:
        x = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=cancel_kb, parse_mode='HTML')
        bot.register_next_step_handler(x, react_special_get_amount)
        return
    if amount > _max:
        x = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=cancel_kb, parse_mode='HTML')
        bot.register_next_step_handler(x, react_special_get_amount)
        return
    pr = svc_price('react_special') * amount
    acc = db.get(f'user_{cid}')
    if int(pr) > int(acc.get('coins', 0)):
        bot.reply_to(message, f'• نقاطك غير كافية ، تحتاج الي {pr} نقطة', reply_markup=bk_cancel, parse_mode='HTML')
        return
    load_ = db.get('accounts')
    if len(load_) < amount:
        bot.reply_to(message, '• عدد حسابات البوت غير كافية لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode='HTML')
        return
    db.delete(f'react_special_chosen_{cid}')
    db.delete(f'react_special_{cid}_proccess')
    _svc_price = svc_price('react_special')
    pr = _svc_price * amount
    show_order_confirm(message, 'رشق ايموجي مميز', amount, url, pr,
                       extra={'emoji_text': emoji_text, 'custom_emoji_id': custom_emoji_id})

def get_react_special(message, url):
    """الخطوة 2: استقبال الإيموجي وطلب العدد"""
    cid = message.from_user.id
    if message.text and message.text.startswith('/'):
        bot.reply_to(message, '❌ تم إلغاء الطلب', reply_markup=bk)
        db.delete(f'react_special_{cid}_proccess')
        return
    emoji_text = (message.text or '').strip()
    cancel_kb = mk(row_width=1)
    cancel_kb.add(btn('❌ إلغاء ورجوع', callback_data='back', color='red'))
    if not emoji_text:
        x = bot.reply_to(message, '• رجاء ارسل الايموجي المميز بشكل صحيح', reply_markup=cancel_kb)
        bot.register_next_step_handler(x, get_react_special, url)
        return
    _mn = svc_min('react_special')
    _mx = svc_max('react_special')
    _req_txt = (
        '╔══════════════════════╗\n'
        '       ✨ طلب رشق ايموجي ( مميز )\n'
        '╚══════════════════════╝\n\n'
        f'🔗 الرابط : {url}\n'
        f'😀 الايموجي : {emoji_text}\n\n'
        f'🔢 أرسل الآن العدد المطلوب ({_mn} - {_mx})\n'
        '━━━━━━━━━━━━━━━━━━━━'
    )
    x = bot.reply_to(message, _req_txt, reply_markup=cancel_kb)
    bot.register_next_step_handler(x, get_url_react_special, url, message)

def get_url_react_special(message, url, emoji_msg):
    """الخطوة 3: استقبال العدد وتنفيذ الطلب"""
    cid = message.from_user.id
    emoji_text = (emoji_msg.text or '').strip()
    cancel_kb = mk(row_width=1)
    cancel_kb.add(btn('❌ إلغاء ورجوع', callback_data='back', color='red'))
    if message.text and message.text.startswith('/'):
        bot.reply_to(message, '❌ تم إلغاء الطلب', reply_markup=bk)
        db.delete(f'react_special_{cid}_proccess')
        return
    try:
        amount = int((message.text or '').strip())
    except:
        x = bot.reply_to(message, '• رجاء ارسل رقم فقط، اعد المحاولة', reply_markup=cancel_kb)
        bot.register_next_step_handler(x, get_url_react_special, url, emoji_msg)
        return
    _min, _max = svc_min('react_special'), svc_max('react_special')
    if amount < _min:
        x = bot.reply_to(message, f'• رجاء ارسل عدد لا يقل عن {_min}', reply_markup=cancel_kb, parse_mode="HTML")
        bot.register_next_step_handler(x, get_url_react_special, url, emoji_msg)
        return
    if amount > _max:
        x = bot.reply_to(message, f'• رجاء ارسل عدد لا يزيد عن {_max}', reply_markup=cancel_kb, parse_mode="HTML")
        bot.register_next_step_handler(x, get_url_react_special, url, emoji_msg)
        return
    pr = svc_price('react_special') * amount
    acc = db.get(f'user_{message.from_user.id}')
    if int(pr) > int(acc.get('coins', 0)):
        bot.reply_to(message, f'• نقاطك غير كافية ، تحتاج الي {pr} نقطة', reply_markup=bk_cancel, parse_mode="HTML")
        return
    load_ = db.get('accounts')
    if len(load_) < amount:
        bot.reply_to(message, '• عدد حسابات البوت غير كافية لتنفيذ طلبك', reply_markup=bk_cancel, parse_mode="HTML")
        return
    if not checks(url):
        bot.reply_to(message, '• رجاء ارسل الرابط بشكل صحيح')
        return
    load_ = db.get('accounts')
    acc = db.get(f'user_{message.from_user.id}')
    _svc_price = svc_price('react_special')
    typerr = 'رشق ايموجي مميز'
    bot.reply_to(message,
        f'• تم بدء طلبك بنجاح ✅\n\n'
        f'• النوع : {typerr}\n'
        f'• الايموجي : {emoji_text}\n'
        f'• الرابط : {url}\n'
        f'• الكمية : {amount}'
    , disable_web_page_preview=True)
    bot.send_message(
        chat_id=int(sudo),
        text=(
            f'• قام شخص بطلب من البوت\n'
            f'• النوع : {typerr}\n'
            f'• العدد : {amount}\n'
            f'• الرابط : {url}\n'
            f'• الايموجي : {emoji_text}\n'
            f'• ايديه : {message.from_user.id}\n'
            f'• يوزره : @{message.from_user.username}'
        )
    )
    send_order_to_channel(message.from_user, typerr, "خدمات البوت", amount, 0)
    true, false = 0, 0
    for y in load_:
        if true >= amount or (true + false) >= amount * 2:
            break
        try:
            x = _pyro_run(reactions(y['s'], url, emoji_text))
            if x == 'o':
                continue
            if x is True:
                true += 1
            else:
                false += 1
        except Exception as e:
            print(e)
            continue
    if true >= 1:
        for ix in range(true):
            acc['coins'] -= _svc_price
        db.set(f'user_{message.from_user.id}', acc)
    addord()
    user_id = message.from_user.id
    buys = int(db.get(f"user_{user_id}_buys")) if db.exists(f"user_{user_id}_buys") else 0
    buys += 1
    db.set(f"user_{user_id}_buys", int(buys))
    bot.reply_to(
        message,
        f'• تم اكتمال طلبك بنجاح ✅\n• تم ارسال : {true}\n• لم يتم ارسال : {false}\n• تم خصم : {true * _svc_price}',
        reply_markup=bk_cancel, parse_mode="HTML"
    )
    send_order_complete_to_channel(message.from_user, typerr, 'خدمات البوت', amount, true, false, true * _svc_price)
    return

def get_url_forward(message, amount):
    url = message.text
    if not checks(url):
        bot.reply_to(message, text=f'• رجاء ارسل الرابط بشكل صحيح')
        return
    acc = db.get(f'user_{message.from_user.id}')
    price = forward_price * amount
    if price > int(acc.get('coins', 0)):
        bot.reply_to(message, f'• نقاطك غير كافية ❌\n• تحتاج إلى <b>{price}</b> نقطة', reply_markup=bk_cancel, parse_mode="HTML")
        return
    show_order_confirm(message, 'توجيهات', amount, url, price)

def get_url_poll(message, amount):
    url = message.text
    x = checks(url)
    if not x:
        bot.reply_to(message, text='• رجاء ارسل الرابط بشكل صحيح')
        return
    try:
        msg_text = "• ارسل الان تسلسل الإجابة في ا��استفتاء\n\n��� يجب ان ي��راوح بين 0 : 9\n• علما بان اول اختيار يكون تسلسلة 0"
        x2 = bot.reply_to(message, msg_text, parse_mode='HTML')
        bot.register_next_step_handler(x2, start_poll, amount, url)
    except Exception as e:
        bot.reply_to(message, "الرسالة ممسوحة أو القناة المجموعة غير صحيحة.")
        print(e)
        return

def start_poll(message, amount, url):
    num = message.text
    if not checks(url):
        bot.reply_to(message, text=f'• رجاء ارسل الرابط بشكل صحيح')
        return
    acc = db.get(f'user_{message.from_user.id}')
    price = poll_price * amount
    if price > int(acc.get('coins', 0)):
        bot.reply_to(message, f'• نقاطك غير كافية ❌\n• تحتاج إلى <b>{price}</b> نقطة', reply_markup=bk_cancel, parse_mode="HTML")
        return
    show_order_confirm(message, 'استفتاء', amount, url, price, extra={'poll_idx': num})

def get_view_url(message, amount):
    url = message.text
    if not checks(url):
        bot.reply_to(message, text=f'• رجاء ارسل الرابط بشكل صحيح')
        return
    acc = db.get(f'user_{message.from_user.id}')
    price = view_price * amount
    if price > int(acc.get('coins', 0)):
        bot.reply_to(message, f'• نقاطك غير كافية ❌\n• تحتاج إلى <b>{price}</b> نقطة', reply_markup=bk_cancel, parse_mode="HTML")
        return
    show_order_confirm(message, 'مشاهدات', amount, url, price)

def casting(message):
    """نظام الإذاعة المتطور — يُستدعى من زر 'إذاعة نص/صورة/فيديو' """
    idm = message.message_id
    # جلب قنوات الإذاعة من DB
    cast_channels = db.get('cast_channels') or []
    d = db.keys('user_%')
    good = 0
    bad = 0
    bot.reply_to(message, f'📡 جاري الإذاعة...\n👥 المستخدمون: {len(list(d))}\n📢 القنوات: {len(cast_channels)}')
    # إذاعة للمستخدمين
    for user in db.keys('user_%'):
        try:
            uid = db.get(user[0])['id']
            bot.copy_message(chat_id=uid, from_chat_id=message.from_user.id, message_id=idm)
            good += 1
        except:
            bad += 1
            continue
    # إذاعة للقنوات
    ch_good = 0
    ch_bad = 0
    for ch in cast_channels:
        try:
            bot.copy_message(chat_id=ch, from_chat_id=message.from_user.id, message_id=idm)
            ch_good += 1
        except:
            ch_bad += 1
    bot.reply_to(
        message,
        f'✅ اكتملت الإذاعة!\n\n'
        f'👥 المست��دمون:\n• ��م: {good} | فشل: {bad}\n\n'
        f'📢 القنوات:\n• تم: {ch_good} | فشل: {ch_bad}'
    )
    return

def casting_with_link(message):
    """إذاعة مع زر رابط — الخطوة الأولى: استلام الرسالة"""
    x = bot.reply_to(message, '🔗 أرسل الآن نص الزر (مثال: زيارة الموقع):', reply_markup=bk_cancel)
    bot.register_next_step_handler(x, _cast_link_btn_text, message)

def _cast_link_btn_text(message, original_msg):
    btn_text = message.text.strip()
    x = bot.reply_to(message, '🔗 أرسل الآن الرابط:', reply_markup=bk_cancel)
    bot.register_next_step_handler(x, _cast_link_do, original_msg, btn_text)

def _cast_link_do(message, original_msg, btn_text):
    link_url = message.text.strip()
    cast_channels = db.get('cast_channels') or []
    d = db.keys('user_%')
    markup = TelebotMarkup()
    markup.add(TelebotButton(text=btn_text, url=link_url))
    good, bad = 0, 0
    bot.reply_to(message, f'📡 جاري الإذاعة مع زر الرابط...')
    for user in db.keys('user_%'):
        try:
            uid = db.get(user[0])['id']
            bot.copy_message(chat_id=uid, from_chat_id=original_msg.from_user.id,
                             message_id=original_msg.message_id, reply_markup=markup)
            good += 1
        except:
            bad += 1
    ch_good, ch_bad = 0, 0
    for ch in cast_channels:
        try:
            bot.copy_message(chat_id=ch, from_chat_id=original_msg.from_user.id,
                             message_id=original_msg.message_id, reply_markup=markup)
            ch_good += 1
        except:
            ch_bad += 1
    bot.reply_to(
        message,
        f'✅ اكتملت الإذاعة مع الرابط!\n\n'
        f'👥 المستخدمون: تم {good} | فشل {bad}\n'
        f'📢 القنوات: تم {ch_good} | فشل {ch_bad}'
    )

def _cast_add_channel_manual(message):
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    ch = message.text.strip().replace('@', '')
    if not ch:
        bot.reply_to(message, '❌ معرف غير صالح')
        return
    cast_channels = db.get('cast_channels') or []
    if ch in cast_channels:
        bot.reply_to(message, f'⚠️ القناة `{ch}` مضافة مسبقاً', parse_mode='Markdown')
        return
    cast_channels.append(ch)
    db.set('cast_channels', cast_channels)
    keys = mk(row_width=1)
    keys.add(btn('➕ إضافة قناة أخرى', callback_data='cast_add_ch', color='green'))
    keys.add(btn('🔙 رجوع للإذاعة', callback_data='cast', color='blue'))
    bot.reply_to(message, f'✅ تم إضافة القناة: `{ch}`\n📢 إجمالي القنوات: *{len(cast_channels)}*', reply_markup=keys, parse_mode='Markdown')

def _set_vip_thresh(message):
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    try:
        val = int(message.text.strip())
        if val < 1:
            raise ValueError
        db.set('vip_invite_threshold', val)
        bot.reply_to(message, f'✅ تم تعيين عدد الدعوات للـ VIP إلى {val} دعوات بنجاح!')
    except:
        bot.reply_to(message, '❌ أرسل رقماً صحيحاً أكبر من 0')

def adminss(message, type_op):
    if type_op == 'add':
        try:
            uid = int(message.text)
        except:
            bot.reply_to(message, f'• ارسل الايدي بشكل صحيح')
            return
        d = db.get('admins')
        if uid in d:
            bot.reply_to(message, f'• هذا العضو ادمن بالفعل')
            return
        else:
            d.append(uid)
            db.set('admins', d)
            bot.reply_to(message, f'• تم اضافته بنجاح ✅')
            return
    if type_op == 'delete':
        try:
            uid = int(message.text)
        except:
            bot.reply_to(message, f'• ارسل الايدي بشكل صحيح')
            return
        d = db.get('admins')
        if uid not in d:
            bot.reply_to(message, f'• هذا العضو ليس من الادمنية بالبوت')
            return
        else:
            d.remove(uid)
            db.set('admins', d)
            bot.reply_to(message, f'• تم ا��الة العضو من الادمنية بنجاح ✅')
            return

def banned(message, type_op):
    if type_op == 'ban':
        try:
            uid = int(message.text)
        except:
            bot.reply_to(message, f'ارسل الايدي بشكل صحيح')
            return
        d = db.get('badguys')
        if uid in d:
            bot.reply_to(message, f'• هذا العضو محظور من قبل ')
            return
        else:
            d.append(uid)
            db.set('badguys', d)
            bot.reply_to(message, f'• تم حظر العضو من استخدام البوت')
            return
    if type_op == 'unban':
        try:
            uid = int(message.text)
        except:
            bot.reply_to(message, f'• ارسل الايدي بشكل صحيح')
            return
        d = db.get('badguys')
        if uid not in d:
            bot.reply_to(message, f'• هذا العضو غير محظور ')
            return
        else:
            d.remove(uid)
            db.set('badguys', d)
            bot.reply_to(message, f'• تم الغاء حظر العضو بنجاح ✅')
            return

def get_info(message):
    try:
        uid = int(message.text)
    except:
        bot.reply_to(message, f'• ارسل الايدي بشكل صحيح رجاء')
        return
    d = db.get(f'user_{uid}')
    if not d:
        bot.reply_to(message, f'• هذا العضو غير موجود')
        return
    coins = d['coins']
    users_count = len(d['users'])
    bot.reply_to(message, f'• ايديه : {uid}.\n• نقاطه: {coins} نقطة \n• عدد مشاركته لرابط الدعوة : {users_count}')
    return

def send(message):
    if message.text and message.text.strip() in ['❌ إلغاء و رجوع', '/start']:
        bot.reply_to(message, '• تم الإلغاء ✅', reply_markup=bk_cancel)
        return
    try:
        uid = int(message.text)
    except:
        bot.reply_to(message, '• ارسل الايدي بشكل صحيح', reply_markup=bk_cancel)
        return
    if not db.exists(f'user_{uid}'):
        bot.reply_to(message, '• هذا العضو غير موجود في البوت ❌', reply_markup=bk_cancel)
        return
    if int(message.text) == int(message.from_user.id):
        bot.reply_to(message, '• عذرا لا يمكنك تحويل نقاط لنفسك ❌', reply_markup=bk_cancel)
        return
    try:
        chat = bot.get_chat(uid)
        name = chat.first_name or str(uid)
    except:
        name = str(uid)
    from_user = db.get(f'user_{message.from_user.id}') or {}
    coins = int(from_user.get('coins', 0))
    x2 = bot.reply_to(
        message,
        f'👤 <b>تحويل النقاط إلى:</b> {name}\n'
        f'💳 رصيدك الحالي: <b>{coins:,} نقطة</b>\n\n'
        f'• أرسل الآن عدد النقاط التي تريد تحويلها:',
        reply_markup=bk_cancel, parse_mode='HTML'
    )
    bot.register_next_step_handler(x2, get_amount_send, uid)

def get_amount_send(message, uid):
    if message.text and message.text.strip() in ['❌ إلغاء و رجوع', '/start']:
        bot.reply_to(message, '• تم الإلغاء ✅', reply_markup=bk_cancel)
        return
    try:
        amount = int(message.text)
    except:
        bot.reply_to(message, '• الكمية يجب أن تكون عدد فقط', reply_markup=bk_cancel)
        return
    to_user   = db.get(f'user_{uid}')
    from_user = db.get(f'user_{message.from_user.id}')
    if amount < 1:
        bot.reply_to(message, '• لا يمكن ت��ويل عدد أقل من 1', reply_markup=bk_cancel)
        return
    if from_user['coins'] < amount + 500:
        bot.reply_to(message,
            f'• نقاطك غير كافية ❌\n'
            f'• رصيدك: <b>{from_user["coins"]:,}</b> نقطة\n'
            f'• المبلغ: <b>{amount:,}</b> نقطة\n'
            f'• الع��ولة: <b>500</b> نقطة\n'
            f'• الإجمالي المطلوب: <b>{amount + 500:,}</b> نقطة',
            reply_markup=bk_cancel, parse_mode='HTML'
        )
        return
    # شاشة تأكيد ا��تحويل
    try:
        chat = bot.get_chat(uid)
        name = chat.first_name or str(uid)
    except:
        name = str(uid)
    _pending_orders[message.from_user.id] = {
        'type': 'transfer', 'uid': uid, 'amount': amount,
        'name': name, 'url': '', 'price': 0, 'extra': {}
    }
    keys = mk(row_width=2)
    keys.add(
        btn('✅ تأكيد التحويل', callback_data='confirm_transfer', color='green'),
        btn('إلغاء',         callback_data='cancel_order',      color='red'),
    )
    bot.reply_to(
        message,
        f'╔══════════════════════╗\n'
        f'       💸 تأكيد تحويل النقاط\n'
        f'╚══════════════════════╝\n\n'
        f'👤 <b>إلى:</b> {name}\n'
        f'💰 <b>المبلغ:</b> {amount:,} نقطة\n'
        f'⚠️ <b>العمولة:</b> 500 نقطة\n'
        f'💸 <b>إجمالي الخصم:</b> {amount + 500:,} نقطة\n'
        f'💳 <b>رصيدك بعد التحويل:</b> {from_user["coins"] - amount - 500:,} نقطة\n'
        f'━━━━━━━━━━━━━━━━━━━━\n'
        f'هل تريد تأكيد التحويل؟',
        reply_markup=keys, parse_mode='HTML'
    )

def addpoints(message):
    try:
        uid = int(message.text)
    except:
        bot.reply_to(message, f'• ارسل الايدي بشكل صحيح رجاء')
        return
    x = bot.reply_to(message, '• ارسل الان الكمية', reply_markup=bk_cancel)
    bot.register_next_step_handler(x, addpoints_final, uid)

def addpoints_final(message, uid):
    try:
        amount = int(message.text)
    except:
        bot.reply_to(message, f'يجب ان تكون الكمية ارقام فقط')
        return
    b = db.get(f'user_{uid}')
    b['coins'] += amount
    db.set(f'user_{uid}', b)
    bot.reply_to(message, f'تم بنجاح نقاطه الان : {b["coins"]} ')
    return

def setfo(message):
    """دالة قديمة للتوافق — محوّلة لـ setfo_add"""
    setfo_add(message)

def setfo_add(message):
    """إضافة قناة اشتراك إجباري جديدة بالصيغة الجديدة"""
    cid_ = message.from_user.id
    if cid_ not in (db.get('admins') or []) and cid_ != sudo:
        return
    text = (message.text or '').strip()
    if text in ('/start', '/cancel'):
        start_message(message)
        return

    # الصيغة: @id | الاسم | رابط_الجوين | الحد
    parts = [p.strip() for p in text.split('|')]

    if len(parts) >= 1:
        raw_id  = parts[0].lstrip('@').strip()
        name_   = parts[1].strip() if len(parts) > 1 else raw_id
        url_    = parts[2].strip() if len(parts) > 2 else f'https://t.me/{raw_id}'
        limit_  = 0
        if len(parts) > 3:
            try:
                limit_ = int(parts[3].strip())
            except:
                limit_ = 0
        if url_ in ('0', ''):
            url_ = f'https://t.me/{raw_id}'
    else:
        bot.reply_to(message, '❌ صيغة غير صحيحة — أرسل: @id | الاسم | رابط | حد')
        return

    if not raw_id:
        bot.reply_to(message, '❌ معرف القناة فارغ')
        return

    new_ch = {'id': '@' + raw_id, 'name': name_, 'url': url_, 'limit': limit_}
    raw = db.get('force') or []
    # إزالة القناة لو موجودة مسبقاً (تحديث)
    raw = [c for c in raw if (_ch_id(c) if isinstance(c, dict) else c.lstrip('@')) != raw_id]
    raw.append(new_ch)
    db.set('force', raw)

    limit_txt = f'{limit_:,}' if limit_ > 0 else 'بلا حد'
    bot.reply_to(
        message,
        f'✅ <b>تمت إضافة القناة بنجاح!</b>\n\n'
        f'📢 الاسم: <b>{name_}</b>\n'
        f'🆔 المعرف: @{raw_id}\n'
        f'🔗 الرابط: {url_}\n'
        f'🔢 الحد: {limit_txt}',
        parse_mode='HTML'
    , disable_web_page_preview=True)

def vipp(message, type_op):
    if type_op == 'add':
        try:
            uid = int(message.text)
        except:
            bot.reply_to(message, f'• ارسل الايدي بشكل صحيح')
            return
        d = db.get(f"user_{uid}")
        if d is None:
            bot.reply_to(message, f'• العضو غ��ر موجود في البوت')
            return
        d['premium'] = True
        db.set(f'user_{uid}', d)
        bot.reply_to(message, f'• اصبح ال��ضو {uid} من المشتركين الـ ViP')
        return
    if type_op == 'les':
        try:
            uid = int(message.text)
        except:
            bot.reply_to(message, f'• ارسل الايدي بشكل صحيح')
            return
        d = db.get(f"user_{uid}")
        if d is None:
            bot.reply_to(message, f'• العضو غير موجود في البوت')
            return
        d['premium'] = False
        db.set(f'user_{uid}', d)
        bot.reply_to(message, f"تم انهاء الاشتراك الـ ViP للمستخدم {uid}")

# شحن النجوم التلقائي — pre_checkout و successful_payment

@bot.pre_checkout_query_handler(func=lambda q: True)
def pre_checkout_stars(pre_checkout_q):
    """الموافقة على طلب الدفع بالنجوم"""
    try:
        bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)
    except Exception as e:
        print(f"[pre_checkout] خطأ: {e}")
        try:
            bot.answer_pre_checkout_query(pre_checkout_q.id, ok=False,
                                           error_message="حدث خطأ، حاول مجدداً")
        except:
            pass

@bot.message_handler(content_types=['successful_payment'])
def handle_successful_payment(message):
    """استقبال الدفع الناجح وإضافة النقاط تلقائياً"""
    try:
        payload = message.successful_payment.invoice_payload
        # payload صيغته: stars_{amt}_{cid}
        if not payload.startswith('stars_'):
            return
        parts = payload.split('_')
        amt = int(parts[1])
        uid = message.from_user.id
        stars_rate = int(db.get("charge_stars_rate")) if db.exists("charge_stars_rate") else 600
        pts = amt * stars_rate

        # إضافة النقاط للمستخدم
        if db.exists(f'user_{uid}'):
            udata = db.get(f'user_{uid}')
            udata['coins'] = int(udata.get('coins', 0)) + pts
            db.set(f'user_{uid}', udata)
            bot.send_message(
                chat_id=uid,
                text=(
                    f"✅ تم الشحن بنجاح!\n\n"
                    f"⭐ النجوم المدفوعة: {amt}\n"
                    f"💰 النقاط المضافة: {pts:,}\n\n"
                    f"رصيدك الحالي: {int(udata['coins']):,} نقطة 🎉"
                )
            )
            # إشعار الأدمن
            try:
                uname = f"@{message.from_user.username}" if message.from_user.username else "بدون يوزر"
                bot.send_message(
                    chat_id=sudo,
                    text=(
                        f"⭐ <b>شحن نجوم ناجح</b>\n\n"
                        f"• المستخدم: {uname}\n"
                        f"• الآيدي: <code>{uid}</code>\n"
                        f"• النجوم: {amt}\n"
                        f"• النقاط المضافة: {pts:,}"
                    ),
                    parse_mode="HTML"
                )
            except:
                pass
        else:
            bot.send_message(uid, "❌ حسابك غير موجود في البوت، تواصل مع الأدمن.")
    except Exception as e:
        print(f"[successful_payment] خطأ: {e}")

# كشف الحظر — لما حد يحظر البوت تيجي رسالة للأدمن

@bot.my_chat_member_handler()
def on_my_chat_member(update):
    """يُشغَّل لما يتغير وضع البوت عند أي مستخدم (حظر / فك حظر / بدء)"""
    try:
        old_status = update.old_chat_member.status  # 'member' أو 'kicked' أو غيرها
        new_status = update.new_chat_member.status
        user = update.from_user

        # المستخدم حظر البوت (kicked = blocked)
        if new_status == 'kicked' and old_status != 'kicked':
            name = user.first_name or ""
            username_str = f"@{user.username}" if user.username else "بدون يوزر"
            uid = user.id
            txt = (
                "🚫 <b>تنبيه: حظر البوت</b>\n\n"
                f"• الاسم: {name}\n"
                f"• المعرف: {username_str}\n"
                f"• الآيدي: <code>{uid}</code>\n\n"
                "❌ هذا المستخدم قام بحظر البوت"
            )
            try:
                bot.send_message(chat_id=sudo, text=txt, parse_mode="HTML")
            except Exception as e:
                print(f"[block_notify] خطأ في إرسال الإشعار: {e}")

        # المستخدم فك الحظر وعاد للبوت
        elif new_status == 'member' and old_status == 'kicked':
            name = user.first_name or ""
            username_str = f"@{user.username}" if user.username else "بدون يوزر"
            uid = user.id
            txt = (
                "✅ <b>تنبيه: فك حظر البوت</b>\n\n"
                f"• الاسم: {name}\n"
                f"• المعرف: {username_str}\n"
                f"• الآيدي: <code>{uid}</code>\n\n"
                "🔓 هذا المستخدم فك حظر البوت وعاد إليه"
            )
            try:
                bot.send_message(chat_id=sudo, text=txt, parse_mode="HTML")
            except Exception as e:
                print(f"[unblock_notify] خطأ في إرسال الإشعار: {e}")
    except Exception as e:
        print(f"[on_my_chat_member] خطأ: {e}")

# 💳 استقبال إثبات الشحن وإرساله للأدمن

# أنواع الشحن — للعرض في رسالة الأدمن
_CHARGE_TYPE_LABELS = {
    'vf':   '📱 فودافون كاش',
    'usdt': '💎 USDT',
    'cash': '💵 كاش',
}

def _charge_proof_received(message, charge_type):
    """يستقبل الصورة أو النص من المستخدم ويرسله للأدمن للمراجعة"""
    uid   = message.from_user.id
    name  = message.from_user.first_name or ''
    uname = f'@{message.from_user.username}' if message.from_user.username else 'بدون يوزر'
    label = _CHARGE_TYPE_LABELS.get(charge_type, charge_type)

    # أزرار القبول والرفض للأدمن
    adm_keys = mk(row_width=2)
    adm_keys.add(
        btn('�� قبول وإض��فة نقاط', callback_data=f'chgapprove_{uid}', color='green'),
        btn('❌ رفض',              callback_data=f'chgreject_{uid}',  color='red'),
    )

    caption = (
        f"💳 <b>طلب شحن جديد</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 الاسم: {name}\n"
        f"🔗 المعرف: {uname}\n"
        f"🆔 الآيدي: <code>{uid}</code>\n"
        f"💰 طريقة الشحن: {label}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📝 اضغط ✅ قبول وأدخل عدد النقاط، أو ❌ رفض"
    )

    try:
        if message.photo:
            bot.send_photo(
                chat_id=sudo,
                photo=message.photo[-1].file_id,
                caption=caption,
                reply_markup=adm_keys,
                parse_mode='HTML'
            )
        elif message.document:
            bot.send_document(
                chat_id=sudo,
                document=message.document.file_id,
                caption=caption,
                reply_markup=adm_keys,
                parse_mode='HTML'
            )
        elif message.text:
            bot.send_message(
                chat_id=sudo,
                text=caption + f"\n\n📄 <b>النص المُرسل:</b>\n{message.text}",
                reply_markup=adm_keys,
                parse_mode='HTML'
            )
        else:
            bot.reply_to(message, '❌ أرسل صورة أو نص إثبات الدفع فقط')
            return
        bot.reply_to(
            message,
            '✅ <b>تم استلام إثبات الدفع!</b>\n\n'
            '⏳ سيتم مراجعته من قِبَل الأدمن وإضافة النقاط خلال وقت قصير.',
            parse_mode='HTML'
        )
    except Exception as e:
        print(f"[charge_proof] خطأ: {e}")
        bot.reply_to(message, '❌ حدث خطأ، أعد المحاولة')

def _do_restore_session(message, phon, broken):
    """يستقبل الـ session string من المستخدم ويتحقق منها ويرجع النقاط"""
    cid = message.from_user.id
    owner_id  = broken.get('owner_id')
    penalty   = int(broken.get('penalty', 1000))

    if cid != owner_id:
        return

    session_str = (message.text or '').strip()
    if not session_str:
        bot.reply_to(message, '❌ أرسل الـ session string النصية')
        return

    # التحقق من صحة الجلسة
    import asyncio

    async def _verify():
        try:
            client = Client('::memory::', api_id=API_ID, api_hash=API_HASH,
                            in_memory=True, session_string=session_str)
            await client.start()
            me = await client.get_me()
            txt = await client.export_session_string()
            await client.stop()
            return txt, me
        except Exception as e:
            return None, str(e)

    try:
        loop = asyncio.new_event_loop()
        txt, me = loop.run_until_complete(_verify())
        loop.close()
    except Exception as e:
        bot.reply_to(message, f'❌ خطأ في التحقق: {e}')
        return

    if not txt:
        bot.reply_to(
            message,
            f'❌ الجلسة غير صالحة أو منتهية: {me}\n\nتأكد من صحة الـ session string وأعد المحاولة.',
            parse_mode='HTML'
        )
        return

    # الجلسة صح — نرجع النقاط ونضيف الجلسة
    if db.exists(f'user_{owner_id}'):
        udata = db.get(f'user_{owner_id}')
        udata['coins'] = int(udata.get('coins', 0)) + penalty
        db.set(f'user_{owner_id}', udata)

    adds_session(txt, phon, owner_id=owner_id)

    # نمسح بيانات الجلسة المكسورة
    try:
        db.delete(f'session_broken_{phon}')
        db.set(f'session_penalized_{phon}', False)
    except:
        pass

    phone_display = phon if phon else '—'
    new_bal = int(udata.get('coins', 0)) if db.exists(f'user_{owner_id}') else '—'
    bot.reply_to(
        message,
        f'✅ <b>تم استرداد الجلسة بنجاح!</b>\n\n'
        f'📱 الرقم: <code>{phone_display}</code>\n'
        f'💰 تم إرجاع <b>{penalty:,} نقطة</b> لرصيدك\n'
        f'���� رصيدك الحالي: <b>{new_bal:,} نقطة</b>',
        parse_mode='HTML'
    )

def _do_charge_approve(message, uid):
    """بعد ما الأدمن يكتب عدد النقاط — يضيفها للمستخدم"""
    adm_id = message.from_user.id
    if adm_id not in db.get("admins") and adm_id != sudo:
        return
    try:
        pts = int(message.text.strip())
        if pts <= 0:
            raise ValueError
        udata = db.get(f'user_{uid}')
        if not udata:
            bot.reply_to(message, f'❌ المستخدم {uid} غير موجود في البوت')
            return
        old_bal = int(udata.get('coins', 0))
        udata['coins'] = old_bal + pts
        db.set(f'user_{uid}', udata)
        # إشعار للأدمن
        bot.reply_to(message,
            f'✅ تم إضافة <b>{pts:,} نقطة</b> للمستخدم <code>{uid}</code>\n'
            f'💰 رصيده الجديد: <b>{udata["coins"]:,} نقطة</b>',
            parse_mode='HTML'
        )
        # إشعار للمستخدم
        try:
            bot.send_message(
                chat_id=uid,
                text=(
                    f'🎉 <b>تم قبول طلب الشحن!</b>\n\n'
                    f'💰 تم إضافة <b>{pts:,} نقطة</b> لرصيدك\n'
                    f'💼 رصيدك الحالي: <b>{udata["coins"]:,} نقطة</b>'
                ),
                parse_mode='HTML'
            )
        except:
            pass
    except ValueError:
        bot.reply_to(message, '❌ أرسل رقماً صحيحاً أكبر من 0')
    except Exception as e:
        bot.reply_to(message, f'❌ خطأ: {e}')

# 🎯 لوحة إعدادات المكافآت

def _rewards_text():
    """يبني نص لوحة المكافآت مع القيم الحالية من DB"""
    daily  = int(db.get("daily_gift"))  if db.exists("daily_gift")  else 30
    invite = int(db.get("link_price"))  if db.exists("link_price")  else link_price
    prizes = get_wheel_prizes()
    remind_on = db.get('daily_remind_enabled')
    remind_on = remind_on if remind_on is not None else True
    remind_status = '✅ مفعّل' if remind_on else '❌ متوقف'
    wheel_lines = "\n".join(
        f"  {'🔸' if i == 0 else '▫️'} {p['label']}  —  احتمالية {p['weight']}%"
        for i, p in enumerate(prizes)
    )
    return (
        "🎯 <b>إعدادات المكافآت</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎁 الهدية اليومية   : <b>{daily} نقطة</b>\n"
        f"🔮 مكافأة الإحالة  : <b>{invite} نقطة</b>\n"
        f"🔔 تذكير الهدية    : <b>{remind_status}</b>\n\n"
        "🎰 <b>جوائز عجلة الحظ:</b>\n"
        f"{wheel_lines}\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "اضغط على أي زر لتعديله 👇"
    )

def _rewards_keys():
    """يبني أزرار لوحة المكافآت"""
    daily  = int(db.get("daily_gift"))  if db.exists("daily_gift")  else 30
    invite = int(db.get("link_price"))  if db.exists("link_price")  else link_price
    remind_on = db.get('daily_remind_enabled')
    remind_on = remind_on if remind_on is not None else True
    remind_lbl = '🔔 تذكير الهدية: مفعّل  🔴 إيقاف' if remind_on else '🔕 تذكير الهدية: متوقف  🟢 تفعيل'
    k = mk(row_width=1)
    k.add(btn(f'🎁 الهدية اليومية: {daily} نقطة  ✏️ تعديل', callback_data='rwd_daily', color='green'))
    k.add(btn(f'🔮 مكافأة الإحالة: {invite} نقطة  ✏️ تعديل', callback_data='rwd_invite', color='blue'))
    k.add(btn('🎰 جوائز عجلة الحظ  ✏️ تعديل', callback_data='rwd_wheel', color='blue'))
    k.add(btn(remind_lbl, callback_data='rwd_toggle_remind', color='green' if not remind_on else 'red'))
    k.add(btn('🔙 رجوع للوحة', callback_data='adm_cat_tasks', color='red'))
    return k


def cb_rewards_panel(call):
    cid = call.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=_rewards_text(),
        reply_markup=_rewards_keys(),
        parse_mode='HTML'
    )


def cb_rwd_daily(call):
    cid = call.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    cur = int(db.get("daily_gift")) if db.exists("daily_gift") else 30
    x = bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=(
            f"🎁 <b>تعديل الهدية اليومية</b>\n\n"
            f"القيمة الحالية: <b>{cur} نقطة</b>\n\n"
            "أرسل القيمة الجديدة (رقم صحيح):"
        ),
        parse_mode='HTML'
    , reply_markup=bk_cancel)
    bot.register_next_step_handler(x, _do_rwd_daily)

def _do_rwd_daily(message):
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    try:
        val = int(message.text.strip())
        if val < 0:
            raise ValueError
        db.set("daily_gift", val)
        bot.reply_to(message, f'✅ تم تعيين الهدية اليومية إلى <b>{val} نقطة</b>', parse_mode='HTML')
        bot.send_message(cid, _rewards_text(), reply_markup=_rewards_keys(), parse_mode='HTML')
    except Exception:
        bot.reply_to(message, '❌ أرسل رقماً صحيحاً أكبر من أو يساوي 0')


def cb_rwd_toggle_remind(call):
    """تفعيل أو إيقاف تذكير الهدية اليومية"""
    cid = call.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    current = db.get('daily_remind_enabled')
    current = current if current is not None else True
    new_val = not current
    db.set('daily_remind_enabled', new_val)
    status = '✅ تم تفعيل تذكير الهدية اليومية' if new_val else '❌ تم إيقاف تذكير الهدية اليومية'
    try:
        _cb_alert(call, text=status, show_alert=False)
    except Exception:
        pass
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=_rewards_text(),
            reply_markup=_rewards_keys(),
            parse_mode='HTML'
        )
    except Exception:
        pass


def cb_rwd_invite(call):
    cid = call.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    cur = int(db.get("link_price")) if db.exists("link_price") else link_price
    x = bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=(
            f"🔮 <b>تعديل مكافأة الإحالة</b>\n\n"
            f"القيمة الحالية: <b>{cur} نقطة</b>\n\n"
            "أرسل القيمة الجديدة (رقم صحيح):"
        ),
        parse_mode='HTML'
    , reply_markup=bk_cancel)
    bot.register_next_step_handler(x, _do_rwd_invite)

def _do_rwd_invite(message):
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    try:
        val = int(message.text.strip())
        if val < 0:
            raise ValueError
        db.set("link_price", val)
        bot.reply_to(message, f'✅ تم تعيين مكافأة الإحالة إلى <b>{val} نقطة</b>', parse_mode='HTML')
        bot.send_message(cid, _rewards_text(), reply_markup=_rewards_keys(), parse_mode='HTML')
    except Exception:
        bot.reply_to(message, '❌ أرسل رقماً صحيحاً أكبر من أو يساوي 0')


def cb_rwd_wheel(call):
    cid = call.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    prizes = get_wheel_prizes()
    cur_txt = "\n".join(f"{p['points']} {p['weight']}" for p in prizes)
    x = bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=(
            "🎰 <b>تعديل جوائز عجلة الحظ</b>\n\n"
            "أرسل الجوائز — كل سطر بالشكل:\n"
            "<code>نقاط  احتمالية</code>\n\n"
            "• الاحتمالية رقم نسبي (كلما زاد = أكثر ظهوراً)\n"
            "• أضف جائزتين على الأقل\n\n"
            "<b>مثال:</b>\n"
            "<code>50 35\n100 25\n200 18\n350 10\n500 7\n750 3\n1000 2</code>\n\n"
            "━━━━━━━━━━━━━━\n"
            f"<b>الحالي:</b>\n<code>{cur_txt}</code>"
        ),
        parse_mode='HTML',
        reply_markup=bk_cancel
    )
    bot.register_next_step_handler(x, _do_rwd_wheel)

def _do_rwd_wheel(message):
    cid = message.from_user.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    try:
        lines = [l.strip() for l in message.text.strip().split('\n') if l.strip()]
        if len(lines) < 2:
            raise ValueError("أضف جائزتين على الأقل")
        new_prizes = []
        for line in lines:
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"سطر خاطئ: <code>{line}</code>")
            pts, wt = int(parts[0]), int(parts[1])
            if pts <= 0 or wt <= 0:
                raise ValueError("الأرقام يجب أن تكون أكبر من 0")
            # اختيار الإيموجي تلقائياً حسب عدد النقاط
            if   pts < 100:  emoji = "🌟"
            elif pts < 200:  emoji = "💫"
            elif pts < 350:  emoji = "⚡"
            elif pts < 500:  emoji = "🔥"
            elif pts < 750:  emoji = "💎"
            elif pts < 1000: emoji = "👑"
            else:            emoji = "🏆"
            new_prizes.append({"label": f"{emoji} {pts} نقطة", "points": pts, "weight": wt})
        db.set("wheel_prizes_cfg", new_prizes)
        summary = "\n".join(f"  ▫️ {p['label']}  —  احتمالية {p['weight']}%" for p in new_prizes)
        bot.reply_to(message, f'✅ تم تحديث جوائز العجلة!\n\n{summary}', parse_mode='HTML')
        bot.send_message(cid, _rewards_text(), reply_markup=_rewards_keys(), parse_mode='HTML')
    except ValueError as e:
        bot.reply_to(
            message,
            f'❌ خطأ: {e}\n\nأرسل كل سطر بالشكل:\n<code>نقاط احتمالية</code>\nمثال: <code>100 25</code>',
            parse_mode='HTML'
        )
    except Exception:
        bot.reply_to(message, '❌ حدث خطأ غير متوقع، أعد المحاولة')

# بوت بايروجرام (لتسجيل الأرقام وتنظيف ال��سابات)

# نظام فحص الجلسات تلقائياً وخصم النقاط عند انتهاء الجلسة

async def _check_sessions_task():
    """\n    فحص جلسات التأجير.\n    - الحلقة تشتغل كل دقيقة\n    - كل جلسة تُفحص مرة كل 10 دقائق فقط (لتجنب إغراق تيليجرام بالاتصالات)\n    - Grace Period: 10 دقائق للحسابات الجديدة\n    - Retry: 3 فشل متتالي قبل الخصم\n    """
    _GRACE_SECONDS      = 600   # 10 دقائق grace للحسابات الجديدة
    _CHECK_INTERVAL     = 600   # 10 دقائق بين كل فحص فعلي للجلسة
    _MAX_FAILS          = 3     # فشل 3 مرات قبل الخصم
    while True:
        try:
            accounts = db.get('accounts') or []
            updated  = []
            now      = time.time()
            for session in accounts:
                sessio   = session.get('s')
                phon     = session.get('phone', '')
                owner_id = session.get('owner_id')
                reg_time = session.get('registered_at', now)


                if not sessio:
                    continue


                if now - reg_time < _GRACE_SECONDS:
                    updated.append(session)
                    continue


                last_check = float(db.get(f'session_last_check_{phon}') or 0)
                if now - last_check < _CHECK_INTERVAL:
                    # لسه مش وقت الفحص — نحتفظ بالجلسة
                    updated.append(session)
                    continue


                db.set(f'session_last_check_{phon}', now)
                session_ok = False
                try:
                    # نستخدم connect/disconnect بدل start/stop عشان نتجنب
                    # أي logout أو session invalidation من Pyrogram
                    client = Client(
                        '::memory::',
                        api_id=API_ID, api_hash=API_HASH,
                        in_memory=True, session_string=sessio,
                        no_updates=True
                    )
                    await client.connect()
                    await client.get_me()
                    await client.disconnect()
                    session_ok = True
                except Exception as ex:
                    err_str = str(ex).lower()
                    # لو الخطأ صريح بانتهاء الجلسة — نعتبره فشل حقيقي
                    # لو خطأ شبكة مؤقت — نتجاهله
                    if any(k in err_str for k in ['auth', 'unauthorized', 'deactivated', 'invalid']):
                        session_ok = False
                    else:
                        # خطأ مؤقت (شبكة/timeout) — نحتفظ بالجلسة ونجرب بعدين
                        print(f"[session_check] {phon}: خطأ مؤقت ({ex}) — تم الاحتفاظ")
                        updated.append(session)
                        continue
                    try:
                        await client.disconnect()
                    except:
                        pass

                if session_ok:
                    # الجلسة تمام — نصفّر عداد الفشل
                    db.set(f'session_fail_count_{phon}', 0)
                    updated.append(session)
                else:

                    fail_count = int(db.get(f'session_fail_count_{phon}') or 0) + 1
                    db.set(f'session_fail_count_{phon}', fail_count)

                    if fail_count < _MAX_FAILS:
                        print(f"[session_check] {phon}: فشل {fail_count}/{_MAX_FAILS} — انتظار")
                        updated.append(session)
                        continue


                    penalized = db.get(f'session_penalized_{phon}')
                    if not penalized and owner_id:
                        _rent_pts = 500
                        try:
                            if db.exists(f'user_{owner_id}'):
                                udata  = db.get(f'user_{owner_id}')
                                coins  = int(udata.get('coins', 0))
                                # يسمح بالرصيد السالب عمداً (بدون max)
                                new_coins = coins - _rent_pts
                                udata['coins'] = new_coins
                                db.set(f'user_{owner_id}', udata)
                                db.set(f'session_penalized_{phon}', True)
                                db.set(f'session_broken_{phon}', {
                                    'phone': phon, 'owner_id': owner_id, 'penalty': _rent_pts,
                                })
                                restore_keys = mk(row_width=1)
                                restore_keys.add(btn(
                                    '🔄 أرجع الجلسة واسترد نقاطك',
                                    callback_data=f'restore_session_{phon}',
                                    color='green'
                                ))
                                # بناء نص الرسالة حسب إذا الرصيد سالب أو لا
                                if new_coins < 0:
                                    balance_note = (
                                        f"💸 تم خصم <b>{_rent_pts:,} نقطة</b> من رصيدك.\n"
                                        f"💰 رصيدك الحالي: <b>{new_coins:,} نقطة</b> (رصيد سالب)\n\n"
                                        "⚠️ رصيدك أصبح سالباً — لن تتمكن من استخدام البوت حتى تُرجع الجلسة وتُصفّي رصيدك."
                                    )
                                else:
                                    balance_note = (
                                        f"💸 تم خصم <b>{_rent_pts:,} نقطة</b> من رصيدك.\n"
                                        f"💰 رصيدك الحالي: <b>{new_coins:,} نقطة</b>"
                                    )
                                try:
                                    bot.send_message(
                                        chat_id=owner_id,
                                        text=(
                                            "⚠️ <b>تنبيه مهم!</b>\n\n"
                                            f"📱 الحساب المرتبط بالرقم <code>{phon}</code> خرجت جلسته من البوت.\n\n"
                                            f"{balance_note}\n\n"
                                            "🔄 اضغط الزر أدناه لإرجاع الجلسة واسترداد نقاطك فوراً."
                                        ),
                                        reply_markup=restore_keys,
                                        parse_mode="HTML"
                                    )
                                except:
                                    pass
                        except Exception as e:
                            print(f"[session_check] خطأ في خصم نقاط: {e}")
                    # نحذف الجلسة المكسورة
            db.set('accounts', updated)
        except Exception as e:
            print(f"[session_check] خطأ عام: {e}")
        # الحلقة كل دقيقة — لكن الفحص الفعلي كل 10 دقائق per session
        await asyncio.sleep(60)

def _start_session_checker():
    """يشغّل دالة الفحص في event loop منفصل"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_check_sessions_task())


_checker_thread = threading.Thread(target=_start_session_checker, daemon=True)
_checker_thread.start()

# gen_bot — بوت تسجيل الأرقام (telebot بدل pyrogram)

gen_bot = TeleBot(token=GIVE_BOT_TOKEN, threaded=True, num_threads=16)

# ── local cache للقيم الثابتة في gen_bot (بيتحدث كل 5 دقائق) ──
_gen_cache = {}
_gen_cache_ts = {}
_GEN_CACHE_TTL = 300  # 5 دقائق

def _gc(key, default=None):
    """يجيب قيمة من cache أو Firebase"""
    now = time.time()
    if key in _gen_cache and now - _gen_cache_ts.get(key, 0) < _GEN_CACHE_TTL:
        return _gen_cache[key]
    val = db.get(key)
    if val is None:
        val = default
    _gen_cache[key] = val
    _gen_cache_ts[key] = now
    return val


_reg_state      = {}     # uid -> 'phone' | 'code' | 'pass'
_reg_data       = {}     # uid -> dict
_reg_processing = set()


_gen_cache = {}          # key -> (value, expire_time)
_GEN_CACHE_TTL = 120      # ثانيتان

def _gcache_get(key):
    item = _gen_cache.get(key)
    if item and _time_module.time() < item[1]:
        return item[0]
    _gen_cache.pop(key, None)
    return None

def _gcache_set(key, val, ttl=_GEN_CACHE_TTL):
    _gen_cache[key] = (val, _time_module.time() + ttl)

def _gcache_del(key):
    _gen_cache.pop(key, None)

_REG_DAILY_LIMIT = 999999  # غير محدود

def _check_daily_limit(uid: int) -> tuple:
    # نستخدم الكاش لتجنب Firebase call في كل رسالة
    key = f'reg_daily_{uid}_{datetime.date.today().isoformat()}'
    rec = db.get(key) or {'count': 0}
    allowed   = rec['count'] < _REG_DAILY_LIMIT
    remaining = max(0, _REG_DAILY_LIMIT - rec['count'])
    return allowed, remaining

def _increment_daily(uid: int):
    key = f'reg_daily_{uid}_{datetime.date.today().isoformat()}'
    rec = db.get(key) or {'count': 0}
    rec['count'] += 1
    db.set(key, rec)

def _gikb(*rows):
    """ينشئ InlineKeyboardMarkup من قوائم أزرار لـ telebot"""
    markup = TelebotMarkup()
    for row in rows:
        markup.add(*row, row_width=len(row))
    return markup

def _gbtn(text, cb=None, url=None):
    return TelebotButton(text=text, callback_data=cb, url=url)

def _notify_admin_reg_sync(from_user, phone, pts, referrer=None):
    """إشعار السودو بتسجيل حساب جديد (sync)"""
    try:
        _name     = ((from_user.first_name or '') + ' ' + (from_user.last_name or '')).strip()
        _username = f'@{from_user.username}' if from_user.username else 'لا يوجد'
        _ref_txt  = f'✅ نعم — #{referrer}' if referrer and referrer != from_user.id else '❌ لا'
        import datetime as _dt
        _total_accounts = len(db.get('accounts') or [])
        _accounts = db.get('accounts') or []
        _count_map = {}
        for _a in _accounts:
            _oid = _a.get('owner_id')
            if _oid:
                _count_map[int(_oid)] = _count_map.get(int(_oid), 0) + 1
        _top3_lines = []
        _medals = ['🥇','🥈','🥉']
        for _i, (_oid, _cnt) in enumerate(sorted(_count_map.items(), key=lambda x: x[1], reverse=True)[:3]):
            _top3_lines.append(f'  {_medals[_i]} #{_oid} — {_cnt} حساب')
        _top3_txt = '\n'.join(_top3_lines) if _top3_lines else '  لا يوجد'
        _reg_submitted = int(db.get(f'user_{from_user.id}_rent_submitted') or 0)
        _notify_text = (
            f'╔══════════════════╗\n'
            f'       📱 مستخدم سجّل رقم جديد!\n'
            f'╚══════════════════╝\n\n'
            f'👤 الاسم : {_name}\n'
            f'📛 اليوزر : {_username}\n'
            f'🆔 الآيدي : <code>{from_user.id}</code>\n'
            f'📞 الرقم : <code>{phone}</code>\n'
            f'💰 النقاط المضافة : {pts:,} نقطة\n'
            f'📱 إجمالي حسابات المسجّل : {_reg_submitted}\n'
            f'🔗 عن طريق إحالة : {_ref_txt}\n\n'
            f'━━━━━━━━━━━━━━━━━━━\n'
            f'📊 إجمالي الأرقام في البوت : {_total_accounts}\n'
            f'🏆 توب 3 :\n{_top3_txt}\n'
            f'🕐 الوقت : {_dt.datetime.now().strftime("%Y-%m-%d %H:%M")}\n'
            f'━━━━━━━━━━━━━━━━━━━'
        )
        _notify_ids = set([int(sudo)])
        _notify_ids.update([int(a) for a in (db.get('admins') or [])])
        for _nid in _notify_ids:
            try:
                bot.send_message(chat_id=_nid, text=_notify_text, parse_mode='HTML')
            except Exception as _ne:
                print(f'[admin notify] {_nid}: {_ne}')
    except Exception as _e:
        print(f'[admin notify] {_e}')

def _finish_registration_sync(message, data, uid, txt_session):
    """تنهي التسجيل وتضيف النقاط"""
    referrer  = data.get('referrer')
    phone     = data.get('phone')
    _rent_pts = int(db.get("rent_reward")) if db.exists("rent_reward") else 100

    _added = adds_session(txt_session, phone, owner_id=uid)
    if not _added:
        kb = _gikb([_gbtn('🔄 حاول مرة أخرى', cb='reg_start')])
        gen_bot.reply_to(message,
            '╔══════════════════╗\n'
            '       ⚠️ خطأ في الحفظ\n'
            '╚══════════════════╝\n\n'
            f'📱 الرقم : <code>{phone}</code>\n'
            '❌ لم يتم إضافة الرقم بشكل صحيح\n\n'
            '• تأكد إن الرقم مش موجود مسبقاً\n'
            '• إذا تكررت المشكلة تواصل مع الدعم',
            reply_markup=kb, parse_mode='HTML'
        )
        _reg_state.pop(uid, None)
        _reg_data.pop(uid, None)
        return

    if db.exists(f'user_{uid}'):
        udata = db.get(f'user_{uid}')
        udata['coins'] = int(udata.get('coins', 0)) + _rent_pts
        user_phones = udata.get('phones', [])
        if phone and phone not in user_phones:
            user_phones.append(phone)
        udata['phones'] = user_phones
        db.set(f'user_{uid}', udata)
        _rc_key = f'user_{uid}_rent_submitted'
        db.set(_rc_key, int(db.get(_rc_key) or 0) + 1)
        new_coins = int(udata['coins'])
    else:
        new_coins = _rent_pts

    _increment_daily(uid)

    if referrer and referrer != uid:
        _ref_bonus = max(int(_rent_pts * 0.1), 1)
        if db.exists(f'user_{referrer}'):
            _rdata = db.get(f'user_{referrer}')
            _rdata['coins'] = int(_rdata.get('coins', 0)) + _ref_bonus
            db.set(f'user_{referrer}', _rdata)
            try:
                bot.send_message(
                    chat_id=referrer,
                    text=(
                        f'🎉 <b>مكافأة إحالة!</b>\n\n'
                        f'📱 مستخدم سجّل رقم عن طريق رابطك\n'
                        f'💰 مكافأتك : +{_ref_bonus:,} نقطة\n'
                        f'👛 رصيدك الجديد : {int(_rdata["coins"]):,} نقطة'
                    ),
                    parse_mode='HTML'
                )
            except:
                pass

    try:
        bot.send_message(
            chat_id=uid,
            text=(
                f'╔══════════════════╗\n'
                f'       ✅ تم قبول حسابك!\n'
                f'╚══════════════════╝\n\n'
                f'📱 الرقم : <code>{phone}</code>\n'
                f'🎁 النقاط المضافة : +{_rent_pts:,}\n'
                f'👛 رصيدك الجديد : {new_coins:,} نقطة'
            ),
            parse_mode='HTML'
        )
    except:
        pass

    threading.Thread(
        target=_notify_admin_reg_sync,
        args=(message.from_user, phone, _rent_pts, referrer),
        daemon=True
    ).start()

    kb = _gikb(
        [_gbtn('➕ تسجيل رقم آ��ر', cb='reg_new')],
        [_gbtn('📊 رصيدي في البوت الرئيسي', cb='reg_balance')]
    )
    gen_bot.reply_to(message,
        f'╔══════════════════╗\n'
        f'       🎉 تم التسجيل بنجاح!\n'
        f'╚══════════════════╝\n\n'
        f'📱 الرقم : <code>{phone}</code>\n'
        f'💰 النقاط المضافة : +{_rent_pts:,} نقطة\n'
        f'🏆 رصيدك الجديد : {new_coins:,} نقطة',
        reply_markup=kb, parse_mode='HTML'
    )
    _reg_state.pop(uid, None)
    _reg_data.pop(uid, None)

# ===== 🤖 الدعم بالذكاء الاصطناعي عبر Groq (Llama 3.3 70B) =====
GROQ_API_KEY = ""  # ← مفتاح Groq الافتراضي (الأفضل ضبطه من لوحة الأدمن)
GROQ_MODEL   = "llama-3.3-70b-versatile"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

def _groq_get_key():
    try:
        return (db.get('groq_api_key') or GROQ_API_KEY or '').strip()
    except Exception:
        return (GROQ_API_KEY or '').strip()

def _ai_support_enabled():
    try:
        v = db.get('ai_support_enabled')
        if v is None:
            return bool(_groq_get_key())
        return bool(v)
    except Exception:
        return False

def _mask_key(k):
    k = (k or '').strip()
    if not k:
        return 'غير مضبوط'
    if len(k) <= 8:
        return k[0] + '***'
    return f'{k[:6]}****{k[-4:]}'

def _ai_system_prompt():
    return (
        "أنت مساعد دعم ذكي داخل بوت تسجيل الأرقام على تليجرام. "
        "أجب فقط عن الأسئلة المتعلقة بالبوت وخدماته: تسجيل الأرقام، النقاط والمكافآت، "
        "شروط التسجيل، طريقة العمل، اشتراك VIP، الشحن، المتجر، والدعم الفني. "
        "إذا سُئلت عن أي موضوع خارج نطاق البوت اعتذر بلطف ووجّه المستخدم لاستخدام البوت. "
        "أجب بالعربية بإيجاز ووضوح."
    )

def _handle_ai_support_chat(message):
    """التعامل مع رسائل الدعم الذكي في البوت الرئيسي."""
    try:
        if not message or not message.text:
            return
        cid = message.from_user.id
        # تجاهل الأوامر (يخرج من وضع المحادثة لو دوس /start أو أي أمر)
        if message.text.startswith('/'):
            return
        q = message.text.strip()
        if len(q) < 2:
            bot.reply_to(message, '⚠️ اكتب سؤالاً أطول من فضلك.')
            try: bot.register_next_step_handler_by_chat_id(cid, _handle_ai_support_chat)
            except Exception: pass
            return
        try:
            bot.send_chat_action(cid, 'typing')
        except Exception:
            pass
        ans, err = _ai_ask(q)
        if err:
            bot.reply_to(message, f'⚠️ {err}')
        else:
            reply_keys = mk(row_width=1)
            reply_keys.add(btn('🚪 إنهاء المحادثة', callback_data='support', color='red'))
            bot.reply_to(message, f'🤖 {ans}\n\n━━━━━━━━━━━━━━\n✍️ تقدر تسأل سؤال تاني أو تضغط إنهاء المحادثة', reply_markup=reply_keys)
        try:
            bot.register_next_step_handler_by_chat_id(cid, _handle_ai_support_chat)
        except Exception:
            pass
    except Exception as _e:
        try: bot.reply_to(message, f'⚠️ خطأ غير متوقّع: {_e}')
        except Exception: pass

def _ai_ask(user_text):
    key = _groq_get_key()
    if not key:
        return None, "⚠️ خدمة المساعد الذكي غير مفعّلة حالياً. تواصل مع الدعم الفني."
    try:
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": _ai_system_prompt()},
                {"role": "user", "content": user_text[:2000]},
            ],
            "temperature": 0.4,
            "max_tokens": 600,
        }
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        resp = _requests_mod.post(GROQ_API_URL, json=payload, headers=headers, timeout=40)
        if resp.status_code != 200:
            print(f"[groq] HTTP {resp.status_code}: {resp.text[:200]}")
            return None, f"❌ تعذّر الوصول للمساعد حالياً (رمز {resp.status_code}). حاول لاحقاً."
        data = resp.json()
        ans = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
        if not ans:
            return None, "❌ لم أستلم رداً واضحاً. أعد صياغة سؤالك من فضلك."
        return ans, None
    except Exception as _e:
        print(f"[groq] error: {_e}")
        return None, "❌ حدث خطأ أثناء الاتصال بالمساعد الذكي. حاول لاحقاً."


def _show_ai_panel(cid, mid=None):
    enabled = _ai_support_enabled()
    key = _groq_get_key()
    status_txt = '✅ مفعّل' if enabled else '⛔️ معطّل'
    keys_ = mk(row_width=1)
    keys_.add(btn(('⏸ تعطيل الدعم AI' if enabled else '▶️ تفعيل الدعم AI'),
                  callback_data='adm_ai_toggle', color=('red' if enabled else 'green')))
    keys_.add(btn('🔑 ضبط Groq API Key', callback_data='adm_ai_setkey', color='blue'))
    keys_.add(btn('🧪 اختبار الاتصال بـ AI', callback_data='adm_ai_test', color='blue'))
    keys_.add(btn('رجوع', callback_data='adm_cat_general', color='blue'))
    txt = (
        '🤖 <b>إدارة الدعم بالذكاء الاصطناعي</b>\n\n'
        f'الحالة: <b>{status_txt}</b>\n'
        f'Groq API Key: <code>{_mask_key(key)}</code>\n\n'
        '<i>يستخدم نموذج Llama 3.3 70B عبر Groq للرد على استفسارات المستخدمين تلقائياً</i>'
    )
    try:
        if mid:
            bot.edit_message_text(text=txt, chat_id=cid, message_id=mid,
                                  reply_markup=keys_, parse_mode='HTML')
        else:
            bot.send_message(cid, txt, reply_markup=keys_, parse_mode='HTML')
    except Exception as _e:
        print(f"[ai_panel] {_e}")

def _do_set_groq_key(message):
    cid = message.chat.id
    if cid not in (db.get("admins") or []) and cid != sudo:
        return
    key = (message.text or '').strip()
    if not key or len(key) < 8:
        bot.send_message(cid, '❌ مفتاح غير صالح. حاول مرة أخرى من زر «ضبط Groq API Key».')
        return
    db.set('groq_api_key', key)
    if db.get('ai_support_enabled') is None:
        db.set('ai_support_enabled', True)
    bot.send_message(cid, f'✅ تم حفظ المفتاح بنجاح.\n\n🔑 <code>{_mask_key(key)}</code>',
                     parse_mode='HTML')
    _show_ai_panel(cid, None)


def _gen_start_menu(uid, first_name):
    _rent_pts = int(db.get("rent_reward")) if db.exists("rent_reward") else 100
    _user_submitted = int(db.get(f'user_{uid}_rent_submitted') or 0)
    _allowed, _remaining = _check_daily_limit(uid)
    _daily_txt = '✅ متاح (غير محدود)'
    kb = _gikb(
        [_gbtn('📱 تسجيل رقم جديد', cb='reg_start')],
        [_gbtn('📊 حساباتي المسجلة', cb='reg_myaccounts')],
        [_gbtn('📋 شروط التسجيل', cb='reg_rules'), _gbtn('❓ كيف يعمل؟', cb='reg_howto')],
        [_gbtn('🤖 مساعد ذكي', cb='reg_ai'), _gbtn('💬 الدعم الفني', cb='reg_support')]
    )
    text = (
        f'╔══════════════════╗\n'
        f'       🤖 بوت تسجيل الأرقام\n'
        f'╚══════════════════╝\n\n'
        f'👋 أهلاً {first_name}!\n\n'
        f'💎 <b>مكافأة كل رقم :</b> {_rent_pts:,} نقطة\n'
        f'📱 <b>أرقام سجّلتها أنت :</b> {_user_submitted} رقم\n'
        f'📅 <b>حالة التسجيل اليوم :</b> {_daily_txt}\n'
        + (f'📊 <b>إجمالي الأرقام :</b> {len(db.get("accounts") or []):,} رقم\n' if uid == int(sudo) or uid in (db.get("admins") or []) else '')
        + f'\n━━━━━━━━━━━━━━━━━━━\n'
        f'📌 اضغط <b>تسجيل رقم جديد</b> للبدء\n'
        f'📋 اقرأ <b>الشروط</b> قبل التسجيل'
    )
    return text, kb


@gen_bot.message_handler(commands=['start'])
def gen_start(message):
    uid = message.from_user.id
    _reg_state.pop(uid, None)
    _reg_data.pop(uid, None)
    _reg_processing.discard(uid)

    param = message.text.split(' ', 1)[1] if ' ' in message.text else ''
    referrer = None
    if param.startswith('earn_'):
        try:
            referrer = int(param.replace('earn_', ''))
        except:
            pass

    _reg_data[uid] = {'referrer': referrer}


    from telebot.types import InlineKeyboardMarkup as _IKM2, InlineKeyboardButton as _IKB2
    _fast_kb = _IKM2()
    _fast_kb.add(_IKB2('⏳ جارٍ التحميل...', callback_data='reg_loading'))
    _sent = gen_bot.reply_to(message, '👋 أهلاً! جارٍ التحميل...', reply_markup=_fast_kb, parse_mode='HTML')


    def _load_and_update():
        try:
            if uid in (db.get('ban_list') or []):
                gen_bot.edit_message_text('🚫 <b>تم حظرك من البوت</b>',
                    message.chat.id, _sent.message_id, parse_mode='HTML')
                return
            text, kb = _gen_start_menu(uid, message.from_user.first_name)
            gen_bot.edit_message_text(text, message.chat.id, _sent.message_id,
                reply_markup=kb, parse_mode='HTML')
        except Exception as _e:
            # لو فشل التعديل — ابعت رسالة جديدة
            try:
                text, kb = _gen_start_menu(uid, message.from_user.first_name)
                gen_bot.send_message(message.chat.id, text, reply_markup=kb, parse_mode='HTML')
            except:
                pass

    threading.Thread(target=_load_and_update, daemon=True).start()

    # إشعار السودو
    try:
        _eu_uname = f'@{message.from_user.username}' if message.from_user.username else 'لا يوجد'
        _eu_submitted = int(db.get(f'user_{uid}_rent_submitted') or 0)
        if not db.exists(f'genbot_visited_{uid}'):
            db.set(f'genbot_visited_{uid}', True)
            threading.Thread(
                target=bot.send_message,
                kwargs={
                    "chat_id": int(sudo),
                    "text": (
                        f'👁 <b>مستخدم دخل بوت الأرقام</b>\n\n'
                        f'👤 الاسم : {message.from_user.first_name or ""}\n'
                        f'📛 اليوزر : {_eu_uname}\n'
                        f'🆔 الأيدي : <code>{uid}</code>\n'
                        f'📱 أرقام سجّلها : {_eu_submitted} رق��'
                    ),
                    "parse_mode": "HTML"
                },
                daemon=True
            ).start()
    except:
        pass


@gen_bot.message_handler(commands=['ping'])
def gen_ping(message):
    gen_bot.reply_to(message, '✅ الجلسة تعمل بشكل طبيعي')


@gen_bot.callback_query_handler(func=lambda c: True)
def gen_cb(call):
    threading.Thread(target=_gen_cb_worker, args=(call,), daemon=True).start()

def _gen_cb_worker(call):
    uid  = call.from_user.id
    data = call.data

    def answer(text=None, alert=False):
        try:
            gen_bot.answer_callback_query(call.id, text=text, show_alert=alert)
        except:
            pass

    def edit(text, kb=None):
        try:
            gen_bot.edit_message_text(
                text, call.message.chat.id, call.message.message_id,
                reply_markup=kb, parse_mode='HTML'
            )
        except:
            pass

    if data == 'reg_start' or data == 'reg_new' or data == 'reg_retry':
        answer()
        if uid in (db.get('ban_list') or []):
            answer('🚫 أنت محظور من البوت', alert=True)
            return
        _allowed, _remaining = _check_daily_limit(uid)
        if not _allowed:
            kb = _gikb([_gbtn('رجوع', cb='reg_back_main')])
            edit(
                f'⛔ <b>وصلت للحد اليومي</b>\n\n'
                f'يمكنك تسجيل {_REG_DAILY_LIMIT} أرقام يومياً فقط\n'
                f'🔄 جرّب مرة أخرى غداً',
                kb
            )
            return
        if not db.exists(f'user_{uid}'):
            kb = _gikb([_gbtn('رجوع', cb='reg_back_main')])
            edit(
                '⚠️ <b>غير مسجل في البوت الرئيسي</b>\n\n'
                'لازم تبدأ أولاً من البوت الرئيسي\n'
                'ثم ارجع لهنا لتسجيل أرقامك',
                kb
            )
            return
        _reg_state[uid] = 'phone'
        if uid not in _reg_data:
            _reg_data[uid] = {'referrer': None}
        kb = _gikb([_gbtn('إلغاء', cb='reg_cancel')])
        edit(
            '📱 <b>الخطوة 1 من 2 — رقم اله��تف</b>\n\n'
            '• أرسل رقم هاتفك مع رمز الدولة\n'
            '• <b>مثال :</b> <code>+201012345678</code>\n\n'
            '⚠️ تأكد إن الرقم نشط ويستقبل رسائل تيليجرام',
            kb
        )

    elif data == 'reg_rules':
        answer()
        kb = _gikb(
            [_gbtn('📱 تسجيل رقم الآن', cb='reg_start')],
            [_gbtn('رجوع', cb='reg_back_main')]
        )
        edit(
            '📋 <b>شروط وأحكام التسجيل</b>\n'
            '━━━━━━━━━━━━━━━━━━━\n\n'
            '✅ <b>الشروط المقبولة :</b>\n'
            '• الرقم يجب يكون نشط على تيليجرام\n'
            '• الرقم يجب يكون مفعّل من أكثر من 30 يوم\n'
            '• الحساب يجب يكون غير محظور من @spambot\n'
            '• رقم واحد لكل جلسة تسجيل\n\n'
            '❌ <b>الشروط الغير مقبولة :</b>\n'
            '• أرقام وهمية أو مؤقتة\n'
            '• أرقام محظورة أو مقيدة\n'
            '• تسجيل نفس الرقم مرتين\n'
            '• لا يوجد حد يومي للتسجيل\n\n'
            '━━━━━━━━━━━━━━━━━━━\n'
            '⚠️ <b>تنبيه :</b> مخالفة الشروط تؤدي للحظر الفوري',
            kb
        )

    elif data == 'reg_howto':
        answer()
        _rent_pts = int(db.get("rent_reward")) if db.exists("rent_reward") else 100
        kb = _gikb(
            [_gbtn('📱 ابدأ التسجيل', cb='reg_start')],
            [_gbtn('رجوع', cb='reg_back_main')]
        )
        edit(
            '❓ <b>كيف يعمل البوت؟</b>\n'
            '━━━━━━━━━━━━━━━━━━━\n\n'
            '1️⃣ اضغط <b>تسجيل رقم جديد</b>\n'
            '2️⃣ أرسل رقمك مع رمز الدولة\n'
            '   مثال: <code>+201012345678</code>\n'
            '3️⃣ استلم كود التحقق على تيليجرام\n'
            '4️⃣ أرسل الكود بالشكل: <code>1-2-3-4-5</code>\n'
            '5️⃣ تستلم نقاطك فوراً 🎉\n\n'
            '━━━━━━━━━━━━━━━━━━━\n'
            f'💰 <b>مكافأة كل رقم :</b> {_rent_pts:,} نقطة\n'
            '📅 <b>الحد اليومي :</b> غير محدود\n'
            '🔄 <b>الحد يتجدد :</b> كل يوم منتصف الليل',
            kb
        )

    elif data == 'reg_support':
        answer()
        _sup = db.get('support_username') or ''
        kb_rows = []
        if _sup:
            kb_rows.append([_gbtn('💬 تواصل مع الدعم', url=f'https://t.me/{_sup.lstrip("@")}')])
        kb_rows.append([_gbtn('رجوع', cb='reg_back_main')])
        edit(
            '🎧 <b>الدعم الفني</b>\n'
            '━━━━━━━━━━━━━━━━━━━\n\n'
            '⏱ وقت الاستجابة: خلال 24 ساعة\n\n'
            '• للمشاكل التقنية اضغط الزر أدناه',
            _gikb(*kb_rows)
        )

    elif data == 'reg_ai':
        if not _ai_support_enabled():
            answer('⚠️ المساعد الذكي غير متاح حالياً', alert=True)
            return
        answer()
        _reg_state[uid] = 'ai_chat'
        kb = _gikb([_gbtn('🚪 إنهاء المحادثة', cb='reg_cancel')])
        edit(
            '🤖 <b>المساعد الذكي</b>\n'
            '━━━━━━━━━━━━━━━━━\n\n'
            '👋 اسألني أي حاجة عن البوت وخدماته:\n'
            '• تسجيل الأرقام والمكافآت\n'
            '• الشروط وطريقة العمل\n'
            '• VIP والشحن والمتجر\n\n'
            '✍️ اكتب سؤالك الآن...',
            kb
        )

    elif data == 'reg_cancel':
        _reg_state.pop(uid, None)
        _reg_data.pop(uid, None)
        _reg_processing.discard(uid)
        answer('تم الإلغاء ✅')
        text, kb = _gen_start_menu(uid, call.from_user.first_name)
        edit(text, kb)

    elif data == 'reg_back_main':
        answer()
        text, kb = _gen_start_menu(uid, call.from_user.first_name)
        edit(text, kb)

    elif data == 'reg_myaccounts':
        answer()
        _submitted = int(db.get(f'user_{uid}_rent_submitted') or 0)
        _rent_pts  = int(db.get("rent_reward")) if db.exists("rent_reward") else 100
        _total_earned = _submitted * _rent_pts
        accounts = db.get('accounts') or []
        user_accounts = [a for a in accounts if str(a.get('owner_id', '')) == str(uid)]
        lines = [
            f'╔══════════════════╗\n'
            f'       📊 حساباتي المسجلة\n'
            f'╚══════════════════╝\n\n'
            f'📱 إجمالي الحسابات : <b>{_submitted}</b>\n'
            f'💰 إجمالي النقاط : <b>{_total_earned:,} نقطة</b>\n'
            f'🎁 مكافأة كل رقم : <b>{_rent_pts:,} نقطة</b>\n'
            f'━━━━━━━━━━━━━━━━━━━'
        ]
        if user_accounts:
            lines.append(f'\n📋 <b>أرقامك ({len(user_accounts)}) :</b>')
            for i, acc in enumerate(user_accounts[:10], 1):
                lines.append(f'  {i}. <code>{acc.get("phone", "غير معروف")}</code>')
            if len(user_accounts) > 10:
                lines.append(f'  ... و {len(user_accounts)-10} أرقام أخرى')
        else:
            lines.append('\n⚠️ لم تسجّل أي أرقام بعد')
        lines.append('━━━━━━━━━━━━━━━━━━━')
        kb = _gikb(
            [_gbtn('🏆 توب 5 أكتر ناس سجّلوا', cb='reg_top5')],
            [_gbtn('📱 تسجيل رقم جديد', cb='reg_start')],
            [_gbtn('رجوع', cb='reg_back_main')]
        )
        edit('\n'.join(lines), kb)

    elif data == 'reg_top5':
        answer()
        medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
        accounts = db.get('accounts') or []
        count_map = {}
        for acc in accounts:
            oid = acc.get('owner_id')
            if oid:
                count_map[int(oid)] = count_map.get(int(oid), 0) + 1
        lines = ['╔══════════════════╗\n       🏆 توب 5 — أكتر ناس سجّلوا\n╚══════════════════╝\n━━━━━━━━━━━━━━━━━━━']
        if not count_map:
            lines.append('⚠️ لا يوجد بيانات حتى الآن')
        else:
            for i, (oid, count) in enumerate(sorted(count_map.items(), key=lambda x: x[1], reverse=True)[:5]):
                lines.append(f'{medals[i]} <b>#{oid}</b> — {count} حساب')
        lines.append('━━━━━━━━━━━━━━━━━━━')
        kb = _gikb([_gbtn('رجوع', cb='reg_myaccounts')])
        edit('\n'.join(lines), kb)

    elif data == 'reg_balance':
        answer()
        udata = db.get(f'user_{uid}') or {}
        coins = int(udata.get('coins', 0))
        submitted = int(db.get(f'user_{uid}_rent_submitted') or 0)
        kb = _gikb([_gbtn('رجوع', cb='reg_back_main')])
        edit(
            f'💰 <b>رصيدك في البوت الرئيسي</b>\n'
            f'━━━━━━━━━━━━━━━━━━━\n\n'
            f'👛 الرصيد الحالي : {coins:,} نقطة\n'
            f'📱 أرقام سجّلتها : {submitted} رقم',
            kb
        )

    elif data == 'clear':
        answer('برجاء الانتظار — جارٍ التنظيف', alert=True)
        threading.Thread(target=_gen_clear_sessions, args=(call,), daemon=True).start()

def _gen_clear_sessions(call):
    """تنظيف الجلسات المنتهية (sync في thread)"""
    if not db.exists('accounts'):
        try:
            gen_bot.edit_message_text('• لا يوجد اي ارقام في البوت', call.message.chat.id, call.message.message_id, reply_markup=_gikb([_gbtn('🔙 رجوع', cb='reg_back_main')]))
        except:
            pass
        return
    sessions = db.get('accounts')
    if len(sessions) < 1:
        try:
            gen_bot.edit_message_text('لا يوجد اي ارقام في البوت', call.message.chat.id, call.message.message_id, reply_markup=_gikb([_gbtn('🔙 رجوع', cb='reg_back_main')]))
        except:
            pass
        return

    deleted_count = 0
    working_count = 0
    updated_sessions = []

    async def _check_all():
        nonlocal deleted_count, working_count
        for session in sessions:
            sessio = session['s']
            phon   = session['phone']
            try:
                client = Client('::memory::', api_id=API_ID, api_hash=API_HASH, in_memory=True, session_string=sessio)
                await client.start()
                await client.get_me()
                working_count += 1
                updated_sessions.append(session)
            except Exception:
                deleted_count += 1
                owner_id  = session.get('owner_id')
                penalized = db.get(f'session_penalized_{phon}')
                if not penalized and owner_id:
                    _penalty = 500
                    if db.exists(f'user_{owner_id}'):
                        udata = db.get(f'user_{owner_id}')
                        coins = int(udata.get('coins', 0))
                        udata['coins'] = max(0, coins - _penalty)
                        db.set(f'user_{owner_id}', udata)
                        db.set(f'session_penalized_{phon}', True)
                        db.set(f'session_broken_{phon}', {'phone': phon, 'owner_id': owner_id, 'penalty': _penalty})

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_check_all())
    loop.close()

    db.set('accounts', updated_sessions)
    try:
        from telebot.types import InlineKeyboardMarkup as _TM, InlineKeyboardButton as _TB
        _clr_kb = _TM(row_width=1)
        _clr_kb.add(_TB(text='🔙 رجوع', callback_data='reg_back_main'))
        gen_bot.edit_message_text(
            f'✅ تم التنظيف\n• شغالة: {working_count}\n• محذوفة: {deleted_count}',
            call.message.chat.id, call.message.message_id,
            reply_markup=_clr_kb
        )
    except:
        pass


@gen_bot.message_handler(func=lambda m: m.chat.type == 'private')
def gen_msg_handler(message):
    uid  = message.from_user.id
    text = (message.text or '').strip()
    step = _reg_state.get(uid)

    if step == 'ai_chat':
        if not text:
            return
        _typing = gen_bot.reply_to(message, '🤖 لحظة... بفكّر في إجابتك')
        ans, err = _ai_ask(text)
        out = ans if ans else err
        kb = _gikb([_gbtn('🚪 إنهاء المحادثة', cb='reg_cancel')])
        try:
            gen_bot.edit_message_text(out, message.chat.id, _typing.message_id, reply_markup=kb)
        except Exception:
            try:
                gen_bot.reply_to(message, out, reply_markup=kb)
            except Exception:
                pass
        return

    if not step:
        _user_submitted = int(db.get(f'user_{uid}_rent_submitted') or 0)
        kb = _gikb([_gbtn('📱 تسجيل رقم جديد', cb='reg_start')])
        gen_bot.reply_to(message,
            f'⚠️ لا توجد جلسة تسجيل نشطة\n\n'
            f'📱 أرقام سجّلتها : {_user_submitted} رقم\n\n'
            f'اضغط الزر للبدء 👇',
            reply_markup=kb
        )
        return

    if step == 'phone':
        if uid in _reg_processing:
            return
        if not text.startswith('+') or len(text) < 8:
            kb = _gikb([_gbtn('إلغاء', cb='reg_cancel')])
            gen_bot.reply_to(message,
                '❌ <b>رقم غير صحيح</b>\n\n'
                '• يجب أن يبدأ بـ <code>+</code> ورمز الدولة\n'
                '• <b>مثال :</b> <code>+201012345678</code>',
                reply_markup=kb, parse_mode='HTML'
            )
            return
        phone = text.strip()
        _reg_processing.add(uid)
        _existing_accounts = _gcache_get('accounts') or db.get('accounts') or []
        _gcache_set('accounts', _existing_accounts, ttl=60)
        _phone_match = next((a for a in _existing_accounts if str(a.get('phone', '')).strip() == phone), None)
        if _phone_match:
            _is_broken = db.get(f'session_broken_{phone}')
            _is_dead   = db.get(f'session_dead_{phone}')
            _owner     = _phone_match.get('owner_id')
            if not _is_broken and not _is_dead:
                # الرقم نشط تماماً — ارفض
                _owner_txt = f'\n👤 مسجّل بواسطة مستخدم آخر' if _owner and int(_owner) != uid else '\n👤 هذا الرقم مسجّل بحسابك مسبقاً'
                kb = _gikb([_gbtn('رجوع', cb='reg_back_main')])
                gen_bot.reply_to(message,
                    f'❌ <b>الرقم مسجّل بالفعل</b>\n\n'
                    f'📱 <code>{phone}</code>{_owner_txt}\n\n'
                    '• لا يمكن تسجيل نفس الرقم مرتين\n'
                    '• إذا كان هذا رقمك وتواجه مشكلة، تواصل مع الدعم',
                    reply_markup=kb, parse_mode='HTML'
                )
                _reg_state.pop(uid, None)
                _reg_processing.discard(uid)
                _reg_data.pop(uid, None)
                return
            elif _is_broken or _is_dead:
                # الرقم موجود لكن مكسور/ميت — نخبره إنه سيتم استبداله
                _status = 'مكسور' if _is_broken else 'غير نشط'
                gen_bot.reply_to(message,
                    f'⚠️ <b>الرقم موجود مسبقاً لكنه {_status}</b>\n\n'
                    f'📱 <code>{phone}</code>\n'
                    '• سيتم تحديث الجلسة بالجلسة الجديدة تلقائياً ✅',
                    parse_mode='HTML'
                )
        wait_msg = gen_bot.reply_to(message, '⏳ جارٍ إرسال كود التحقق...')
        threading.Thread(
            target=_gen_send_code,
            args=(message, phone, uid, wait_msg),
            daemon=True
        ).start()

    elif step == 'code':
        code_raw = text.replace('-', '').replace(' ', '').strip()
        if not code_raw.isdigit() or len(code_raw) < 4:
            kb = _gikb([_gbtn('إلغاء', cb='reg_cancel')])
            gen_bot.reply_to(message,
                '❌ <b>كود غير صحيح</b>\n\n'
                '• أرسل الكود بالشكل : <code>1-2-3-4-5</code>\n'
                '• أو أرسله متصلاً : <code>12345</code>',
                reply_markup=kb, parse_mode='HTML'
            )
            return
        threading.Thread(
            target=_gen_verify_code,
            args=(message, code_raw, uid),
            daemon=True
        ).start()

    elif step == 'pass':
        threading.Thread(
            target=_gen_verify_pass,
            args=(message, text, uid),
            daemon=True
        ).start()


import asyncio as _pyro_asyncio

# ── Event loop دائم يعمل في thread مخصص ──
# الكود القديم كان بينده run_until_complete على نفس الـ loop من أكتر من thread
# في نفس الوقت (تسجيل أرقام + تنفيذ طلبات)، وده بيرمي:
#   RuntimeError: This event loop is already running
# وبيخلي العمليات تتسلسل ورا بعض (بطء) أو تفشل، وكمان بيقطع جلسة pyrogram بين
# خطوة إرسال الكود وخطوة التأكيد. الحل: loop واحد شغّال بـ run_forever في الخلفية،
# ونبعتله الـ coroutines بشكل thread-safe عن طريق run_coroutine_threadsafe.

_pyro_loop = _pyro_asyncio.new_event_loop()
_pyro_loop_lock = threading.Lock()

def _pyro_loop_runner():
    _pyro_asyncio.set_event_loop(_pyro_loop)
    _pyro_loop.run_forever()

_pyro_loop_thread = threading.Thread(target=_pyro_loop_runner, daemon=True)
_pyro_loop_thread.start()

def _pyro_run(coro):
    """يشغّل coroutine على loop دائم مشترك — آمن للاستدعاء من أي thread وبشكل متزامن."""
    global _pyro_loop, _pyro_loop_thread
    # لو الـ loop اتقفل أو الـ thread وقف لأي سبب — أعد تشغيله
    if _pyro_loop.is_closed() or not _pyro_loop_thread.is_alive():
        with _pyro_loop_lock:
            if _pyro_loop.is_closed() or not _pyro_loop_thread.is_alive():
                _pyro_loop = _pyro_asyncio.new_event_loop()
                _pyro_loop_thread = threading.Thread(target=_pyro_loop_runner, daemon=True)
                _pyro_loop_thread.start()
    future = _pyro_asyncio.run_coroutine_threadsafe(coro, _pyro_loop)
    return future.result()

def _gen_send_code(message, phone, uid, wait_msg):
    """إرسال كود التحقق في thread مستقل"""
    async def _do():
        from pyrogram.errors import ApiIdInvalid, PhoneNumberInvalid, FloodWait
        client_1 = Client(name="user_tmp", api_id=API_ID, api_hash=API_HASH,
                          lang_code="ar", in_memory=True)
        await client_1.connect()
        try:
            code = await client_1.send_code(phone)
        except ApiIdInvalid:
            try: await client_1.disconnect()
            except: pass
            try: gen_bot.delete_message(wait_msg.chat.id, wait_msg.message_id)
            except: pass
            gen_bot.reply_to(message, '❌ مشكلة في إعدادات البوت، أبلغ المطور')
            _reg_state.pop(uid, None)
            _reg_processing.discard(uid)
            return
        except PhoneNumberInvalid:
            try: await client_1.disconnect()
            except: pass
            try: gen_bot.delete_message(wait_msg.chat.id, wait_msg.message_id)
            except: pass
            kb = _gikb([_gbtn('إلغاء', cb='reg_cancel')])
            gen_bot.reply_to(message,
                f'❌ <b>رقم غير صالح</b>\n\n<code>{phone}</code>\n\nأعد إرسال رقم صحيح',
                reply_markup=kb, parse_mode='HTML'
            )
            _reg_processing.discard(uid)
            return
        except FloodWait as fw:
            try: await client_1.disconnect()
            except: pass
            try: gen_bot.delete_message(wait_msg.chat.id, wait_msg.message_id)
            except: pass
            gen_bot.reply_to(message, f'⏳ انتظر {fw.value} ثانية ثم حاول مجدداً')
            _reg_state.pop(uid, None)
            _reg_processing.discard(uid)
            return
        except Exception as e:
            try: await client_1.disconnect()
            except: pass
            try: gen_bot.delete_message(wait_msg.chat.id, wait_msg.message_id)
            except: pass
            kb = _gikb([_gbtn('🔄 حاول مرة أخرى', cb='reg_start')])
            gen_bot.reply_to(message, f'❌ خطأ: {e}', reply_markup=kb)
            _reg_state.pop(uid, None)
            _reg_processing.discard(uid)
            return

        _reg_data[uid] = _reg_data.get(uid, {})
        _reg_data[uid].update({'phone': phone, 'hash': code.phone_code_hash, 'client': client_1})
        _reg_state[uid] = 'code'
        _reg_processing.discard(uid)

        try: gen_bot.delete_message(wait_msg.chat.id, wait_msg.message_id)
        except: pass
        kb = _gikb([_gbtn('إلغاء', cb='reg_cancel')])
        gen_bot.reply_to(message,
            '📩 <b>الخطوة 2 من 2 — كود التحقق</b>\n\n'
            f'📱 تم إرسال كود التحقق إلى : <code>{phone}</code>\n\n'
            '• أرسل الكود بالشكل : <code>1-2-3-4-5</code>\n'
            '⚠️ لا تشارك الكود مع أي أحد!',
            reply_markup=kb, parse_mode='HTML'
        )

    _pyro_run(_do())

def _gen_verify_code(message, code_raw, uid):
    """التحقق من الكود في thread مستقل"""
    async def _do():
        from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired
        data   = _reg_data.get(uid, {})
        client = data.get('client')
        phone  = data.get('phone')
        ph_hash = data.get('hash')
        if not client or not phone:
            gen_bot.reply_to(message, '❌ انتهت الجلسة، ابدأ من جديد')
            _reg_state.pop(uid, None)
            _reg_data.pop(uid, None)
            return
        try:
            signed = await client.sign_in(phone, ph_hash, code_raw)
        except SessionPasswordNeeded:
            _reg_state[uid] = 'pass'
            kb = _gikb([_gbtn('إلغاء', cb='reg_cancel')])
            gen_bot.reply_to(message,
                '🔐 <b>التحقق بخطوتين مفعّل</b>\n\n'
                '• أرسل كلمة مرور الحساب الآن:',
                reply_markup=kb, parse_mode='HTML'
            )
            return
        except PhoneCodeInvalid:
            kb = _gikb([_gbtn('إلغاء', cb='reg_cancel')])
            gen_bot.reply_to(message, '❌ <b>كود خاطئ</b>\n\nأعد إرسال الكود', reply_markup=kb, parse_mode='HTML')
            return
        except PhoneCodeExpired:
            kb = _gikb([_gbtn('🔄 إرسال كود جديد', cb='reg_start')])
            gen_bot.reply_to(message, '❌ <b>الكود انتهت صلاحيته</b>\n\nاضغط ل��رسال كود جديد', reply_markup=kb, parse_mode='HTML')
            _reg_state.pop(uid, None)
            return
        except Exception as e:
            gen_bot.reply_to(message, f'❌ خطأ: {e}')
            return
        txt_session = await client.export_session_string()
        await client.disconnect()
        _finish_registration_sync(message, data, uid, txt_session)

    _pyro_run(_do())

def _gen_verify_pass(message, password, uid):
    """التحقق من كلمة المرور في thread مستقل"""
    async def _do():
        from pyrogram.errors import PasswordHashInvalid
        data   = _reg_data.get(uid, {})
        client = data.get('client')
        if not client:
            gen_bot.reply_to(message, '❌ انتهت الجلسة، ابدأ من جديد')
            _reg_state.pop(uid, None)
            _reg_data.pop(uid, None)
            return
        try:
            await client.check_password(password)
        except PasswordHashInvalid:
            kb = _gikb([_gbtn('إلغاء', cb='reg_cancel')])
            gen_bot.reply_to(message, '❌ <b>كلمة مرور خاطئة</b>\n\nأعد المحاولة:', reply_markup=kb, parse_mode='HTML')
            return
        except Exception as e:
            gen_bot.reply_to(message, f'❌ خطأ: {e}')
            return
        txt_session = await client.export_session_string()
        await client.disconnect()
        _finish_registration_sync(message, data, uid, txt_session)

    _pyro_run(_do())

def run_gen_app():
    """يشغّل بوت تسجيل الأرقام (gen_bot — telebot)"""
    print("[✅] بوت تسجيل الأرقام (gen_bot/telebot) يعمل...")
    while True:
        try:
            gen_bot.infinity_polling(
                timeout=30,
                long_polling_timeout=10,
                allowed_updates=['message', 'callback_query'],
                skip_pending=True,
                interval=0
            )
        except Exception as e:
            print(f"[gen_bot] خطأ — إعادة التشغيل بعد 3 ثواني: {e}")
            _time_module.sleep(3)

@bot.channel_post_handler(func=lambda m: True)
def on_channel_post(message):
    """يستقبل المنشورات الجديدة في القنوات لتنفيذ المشاهدات المستقبلية"""
    try:
        ch = str(message.chat.username or message.chat.id).lstrip('@')
        msg_link = f'https://t.me/{ch}/{message.message_id}'
        if _future_views_subs:
            threading.Thread(
                target=_process_future_view,
                args=(ch, msg_link),
                daemon=True
            ).start()
    except Exception as _fve:
        print(f'[future_views listener] {_fve}')

# ══════════════════════════════════════════════════════════════
#  دوال مكتملة — كانت مستدعاة بس مش معرّفة أو ناقصة
# ══════════════════════════════════════════════════════════════

def get_url_linkbot(message, amount):
    """يستقبل رابط البوت لخدمة linkbot ثم يطلب النص"""
    cid = message.from_user.id
    if not db.get(f'linkbot_{cid}_proccess'):
        return
    if not message.text:
        r = bot.reply_to(message, '❌ أرسل رابط أو معرف البوت (مثال: @mybot)', reply_markup=_bk_cancel_svc('normal'))
        bot.register_next_step_handler(r, get_url_linkbot, amount)
        return
    url = message.text.strip()
    if not url.startswith('@') and not url.startswith('https://t.me/') and not url.startswith('t.me/'):
        r = bot.reply_to(message, '❌ رابط غير صالح، أرسل مثال: @mybot أو https://t.me/mybot', reply_markup=_bk_cancel_svc('normal'))
        bot.register_next_step_handler(r, get_url_linkbot, amount)
        return
    bot_user_clean = url.replace('https://t.me/', '').replace('t.me/', '').replace('@', '').strip()
    x = bot.reply_to(message,
        f'📝 <b>أرسل الآن نص الرسالة</b> التي ستُرسل للبوت\n\n'
        f'✅ الكمية: {amount}\n'
        f'🤖 البوت: @{bot_user_clean}\n\n'
        f'• مثال: /start\n• أو أي رسالة تريدها',
        reply_markup=_bk_cancel_svc('normal'), parse_mode='HTML')
    bot.register_next_step_handler(x, link_bot, amount)


def _ensure_user(user_id):
    """يتأكد أن المستخدم م��جود في DB وإلا ينشئه"""
    if not db.get(f'user_{user_id}'):
        db.set(f'user_{user_id}', {'id': user_id, 'coins': 0, 'premium': False, 'users': []})


def _safe_edit(chat_id, message_id, text, reply_markup=None, parse_mode='HTML'):
    """edit_message_text آمن — لو فشل يبعت رسالة جديدة"""
    try:
        bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id,
                              reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        try:
            bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            pass


def _deduct_coins(user_id: int, amount: int) -> bool:
    """يخصم نقاط من المستخدم — يرجع True لو نجح"""
    try:
        info = db.get(f'user_{user_id}') or {}
        current = int(info.get('coins', 0))
        if current < amount:
            return False
        info['coins'] = current - amount
        db.set(f'user_{user_id}', info)
        return True
    except Exception as e:
        print(f'[deduct_coins] {e}')
        return False


def _add_coins(user_id: int, amount: int):
    """يضيف نقاط للمستخدم"""
    try:
        info = db.get(f'user_{user_id}') or {'id': user_id, 'coins': 0, 'premium': False, 'users': []}
        info['coins'] = int(info.get('coins', 0)) + amount
        db.set(f'user_{user_id}', info)
    except Exception as e:
        print(f'[add_coins] {e}')


def _svc_not_enough_accounts(message, amount):
    """رسالة موحدة: عدد الحسابات غير كافٍ"""
    bot.reply_to(message,
        f'⚠️ <b>عدد الحسابات غير كافٍ</b>\n\n'
        f'• الكمية المطلوبة: {amount}\n'
        f'• الحسابات المتاحة: {len(db.get("accounts") or [])}\n\n'
        f'يرجى تقليل الكمية أو المحاولة لاحقاً.',
        reply_markup=bk, parse_mode='HTML')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  إصلاح: نظام تأكيد الطلب الموحد
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _send_order_confirm(cid, service_label, section_label, amount, price, extra=None):
    """
    يعرض رسالة تأكيد الطلب قبل التنفيذ.
    يُخزّن الطلب في _pending_orders[cid] ثم ينتظر callback confirm_order أو cancel_order.
    """
    info = db.get(f'user_{cid}') or {}
    balance = int(info.get('coins', 0))
    order = {
        'type': service_label,
        'section': section_label,
        'amount': amount,
        'price': price,
        'extra': extra or {},
        'uid': cid,
    }
    _pending_orders[cid] = order

    confirm_keys = mk(row_width=1)
    confirm_keys.add(btn('✅ تأكيد الطلب', callback_data='confirm_order', color='green'))
    confirm_keys.add(btn('❌ إلغاء', callback_data='cancel_order', color='red'))

    txt = (
        f'╔══════════════════════╗\n'
        f'       📋 تأكيد الطلب\n'
        f'╚══════════════════════╝\n\n'
        f'📂 القسم : {section_label}\n'
        f'🛠 الخدمة : {service_label}\n'
        f'📦 الكمية : {amount:,}\n'
        f'💰 التكلفة : <b>{price:,} نقطة</b>\n'
        f'💳 رصيدك : {balance:,} نقطة\n'
        f'━━━━━━━━━━━━━━━━━━━━\n'
        f'هل تريد تأكيد الطلب؟'
    )
    try:
        bot.send_message(cid, txt, reply_markup=confirm_keys, parse_mode='HTML')
    except Exception as e:
        print(f'[send_order_confirm] {e}')


# ══════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════
#  نظام التذكير بالهدية اليومية — Timer دقيق لكل مستخدم
#  كل مستخدم عنده threading.Timer بيدق بالظبط بعد 24 ساعة
#  من آخر مرة سحب فيها الهدية
# ══════════════════════════════════════════════════════════════

_remind_timers: dict = {}   # uid → threading.Timer الشغال حالياً
_remind_timers_lock = threading.Lock()


def _send_daily_reminder(uid: int):
    """
    يبعت رسالة التذكير.
    بعد الإرسال يجدول تذكير تاني بعد 24 ساعة
    (لو المستخدم شاف الرسالة بس نسي يضغط).
    لو المستخدم blocked البوت (exception 403) → مش بيجدول تاني.
    """
    with _remind_timers_lock:
        _remind_timers.pop(uid, None)

    # فحص: هل التذكير مفعّل؟
    remind_enabled = db.get('daily_remind_enabled')
    remind_enabled = remind_enabled if remind_enabled is not None else True
    if not remind_enabled:
        return

    try:
        daily_gift = int(db.get("daily_gift")) if db.exists("daily_gift") else 30
        keys = TelebotMarkup(row_width=1)
        keys.add(btn('🎁 استلم هديتك الآن', callback_data='daily_gift_claim', color='green'))
        txt = (
            f'🔔 <b>تذكير: هديتك اليومية في انتظارك!</b>\n\n'
            f'🎁 يمكنك استلام <b>{daily_gift} نقطة</b> مجاناً الآن\n'
            f'⏰ لا تفوّت هديتك اليومية'
        )
        bot.send_message(uid, txt, reply_markup=keys, parse_mode='HTML')
        # ✅ بعت التذكير — جدول تاني بعد 24 ساعة لو ما ضغطش
        _schedule_reminder(uid, 24 * 60 * 60)
    except Exception as _e:
        err = str(_e).lower()
        # BUG 5 FIX: لو المستخدم blocked البوت أو محذوف → وقف التذكير
        if 'forbidden' in err or '403' in err or 'blocked' in err or 'deactivated' in err:
            return   # مش بنجدول تاني
        # أي خطأ تاني → جرب تاني بعد ساعة
        _schedule_reminder(uid, 3600)


def _schedule_reminder(uid: int, delay_seconds: float):
    """
    يجدول تذكير لمستخدم واحد بعد delay_seconds.
    لو عنده Timer قديم يلغيه أولاً.
    """
    if delay_seconds < 0:
        delay_seconds = 0

    with _remind_timers_lock:
        old = _remind_timers.pop(uid, None)
        if old:
            try:
                old.cancel()
            except Exception:
                pass
        t = threading.Timer(delay_seconds, _send_daily_reminder, args=(uid,))
        t.daemon = True
        t.start()
        _remind_timers[uid] = t


def _schedule_reminder_for_user(uid: int):
    """
    يحسب متى تجهز هدية المستخدم ويجدول التذكير بالظبط.
    يُستدعى عند:
      - بداية البوت  (لكل المستخدمين)
      - بعد ما المستخدم يسحب الهدية  (يجدد الـ Timer لـ 24 ساعة)
    """
    WAIT = 24 * 60 * 60
    now = time.time()

    gift_data = db.get(f'user_{uid}_giftt')

    if gift_data is None or not isinstance(gift_data, dict):
        # ما سحبش هدية قط → الهدية جاهزة
        # BUG 2 FIX: stagger حسب uid عشان الكل ما يتذكرش في نفس الثانية
        delay = float(uid % 300)   # موزع على 5 دقائق
    else:
        last_time = gift_data.get('timee', 0)
        elapsed = now - last_time
        remaining = WAIT - elapsed
        if remaining <= 0:
            # الهدية جاهزة بالفعل → stagger حسب uid
            delay = float(uid % 300)
        else:
            # الهدية تجهز بعد remaining ثانية بالظبط
            delay = remaining

    _schedule_reminder(uid, delay)


def _start_daily_reminder_thread():
    """
    عند بداية البوت: يمشي على كل المستخدمين ويجدول Timer دقيق لكل واحد.
    بيشتغل في thread منفصل عشان ما يبطّئش البوت وقت الإقلاع.
    """
    def _boot_scheduler():
        time.sleep(5)   # استنى البوت يكمل إقلاعه الأول
        try:
            delay_between = 0.02   # 20ms بين كل مستخدم ومستخدم
            count = 0
            for key_row in db.keys('user_%'):
                try:
                    key = key_row[0] if isinstance(key_row, (list, tuple)) else key_row
                    if any(x in key for x in ('_daily_count','_giftt','_remind','_daily_reminded')):
                        continue
                    info = db.get(key)
                    if not isinstance(info, dict) or not info.get('id'):
                        continue
                    uid = int(info['id'])
                    _schedule_reminder_for_user(uid)
                    count += 1
                    time.sleep(delay_between)
                except Exception:
                    continue
            print(f'[✅] daily reminder: جدولة {count} مستخدم تمت')
        except Exception as e:
            print(f'[daily_reminder boot] {e}')

    t = threading.Thread(target=_boot_scheduler, daemon=True, name='daily_reminder_boot')
    t.start()
    print('[✅] daily reminder thread: شغال')


if __name__ == "__main__":
    print("[🚀] جارٍ تشغيل البوت...")

    # thread 1: gen_bot (بوت تسجيل الأرقام)
    t1 = threading.Thread(target=run_gen_app, daemon=True)
    t1.start()
    print("[✅] thread 1: بوت تسجيل الأرقام يعمل")

    # thread 2: تذكير الهدية اليومية
    _start_daily_reminder_thread()

    print("[✅] main thread: البوت الرئيسي يبدأ الآن...")
    # main thread: telebot (البوت الرئيسي)
    while True:
        try:
            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=10,
                allowed_updates=['message', 'callback_query'],
                skip_pending=True,
                interval=0
            )
        except Exception as e:
            import re as _re2
            err = str(e).lower()
            if "flood" in err or "too many" in err or "retry" in err:
                wait = 30
                try:
                    found = _re2.search(r'retry[_ ]after[: ]+(\d+)', err)
                    if found:
                        wait = int(found.group(1)) + 2
                except: pass
                print(f"[⚠️] FloodWait — انتظار {wait} ثانية...")
                _time_module.sleep(wait)
            elif "timed out" in err or "timeout" in err or "connection" in err:
                print(f"[⚠️] مشكلة نت — إعادة المحاولة خلال 10 ثواني...")
                _time_module.sleep(10)
            else:
                print(f"[!] خطأ في تيليبوت: {e}")
                _time_module.sleep(5)
