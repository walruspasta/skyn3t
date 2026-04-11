#!/usr/bin/env python3
"""
Prime1 - sykn3t IRC Bot
A rude, entertaining IRC bot recreated from the original.
"""

import socket
import sys
import ssl
import re
import random
import time
import json
import os
import threading
import urllib.request
import urllib.parse
import urllib.error
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler

# ============================================================
# LOGGING SETUP
# ============================================================

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        RotatingFileHandler("logs/prime1.log", maxBytes=5*1024*1024, backupCount=3),
        logging.StreamHandler()
    ]
)

# ============================================================
# ENVIRONMENT / CONFIGURATION
# ============================================================

def _get_env(key, default=""):
    """Load an environment variable with a default value."""
    return os.environ.get(key, default)

GLOBAL_CONFIG = {
    "owner": "BlastGT1",                  # Your IRC nick — has bot admin
    "oper_pass": "",                       # Leave blank unless bot needs IRC oper
    "flood_delay": 1.5,                    # Seconds between responses
    "reconnect_delay": 30,                 # Seconds before reconnect attempt
    "youtube_api_key": _get_env("YOUTUBE_API_KEY"),
    "gemini_api_key": _get_env("GEMINI_API_KEY"),
}

NETWORKS = [
    {
        "server": "irc.sykn3t.net",
        "port": 6697,
        "use_ssl": True,
        "nick": "Prime1",
        "ident": "prime1",
        "realname": "Prime1 - skyn3t Entertainment Unit",
        "channels": ["#skyn3t"],
        "nickserv_password": _get_env("NICKSERV_PASS"),
    }
]

# ============================================================
# PERSISTENT COUNTERS
# ============================================================

COUNTER_FILE = os.path.join(os.path.dirname(__file__), "counters.json")
_counter_lock = threading.Lock()

def load_counters():
    defaults = {
        "cupcakes": 558,
        "thefts": 170,
        "fatalities": 387,
        "yomamas": 89,
        "hugs": 43,
        "fights": 116,
        "bombs": 0,
    }
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE) as f:
            saved = json.load(f)
        defaults.update(saved)
    return defaults

def save_counters(counters_dict):
    """Write counters to disk. Must be called with _counter_lock held."""
    with open(COUNTER_FILE, "w") as f:
        json.dump(counters_dict, f, indent=2)

counters = load_counters()

from data.content import *

# ============================================================
# BOT CLASS
# ============================================================

class Prime1Bot:
    """
    Prime1 - skyn3t IRC Bot
    A rude, entertaining IRC bot recreated from the original.
    """

    def __init__(self, network_config, shutdown_event):
        self.config = GLOBAL_CONFIG.copy()
        self.config.update(network_config)
        self.shutdown_event = shutdown_event
        self.sock = None
        self.connected = False
        self.channels = {}               # channel -> list of nicks
        self._flood_lock = threading.Lock()
        self.last_response = 0           # flood control timestamp
        self.last_data_received = time.time()
        self.running = True
        self._nick_list_building = set() # channels currently receiving 353 lists
        self.logger = logging.getLogger(f"Prime1[{self.config['server']}]")

        # GPT rate limiting
        self._gpt_user_calls = {}        # nick -> [timestamp, ...] recent calls
        self._gpt_global_last = 0        # timestamp of last global call
        self._gpt_daily_count = 0        # calls made today
        self._gpt_daily_reset = 0        # timestamp of last daily reset

        # Active timebombs: channel -> {target, wire, thread, defused}
        self._timebombs = {}

    # ----------------------------------------------------------
    # CONNECTION & LOOP
    # ----------------------------------------------------------

    def send_raw(self, msg):
        if self.sock:
            try:
                self.logger.debug(f">> {msg}")
                self.sock.sendall((msg + "\r\n").encode("utf-8", errors="replace"))
            except Exception as e:
                self.logger.error(f"send_raw failed: {e}")

    def connect_and_loop(self):
        """Main loop: connect, read, dispatch. Reconnects with exponential back-off."""
        retry_delay = self.config["reconnect_delay"]
        while self.running and not self.shutdown_event.is_set():
            try:
                raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if self.config["use_ssl"]:
                    ctx = ssl.create_default_context()
                    self.sock = ctx.wrap_socket(raw_sock, server_hostname=self.config["server"])
                else:
                    self.sock = raw_sock

                self.logger.info(f"Connecting to {self.config['server']}:{self.config['port']}...")
                self.sock.connect((self.config['server'], self.config['port']))
                self.sock.settimeout(300)

                self.send_raw(f"NICK {self.config['nick']}")
                self.send_raw(f"USER {self.config['ident']} 0 * :{self.config['realname']}")

                self.connected = True
                self.last_data_received = time.time()
                retry_delay = self.config["reconnect_delay"]
                read_buffer = ""

                try:
                    while self.running and not self.shutdown_event.is_set():
                        self.sock.settimeout(1.0)
                        try:
                            chunk = self.sock.recv(4096)
                        except socket.timeout:
                            idle_time = time.time() - self.last_data_received
                            if idle_time > 240:
                                self.logger.warning("No data received for 240s, reconnecting...")
                                break
                            elif idle_time > 120:
                                self.send_raw("PING :keepalive")
                            continue
                        except OSError:
                            break

                        if not chunk:
                            self.logger.warning("Server closed the connection.")
                            break

                        self.last_data_received = time.time()
                        read_buffer += chunk.decode("utf-8", errors="replace")
                        lines = read_buffer.split("\r\n")
                        read_buffer = lines.pop()
                        for line in lines:
                            self.handle_line(line)
                finally:
                    self.connected = False
                    self.channels = {}
                    if self.sock:
                        try:
                            self.sock.close()
                        except Exception:
                            pass
                        self.sock = None

            except (ConnectionRefusedError, ConnectionResetError, OSError) as e:
                self.logger.warning(f"Connection lost ({e}). Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 300)
            except Exception as e:
                self.logger.exception(f"Unexpected error in connect_and_loop: {e}")
                time.sleep(5)

    def send_msg(self, target, msg):
        self.send_raw(f"PRIVMSG {target} :{msg}")

    def send_action(self, target, msg):
        self.send_raw(f"PRIVMSG {target} :\x01ACTION {msg}\x01")

    def send_notice(self, target, msg):
        self.send_raw(f"NOTICE {target} :{msg}")

    # ----------------------------------------------------------
    # FLOOD CONTROL
    # ----------------------------------------------------------

    def flood_ok(self):
        with self._flood_lock:
            now = time.time()
            if now - self.last_response >= self.config["flood_delay"]:
                self.last_response = now
                return True
            return False

    # ----------------------------------------------------------
    # CHANNEL NICK TRACKING
    # ----------------------------------------------------------

    def channel_nicks(self, channel):
        nicks = self.channels.get(channel.lower(), [])
        return [n for n in nicks if n.lower() != self.config["nick"].lower()]

    def random_nick(self, channel, exclude=None):
        nicks = self.channel_nicks(channel)
        if exclude:
            nicks = [n for n in nicks if n.lower() != exclude.lower()]
        return random.choice(nicks) if nicks else "someone"

    # ----------------------------------------------------------
    # RESPONSE HELPERS
    # ----------------------------------------------------------

    def format_response(self, text, nick, channel, target=None):
        """Replace template variables in a response string."""
        text = text.replace("{nick}", nick)
        text = text.replace("{owner}", self.config["owner"])
        text = text.replace("{target}", target or nick)
        text = text.replace("{year}", str(datetime.now().year))
        return text

    def respond(self, channel, nick, text, target=None):
        """Send a response, handling ACTION prefix."""
        text = self.format_response(text, nick, channel, target)
        if text.startswith("ACTION "):
            self.send_action(channel, text[7:])
        else:
            self.send_msg(channel, text)

    # ----------------------------------------------------------
    # COMMAND HANDLERS
    # ----------------------------------------------------------

    def handle_8ball(self, channel, nick, question):
        if not question.strip():
            self.send_msg(channel, f"{nick}: Ask a question first, genius.")
            return
        self.send_msg(channel, random.choice(EIGHTBALL_RESPONSES))

    def handle_gay(self, channel, nick, args):
        self.send_msg(channel, "In my opinion, gay.")

    def handle_test(self, channel, nick, test_name, target):
        if not target:
            target = nick
        if test_name not in TESTS:
            return
        pct = random.randint(1, 99)
        line1, line2 = TESTS[test_name]
        self.send_msg(channel, line1.format(nick=target, pct=pct))
        time.sleep(1.0)
        self.send_msg(channel, line2.format(nick=target, pct=pct))

    def handle_pizza(self, channel, nick, target):
        if not target or target.lower() == "everyone":
            self.send_action(channel, f"makes a massive pizza masterpiece and serves everyone. {nick} says \"Enjoy!\"")
        else:
            self.send_action(channel, f"makes a massive pizza masterpiece and slides a slice to {target}. {nick} says \"Enjoy!\"")

    def handle_soda(self, channel, nick, target):
        if not target or target.lower() == "everyone":
            self.send_action(channel, f"nabs a cold can of soda and tosses it to everyone. {nick} thought you all looked thirsty.")
        else:
            self.send_action(channel, f"nabs a cold can of soda and tosses it to {target}. {nick} thought you looked thirsty.")

    def handle_milk(self, channel, nick, target):
        if not target:
            self.send_action(channel, f"hands a refreshingly cold glass of milk to {nick}")
        else:
            self.send_action(channel, f"gives an ice cold glass of milk to {target}. {nick} says only the dairy best for you!")

    def handle_shot(self, channel, nick, target):
        if not target:
            target = nick
        drink = random.choice(SHOT_OPTIONS)
        self.send_action(channel, f"pours {target} a shot of {drink}")

    def handle_die(self, channel, nick, target):
        if not target:
            target = nick
        self.send_action(channel, f"takes {target} bungee jumping, and \"forgets\" to secure {target}'s line before {target} jumps")

    def handle_chuck(self, channel, nick, args):
        self.send_msg(channel, random.choice(CHUCK_NORRIS))

    def handle_bofh(self, channel, nick, args):
        self.send_msg(channel, f"Random Bastard Operator From Hell error of the day: {random.choice(BOFH_ERRORS)}")

    def handle_confucius(self, channel, nick, args):
        self.send_msg(channel, f"\"{random.choice(CONFUCIUS)}\"")

    def handle_dumblaws(self, channel, nick, args):
        self.send_msg(channel, random.choice(DUMB_LAWS))

    def handle_emo(self, channel, nick, args):
        self.send_msg(channel, random.choice(EMO_QUOTES))

    def handle_drunkbot(self, channel, nick, args):
        line = random.choice(DRUNKBOT_LINES)
        self.respond(channel, nick, line)

    def handle_rcupcake(self, channel, nick, args):
        threading.Thread(
            target=self._rcupcake_worker,
            args=(channel, nick),
            daemon=True
        ).start()

    def _rcupcake_worker(self, channel, nick):
        with _counter_lock:
            counters["cupcakes"] += 1
            save_counters(counters)
        target = self.random_nick(channel, exclude=nick)
        amount = random.randint(1, 20)
        milk = random.randint(1000, 9999999)
        self.send_action(channel, "loads up the cupcake cannon, aims and..")
        time.sleep(0.8)
        self.send_msg(channel, f"FIRES! Sending {amount} cupcake(s) into {target}'s mouth!")
        self.send_action(channel, "thinks its time for the milk hose now, so he gets it out, aims and...")
        time.sleep(0.8)
        self.send_msg(channel, f"FIRES! ... INTO THE SKY. {milk:,} gallons of milk will rain down for days to come.")
        with _counter_lock:
            self.send_msg(channel, f"Number of people cupcaked: {counters['cupcakes']}")

    def handle_cupcake(self, channel, nick, target):
        threading.Thread(
            target=self._cupcake_worker,
            args=(channel, nick, target),
            daemon=True
        ).start()

    def _cupcake_worker(self, channel, nick, target):
        with _counter_lock:
            counters["cupcakes"] += 1
            save_counters(counters)
        rando = self.random_nick(channel, exclude=target or nick)
        rando2 = self.random_nick(channel, exclude=rando)
        amount = random.randint(1, 50)
        milk = random.randint(1, 10)
        self.send_action(channel, "loads up the cupcake cannon, aims and..")
        time.sleep(0.8)
        self.send_msg(channel, f"FIRES! ... But it missed and fills {rando}'s mouth with {amount} cupcake(s)!")
        self.send_action(channel, "thinks its time for the milk hose now, so he gets it out, aims and...")
        time.sleep(0.8)
        self.send_msg(channel, f"FIRES! ...But misses and \"accidentally\" drenches {rando2} with {milk} gallon(s) of milk.")
        with _counter_lock:
            self.send_msg(channel, f"Number of people cupcaked: {counters['cupcakes']}")

    def handle_rpickpocket(self, channel, nick, args):
        threading.Thread(
            target=self._rpickpocket_worker,
            args=(channel, nick),
            daemon=True
        ).start()

    def _rpickpocket_worker(self, channel, nick):
        with _counter_lock:
            counters["thefts"] += 1
            save_counters(counters)
        target = self.random_nick(channel, exclude=nick)
        loot = random.choice(PICKPOCKET_LOOT).replace("{year}", str(datetime.now().year))
        self.send_action(channel, f"goes into ninja mode and sneaks up behind {target}")
        time.sleep(0.8)
        self.send_action(channel, f"reaches into {target}'s pocket with maximum stealth, and comes out with.....")
        time.sleep(0.8)
        self.send_msg(channel, loot)
        with _counter_lock:
            self.send_msg(channel, f"Random thefts committed to date: {counters['thefts']}")

    def handle_ryomama(self, channel, nick, args):
        with _counter_lock:
            counters["yomamas"] += 1
            save_counters(counters)
        sender = self.random_nick(channel, exclude=nick)
        self.send_msg(channel, f"{sender}: {random.choice(YOMAMA)}")
        with _counter_lock:
            self.send_msg(channel, f"Random peoples' mamas insulted since yomama: {counters['yomamas']}")

    def handle_fatality(self, channel, nick, target):
        threading.Thread(
            target=self._fatality_worker,
            args=(channel, nick, target),
            daemon=True
        ).start()

    def _fatality_worker(self, channel, nick, target):
        if not target:
            target = self.random_nick(channel, exclude=nick)
        with _counter_lock:
            counters["fatalities"] += 1
            save_counters(counters)
        style_text, style_name = random.choice(FATALITY_STYLES)
        move = style_text.format(target=target, winner=nick)
        self.send_msg(channel, "\x034FINISH HIM!!")
        time.sleep(0.8)
        self.send_msg(channel, f"{nick} finishes {move}!")
        time.sleep(0.5)
        self.send_msg(channel, f"{nick} wins!")
        self.send_msg(channel, "\x034FATALITY")
        with _counter_lock:
            self.send_msg(channel, f"Total Kombatants killed: {counters['fatalities']}")

    def handle_rfatality(self, channel, nick, args):
        threading.Thread(
            target=self._fatality_worker,
            args=(channel, nick, self.random_nick(channel, exclude=nick)),
            daemon=True
        ).start()

    def handle_hug(self, channel, nick, target):
        if not target:
            target = nick
        responses = [
            f"gives {target} a great big hug",
            f"looks at {target}.........then grabs {target} in a bear hug!",
            f"squeezes {target} so hard their eyes bulge",
            f"runs at {target} full speed and nearly knocks {target} over with a hug",
        ]
        self.send_action(channel, random.choice(responses))

    def handle_rhug(self, channel, nick, args):
        with _counter_lock:
            counters["hugs"] += 1
            save_counters(counters)
        target = self.random_nick(channel, exclude=nick)
        responses = [
            f"ACTION can't hug {target} quickly enough!",
            f"ACTION cries tears of joy as {target} hugs him",
            f"ACTION tackle-hugs {target} without warning",
            f"ACTION wraps both arms around {target} and refuses to let go",
        ]
        self.respond(channel, nick, random.choice(responses))
        with _counter_lock:
            self.send_msg(channel, f"Random people hugged to date: {counters['hugs']}")

    def handle_beer(self, channel, nick, target):
        if not target:
            target = self.random_nick(channel, exclude=nick)
            self.send_action(channel, f"tosses a cold beer to {nick}, no worries it's on {target}")
        else:
            self.send_action(channel, f"tosses a cold beer to {target}.")

    def handle_roulette(self, channel, nick, target):
        self.send_msg(channel, "*CLICK*")

    def handle_weed(self, channel, nick, args):
        self.send_msg(channel, f"{nick}, I'm allergic to weed.......ragweed, that is")

    def handle_condom(self, channel, nick, args):
        self.send_msg(channel, f"Random condom slogan: {random.choice(CONDOM_SLOGANS)}")

    def handle_rd20(self, channel, nick, args):
        with _counter_lock:
            counters["fights"] += 1
            save_counters(counters)
        target = self.random_nick(channel, exclude=nick)
        roll = random.randint(1, 20)
        result_text = next(
            (text for threshold, text in RD20_RESULTS if roll >= threshold),
            RD20_RESULTS[-1][1]
        )
        result_text = result_text.replace("{nick}", nick).replace("{target}", target)
        self.send_msg(channel, result_text)
        with _counter_lock:
            self.send_msg(channel, f"Random fights picked to date: {counters['fights']}")

    def handle_search(self, channel, nick, args):
        if not args.strip():
            self.send_msg(channel, f"{nick}: Search for what, genius?")
            return
        query = urllib.parse.quote_plus(args.strip())
        self.send_msg(channel, f"You will find the answer here: https://duckduckgo.com/?q={query}")

    def handle_timebomb(self, channel, nick, target):
        if not target:
            self.send_msg(channel, f"{nick}: Who are you bombing? !timebomb <nick>")
            return
        if channel in self._timebombs:
            self.send_msg(channel, "There's already a bomb ticking! Defuse it first!")
            return
        seconds = random.randint(20, 60)
        wire = random.choice(TIMEBOMB_WIRES)
        self._timebombs[channel] = {"target": target, "wire": wire, "defused": False}
        wire_list = " ".join(TIMEBOMB_WIRES)
        self.send_action(channel, f"stuffs the bomb into {target}'s pants. The display reads [{seconds}] seconds.")
        self.send_msg(channel, f"Defuse the bomb! Cut the correct wire by typing !cutwire <color>. There are {len(TIMEBOMB_WIRES)} wires. They are {wire_list}.")
        self.send_msg(channel, "\x034tic... tic... tic...")
        t = threading.Timer(seconds, self._bomb_explode, args=(channel, target))
        self._timebombs[channel]["thread"] = t
        t.start()

    def _bomb_explode(self, channel, target):
        if channel in self._timebombs and not self._timebombs[channel].get("defused"):
            self.send_msg(channel, f"\x034*BOOOM!* {target} is now in several pieces. Messy.")
            del self._timebombs[channel]

    def handle_cutwire(self, channel, nick, args):
        if channel not in self._timebombs:
            self.send_msg(channel, "There's no bomb ticking. Relax.")
            return
        bomb = self._timebombs[channel]
        guess = args.strip().capitalize()
        if guess == bomb["wire"]:
            bomb["defused"] = True
            bomb["thread"].cancel()
            del self._timebombs[channel]
            self.send_msg(channel, f"\x033{nick} cut the {guess} wire! The bomb is defused! Nice work, hero.")
        else:
            self.send_msg(channel, f"\x034WRONG WIRE! {nick} cut the {guess} wire... nothing happened. Yet. Keep trying.")

    def fetch_youtube_info(self, video_id):
        """Fetch YouTube video title and channel from the Data API."""
        key = self.config.get("youtube_api_key", "")
        if not key:
            return None
        url = (
            "https://www.googleapis.com/youtube/v3/videos"
            f"?part=snippet&id={urllib.parse.quote(video_id)}&key={key}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Prime1-IRC-Bot/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
            items = data.get("items", [])
            if not items:
                return None
            snippet = items[0]["snippet"]
            title = snippet.get("title", "Unknown title")
            channel = snippet.get("channelTitle", "Unknown channel")
            return title, channel
        except Exception:
            return None

    def search_youtube(self, query):
        """Search YouTube and return top result."""
        key = self.config.get("youtube_api_key", "")
        if not key:
            return None
        url = (
            "https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet&q={urllib.parse.quote(query)}&type=video&maxResults=1&key={key}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Prime1-IRC-Bot/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
            items = data.get("items", [])
            if not items:
                return None
            item = items[0]
            video_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            channel = item["snippet"]["channelTitle"]
            link = f"https://youtu.be/{video_id}"
            return title, channel, link
        except Exception:
            return None

    def handle_yt(self, channel, nick, args):
        """Handle .yt search query."""
        if not args.strip():
            self.send_msg(channel, f"{nick}: .yt what? Give me something to search for.")
            return
        threading.Thread(
            target=self._yt_search_worker,
            args=(channel, nick, args.strip()),
            daemon=True
        ).start()

    def _yt_search_worker(self, channel, nick, query):
        result = self.search_youtube(query)
        if result:
            title, ch, link = result
            self.send_msg(channel, f"[YouTube] {title} \u2014 {ch} \u2192 {link}")
        else:
            self.send_msg(channel, f"{nick}: Couldn't find anything for that. YouTube hates you.")

    def _yt_url_worker(self, channel, video_id, url):
        result = self.fetch_youtube_info(video_id)
        if result:
            title, ch = result
            self.send_msg(channel, f"[YouTube] {title} \u2014 {ch} \u2192 https://youtu.be/{video_id}")

    # ----------------------------------------------------------
    # GPT RATE LIMITING
    # ----------------------------------------------------------

    GPT_USER_BURST = 3            # calls allowed before cooldown kicks in
    GPT_USER_COOLDOWN = 180       # seconds cooldown after burst (3 minutes)
    GPT_GLOBAL_COOLDOWN = 6       # seconds between any calls (keeps under 10/min)
    GPT_DAILY_LIMIT = 230         # stop at 230 to leave buffer before 250 hard limit

    def _gpt_check_rate(self, channel, nick):
        """Check rate limits. Returns True if OK to proceed, False if limited."""
        now = time.time()
        nick_lower = nick.lower()

        # Reset daily counter at midnight
        today_start = now - (now % 86400)
        if self._gpt_daily_reset < today_start:
            self._gpt_daily_count = 0
            self._gpt_daily_reset = today_start

        # Daily limit check
        if self._gpt_daily_count >= self.GPT_DAILY_LIMIT:
            remaining = int(today_start + 86400 - now) // 3600
            self.send_msg(channel, f"{nick}: Daily GPT limit reached ({self.GPT_DAILY_LIMIT} calls). Resets in ~{remaining}h.")
            return False

        # Global cooldown
        since_global = now - self._gpt_global_last
        if since_global < self.GPT_GLOBAL_COOLDOWN:
            wait = int(self.GPT_GLOBAL_COOLDOWN - since_global) + 1
            self.send_msg(channel, f"{nick}: Too busy, wait {wait}s.")
            return False

        # Per-user burst + cooldown
        calls = self._gpt_user_calls.get(nick_lower, [])
        calls = [t for t in calls if now - t < self.GPT_USER_COOLDOWN]
        if len(calls) >= self.GPT_USER_BURST:
            wait = int(self.GPT_USER_COOLDOWN - (now - calls[0])) + 1
            mins = wait // 60
            secs = wait % 60
            time_str = f"{mins}m {secs}s" if mins else f"{secs}s"
            self.send_msg(channel, f"{nick}: You've used your {self.GPT_USER_BURST} GPT calls. Cooldown expires in {time_str}.")
            return False

        # All good — update tracking
        calls.append(now)
        self._gpt_user_calls[nick_lower] = calls
        self._gpt_global_last = now
        self._gpt_daily_count += 1
        return True

    def handle_gpt(self, channel, nick, args):
        """Handle .gpt query using Gemini 2.5 Flash."""
        if not args.strip():
            self.send_msg(channel, f"{nick}: Ask me something.")
            return
        if not self._gpt_check_rate(channel, nick):
            return
        threading.Thread(
            target=self._gpt_worker,
            args=(channel, nick, args.strip()),
            daemon=True
        ).start()

    def _gpt_worker(self, channel, nick, query):
        key = self.config.get("gemini_api_key", "")
        if not key:
            self.send_msg(channel, f"{nick}: No Gemini API key configured.")
            return
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash:generateContent?key={key}"
        )
        prompt = (
            f"Answer this question in 1-2 complete sentences. "
            f"Be conversational and finish your thought completely. "
            f"No markdown, no bullet points, plain text only.\n\n"
            f"Question: {query}"
        )
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 300,
                "temperature": 0.8,
                "thinkingConfig": {"thinkingBudget": 0}
            }
        }).encode()
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "Prime1-IRC-Bot/1.0"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            text = " ".join(text.split())
            if len(text) > 450:
                truncated = text[:450]
                last_end = max(
                    truncated.rfind(". "),
                    truncated.rfind("! "),
                    truncated.rfind("? "),
                )
                if last_end > 50:
                    text = truncated[:last_end + 1].strip()
                else:
                    text = truncated[:447] + "..."
            self.send_msg(channel, f"[GPT] {text}")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            self.logger.error(f"[GPT] HTTP {e.code}: {body}")
            self.send_msg(channel, f"{nick}: Gemini HTTP {e.code} \u2014 check bot logs for details.")
        except Exception as e:
            self.logger.error(f"[GPT] Exception: {type(e).__name__}: {e}")
            self.send_msg(channel, f"{nick}: Something went wrong asking Gemini.")

    def handle_triggerme(self, channel, nick, args):
        commands = (
            "!8ball <question>, !gay <question>, !hug <nick>, !rhug, !pizza [nick/everyone], "
            "!soda [nick/everyone], !milk [nick], !shot [nick], !die <nick>, !beer [nick], "
            "!chuck, !bofh, !confucius, !dumblaws, !emo, !drunkbot, !weed, !condom, "
            "!roulette, !rd20, !search <term>, !timebomb <nick>, !cutwire <color>, "
            "!rcupcake, !cupcake <nick>, !rpickpocket, !ryomama, "
            "!fatality <nick>, !rfatality, !tests, .yt <search>, .gpt <question>"
        )
        self.send_notice(nick, f"Prime1's commands: {commands}")
        self.send_notice(nick, "Keyword triggers: prime1, hey right nut, hey left nut, stupid bot, stfu, who's your daddy, slap, and more. Just talk, I'm listening.")

    def handle_tests(self, channel, nick, args):
        test_list = ", ".join(f"!{t} <nick>" for t in sorted(TESTS.keys()))
        self.send_msg(channel, test_list)

    def handle_reload(self, channel, nick, args):
        if nick.lower() != self.config["owner"].lower():
            self.send_msg(channel, f"{nick}: You're not the boss of me.")
            return

        self.logger.warning(f"Reload command received from {nick} \u2014 restarting process.")
        self.send_msg(channel, "Restarting...")
        self.send_raw("QUIT :Reloading...")
        time.sleep(1)
        try:
            os.execl(sys.executable, sys.executable, *sys.argv)
        except Exception as e:
            self.logger.error(f"Reload failed: {e}")
            self.send_msg(channel, f"Reload failed: {e}")

    # ----------------------------------------------------------
    # COMMAND DISPATCH
    # ----------------------------------------------------------

    COMMANDS = {
        "!8ball":        (handle_8ball,      "args"),
        "!gay":          (handle_gay,        "args"),
        "!hug":          (handle_hug,        "target"),
        "!rhug":         (handle_rhug,       "args"),
        "!pizza":        (handle_pizza,      "target"),
        "!soda":         (handle_soda,       "target"),
        "!milk":         (handle_milk,       "target"),
        "!shot":         (handle_shot,       "target"),
        "!die":          (handle_die,        "target"),
        "!chuck":        (handle_chuck,      "args"),
        "!bofh":         (handle_bofh,       "args"),
        "!confucius":    (handle_confucius,  "args"),
        "!dumblaws":     (handle_dumblaws,   "args"),
        "!emo":          (handle_emo,        "args"),
        "!drunkbot":     (handle_drunkbot,   "args"),
        "!beer":         (handle_beer,       "target"),
        "!roulette":     (handle_roulette,   "target"),
        "!weed":         (handle_weed,       "args"),
        "!condom":       (handle_condom,     "args"),
        "!rd20":         (handle_rd20,       "args"),
        "!search":       (handle_search,     "args"),
        "!timebomb":     (handle_timebomb,   "target"),
        "!cutwire":      (handle_cutwire,    "args"),
        "!rfatality":    (handle_rfatality,  "args"),
        "!rcupcake":     (handle_rcupcake,   "args"),
        "!cupcake":      (handle_cupcake,    "target"),
        "!rpickpocket":  (handle_rpickpocket,"args"),
        "!ryomama":      (handle_ryomama,    "args"),
        "!fatality":     (handle_fatality,   "target"),
        "!triggerme":    (handle_triggerme,  "args"),
        "!tests":        (handle_tests,      "args"),
        "!reload":       (handle_reload,     "args"),
        "!prime":        (None,              "special"),
        ".yt":           (handle_yt,         "args"),
        ".gpt":          (handle_gpt,        "args"),
    }

    def dispatch_command(self, channel, nick, cmd, args):
        """Route a !command to its handler."""
        cmd_lower = cmd.lower()

        # Test commands
        test_name = cmd_lower.lstrip("!")
        if test_name in TESTS:
            target = args.strip() if args.strip() else nick
            self.handle_test(channel, nick, test_name, target)
            return

        if cmd_lower not in self.COMMANDS:
            return

        handler, arg_type = self.COMMANDS[cmd_lower]

        if cmd_lower == "!prime":
            if args.strip():
                self.send_msg(channel, "Say what?")
            else:
                self.send_msg(channel, "That's my name, don't wear it out.")
            return

        if arg_type == "args":
            handler(self, channel, nick, args.strip())
        else:  # target
            handler(self, channel, nick, args.strip() or None)

    # ----------------------------------------------------------
    # MESSAGE HANDLER
    # ----------------------------------------------------------

    def handle_privmsg(self, nick, channel, message):
        """Main message handler — commands first, then keyword triggers."""
        if not channel.startswith("#"):
            return  # ignore PMs for now
        if nick.lower() == self.config["nick"].lower():
            return

        msg = message.strip()

        # Detect ACTION messages (/me slaps prime1)
        is_action = msg.startswith("\x01ACTION ") and msg.endswith("\x01")
        if is_action:
            msg = msg[8:-1].strip()

        msg_lower = msg.lower()

        # YouTube URL detection — runs in background, no flood check needed
        if not is_action:
            yt_match = re.search(
                r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})',
                msg
            )
            if yt_match:
                video_id = yt_match.group(1)
                threading.Thread(
                    target=self._yt_url_worker,
                    args=(channel, video_id, msg),
                    daemon=True
                ).start()

            # Dot commands (.yt, .gpt)
            if msg.startswith("."):
                parts = msg.split(None, 1)
                cmd = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""
                if cmd in self.COMMANDS:
                    self.dispatch_command(channel, nick, cmd, args)
                return

            # Bang commands (!8ball, !chuck, etc.)
            if msg.startswith("!"):
                parts = msg.split(None, 1)
                cmd = parts[0]
                args = parts[1] if len(parts) > 1 else ""
                self.dispatch_command(channel, nick, cmd, args)
                return

        # Keyword triggers — fire for both normal and ACTION messages
        if self.flood_ok():
            for pattern, responses in KEYWORD_TRIGGERS:
                if re.search(pattern, msg_lower):
                    response = random.choice(responses)
                    self.respond(channel, nick, response)
                    return

    # ----------------------------------------------------------
    # IRC EVENT LOOP
    # ----------------------------------------------------------

    def handle_line(self, line):
        self.logger.debug(f"<< {line}")

        # PING/PONG
        if line.startswith("PING"):
            self.send_raw("PONG " + line[5:])
            return

        parts = line.split(" ", 3)
        if len(parts) < 2:
            return

        prefix = parts[0].lstrip(":")
        command = parts[1]

        # Welcome — join channels
        if command == "001":
            self.on_connect()

        # Nick list for channel
        elif command == "353":
            channel = parts[3].split()[0].lstrip("=@").lower()
            nicks_raw = parts[3].split(":", 1)[1].split()
            nicks = [n.lstrip("@+%&~") for n in nicks_raw]
            if channel not in self._nick_list_building:
                self.channels[channel] = []
                self._nick_list_building.add(channel)
            self.channels[channel].extend(nicks)

        # End of names list
        elif command == "366":
            channel = parts[3].split()[0].lower()
            self._nick_list_building.discard(channel)

        # JOIN
        elif command == "JOIN":
            channel = parts[2].lstrip(":").lower()
            joining_nick = prefix.split("!")[0]
            self.channels.setdefault(channel, [])
            if joining_nick not in self.channels[channel]:
                self.channels[channel].append(joining_nick)

        # PART / QUIT
        elif command in ("PART", "QUIT"):
            leaving_nick = prefix.split("!")[0]
            for ch in self.channels:
                if leaving_nick in self.channels[ch]:
                    self.channels[ch].remove(leaving_nick)

        # NICK change
        elif command == "NICK":
            old_nick = prefix.split("!")[0]
            new_nick = parts[2].lstrip(":")
            for ch in self.channels:
                if old_nick in self.channels[ch]:
                    self.channels[ch].remove(old_nick)
                    self.channels[ch].append(new_nick)

        # KICK
        elif command == "KICK":
            channel = parts[2].lower()
            kicked_nick = parts[3].split()[0]
            if channel in self.channels and kicked_nick in self.channels[channel]:
                self.channels[channel].remove(kicked_nick)
            if kicked_nick.lower() == self.config["nick"].lower():
                threading.Timer(3, self.send_raw, args=(f"JOIN {channel}",)).start()

        # PRIVMSG
        elif command == "PRIVMSG":
            sender_nick = prefix.split("!")[0]
            target = parts[2]
            message = parts[3].lstrip(":") if len(parts) > 3 else ""
            self.handle_privmsg(sender_nick, target, message)

    def on_connect(self):
        """Called when bot is successfully connected and registered."""
        self.logger.info("Registration complete.")
        self.send_msg("NickServ", f"IDENTIFY {self.config['nickserv_password']}")
        for ch in self.config["channels"]:
            self.send_raw(f"JOIN {ch}")


if __name__ == "__main__":
    if not NETWORKS:
        logging.critical("No networks configured in NETWORKS. Exiting.")
        sys.exit(1)

    shutdown_event = threading.Event()
    bots = []

    for net_cfg in NETWORKS:
        bot = Prime1Bot(net_cfg, shutdown_event)
        t = threading.Thread(target=bot.connect_and_loop, daemon=True)
        t.start()
        bots.append(bot)

    try:
        while not shutdown_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt received — initiating graceful shutdown.")
        shutdown_event.set()

    for bot in bots:
        bot.running = False
        bot.send_raw("QUIT :Prime1 shutting down.")

    time.sleep(1)
    logging.info("Shutdown complete.")
