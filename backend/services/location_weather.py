from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests

try:
    import winrt.windows.devices.geolocation as geolocation
except Exception:
    geolocation = None

try:
    import jdatetime
except Exception:
    jdatetime = None

_WMO_FA = {
    0: "صاف", 1: "عمدتاً صاف", 2: "کمی ابری", 3: "ابری", 45: "مه‌آلود", 48: "مه یخ‌زن",
    51: "نم‌نم باران", 53: "نم‌نم باران", 55: "نم‌نم باران شدید", 56: "نم‌نم باران یخ‌زن", 57: "نم‌نم باران یخ‌زن شدید",
    61: "باران سبک", 63: "باران", 65: "باران شدید", 66: "باران یخ‌زن سبک", 67: "باران یخ‌زن شدید",
    71: "برف سبک", 73: "برف", 75: "برف شدید", 77: "دانه‌های برف", 80: "رگبار سبک", 81: "رگبار", 82: "رگبار شدید",
    85: "رگبار برف سبک", 86: "رگبار برف شدید", 95: "رعدوبرق", 96: "رعدوبرق با تگرگ سبک", 99: "رعدوبرق با تگرگ شدید",
}
_WMO_EN = {
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "foggy", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "light showers", 81: "showers", 82: "heavy showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "strong thunderstorm with hail",
}

class LocationWeatherService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._location_cache: dict | None = None
        self._weather_cache: dict[tuple[float,float,str], tuple[float,dict]] = {}
        self._reverse_cache: dict[tuple[float,float], tuple[float,dict]] = {}

    def _win_location(self) -> dict:
        if geolocation is None:
            return {"ok": False, "error": "Windows location API is unavailable in this Python environment.", "settings_uri": "ms-settings:privacy-location"}
        try:
            async def read():
                locator = geolocation.Geolocator()
                position = await locator.get_geoposition_async()
                coord = position.coordinate
                return float(coord.latitude), float(coord.longitude)
            lat, lon = asyncio.run(asyncio.wait_for(read(), timeout=5.0))
            return {"ok": True, "latitude": lat, "longitude": lon, "source": "windows-location"}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "settings_uri": "ms-settings:privacy-location"}

    def _reverse_geocode(self, latitude: float, longitude: float) -> dict:
        key=(round(float(latitude),4), round(float(longitude),4))
        with self._lock:
            cached=self._reverse_cache.get(key)
            if cached and time.time()-cached[0] < 900:
                return dict(cached[1])
        try:
            response=requests.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat":latitude,"lon":longitude,"format":"json","accept-language":"fa"},
                headers={"User-Agent":"Smartis/2.2"},
                timeout=5,
            )
            data=response.json() if response.ok else {}
            address=data.get("address") or {}
            result={
                "city": address.get("city") or address.get("town") or address.get("municipality") or address.get("village") or address.get("county") or "",
                "admin1": address.get("state") or "",
                "display_name": data.get("display_name") or "",
            }
        except Exception:
            result={"city":"","admin1":"","display_name":""}
        with self._lock:
            self._reverse_cache[key]=(time.time(),result)
        return result

    def _ip_location(self) -> dict:
        # Last-resort approximate location. This is intentionally marked as
        # approximate; it is only used to keep the weather dashboard useful
        # when the Windows Location API is unavailable to Python.
        providers = (
            ("https://ipapi.co/json/", lambda d: (d.get("latitude"), d.get("longitude"), d.get("city"), d.get("region"))),
            ("https://ipwho.is/", lambda d: (d.get("latitude"), d.get("longitude"), (d.get("city") or ""), (d.get("region") or ""))),
        )
        for url, unpack in providers:
            try:
                r=requests.get(url, timeout=4, headers={"User-Agent":"Smartis/2.3"})
                if not r.ok: continue
                data=r.json(); lat,lon,city,admin=unpack(data)
                if lat is None or lon is None: continue
                return {"ok":True,"latitude":float(lat),"longitude":float(lon),"city":str(city or ""),"admin1":str(admin or ""),"source":"ip-approximate","approximate":True}
            except Exception:
                continue
        return {"ok":False,"error":"Unable to determine location.","settings_uri":"ms-settings:privacy-location"}

    def location(self, refresh: bool = False) -> dict:
        with self._lock:
            if self._location_cache and not refresh:
                return dict(self._location_cache)
        result = self._win_location()
        if result.get("ok"):
            reverse=self._reverse_geocode(result["latitude"],result["longitude"])
            result.update(reverse)
            result["approximate"] = False
        else:
            fallback=self._ip_location()
            if fallback.get("ok"):
                result=fallback
        if result.get("ok"):
            with self._lock: self._location_cache = dict(result)
        return result

    def _geocode_city(self, city: str, language: str) -> dict:
        resp = requests.get("https://geocoding-api.open-meteo.com/v1/search", params={"name":city,"count":5,"language":("fa" if language=="fa" else "en"),"format":"json"}, timeout=5)
        resp.raise_for_status(); results = resp.json().get("results") or []
        if not results: return {}
        # Prefer Iran when the query is Persian or the result itself is Iranian.
        if language == "fa":
            for item in results:
                if item.get("country_code") == "IR": return item
        return results[0]

    def weather(self, city: str | None, language: str = "fa", use_location: bool = False) -> dict:
        fa = language != "en"
        try:
            if use_location:
                loc = self.location()
                if not loc.get("ok"):
                    message = "برای تشخیص خودکار شهر، Location ویندوز را روشن کن." if fa else "Turn on Windows Location so I can detect your city automatically."
                    return {"ok": False, "location_required": True, "settings_uri":"ms-settings:privacy-location", "error": message, "speak": message}
                lat, lon = loc["latitude"], loc["longitude"]; city_name = loc.get("city") or ("مکان فعلی" if fa else "your current location")
            else:
                city_name = (city or ("تهران" if fa else "London")).strip()
                item = self._geocode_city(city_name, language)
                if not item: 
                    message=f"شهر «{city_name}» پیدا نشد." if fa else f"I couldn't find {city_name}."
                    return {"ok":False,"error":message,"speak":message}
                lat, lon = item["latitude"], item["longitude"]; city_name = item.get("name") or city_name
        except Exception:
            message="الان به سرویس آب‌وهوا دسترسی ندارم. اتصال اینترنت را بررسی کن." if fa else "I cannot reach the weather service right now. Please check your internet connection."
            return {"ok":False,"error":message,"speak":message}
        key=(round(lat,3),round(lon,3),"fa" if fa else "en")
        with self._lock:
            cached=self._weather_cache.get(key)
            if cached and time.time()-cached[0] < 90: return dict(cached[1])
        params={"latitude":lat,"longitude":lon,"current":"temperature_2m,apparent_temperature,weather_code,relative_humidity_2m,wind_speed_10m","hourly":"precipitation_probability","daily":"precipitation_probability_max","timezone":"auto","forecast_days":1}
        try:
            response=requests.get("https://api.open-meteo.com/v1/forecast",params=params,timeout=7)
            response.raise_for_status(); data=response.json()
            cur=data["current"]; hourly=data.get("hourly",{}) or {}; probs=hourly.get("precipitation_probability") or []; times=hourly.get("time") or []
        except Exception:
            message="الان به سرویس آب‌وهوا دسترسی ندارم. اتصال اینترنت را بررسی کن." if fa else "I cannot reach the weather service right now. Please check your internet connection."
            return {"ok":False,"error":message,"speak":message}
        precip_now=0
        if probs:
            # Pick the hourly value closest to the current local hour instead of always using midnight.
            now_key=datetime.now().strftime("%Y-%m-%dT%H:00")
            try:
                idx=min(range(len(times)), key=lambda i: abs((datetime.fromisoformat(str(times[i]))-datetime.fromisoformat(now_key)).total_seconds()))
            except Exception:
                idx=0
            precip_now=int(probs[min(idx,len(probs)-1)] or 0)
        else:
            precip_now=int((data.get("daily",{}).get("precipitation_probability_max") or [0])[0])
        code=int(cur.get("weather_code",0)); temp=round(float(cur.get("temperature_2m",0)))
        if fa:
            desc=_WMO_FA.get(code,"نامشخص"); text=f"هوای {city_name}: {temp} درجه سانتی‌گراد است؛ وضعیت هوا {desc} است و احتمال بارش {precip_now} درصد است."
        else:
            desc=_WMO_EN.get(code,"unknown"); text=f"Weather in {city_name}: {temp} degrees Celsius, {desc}, {precip_now}% chance of precipitation."
        result={"ok":True,"city":city_name,"latitude":lat,"longitude":lon,"temperature_c":temp,"apparent_temperature_c":round(float(cur.get("apparent_temperature",temp))),"condition":desc,"precipitation_probability":precip_now,"humidity":int(cur.get("relative_humidity_2m",0)),"wind_kmh":round(float(cur.get("wind_speed_10m",0))),"message":text,"speak":text}
        with self._lock: self._weather_cache[key]=(time.time(),result)
        return result

    def time_date(self, language: str = "fa") -> dict:
        now=datetime.now().astimezone()
        if jdatetime:
            jd=jdatetime.datetime.fromgregorian(datetime=now)
            days_fa={0:"دوشنبه",1:"سه‌شنبه",2:"چهارشنبه",3:"پنجشنبه",4:"جمعه",5:"شنبه",6:"یکشنبه"}
            months=["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور","مهر","آبان","آذر","دی","بهمن","اسفند"]
            date_fa=f"{days_fa[now.weekday()]} {jd.day} {months[jd.month-1]} {jd.year}"
        else:
            date_fa=f"{now.strftime('%A')} {now.strftime('%Y-%m-%d')}"
        if language == "en":
            return {"ok":True,"time":now.strftime("%H:%M:%S"),"date":now.strftime("%A, %B %d, %Y"),"speak":f"It is {now.strftime('%H:%M:%S')}. Today is {now.strftime('%A, %B %d, %Y')}."}
        return {"ok":True,"time":now.strftime("%H:%M:%S"),"date_fa":date_fa,"date":now.strftime("%Y-%m-%d"),"speak":f"ساعت دقیق {now.strftime('%H:%M:%S')} است. امروز {date_fa} است."}
