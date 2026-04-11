# Prime1 - sykn3t IRC Bot

Prime1 is a rude, entertaining, and highly interactive IRC bot. It features a wide array of games, jokes, and utility commands, including integration with YouTube and Google Gemini (AI).

## 🚀 Getting Started

### Prerequisites
- Python 3.8+
- An IRC server to connect to.
- (Optional) Google Gemini API Key for `.gpt` command.
- (Optional) YouTube Data API v3 Key for `.yt` and URL lookups.

### Installation
1.  Clone or copy the bot files into a directory.
2.  Ensure the following structure exists:
    ```
    /project-root
    ├── prime1.py          # Main executable
    ├── counters.json      # (Auto-generated) Stats tracking
    ├── data/
    │   └── content.py     # Joke/Test/Trigger pools
    └── logs/              # (Auto-generated) Bot logs
    ```

### Configuration
The bot now uses a hybrid configuration model:

#### 1. Environment Variables (Secrets)
For security, do **not** put passwords or API keys in the source code. Set these in your OS environment or a `.env` file (if using a loader):
- `NICKSERV_PASS`: Your bot's NickServ password.
- `GEMINI_API_KEY`: Google Gemini API key.
- `YOUTUBE_API_KEY`: YouTube Data API v3 key.

#### 2. `prime1.py` Settings
Open `prime1.py` and look for the `GLOBAL_CONFIG` and `NETWORKS` sections at the top:
- **`GLOBAL_CONFIG`**: Set your IRC nick (the owner who can use `!reload`) and flood delays here.
- **`NETWORKS`**: This is a list. You can add multiple server blocks to have the bot connect to multiple networks simultaneously!
  ```python
  NETWORKS = [
      {
          "server": "irc.sykn3t.net",
          "port": 6697,
          "use_ssl": True,
          "nick": "Prime1",
          "ident": "prime1",
          "channels": ["#skyn3t"],
          "nickserv_password": _get_env("NICKSERV_PASS"),
      }
  ]
  ```

### Running the Bot
Simply run:
```bash
python prime1.py
```

---

## 🛠 Features & Commands

### 🎮 Games & Fun
- `!timebomb <nick>`: Plant a bomb! The target must `!cutwire <color>` before it explodes.
- `!fatality <nick>`: Perform a Mortal Kombat style finishing move.
- `!rd20`: Roll a 20-sided die for a random battle result.
- `!cupcake <nick>`: Fire the cupcake cannon.
- `!rpickpocket`: Stealthily steal a random item from someone.
- `!ryomama`: Insult a random person's mother.
- `!drunkbot`: Act like a total mess.
- `!roulette`: *Click*...

### 🧪 Tests (Usage: `!<test> <nick>`)
Check someone's stats! Examples:
`!asshattest`, `!babetest`, `!cooltest`, `!drunktest`, `!idiottest`, `!sexytest`, `!noobtest`, and many more. Use `!tests` to see the full list.

### 📚 Wisdom & Jokes
- `!chuck`: Random Chuck Norris fact.
- `!bofh`: Random Bastard Operator From Hell excuse.
- `!confucius`: Ancient (and questionable) wisdom.
- `!dumblaws`: Bizarre laws from around the world.
- `!emo`: Deeply sad quotes.
- `!8ball <question>`: Consult the magic ball.

### 🔍 Utility & AI
- `.gpt <query>`: Ask the Gemini AI anything (Rate limited).
- `.yt <search>`: Search YouTube for a video.
- **URL Lookup**: Post a YouTube link, and Prime1 will automatically fetch the title and channel.
- `!search <query>`: Get a DuckDuckGo search link.
- `!triggerme`: Sends a private notice with all available commands.

### 👑 Admin (Owner Only)
- `!reload`: Restarts the bot process to apply code or content changes.

---

## 🧠 Personality (Keyword Triggers)
Prime1 listens to everything. He might react if you mention his name, call him "stupid bot", slap him, or use certain "colorful" language. He is designed to be rude—don't take it personally.

## 📁 Maintenance
- **Logs**: Check `logs/prime1.log` for connection issues or errors.
- **Counters**: `counters.json` tracks total stats (cupcakes fired, fatalities, etc.).
- **Content**: You can edit `data/content.py` to add your own jokes or triggers without touching the bot's core logic.
